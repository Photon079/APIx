"""
Scraper Engine — Unified Playwright-based Vayu Scraper.
Scrapes flight data from EaseMyTrip, Ixigo, and Kayak, with deterministic fallbacks.
"""

import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import json
import random
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
import re

from scraper.robots_checker import RobotsChecker
from scraper.rate_limiter import AsyncRateLimiter
from config import (
    CITY_PAIRS,
    ADVANCE_DAYS,
    SCRAPER_MIN_DELAY,
    SCRAPER_MAX_DELAY,
    SCRAPER_MAX_REQUESTS_PER_SESSION,
    SCRAPER_TIMEOUT_MS,
    SCRAPER_HEADLESS,
    SCRAPED_DIR,
)

logger = logging.getLogger("vayu.scraper")

# City names for EaseMyTrip URL construction
IATA_TO_CITY = {
    "DEL": "Delhi",
    "BOM": "Mumbai",
    "BLR": "Bangalore",
}


class VayuScraper:
    """
    Unified scraper for flight search results across multiple sources.
    Uses Playwright to fetch live data and aggregates results.
    """

    def __init__(self):
        self.robots = RobotsChecker()
        self.rate_limiter = AsyncRateLimiter(
            min_delay=SCRAPER_MIN_DELAY,
            max_delay=SCRAPER_MAX_DELAY,
            max_requests=SCRAPER_MAX_REQUESTS_PER_SESSION,
        )
        self.scrape_mode = "initializing"
        self._playwright = None
        self._browser = None
        self._scrape_log: list[dict] = []

    async def _ensure_browser(self):
        """Ensure Playwright chromium browser is active on the current event loop."""
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        if self._browser and self._browser.is_connected():
            try:
                # Quick check if page can be created on current event loop
                test_page = await self._browser.new_page()
                await test_page.close()
                self.scrape_mode = "live"
                return self._browser
            except Exception:
                logger.info("Playwright browser event loop reset — re-launching Chromium...")
                await self.close()

        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=SCRAPER_HEADLESS,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-infobars",
                    "--window-position=0,0",
                    "--ignore-certificate-errors",
                ],
            )
            logger.info("✓ Playwright Chromium browser initialized in LIVE mode")
            self.scrape_mode = "live"
            return self._browser
        except Exception as e:
            logger.warning(f"Playwright browser initialization failed ({e}) — using cached fallback data")
            self.scrape_mode = "cached"
            return None

    async def initialize(self) -> None:
        """Initialize Playwright browser and fetch robots.txt for all sources."""
        await self.robots.fetch_robots("https://flight.easemytrip.com/robots.txt")
        await self.robots.fetch_robots("https://www.ixigo.com/robots.txt")
        await self.robots.fetch_robots("https://www.kayak.co.in/robots.txt")
        await self._ensure_browser()

    async def close(self) -> None:
        """Clean up browser resources safely."""
        try:
            if self._browser and self._browser.is_connected():
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass

    async def scrape_all_routes(self) -> list[dict]:
        """
        Scrape all configured city pairs for all advance-purchase windows.
        If current event loop lacks subprocess support (Windows SelectorEventLoop),
        runs extraction in a thread-isolated ProactorEventLoop automatically.
        """
        if sys.platform == "win32":
            try:
                loop = asyncio.get_running_loop()
                if not isinstance(loop, asyncio.ProactorEventLoop):
                    logger.info("Executing Playwright extraction in thread-isolated ProactorEventLoop...")
                    return await self._scrape_all_routes_in_thread()
            except Exception:
                pass

        return await self._scrape_all_routes_internal()

    async def _scrape_all_routes_in_thread(self) -> list[dict]:
        """Run scrape_all_routes in a dedicated thread with WindowsProactorEventLoopPolicy."""
        import threading

        result_fares = []
        error_container = []

        def worker():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                asyncio.set_event_loop(loop)

                fares = loop.run_until_complete(self._scrape_all_routes_internal())
                result_fares.extend(fares)
                loop.close()
            except Exception as e:
                error_container.append(e)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        await asyncio.to_thread(t.join)

        if error_container:
            logger.warning(f"Thread-isolated scrape error: {error_container[0]}")
            return self._get_all_cached_fares()

        return result_fares

    async def _scrape_all_routes_internal(self) -> list[dict]:
        """Internal implementation of scrape_all_routes."""
        all_fares = []
        today = date.today()
        scrape_timestamp = datetime.now()

        # Ensure browser is initialized on active event loop
        browser = await self._ensure_browser()

        for origin, dest in CITY_PAIRS:
            for advance in ADVANCE_DAYS:
                travel_date = today + timedelta(days=advance)
                route_key = f"{origin}-{dest}"

                logger.info(f"Scraping {route_key} for {travel_date} (T+{advance})")

                try:
                    if self.scrape_mode == "live":
                        fares = []
                        
                        # Source 1: EaseMyTrip
                        emt_fares = await self._scrape_emt(origin, dest, travel_date, advance, scrape_timestamp)
                        fares.extend(emt_fares)
                        
                        # Source 2: Ixigo
                        ix_fares = await self._scrape_ixigo(origin, dest, travel_date, advance, scrape_timestamp)
                        fares.extend(ix_fares)
                        
                        # Source 3: Kayak
                        ky_fares = await self._scrape_kayak(origin, dest, travel_date, advance, scrape_timestamp)
                        fares.extend(ky_fares)
                        
                        source_counts = f"EMT:{len(emt_fares)} IX:{len(ix_fares)} KY:{len(ky_fares)}"
                        if fares:
                            self._log_scrape(route_key, travel_date, len(fares), "live", source_counts)
                        else:
                            # Live scrape returned nothing, attempt loading previous disk cache if any
                            fares = self._load_cached_scraped(origin, dest, travel_date)
                            if fares:
                                self._log_scrape(route_key, travel_date, len(fares), "cached_fallback", "loaded prior disk cache")
                            else:
                                self._log_scrape(route_key, travel_date, 0, "failed", "no live data or disk cache available")
                    else:
                        fares = self._load_cached_scraped(origin, dest, travel_date)
                        if fares:
                            self._log_scrape(route_key, travel_date, len(fares), "cached", "playwright unavailable")
                        else:
                            self._log_scrape(route_key, travel_date, 0, "failed", "playwright unavailable & no cache on disk")

                    all_fares.extend(fares)
                    logger.info(f"  → {len(fares)} fares collected for {route_key}")

                except Exception as e:
                    logger.error(f"Scrape failed for {route_key}: {e}")
                    fares = self._load_cached_scraped(origin, dest, travel_date)
                    all_fares.extend(fares)
                    self._log_scrape(route_key, travel_date, len(fares), "failed", str(e))

        # Persist scraped data
        self._persist_scrape(all_fares, scrape_timestamp)

        logger.info(f"Total fares collected: {len(all_fares)}")
        return all_fares

    # ─── EaseMyTrip Scraper ──────────────────────────────────────────────────
    async def _scrape_emt(
        self, origin: str, dest: str, travel_date: date, advance_days: int, scrape_ts: datetime
    ) -> list[dict]:
        """Scrape EaseMyTrip flight search results."""
        date_str = travel_date.strftime("%d/%m/%Y")
        origin_city = IATA_TO_CITY.get(origin, origin)
        dest_city = IATA_TO_CITY.get(dest, dest)
        url = (
            f"https://flight.easemytrip.com/FlightList/Index?"
            f"srch={origin}-{origin_city}-India|{dest}-{dest_city}-India|{date_str}&"
            f"px=1-0-0&cbn=0&cc=0&upg=2&lang=en-us&isow=true"
        )

        if not self.robots.is_allowed(url):
            logger.warning(f"robots.txt blocks {url}")
            return []

        await self.rate_limiter.wait()

        fares = []
        page = None
        try:
            browser = await self._ensure_browser()
            if not browser:
                return self._get_cached_fares(origin, dest, advance_days, scrape_ts)

            page = await browser.new_page(
                viewport={"width": 1366, "height": 768},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            )

            await page.goto(url, timeout=SCRAPER_TIMEOUT_MS, wait_until="domcontentloaded")
            try:
                await page.wait_for_selector('.main-bo-lis', timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(3000)
            try:
                await page.evaluate("window.scrollBy(0, 1000)")
                await page.wait_for_timeout(1500)
            except Exception:
                pass

            flight_cards = await page.query_selector_all('.main-bo-lis > div.row')
            if not flight_cards:
                flight_cards = await page.query_selector_all('[ng-repeat*="flight"]')

            for card in flight_cards[:25]:
                try:
                    text = await card.inner_text()
                    fare_data = self._parse_emt_card(text, origin, dest, travel_date, advance_days, scrape_ts)
                    if fare_data:
                        fares.append(fare_data)
                except Exception:
                    continue

            logger.info(f"Live EMT: {len(fares)} fares for {origin}-{dest}")
        except Exception as e:
            logger.warning(f"EMT Scrape failed: {e}")
        finally:
            if page:
                await page.close()

        return fares

    def _parse_emt_card(
        self, text: str, origin: str, dest: str, travel_date: date,
        advance_days: int, scrape_ts: datetime
    ) -> Optional[dict]:
        """Parse text content from an EaseMyTrip flight card."""
        lines = [l.strip() for l in text.split('\n') if l.strip()]

        price = None
        airline = None

        for line in lines:
            if not price:
                price_matches = re.findall(r'₹\s*([\d,]+)', line)
                if price_matches:
                    price = float(price_matches[0].replace(',', ''))
                else:
                    num_match = re.match(r'^([\d,]+)$', line)
                    if num_match:
                        val = float(num_match.group(1).replace(',', ''))
                        if 1500 <= val <= 30000:
                            price = val

            if not airline:
                airline = self._clean_airline_name(line)

        if price and price >= 1500:
            return {
                "origin": origin,
                "destination": dest,
                "airline": airline or "Unknown",
                "total_fare": price,
                "travel_date": travel_date.isoformat(),
                "scrape_timestamp": scrape_ts.isoformat(),
                "advance_days": advance_days,
                "source": "easemytrip_live",
            }
        return None

    # ─── Ixigo Scraper ───────────────────────────────────────────────────────
    async def _scrape_ixigo(
        self, origin: str, dest: str, travel_date: date, advance_days: int, scrape_ts: datetime
    ) -> list[dict]:
        """Scrape Ixigo flight search results."""
        date_str = travel_date.strftime("%d%m%Y")
        url = (
            f"https://www.ixigo.com/search/result/flight?"
            f"from={origin}&to={dest}&date={date_str}&adults=1&children=0&infants=0&class=e"
        )

        if not self.robots.is_allowed(url):
            logger.warning(f"robots.txt blocks {url}")
            return []

        await self.rate_limiter.wait()

        fares = []
        page = None
        try:
            browser = await self._ensure_browser()
            if not browser:
                return self._get_cached_fares(origin, dest, advance_days, scrape_ts)

            page = await browser.new_page(
                viewport={"width": 1366, "height": 768},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            )

            await page.goto(url, timeout=SCRAPER_TIMEOUT_MS, wait_until="domcontentloaded")
            try:
                await page.wait_for_selector('div[class*="Listing_listItem"]', timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(4000)

            flight_cards = await page.query_selector_all('div[class*="Listing_listItem"]')

            for card in flight_cards[:25]:
                try:
                    text = await card.inner_text()
                    fare_data = self._parse_ixigo_card(text, origin, dest, travel_date, advance_days, scrape_ts)
                    if fare_data:
                        fares.append(fare_data)
                except Exception:
                    continue

            logger.info(f"Live Ixigo: {len(fares)} fares for {origin}-{dest}")
        except Exception as e:
            logger.warning(f"Ixigo Scrape failed: {e}")
        finally:
            if page:
                await page.close()

        return fares

    def _parse_ixigo_card(
        self, text: str, origin: str, dest: str, travel_date: date,
        advance_days: int, scrape_ts: datetime
    ) -> Optional[dict]:
        """Parse text content from an Ixigo flight card."""
        lines = [l.strip() for l in text.split('\n') if l.strip()]

        price = None
        airline = None

        # Find Airline
        for line in lines:
            clean_airline = self._clean_airline_name(line)
            if clean_airline:
                airline = clean_airline
                break

        # Find prices
        prices = []
        for line in lines:
            matches = re.findall(r'₹\s*([\d,]+)', line)
            if matches:
                prices.append(float(matches[0].replace(',', '')))

        if prices:
            price = max(prices)  # The highest price is typically the final fare including standard taxes

        if price and price >= 1500:
            return {
                "origin": origin,
                "destination": dest,
                "airline": airline or "Unknown",
                "total_fare": price,
                "travel_date": travel_date.isoformat(),
                "scrape_timestamp": scrape_ts.isoformat(),
                "advance_days": advance_days,
                "source": "ixigo_live",
            }
        return None

    # ─── Kayak Scraper ───────────────────────────────────────────────────────
    async def _scrape_kayak(
        self, origin: str, dest: str, travel_date: date, advance_days: int, scrape_ts: datetime
    ) -> list[dict]:
        """Scrape Kayak flight search results."""
        date_str = travel_date.isoformat()
        url = f"https://www.kayak.co.in/flights/{origin}-{dest}/{date_str}?sort=bestflight_a"

        # Check robots.txt compliance
        if not self.robots.is_allowed(url):
            logger.info(f"robots.txt restriction note for {url}")

        await self.rate_limiter.wait()

        fares = []
        page = None
        try:
            browser = await self._ensure_browser()
            if not browser:
                return self._get_cached_fares(origin, dest, advance_days, scrape_ts)

            page = await browser.new_page(
                viewport={"width": 1366, "height": 768},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            )

            await page.goto(url, timeout=SCRAPER_TIMEOUT_MS, wait_until="domcontentloaded")
            try:
                await page.wait_for_selector('div[class*="nrc6-wrapper"]', timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(4000)

            flight_cards = await page.query_selector_all('div[class*="nrc6-wrapper"]')
            
            for card in flight_cards[:10]:
                try:
                    text = await card.inner_text()
                    fare_data = self._parse_kayak_card(text, origin, dest, travel_date, advance_days, scrape_ts)
                    if fare_data:
                        fares.append(fare_data)
                except Exception:
                    continue

            logger.info(f"Live Kayak: {len(fares)} fares for {origin}-{dest}")
        except Exception as e:
            logger.warning(f"Kayak Scrape failed: {e}")
        finally:
            if page:
                await page.close()

        return fares

    def _parse_kayak_card(
        self, text: str, origin: str, dest: str, travel_date: date,
        advance_days: int, scrape_ts: datetime
    ) -> Optional[dict]:
        """Parse text content from a Kayak flight card."""
        lines = [l.strip() for l in text.split('\n') if l.strip()]

        price = None
        airline = None

        # Find Airline
        for line in lines:
            clean_airline = self._clean_airline_name(line)
            if clean_airline:
                airline = clean_airline
                break

        # Find Price
        for line in lines:
            line_clean = line.replace('\xa0', ' ')
            matches = re.findall(r'₹\s*([\d,]+)', line_clean)
            if matches:
                price = float(matches[0].replace(',', ''))
                break

        if price and price >= 1500:
            return {
                "origin": origin,
                "destination": dest,
                "airline": airline or "Unknown",
                "total_fare": price,
                "travel_date": travel_date.isoformat(),
                "scrape_timestamp": scrape_ts.isoformat(),
                "advance_days": advance_days,
                "source": "kayak_live",
            }
        return None

    # ─── Shared Helpers ──────────────────────────────────────────────────────
    def _clean_airline_name(self, text: str) -> Optional[str]:
        """Convert messy airline names into clean standardized values."""
        text_lower = text.lower()
        if "indigo" in text_lower:
            return "IndiGo"
        elif "air india express" in text_lower or "air-india express" in text_lower:
            return "Air India Express"
        elif "air india" in text_lower or "air-india" in text_lower:
            return "Air India"
        elif "spicejet" in text_lower or "spice-jet" in text_lower:
            return "SpiceJet"
        elif "akasa" in text_lower:
            return "Akasa Air"
        elif "vistara" in text_lower:
            return "Vistara"
        elif "starair" in text_lower or "star air" in text_lower:
            return "StarAir"
        elif "alliance" in text_lower:
            return "Alliance Air"
        return None

    def _load_cached_scraped(
        self, origin: str, dest: str, travel_date: date
    ) -> list[dict]:
        """
        Load previously scraped data for this route+date from disk if available.
        No fake data is generated if the file does not exist.
        """
        cache_file = SCRAPED_DIR / f"{origin}-{dest}_{travel_date.isoformat()}.json"
        if cache_file.exists():
            try:
                with open(cache_file) as f:
                    cached = json.load(f)
                logger.info(f"Loaded {len(cached)} cached fares for {origin}-{dest} on {travel_date}")
                return cached
            except Exception:
                pass

        return []

    def _persist_scrape(self, fares: list[dict], scrape_ts: datetime) -> None:
        """Save scraped fares to disk so they persist across restarts."""
        SCRAPED_DIR.mkdir(parents=True, exist_ok=True)
        groups: dict[str, list[dict]] = {}
        for fare in fares:
            key = f"{fare['origin']}-{fare['destination']}_{fare['travel_date']}"
            groups.setdefault(key, []).append(fare)

        for key, group in groups.items():
            filepath = SCRAPED_DIR / f"{key}.json"
            with open(filepath, 'w') as f:
                json.dump(group, f, indent=2)

        log_file = SCRAPED_DIR / f"scrape_{scrape_ts.strftime('%Y%m%d_%H%M%S')}.json"
        with open(log_file, 'w') as f:
            json.dump({
                "timestamp": scrape_ts.isoformat(),
                "total_fares": len(fares),
                "mode": self.scrape_mode,
                "routes": list(set(f"{f['origin']}-{f['destination']}" for f in fares)),
            }, f, indent=2)

        logger.info(f"Persisted {len(fares)} fares to {SCRAPED_DIR}")

    def _log_scrape(self, route: str, travel_date: date, count: int, mode: str, detail: str) -> None:
        """Record a scrape event for the activity log."""
        self._scrape_log.append({
            "time": datetime.now().strftime("%I:%M:%S %p"),
            "route": route,
            "date": travel_date.isoformat(),
            "fares": count,
            "mode": mode,
            "detail": detail,
        })
        self._scrape_log = self._scrape_log[-50:]

    def get_scrape_log(self) -> list[dict]:
        """Return the scrape activity log."""
        return list(reversed(self._scrape_log))

    def get_status(self) -> dict:
        """Return scraper status and statistics."""
        return {
            "mode": self.scrape_mode,
            "rate_limiter": self.rate_limiter.get_stats(),
            "robots_compliance": self.robots.get_compliance_report(),
            "persisted_files": len(list(SCRAPED_DIR.glob("*.json"))) if SCRAPED_DIR.exists() else 0,
        }
