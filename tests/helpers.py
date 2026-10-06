"""Uçtan uca testler için sahte toplayıcı, sahte LLM ve sentetik sayfa üreticileri."""
from datetime import date
from arac_eksper.collector.base import FetchResult
from arac_eksper.llm.client import LLMUnavailable
from arac_eksper.schemas import DescriptionFindings, Evidence


PART_CSS = {"on_tampon": "front-bumper", "arka_tampon": "rear-bumper", "motor_kaputu": "front-hood",
            "bagaj_kapagi": "rear-hood", "tavan": "roof", "sol_on_camurluk": "front-left-mudguard"}
STATE_CSS = {"orijinal": "original-new", "boyali": "painted-new", "lokal_boyali": "localpainted-new", "degisen": "changed-new"}


def _tl(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def list_html(items):
    """items: [(ilan_no, fiyat, baslik)] — yıl 2022, km 60.000 sabit (aynı emsal kümesi). Gerçek arama sayfası yapısı."""
    head = ("<thead><tr><td></td><td>Marka</td><td>Seri</td><td>Model</td><td>İlan Başlığı</td><td>Yıl</td><td>KM</td>"
            "<td>Fiyat</td><td>İlan Tarihi</td><td>İl / İlçe</td><td></td></tr></thead>")
    rows = "".join(f'''<tr class="searchResultsItem" data-id="{no}"><td></td>
        <td class="searchResultsTagAttributeValue">Renault</td><td class="searchResultsTagAttributeValue">Megane</td>
        <td class="searchResultsTagAttributeValue">1.5 dCi Touch</td>
        <td class="searchResultsTitleValue"><a class="classifiedTitle" href="/ilan/{no}">{baslik}</a></td>
        <td class="searchResultsAttributeValue">2022</td><td class="searchResultsAttributeValue">60.000</td>
        <td class="searchResultsPriceValue">{_tl(fiyat)} TL</td>
        <td class="searchResultsDateValue"><span>05 Ekim</span><br><span>2026</span></td>
        <td class="searchResultsLocationValue">Bursa<br>Nilüfer</td></tr>''' for no, fiyat, baslik in items)
    return f"<html><body><table>{head}<tbody>{rows}</tbody></table></body></html>"


def detail_html(no, fiyat, baslik=None, aciklama="Araç ilk sahibinden, bakımlı.", tavan="orijinal",
                hasar="Hayır"):
    """Gerçek ilan sayfası yapısı (dl.classifiedInfoList, .car-parts sınıfları)."""
    baslik = baslik or f"Temiz Megane {no}"   # aynı başlık+yıl+km = aynı araç sayılır (yeniden yayın)
    info = {"İlan No": no, "İlan Tarihi": "05 Ekim 2026", "Marka": "Renault", "Seri": "Megane",
            "Model": "1.5 dCi Touch", "Yıl": "2022", "Yakıt / Motor Tipi": "Dizel", "Vites": "Otomatik", "KM": "60.000",
            "Kimden": "Sahibinden", "Ağır Hasar Kayıtlı": hasar}
    return _detail_page(baslik, fiyat, info, aciklama, {"tavan": tavan, "motor_kaputu": "orijinal"})


def _detail_page(baslik, fiyat, info, aciklama, parts):
    items = "".join(f'<div class="classifiedInfoItem"><dt>{k}</dt><dd>{v}</dd></div>' for k, v in info.items())
    divs = "".join(f'<div class="{PART_CSS[k]} {STATE_CSS[v]}"></div>' for k, v in parts.items())
    return (f'<html><body><div class="classifiedDetailTitle"><h1>{baslik}</h1></div>'
            f'<div class="classifiedInfo"><h3 class="classifiedPriceValue">{_tl(fiyat)} TL</h3>'
            f'<dl class="classifiedInfoList">{items}</dl></div>'
            f'<div id="classifiedDescription">{aciklama}</div><div class="car-parts">{divs}</div></body></html>')


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
