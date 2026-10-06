"""Uçtan uca testler için sahte toplayıcı, sahte LLM ve sentetik sayfa üreticileri."""
from datetime import date
from arac_eksper.collector.base import FetchResult
from arac_eksper.llm.client import LLMUnavailable
from arac_eksper.schemas import DescriptionFindings, Evidence


def list_html(items):
    """items: [(ilan_no, fiyat, baslik)] — yıl 2022, km 60.000 sabit (aynı emsal kümesi)."""
    rows = "".join(f'''<div class="list-item"><a class="ilan-link" href="/ilan/{no}">x</a>
        <span class="ilan-no">{no}</span><h3 class="baslik">{baslik}</h3><span class="fiyat">{fiyat:,} TL</span>
        <span class="yil">2022</span><span class="km">60.000</span><span class="il">Bursa</span><span class="ilce">Nilüfer</span>
        <span class="ilan-tarihi">5 Ekim 2026</span></div>'''.replace(",", ".") for no, fiyat, baslik in items)
    return f"<html><body>{rows}</body></html>"


def detail_html(no, fiyat, baslik=None, aciklama="Araç ilk sahibinden, bakımlı.", tavan="orijinal",
                hasar="Hayır"):
    baslik = baslik or f"Temiz Megane {no}"   # aynı başlık+yıl+km = aynı araç sayılır (yeniden yayın)
    info = {"İl / İlçe": "Bursa / Nilüfer", "İlan Tarihi": "5 Ekim 2026", "Marka": "Renault", "Seri": "Megane",
            "Model": "1.5 dCi Touch", "Yıl": "2022", "Kilometre": "60.000", "Vites": "Otomatik",
            "Yakıt Tipi": "Dizel", "Kimden": "Sahibinden", "Ağır Hasar Kayıtlı": hasar}
    items = "".join(f'<div class="info-item"><span class="label">{k}</span><span class="value">{v}</span></div>'
                    for k, v in info.items())
    return f'''<html><body><span class="ilan-no">{no}</span><h1 class="baslik">{baslik}</h1>
        <span class="fiyat">{fiyat:,} TL</span><div class="info-list">{items}</div>
        <div class="aciklama">{aciklama}</div>
        <div class="part" data-name="tavan" data-state="{tavan}"></div>
        <div class="part" data-name="motor_kaputu" data-state="orijinal"></div></body></html>'''.replace(",", ".", 1)


def ok(html):
    return FetchResult(status="OK", html=html, final_url="u")


def blocked(note="doğrulama/engel sayfası"):
    return FetchResult(status="BLOCKED", final_url="u", note=note)


class FakeCollector:
    def __init__(self, lists, details=None, auto_prices=None):
        self.lists = list(lists)          # sırayla dönen liste yanıtları (son eleman tekrar edilir)
        self.details = details or {}      # ilan_no -> FetchResult
        self.auto_prices = auto_prices or {}   # ilan_no -> fiyat: listede olup details'te olmayanlar için
        self.list_calls = 0
        self.detail_calls = []

    async def fetch_list(self, url):
        self.list_calls += 1
        return self.lists.pop(0) if len(self.lists) > 1 else self.lists[0]

    async def fetch_detail(self, url):
        no = url.rstrip("/").split("/")[-1]
        self.detail_calls.append(no)
        if no not in self.details and no in self.auto_prices:
            return ok(detail_html(no, self.auto_prices[no]))
        return self.details[no]


class FakeLLM:
    """Açıklama 'ilk sahibinden' içeriyorsa olumlu sinyal döner; kırmızı bayrak yok → tek geçiş."""
    def __init__(self):
        self.calls = 0

    def parse_structured(self, system_prompt, user_prompt, response_model, model_name=None):
        self.calls += 1
        return DescriptionFindings(
            sase_direk_podye_islem="yok_beyan", airbag="orijinal_beyan", motor_sanziman="sorunsuz_beyan",
            km_degisimi_suphesi=False, tramer_tutari=0,
            olumlu_sinyaller=[Evidence(etiket="ilk sahibinden", alinti="ilk sahibinden")]
            if "ilk sahibinden" in user_prompt.lower() else [])


class DownLLM:
    def parse_structured(self, *a, **k):
        raise LLMUnavailable("havuz yok")
