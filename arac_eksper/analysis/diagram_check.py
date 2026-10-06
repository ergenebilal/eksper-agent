"""Hasar şeması tutarlılığı (R0, 2026-10-07 gerçek sayfa bulgusu).

Satıcı boya/değişen şemasını doldurmadığında site 13 parçanın hepsini "orijinal" gösterir ve "Aracın tüm parçaları
orijinaldır" yazar: DOM'da gerçek bir "hepsi orijinal" beyanından AYIRT EDİLEMEZ (13 gerçek ilanla doğrulandı; "komple boyalı"
başlıklı üç ilanın şeması tamamen orijinaldi). Bu yüzden kontrol anlam düzeyindedir:
şema tamamen orijinal + başlık/açıklama olumsuzlanmamış bir boya/değişen beyanı içeriyor → şema güvenilmez, parçalar
BİLİNMİYOR sayılır (kural 6: bilinmeyen "iyi" sayılmaz). LLM kullanmaz: ön hesapta da anında çalışır.
"""
import re

from arac_eksper.schemas import ListingDetail, PartState

_FOLD = str.maketrans("çşğöüıâîûÇŞĞÖÜİÂÎÛ", "csgouiaiucsgouiaiu")
# Kaporta parçaları (şemadaki 13 parça ve eş anlamlıları) — "değiş*" fiili yalnız bunların yakınında sayılır
_GOVDE = ("kaput", "kapi", "camurluk", "tampon", "tavan", "bagaj", "panel", "parca", "direk", "marspiyel", "kaporta", "kasa")
_NEG = ("yok", "yoktur", "bulunmamaktadir", "bulunmamakta", "bulunmuyor", "degil", "degildir", "olmamistir", "yapilmamistir")
_TOKEN = re.compile(r"[a-z0-9]+")


def _fold(text: str) -> str:
    return (text or "").replace("İ", "i").replace("I", "ı").translate(_FOLD).lower()


_POS = ("var", "vardir", "mevcut", "mevcuttur", "bulunmaktadir", "bulunuyor")
_STOP = ("ama", "fakat", "ancak", "lakin", "sadece")


def _negated(toks: list[str], i: int, span: int = 4) -> bool:
    """Beyandan sonraki birkaç kelimede olumsuzluk var mı? Olumlu fiil ya da 'ama/fakat' görülünce arama durur
    ("boyası var ama değişeni yok" → boya beyanı olumsuzlanmamış)."""
    for t in toks[i + 1:i + 1 + span]:
        if t in _POS or t in _STOP:
            return False
        if t in _NEG:
            return True
    return False


def boya_degisen_beyanlari(text: str) -> list[str]:
    """Metindeki olumsuzlanmamış boya/değişen beyanları (kısa alıntılar, katlanmış metinden)."""
    toks = _TOKEN.findall(_fold(text))
    out = []
    for i, t in enumerate(toks):
        hit = False
        if t.startswith("boya") and not t.startswith(("boyasiz", "boyaci")):
            # boyali, boyalidir, boyadir, boyandi, boyanmis, boyasi var, boya var — "boya koruma(si)" hariç;
            # "boya islemi yoktur", "boyasi yok" gibi olumsuzlamaları _negated yakalar
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            hit = not (t == "boya" and nxt.startswith("koruma"))
        elif t.startswith(("rotus", "rotuslu")):
            hit = True
        elif t.startswith("degisen") and not t.startswith("degisensiz"):
            hit = True
        elif t.startswith(("degisti", "degismis", "degistirildi", "degistirilmis")):
            hit = any(g in w for w in toks[max(0, i - 5):i] for g in _GOVDE)
        if hit and not _negated(toks, i):
            out.append(" ".join(toks[max(0, i - 2):i + 3]))
    return out


def tamami_orijinal(parts: dict) -> bool:
    vals = [PartState(v) if not isinstance(v, PartState) else v for v in (parts or {}).values()]
    return len(vals) >= 10 and all(v == PartState.ORIGINAL for v in vals)


def sema_kontrolu(detail: ListingDetail) -> tuple[ListingDetail, str | None]:
    """Şema 'tamamı orijinal' iken metin boya/değişen diyorsa: parçalar bilinmiyor sayılır + uyarı metni döner."""
    if not tamami_orijinal(detail.parts):
        return detail, None
    kanit = boya_degisen_beyanlari(f"{detail.baslik}\n{detail.aciklama}")
    if not kanit:
        return detail, None
    uyari = (f"Hasar şeması 'tamamı orijinal' gösteriyor ama ilan metni boya/değişen diyor (“{kanit[0]}”): "
             "şema doldurulmamış olabilir; parçalar bilinmiyor sayıldı.")
    return detail.model_copy(update={"parts": {}}), uyari
