from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Dict, Any
from enum import Enum
from datetime import date, datetime

class PartState(str, Enum):
    ORIGINAL = "orijinal"
    LOCAL_PAINT = "lokal_boyali"
    PAINTED = "boyali"
    REPLACED = "degisen"
    UNKNOWN = "belirtilmemis"

class SearchCriteria(BaseModel):
    marka: str
    model: str
    seri: Optional[str] = None
    max_butce: int
    min_butce: Optional[int] = None
    min_yil: Optional[int] = None
    max_km: Optional[int] = None
    vites: Optional[Literal["manuel", "otomatik", "yari_otomatik"]] = None
    yakit: Optional[Literal["benzin", "dizel", "lpg", "hibrit", "elektrik"]] = None
    il: Optional[str] = None
    kimden: Literal["sahibinden", "galeriden", "hepsi"] = "hepsi"

class ListingSummary(BaseModel):
    ilan_no: str
    url: str
    baslik: str
    marka: str = ""
    model: str = ""
    fiyat: int
    yil: int
    km: int
    il: str
    ilce: Optional[str] = None
    ilan_tarihi: date
    source: str = "list"

class ListingDetail(ListingSummary):
    seri: Optional[str] = None
    paket: Optional[str] = None
    vites: Optional[str] = None
    yakit: Optional[str] = None
    kasa_tipi: Optional[str] = None
    motor_hacmi: Optional[str] = None
    renk: Optional[str] = None
    kimden: Optional[str] = None
    agir_hasar_kayitli: Optional[bool] = None
    parts: Dict[str, PartState] = Field(default_factory=dict)
    tramer_tutari_yapilandirilmis: Optional[int] = None
    aciklama: str
    fetched_at: datetime
    raw_html_path: Optional[str] = None

class Evidence(BaseModel):
    etiket: str
    alinti: str

class DescriptionFindings(BaseModel):
    tramer_tutari: Optional[int] = None
    sase_direk_podye_islem: Literal["yok_beyan", "var", "belirsiz"]
    sase_alinti: Optional[str] = None
    airbag: Literal["orijinal_beyan", "acmis", "belirsiz"]
    airbag_alinti: Optional[str] = None
    motor_sanziman: Literal["sorunsuz_beyan", "degisen", "sorunlu", "belirsiz"]
    motor_alinti: Optional[str] = None
    km_degisimi_suphesi: bool
    agir_hasar_beyan: Literal["yok_beyan", "var", "belirsiz"] = "belirsiz"   # pert / çekme belgeli / ağır hasar
    agir_hasar_alinti: Optional[str] = None
    dogrulanamayan_iddia: bool = False   # LLM olumsuz iddia kurdu ama alıntısı metinde doğrulanamadı → 🟢 olamaz
    olumlu_sinyaller: List[Evidence] = Field(default_factory=list)
    olumsuz_sinyaller: List[Evidence] = Field(default_factory=list)
    dolandiricilik_sinyalleri: List[Evidence] = Field(default_factory=list)
    belirsiz_ifadeler: List[Evidence] = Field(default_factory=list)

class MarketStats(BaseModel):
    n: int
    medyan: int
    p25: int
    p75: int
    guven: str

class Verdict(BaseModel):
    ilan_no: str
    etiket: Literal["ALINIR", "DUSUNULEBILIR", "ALINMAZ"]
    guven_skoru: float
    veri_tamlik: float
    hard_fails: List[str] = Field(default_factory=list)
    artilar: List[str] = Field(default_factory=list)
    eksiler: List[str] = Field(default_factory=list)
    piyasa: Optional[MarketStats] = None
    tavsiye_teklif: Optional[int] = None
    ust_sinir: Optional[int] = None
    ekspertiz_kontrol_listesi: List[str] = Field(default_factory=list)
    trace: List[Dict[str, Any]] = Field(default_factory=list)  # karar dökümü: [{kural, puan}]
    beklemede: bool = False  # LLM erişilemedi, analiz bekliyor
