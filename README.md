# APIx — Airfare Price Index

APIx is a real-time airfare inflation tracking prototype built for MoSPI / DGCA. It features a persistent, deterministic data pipeline that pulls fares, validates them via Pydantic, applies IQR outlier removal, and computes a chain-based Laspeyres index weighted by DGCA passenger volumes. The project includes a Bloomberg-style institutional dashboard for monitoring the index and data quality.

## How to Run

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Install Playwright browsers (optional, for live scraping):**
   ```bash
   playwright install chromium
   ```

3. **Start the FastAPI server:**
   ```bash
   python -m uvicorn main:app --host 0.0.0.0 --port 8000
   ```

4. **Access the Dashboard:**
   Open [http://localhost:8000](http://localhost:8000) in your web browser.
