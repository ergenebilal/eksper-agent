"""Gerçek maliyet (R2.2 + R2.3): ilan metnindeki YAPILACAK masraflar + km'si gelmiş ağır bakım → tahmini TL aralığı.

LLM'siz, kural tabanlı (kural 5: tutar uydurulmaz). Kalem tanıma `masraf_kb.yaml` anahtar kelimeleriyle; bir anahtar kelime
ancak yakınında İHTİYAÇ ifadesi varsa ("değişecek", "yapılacak", "gerekiyor", "bitik", "ses yapıyor") masraf sayılır;
TAMAMLANMIŞ ifadesi ("yapıldı", "yeni", "sıfır", "değiştirildi") ya da olumsuzluk ("yağ kaçağı yoktur") varsa sayılmaz.
Her bulgu ilan metninden birebir alıntı taşır. Tutar yalnız ONAYLI kalemlerden, segment aralığı olarak gelir.
"""
import re

from arac_eksper.analysis import masraf_kb
from arac_eksper.analysis.models_kb import bakim_kalemleri
from arac_eksper.schemas import ListingDetail

_FOLD = str.maketrans("çşğöüıâîûÇŞĞÖÜÂÎÛ", "csgouiaiucsgouaiu")
_TOK = re.compile(r"[a-z0-9]+")
_NEED_WORDS = {"gerekiyor", "gerekli", "gerek", "lazim", "bitik", "bitmis", "bitmek", "gelmis", "geldi", "arizali",
               "sorunlu", "ses", "sesi", "titriyor", "titreme", "atiyor", "kaciriyor", "yaniyor", "sizdiriyor", "kacak",
               "kacagi", "eksiltiyor", "yakiyor", "sogutmuyor", "calismiyor", "bozuk", "masrafi", "yapilmali", "degismeli"}
_NEED_RE = re.compile(r"^(degis|deyis|yapil|basil|bakil|boyan|tamir|onaril|yenilen|takil)\w*(ecek|acak|cek|cak|meli|mali)\w*$")
_DONE_WORDS = {"yapildi", "yapilmistir", "yapilmis", "yapilmisdir", "degisti", "degismistir", "degistirildi", "degistirilmistir",
               "yenilendi", "yenilenmistir", "yenilenmis", "yeni", "sifir", "sifirdir", "takildi", "takilmistir", "bakimli",
               "yaptirildi", "yaptirdik", "degisik", "sorunsuz", "kusursuz", "aktif", "calisiyor"}
_NEG = {"yok", "yoktur", "bulunmamaktadir", "degil", "degildir"}
_STOP = {"ama", "fakat", "ancak", "lakin", "harici", "haricinde"}


def _fold(text: str) -> str:
    return (text or "").replace("İ", "i").replace("I", "ı").translate(_FOLD).lower()


def _is_need(t: str) -> bool:
    return t in _NEED_WORDS or bool(_NEED_RE.match(t))


def _tokens(text: str):
    folded = _fold(text)
    return [(m.group(0), m.start(), m.end()) for m in _TOK.finditer(folded)]


def _kw_tokens(kw: str) -> list[str]:
    return [t for t in _TOK.findall(_fold(kw))]


def _need_after(toks, j: int, span: int = 4) -> int | None:
    """Anahtar kelimeden (son token j) sonra ihtiyaç kelimesinin konumu; tamamlanmış/olumsuz/ayraç önce gelirse None."""
    for k in range(j + 1, min(len(toks), j + 1 + span)):
        t = toks[k][0]
        if t in _DONE_WORDS or t in _STOP:
            return None
        if _is_need(t):
            nxt = [toks[x][0] for x in range(k + 1, min(len(toks), k + 3))]
            return None if any(n in _NEG for n in nxt) else k
    return None


def metinden_masraflar(text: str, kalem_map: dict[str, dict]) -> list[dict]:
    """[{kod, ad, alinti}] — her kalem bir kez; alıntı orijinal metinden."""
    toks, found, seen, claimed = _tokens(text), [], set(), set()
    # Uzun (özgül) anahtar kelime önce: "baskı balata" (debriyaj), "balata"dan (fren) önce eşleşir; kullanılan token tekrar sayılmaz
    pairs = sorted(((kod, _kw_tokens(kw)) for kod, k in kalem_map.items() for kw in k.get("anahtar_kelimeler") or []),
                   key=lambda p: -len(p[1]))
    for kod, kt in pairs:
        if not kt or kod in seen:
            continue
        for i in range(len(toks) - len(kt) + 1):
            if any(i + n in claimed for n in range(len(kt))):
                continue
            if not all(toks[i + n][0].startswith(kt[n]) for n in range(len(kt))):
                continue
            last = i + len(kt) - 1
            # anahtar kelimenin kendisi ihtiyaç bildiriyor olabilir ("basılacak", "boyanacak", "bitik")
            need = last if _is_need(toks[last][0]) else _need_after(toks, last)
            if need is None:
                continue
            found.append({"kod": kod, "ad": kalem_map[kod]["ad"], "alinti": text[toks[i][1]:toks[need][2]].strip()})
            seen.add(kod)
            claimed.update(range(i, need + 1))
            break
    return found


def _done_in_text(text: str, kalem: dict) -> bool:
    """Metin bu kalemin YAPILDIĞINI söylüyor mu? ("triger seti yapıldı", "ağır bakımı yapıldı")"""
    toks = _tokens(text)
    keys = [_kw_tokens(kw) for kw in (kalem.get("anahtar_kelimeler") or [])] + [["agir", "bakim"]]
    for kt in keys:
        for i in range(len(toks) - len(kt) + 1):
            if all(toks[i + n][0].startswith(kt[n]) for n in range(len(kt))):
                after = [toks[x][0] for x in range(i + len(kt), min(len(toks), i + len(kt) + 4))]
                if any(a in _DONE_WORDS or a.startswith(("yapil", "degisti", "degistiril", "yenilen")) for a in after):
                    return True
    return False


def gercek_maliyet(detail: ListingDetail, kb_kalem: dict[str, dict] | None = None, tum_kalem: dict[str, dict] | None = None,
                   model_kb: list[dict] | None = None, seg: str | None = None) -> dict | None:
    """Tahmini gerçek maliyet. Kalem yoksa None. Onaysız kalem listelenir ama tutarı yoktur (aralik None).
    kesinlik: 'beyan' = ilan metni söylüyor; 'olasi' = km'si gelmiş bakım, yapıldığı belirtilmemiş."""
    onayli = masraf_kb.kalemler() if kb_kalem is None else kb_kalem
    tum = masraf_kb.kalemler(include_unapproved=True) if tum_kalem is None else tum_kalem
    seg = seg or masraf_kb.segment(detail.marka, detail.seri or detail.model)
    text = f"{detail.baslik}\n{detail.aciklama}"
    kalemler = [dict(x, kesinlik="beyan") for x in metinden_masraflar(text, tum)]
    for b in bakim_kalemleri(detail, model_kb):
        kod = b.get("masraf")
        if kod and kod in tum and kod not in {k["kod"] for k in kalemler} and not _done_in_text(text, tum[kod]):
            kalemler.append({"kod": kod, "ad": tum[kod]["ad"], "alinti": None, "kesinlik": "olasi",
                             "neden": f"{b['aralik_km'][0]:,}-{b['aralik_km'][1]:,} km'de yapılır; ilanda yapıldığı yazmıyor".replace(",", ".")})
    if not kalemler:
        return None
    for k in kalemler:
        a = masraf_kb.aralik(k["kod"], seg, onayli)
        k["aralik"] = list(a) if a else None
    toplam = lambda kes, i: sum(k["aralik"][i] for k in kalemler if k["aralik"] and k["kesinlik"] in kes)
    return {"segment": seg, "kalemler": kalemler,
            "beyan_alt": toplam(("beyan",), 0), "beyan_ust": toplam(("beyan",), 1),
            "olasi_alt": toplam(("olasi",), 0), "olasi_ust": toplam(("olasi",), 1),
            "toplam_alt": detail.fiyat + toplam(("beyan",), 0),
            "toplam_ust": detail.fiyat + toplam(("beyan", "olasi"), 1),
            "tutarsiz_kalem": sum(1 for k in kalemler if not k["aralik"])}


def teklife_uygula(b: dict | None, gm: dict | None) -> dict | None:
    """İlanda BEYAN edilen masrafların onaylı alt tahminini teklif değerlerinden düşer (olası bakım düşülmez).
    Sıra korunur: açılış ≤ anlaşma ≤ üst sınır; 5.000'e aşağı yuvarlanır."""
    if not b or not gm or gm.get("beyan_alt", 0) <= 0:
        return b
    from arac_eksper.analysis.offer import floor_to_5000
    d = gm["beyan_alt"]
    for key in ("hedef", "acilis", "anlasma", "ust_sinir"):
        if b.get(key) is not None:
            b[key] = max(floor_to_5000(b[key] - d), 0)
    b["acilis"] = min(b["acilis"], b["anlasma"], b["ust_sinir"])
    b["anlasma"] = min(max(b["anlasma"], b["acilis"]), b["ust_sinir"])
    adet = sum(1 for k in gm["kalemler"] if k["kesinlik"] == "beyan" and k["aralik"])
    b["dayanak"].append(f"İlanda belirtilen masraflar ({adet} kalem, alt tahmin): −{d:,} TL".replace(",", "."))
    b["masraf_dusuldu"] = d
    return b
