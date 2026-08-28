"""
robots.txt Compliance Checker
Fetches and parses robots.txt for target domains to ensure ethical scraping.
"""

import httpx
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import logging

logger = logging.getLogger("apix.robots")


class RobotsChecker:
    """Checks robots.txt compliance before making scraping requests."""

    def __init__(self):
        self._parsers: dict[str, RobotFileParser] = {}
        self._fetch_errors: dict[str, str] = {}

    async def fetch_robots(self, url: str) -> None:
        """Fetch and parse robots.txt for the given URL's domain."""
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"

        if domain in self._parsers:
            return

        robots_url = f"{domain}/robots.txt"
        logger.info(f"Fetching robots.txt: {robots_url}")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(robots_url, follow_redirects=True)

            parser = RobotFileParser()
            parser.set_url(robots_url)

            if response.status_code == 200:
                parser.parse(response.text.splitlines())
                logger.info(f"✓ Parsed robots.txt for {domain}")
            else:
                # If robots.txt doesn't exist (404), everything is allowed
                parser.parse([])
                logger.warning(
                    f"robots.txt returned {response.status_code} for {domain} — "
                    f"assuming all paths allowed"
                )

            self._parsers[domain] = parser

        except Exception as e:
            error_msg = f"Failed to fetch robots.txt for {domain}: {e}"
            logger.error(error_msg)
            self._fetch_errors[domain] = error_msg
            # Conservative: create a parser that allows nothing if we can't check
            parser = RobotFileParser()
            parser.parse(["User-agent: *", "Disallow: /"])
            self._parsers[domain] = parser

    def is_allowed(self, url: str, user_agent: str = "*") -> bool:
        """Check if the given URL is allowed for scraping."""
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"

        parser = self._parsers.get(domain)
        if parser is None:
            logger.warning(f"No robots.txt loaded for {domain} — denying access")
            return False

        allowed = parser.can_fetch(user_agent, url)
        status = "ALLOWED" if allowed else "BLOCKED"
        logger.info(f"robots.txt {status}: {url}")
        return allowed

    def get_crawl_delay(self, url: str, user_agent: str = "*") -> float | None:
        """Get the crawl-delay directive if specified."""
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"

        parser = self._parsers.get(domain)
        if parser is None:
            return None

        try:
            delay = parser.crawl_delay(user_agent)
            return float(delay) if delay else None
        except Exception:
            return None

    def get_compliance_report(self) -> dict:
        """Generate a compliance report for all checked domains."""
        return {
            "domains_checked": list(self._parsers.keys()),
            "fetch_errors": self._fetch_errors,
            "total_domains": len(self._parsers),
        }
