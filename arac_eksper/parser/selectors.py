# UNVERIFIED — bu selector'lar ve BLOCK_MARKERS gerçek sahibinden HTML'iyle doğrulanmadı.
# Gerçek sayfalar tests/fixtures/real/ altına konunca YALNIZCA oradan çıkarılıp güncellenecek (CLAUDE.md kural 5).
class Selectors:
    LIST_ITEM = "div.list-item"
    LIST_ILAN_LINK = "a.ilan-link"
    LIST_ILAN_NO = "span.ilan-no"
    LIST_BASLIK = "h3.baslik"
    LIST_FIYAT = "span.fiyat"
    LIST_YIL = "span.yil"
    LIST_KM = "span.km"
    LIST_IL = "span.il"
    LIST_ILCE = "span.ilce"
    LIST_TARIH = "span.ilan-tarihi"
    LIST_NEXT_PAGE = "a.next-page"

    DETAIL_ILAN_NO = "span.ilan-no"
    DETAIL_BASLIK = "h1.baslik"
    DETAIL_FIYAT = "span.fiyat"
    DETAIL_INFO_LIST = "div.info-item"
    DETAIL_INFO_LABEL = "span.label"
    DETAIL_INFO_VALUE = "span.value"
    DETAIL_ACIKLAMA = "div.aciklama"

    DAMAGE_PART = "div.part"


# Engel/doğrulama sayfası işaretleri. Sıradan sayfalarda geçebilecek genel ifadeler
# ("Bireysel Giriş", "Ray ID" vb. — üst menüde/altbilgide olabilir) BİLEREK dışarıda.
# Karar tek başına marker'a değil, marker + beklenen ana elementin yokluğuna bağlıdır.
BLOCK_MARKERS = [
    "cf-browser-verification",
    "challenge-platform",
    "Just a moment",
    "Attention Required",
    "Access Denied",
    "_Incapsula_",
    "captcha",
]
