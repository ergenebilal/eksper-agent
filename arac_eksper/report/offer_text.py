"""Satıcıya gidecek (kullanıcının KOPYALAYIP kendisinin göndereceği) teklif metni. Deterministik şablon: LLM yazmaz.
Üst sınır ASLA metne girmez; yalnız açılış teklifi. Yalnızca ilanda yapısal olarak görünen kusurlar anılır."""
from arac_eksper.schemas import ListingDetail, PartState, Verdict

_DURUM = {PartState.REPLACED: "değişen", PartState.PAINTED: "boyalı", PartState.LOCAL_PAINT: "lokal boyalı"}
_SIRA = [PartState.REPLACED, PartState.PAINTED, PartState.LOCAL_PAINT]


def _kusurlar(detail: ListingDetail, limit: int = 3) -> list[str]:
    out = []
    for state in _SIRA:
        for name, st in detail.parts.items():
            if st == state and "tampon" not in name:
                out.append(f"{name.replace('_', ' ')} {_DURUM[st]}")
    return out[:limit]


def whatsapp_text(detail: ListingDetail, verdict: Verdict) -> str | None:
    if verdict.beklemede or verdict.etiket == "ALINMAZ" or not verdict.tavsiye_teklif:
        return None
    arac = " ".join(x for x in (str(detail.yil), detail.marka, detail.model) if x)
    teklif = f"{verdict.tavsiye_teklif:,}".replace(",", ".")
    kusur = _kusurlar(detail)
    giris = f"İlanda {', '.join(kusur)} bilgisi görünüyor; bunu da dikkate alarak " if kusur else ""
    return (f"Merhaba, {arac} ilanınızla ilgileniyorum. {giris}ekspertiz şartıyla {teklif} TL teklif etmek isterim. "
            "Uygun olursa aracı görmek için ne zaman müsait olursunuz?")
