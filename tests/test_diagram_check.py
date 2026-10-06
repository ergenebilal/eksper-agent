"""Boş/doldurulmamış hasar şemasını "orijinal" sanma hatası (R0 bulgusu). İfadeler gerçek ilanlardan alınmıştır."""
from datetime import datetime, timezone

import pytest

from arac_eksper.analysis.diagram_check import boya_degisen_beyanlari, sema_kontrolu, tamami_orijinal
from arac_eksper.schemas import ListingDetail

PARCALAR = ["on_tampon", "arka_tampon", "motor_kaputu", "bagaj_kapagi", "tavan", "sol_on_camurluk", "sag_on_camurluk",
            "sol_arka_camurluk", "sag_arka_camurluk", "sol_on_kapi", "sag_on_kapi", "sol_arka_kapi", "sag_arka_kapi"]


@pytest.mark.parametrize("metin", [
    "HATASIZ DEĞİSENSİZ GÜNEŞ YANIKLI KOMPLE BOYALI",
    "Degişensiz komple boyalı",
    "Komple temizlik boyalı doğan",
    "sağ ön çamurlukta boya vardır",
    "1 DEĞİŞEN SAĞ ÖN kapı",
    "2 parça boya bulunmaktadır",
    "kaput rötuşlu",
    "sol arka kapı değiştirildi",
    "boyası var ama değişeni yok",
])
def test_paint_or_change_declarations_are_found(metin):
    assert boya_degisen_beyanlari(metin)


@pytest.mark.parametrize("metin", [
    "88 KİLOMETREDE DEĞİŞENSİZ BOYASIZ KAYITSIZ",
    "darbe boya hata yok.",
    "Aracımda değişen,işlem vs bulunmamaktadır.",
    "Boyasız Göcük Düzeltme Yapılmıştır. Boya İşlemi Yoktur.",
    "termostat değiştirildi, filtreleri değişmiştir",
    "AMASÖR DEĞİŞECEK SES YAPIYOR",
    "Far değişiminden dolayı",
    "seramik boya koruma uygulandı",
    "boyalı veya değişen parçası yoktur",
    "HATASIZ BOYASIZ FULL SERVİS BAKIMLI",
])
def test_negations_and_non_body_changes_are_not_declarations(metin):
    assert boya_degisen_beyanlari(metin) == []


def car(parts, baslik="", aciklama=""):
    return ListingDetail(ilan_no="1", url="", baslik=baslik, fiyat=1, yil=2015, km=1, il="", aciklama=aciklama,
                         ilan_tarihi=datetime.now().date(), fetched_at=datetime.now(timezone.utc), parts=parts)


def test_all_original_diagram_with_paint_text_becomes_unknown():
    d, uyari = sema_kontrolu(car({p: "orijinal" for p in PARCALAR}, baslik="Degişensiz komple boyalı"))
    assert d.parts == {} and "doldurulmamış olabilir" in uyari and "komple boyali" in uyari


def test_all_original_diagram_without_conflict_is_kept():
    parts = {p: "orijinal" for p in PARCALAR}
    d, uyari = sema_kontrolu(car(parts, baslik="HATASIZ BOYASIZ", aciklama="Değişen yok."))
    assert uyari is None and len(d.parts) == 13


def test_filled_diagram_is_trusted_even_if_text_mentions_paint():
    parts = {p: "orijinal" for p in PARCALAR} | {"motor_kaputu": "boyali"}
    d, uyari = sema_kontrolu(car(parts, baslik="PARÇA BOYALI"))
    assert uyari is None and d.parts["motor_kaputu"] == "boyali"
    assert tamami_orijinal(parts) is False and tamami_orijinal({}) is False
