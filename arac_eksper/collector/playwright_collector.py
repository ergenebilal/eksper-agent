import asyncio
import gzip
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright
from sqlalchemy.orm import Session

from arac_eksper.collector import guard
from arac_eksper.collector.base import Collector, FetchResult
from arac_eksper.config.settings import DATA_DIR, settings
from arac_eksper.parser.selectors import Selectors, BLOCK_MARKERS
from arac_eksper.storage.models import FetchLog
from bs4 import BeautifulSoup
from arac_eksper.privacy import mask_phones


def detect_block(status_code: int, html: str, expected_selector: Optional[str]) -> bool:
    """Engel kararı: 403/429 VEYA (engel işareti + beklenen ana element yok).
    Tek başına marker yeterli değildir (sıradan sayfalarda da geçebilir); ana element
    bulunuyorsa sayfa sağlamdır."""
    if status_code in (403, 429):
        return True
    if not any(m.lower() in html.lower() for m in BLOCK_MARKERS):
        return False
    if expected_selector is None:
        return True
    return BeautifulSoup(html, "lxml").select_one(expected_selector) is None


class PlaywrightCollector(Collector):
    """Kullanıcının kendi tarayıcı profiliyle, görünür (headed) modda, düşük hacimli toplama.
    Fingerprint sahteciliği, proxy, CAPTCHA çözümü YOK (CLAUDE.md kural 3)."""

    def __init__(self, db: Session):
        self.db = db
        self.profile_dir = settings.browser_profile_dir
        Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "raw").mkdir(parents=True, exist_ok=True)

    def _check_rate_limit(self) -> bool:
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        count = self.db.query(FetchLog).filter(FetchLog.timestamp >= one_hour_ago).count()
        return count < settings.max_pages_per_hour

    def _log_fetch(self, url: str, status: str):
        self.db.add(FetchLog(url=url, status=status))
        self.db.commit()

    async def _navigate(self, url: str, is_detail: bool) -> tuple[int, str]:
        """Tarayıcı katmanı (testlerde değiştirilir). (HTTP durum kodu, HTML) döner."""
        async with async_playwright() as p:
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=self.profile_dir, headless=False,
                viewport={"width": 1280, "height": 800},
            )
            try:
                page = await browser.new_page()
                response = await page.goto(url, wait_until="domcontentloaded")
                status_code = response.status if response else 0
                if status_code not in (403, 429, 404) and is_detail:
                    for _ in range(5):  # doğal okuma: yumuşak kaydırma
                        await page.mouse.wheel(0, random.randint(200, 600))
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                return status_code, await page.content()
            finally:
                await browser.close()

    async def _sleep_between_requests(self):
        await asyncio.sleep(random.uniform(8, 20))

    async def _fetch(self, url: str, is_detail: bool) -> FetchResult:
        # 1) Backoff: engel bekleme süresi dolmadan hiçbir istek atılmaz.
        until = guard.is_blocked_now(self.db)
        if until:
            return FetchResult(status="BLOCKED", final_url=url,
                               note=f"engel beklemesi: {until.astimezone().strftime('%H:%M')} sonrasına kadar")

        # 2) Saatlik limit (kod seviyesinde zorunlu, config ile kapatılamaz).
        if not self._check_rate_limit():
            return FetchResult(status="RATE_LIMITED", final_url=url,
                               note=f"saatlik limit doldu ({settings.max_pages_per_hour} sayfa)")

        await self._sleep_between_requests()

        try:
            status_code, html = await self._navigate(url, is_detail)
        except Exception as e:  # noqa: BLE001
            self._log_fetch(url, "ERROR")
            return FetchResult(status="ERROR", final_url=url, note=f"tarayıcı hatası: {e}")

        if status_code == 404:
            self._log_fetch(url, "NOT_FOUND")
            return FetchResult(status="NOT_FOUND", final_url=url)

        expected = Selectors.DETAIL_ILAN_NO if is_detail else Selectors.LIST_ITEM
        if detect_block(status_code, html, expected):
            self._log_fetch(url, "BLOCKED")
            return FetchResult(status="BLOCKED", final_url=url, note="doğrulama/engel sayfası")

        self._log_fetch(url, "OK")

        ilan_no = "list"
        if is_detail:
            m = re.search(r"-?(\d{6,})(?:/|\?|$)", url)
            ilan_no = m.group(1) if m else "detail"
        save_dir = (DATA_DIR / "raw") / ilan_no
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.html.gz"
        with gzip.open(save_path, "wt", encoding="utf-8") as f:
            f.write(mask_phones(html))  # satıcı telefonu diske yazılmaz; HTML'i yeniden parse için çevrilmez (yalnız metin maskelenir)
        return FetchResult(status="OK", html=html, final_url=url, saved_path=str(save_path))

    async def fetch_list(self, url: str) -> FetchResult:
        return await self._fetch(url, is_detail=False)

    async def fetch_detail(self, url: str) -> FetchResult:
        return await self._fetch(url, is_detail=True)
