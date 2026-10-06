# R0.4 (2026-10-07): 18 gerçek ilan + 3 gerçek arama sayfasından (tests/fixtures/real) ÇIKARILDI; eklentinin
# extension/lib/selectors.js dosyasıyla aynı yapı. Değerler yalnız kaydedilmiş gerçek sayfalardan güncellenir (kural 5).
# Satıcıya ait hiçbir alan (ad, telefon, mağaza, profil) için seçici TANIMLANMAZ.
class Selectors:
    # Arama sonuçları: tablo satırı; başlıklar thead içinde TD; reklam satırı tr.nativeAd atlanır
    LIST_HEADER_CELLS = "thead td"
    LIST_ITEM = "tr.searchResultsItem:not(.nativeAd)"
    LIST_ILAN_NO_ATTR = "data-id"
    LIST_ILAN_LINK = "a.classifiedTitle"
    LIST_BASLIK = "td.searchResultsTitleValue"
    LIST_TAG = "td.searchResultsTagAttributeValue"          # Marka / Seri / Model (başlık sırasıyla)
    LIST_ATTR = "td.searchResultsAttributeValue"            # Yıl / KM (başlık sırasıyla)
    LIST_FIYAT = "td.searchResultsPriceValue"
    LIST_TARIH = "td.searchResultsDateValue"
    LIST_KONUM = "td.searchResultsLocationValue"            # "İl<br>İlçe"
    LIST_PAGES = "ul.pageNaviButtons"
    LIST_CURRENT_PAGE = "span.currentPage"

    # İlan detayı
    DETAIL_BASLIK = ".classifiedDetailTitle h1"
    DETAIL_FIYAT = "h3.classifiedPriceValue"
    DETAIL_INFO_LIST = ".classifiedInfoList .classifiedInfoItem"
    DETAIL_INFO_LABEL = "dt"
    DETAIL_INFO_VALUE = "dd"
    DETAIL_ACIKLAMA = "#classifiedDescription"

    # Hasar şeması: her parça bir div; 1. sınıf parça, 2. sınıf durum
    DAMAGE_PART = ".car-parts > div"


PART_CLASS = {
    "front-bumper": "on_tampon", "rear-bumper": "arka_tampon", "front-hood": "motor_kaputu", "rear-hood": "bagaj_kapagi",
    "roof": "tavan", "front-left-mudguard": "sol_on_camurluk", "front-right-mudguard": "sag_on_camurluk",
    "rear-left-mudguard": "sol_arka_camurluk", "rear-right-mudguard": "sag_arka_camurluk",
    "front-left-door": "sol_on_kapi", "front-right-door": "sag_on_kapi", "rear-left-door": "sol_arka_kapi",
    "rear-right-door": "sag_arka_kapi",
}
STATE_CLASS = {"original-new": "orijinal", "painted-new": "boyali", "localpainted-new": "lokal_boyali",
               "changed-new": "degisen"}       # tanınmayan sınıf → eklenmez (bilinmiyor sayılır)


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
