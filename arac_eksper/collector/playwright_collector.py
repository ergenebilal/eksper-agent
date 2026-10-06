import asyncio
import random
import time
import gzip
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from playwright.async_api import async_playwright
from arac_eksper.collector.base import Collector, FetchResult
from arac_eksper.config.settings import settings
from arac_eksper.parser.selectors import Selectors
from sqlalchemy.orm import Session
from arac_eksper.storage.models import FetchLog

BLOCK_MARKERS = ["Bireysel Oturum Aç", "Bireysel Giriş", "Güvenlik Kontrolü", "cf-browser-verification", "Ray ID"]

class PlaywrightCollector(Collector):
    def __init__(self, db: Session):
        self.db = db
        self.profile_dir = settings.browser_profile_dir
        Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
        Path("data/raw").mkdir(parents=True, exist_ok=True)
        
    def _check_rate_limit(self) -> bool:
        # DB tabanlı Token Bucket
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        count = self.db.query(FetchLog).filter(FetchLog.timestamp >= one_hour_ago).count()
        return count < settings.max_pages_per_hour
        
    async def _fetch(self, url: str, is_detail: bool) -> FetchResult:
        if not self._check_rate_limit():
            print(f"Rate limit aşıldı! Saatte max {settings.max_pages_per_hour} sayfa.")
            return FetchResult(status="ERROR", final_url=url)
            
        await asyncio.sleep(random.uniform(8, 20))
        
        async with async_playwright() as p:
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=self.profile_dir,
                headless=False, # Spec: headed mod
                viewport={'width': 1280, 'height': 800}
            )
            page = await browser.new_page()
            
            try:
                response = await page.goto(url, wait_until="domcontentloaded")
                status_code = response.status if response else 0
                
                if status_code in [403, 429]:
                    self._log_fetch(url, "BLOCKED")
                    await browser.close()
                    return FetchResult(status="BLOCKED", final_url=url)
                    
                if status_code == 404:
                    self._log_fetch(url, "NOT_FOUND")
                    await browser.close()
                    return FetchResult(status="NOT_FOUND", final_url=url)
                    
                html = await page.content()
                
                # Block Markers
                if any(marker in html for marker in BLOCK_MARKERS):
                    self._log_fetch(url, "BLOCKED")
                    await browser.close()
                    return FetchResult(status="BLOCKED", final_url=url)
                    
                # Eğer detay sayfasıysa doğal okuma simülasyonu
                if is_detail:
                    for _ in range(5):
                        await page.mouse.wheel(0, random.randint(200, 600))
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                    html = await page.content()
                    
                self._log_fetch(url, "OK")
                
                # Gzip ham HTML kaydet
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                ilan_no = "list"
                if is_detail:
                    import re
                    m = re.search(r'-(\d+)$', url)
                    if m: ilan_no = m.group(1)
                
                save_dir = Path("data/raw") / ilan_no
                save_dir.mkdir(parents=True, exist_ok=True)
                save_path = save_dir / f"{timestamp}.html.gz"
                
                with gzip.open(save_path, 'wt', encoding='utf-8') as f:
                    f.write(html)
                    
                await browser.close()
                return FetchResult(status="OK", html=html, final_url=url, saved_path=str(save_path))
                
            except Exception as e:
                print(f"Playwright error: {e}")
                self._log_fetch(url, "ERROR")
                await browser.close()
                return FetchResult(status="ERROR", final_url=url)
                
    def _log_fetch(self, url: str, status: str):
        log = FetchLog(url=url, status=status)
        self.db.add(log)
        self.db.commit()

    async def fetch_list(self, url: str) -> FetchResult:
        return await self._fetch(url, is_detail=False)
        
    async def fetch_detail(self, url: str) -> FetchResult:
        return await self._fetch(url, is_detail=True)
