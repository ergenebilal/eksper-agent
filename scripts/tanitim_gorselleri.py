"""Tanıtım sayfası (/) görselleri: GERÇEK yan panel, örnek (uydurma) bir ilanla çizilir ve bölümleri kırpılır.
Panel tasarımı değişince yeniden çalıştırın:  uv run python scripts/tanitim_gorselleri.py
Çıktı: arac_eksper/web/static/tanitim/*.png. Siteye istek atılmaz; sunucu bellekte, LLM sahte (sabit bulgular)."""
import pathlib
import sys
import tempfile
import time
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from arac_eksper.analysis import belge as bg  # noqa: E402
from arac_eksper.config.settings import settings  # noqa: E402
from arac_eksper.schemas import DescriptionFindings, Evidence, MasrafEvidence  # noqa: E402
from arac_eksper.web import api, xray_app  # noqa: E402

OUT = ROOT / "arac_eksper" / "web" / "static" / "tanitim"
EXT = ROOT / "extension"
TOKEN = "t" * 32

ACIKLAMA = ("Aracım ilk sahibinden, tüm bakımları yetkili serviste yapıldı. Şase, podye ve airbagler orijinal. "
            "Sol ön çamurlukta lokal boya var, başka boya ve değişen yok. Tramer kaydı 12.400 TL. "
            "Klimanın gazı bitti, doldurulması lazım. Ağır bakımı 90 binde yapıldı. Ufak tefek çizikler mevcut.")
PARCALAR = {p: "orijinal" for p in ("on_tampon", "arka_tampon", "motor_kaputu", "bagaj_kapagi", "tavan", "sag_on_camurluk",
                                     "sol_arka_camurluk", "sag_arka_camurluk", "sol_on_kapi", "sag_on_kapi", "sol_arka_kapi",
                                     "sag_arka_kapi")}
PARCALAR["sol_on_camurluk"] = "lokal_boyali"


class OrnekLLM:
    def parse_structured(self, system_prompt, user_prompt, response_model, model_name=None):
        if response_model is bg.EkspertizBulgular:
            return bg.EkspertizBulgular(
                rapor_km=98_450, km_alinti="Kilometre: 98.450", tramer_tutari=12_400, tramer_alinti="Tramer kaydı: 12.400 TL",
                yapisal="temiz", yapisal_alinti="Şase, podye ve direkler: İşlem yok, temiz",
                parcalar=[bg.BelgeParca(parca="sol_on_camurluk", durum="lokal_boyali", alinti="Sol ön çamurluk: Lokal boyalı"),
                          bg.BelgeParca(parca="motor_kaputu", durum="boyali", alinti="Motor kaputu: Boyalı")],
                kusurlar=[bg.BelgeKusur(baslik="Ön balatalar bitmek üzere", ciddiyet="orta", alinti="Ön balatalar %20")])
        if response_model.__name__ == "Anlatim":
            from arac_eksper.analysis.compare import Anlatim
            raise ValueError("şablon anlatım kullanılsın")  # noqa: F841
        return DescriptionFindings(
            tramer_tutari=12_400, sase_direk_podye_islem="yok_beyan", sase_alinti="Şase, podye ve airbagler orijinal",
            airbag="orijinal_beyan", airbag_alinti="Şase, podye ve airbagler orijinal", motor_sanziman="belirsiz",
            km_degisimi_suphesi=False,
            olumlu_sinyaller=[Evidence(etiket="İlk sahibinden", alinti="ilk sahibinden"),
                              Evidence(etiket="Yetkili servis bakımlı", alinti="tüm bakımları yetkili serviste yapıldı")],
            olumsuz_sinyaller=[Evidence(etiket="Klima gazı bitmiş", alinti="Klimanın gazı bitti")],
            belirsiz_ifadeler=[Evidence(etiket="Belirsiz kozmetik ifade", alinti="Ufak tefek çizikler mevcut")],
            masraf_kalemleri=[MasrafEvidence(kod="klima_gaz", alinti="Klimanın gazı bitti, doldurulması lazım")])

    def vision_text(self, *a, **k):
        raise AssertionError("kullanılmaz")


def emsal():
    km = [72_000, 85_000, 91_000, 99_000, 104_000, 110_000, 118_000, 95_000, 88_000, 101_000, 107_000, 93_000]
    return [dict(id=f"E{i}", yil=2019, km=k, fiyat=f, seri="Megane")
            for i, (k, f) in enumerate(zip(km, [905_000, 889_000, 912_000, 879_000, 869_000, 858_000, 849_000, 899_000,
                                               915_000, 884_000, 872_000, 895_000]))]


def ilan(no="2001", fiyat=835_000, baslik="2019 Renault Megane 1.5 dCi Touch EDC", **kw):
    return dict(dict(ilan_no=no, baslik=baslik, fiyat=fiyat, yil=2019, km=98_000, marka="Renault", seri="Megane",
                     paket="1.5 dCi Touch", vites="Otomatik", yakit="Dizel", kasa_tipi="Sedan", motor_hacmi="1461 cc",
                     parts=PARCALAR, aciklama=ACIKLAMA, kimden="Sahibinden",
                     ilan_tarihi=(date.today() - timedelta(days=21)).isoformat(), fiyat_degisti=False, emsal=emsal()), **kw)


def main():
    settings.extension_token, settings.panel_allowed_hosts = TOKEN, ["panel.test"]
    xray_app.app.dependency_overrides[api.get_llm] = lambda: OrnekLLM()
    H = {"Authorization": "Bearer " + TOKEN}
    with TestClient(xray_app.app, base_url="http://panel.test") as c:
        a = c.post("/api/v1/analyze", headers=H, json=ilan()).json()
        rapor = "\n".join(["OTO EKSPERTİZ RAPORU", "Kilometre: 98.450", "Sol ön çamurluk: Lokal boyalı",
                           "Motor kaputu: Boyalı", "Şase, podye ve direkler: İşlem yok, temiz", "Ön balatalar %20",
                           "Tramer kaydı: 12.400 TL"])
        b = c.post("/api/v1/belge", headers=H, json={"tur": "ekspertiz", "metin": rapor, "ilan": ilan()}).json()
        aday = [ilan(), ilan("2002", 789_000, "2018 Renault Megane 1.5 dCi Joy", fiyat_degisti=True,
                             ilan_tarihi=(date.today() - timedelta(days=58)).isoformat()),
                ilan("2003", 760_000, "2018 Renault Megane 1.6 Touch")]
        sonuc = {"2001": {"etiket": a["etiket"], "skor": a["skor"], "veri_tamlik": a["veri_tamlik"], "hard_fails": [],
                          "eksiler": a["eksiler"][:4], "artilar": a["artilar"][:4], "sapma_yuzde": a["sapma_yuzde"]},
                 "2002": {"etiket": "DUSUNULEBILIR", "skor": 6.8, "veri_tamlik": 0.7, "hard_fails": [], "eksiler": [],
                          "artilar": [], "sapma_yuzde": -3.1},
                 "2003": {"etiket": "ALINMAZ", "skor": 5.1, "veri_tamlik": 0.8, "hard_fails": ["Tavan boyalı"],
                          "eksiler": ["Tavan boyalı"], "artilar": [], "sapma_yuzde": -14.0}}
        k = c.post("/api/v1/compare", headers=H, json={"ilanlar": [
            dict(i, sonuc=sonuc[i["ilan_no"]], gorulen_fiyatlar=[i["fiyat"] + (25_000 if i["ilan_no"] == "2002" else 0)])
            for i in aday]}).json()
    print("etiket:", a["etiket"], a["skor"], "| belge:", b["ozet"][:60], "| galip:", k["galip"])

    meta = {"ilan_no": "2001", "baslik": aday[0]["baslik"], "fiyat": 835_000, "yil": 2019, "km": 98_000}
    now = int(time.time() * 1000)
    havuz = {"items": {i["ilan_no"]: {"ilan_no": i["ilan_no"], "url": "https://example.invalid/", "eklendi": now,
                                      "meta": {"baslik": i["baslik"], "fiyat": i["fiyat"], "yil": i["yil"], "km": i["km"]},
                                      "gorulen": [{"t": now, "f": i["fiyat"]}], "ilan_tarihi": i["ilan_tarihi"],
                                      "fiyat_degisti": i["fiyat_degisti"], "sonuc": sonuc[i["ilan_no"]]} for i in aday},
             "son": {"t": now, "ids": ["2001", "2002", "2003"], "data": k}}
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as prof, sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(prof, channel="chromium", headless=True, device_scale_factor=2,
                                                   args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"],
                                                   viewport={"width": 380, "height": 2600})
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
        pg = ctx.new_page()
        pg.goto(f"chrome-extension://{sw.url.split('/')[2]}/sidepanel/sidepanel.html?tabId=7")
        pg.evaluate("v => chrome.storage.session.set(v)", {"r:7": {"status": "ok", "meta": meta, "data": a, "at": now},
                                                            "b:7": {"t": now, "ilan_no": "2001", "data": b}})
        pg.evaluate("h => chrome.storage.local.set({havuz: h})", havuz)
        pg.reload()
        pg.wait_for_selector("#verdict")
        time.sleep(1.2)
        top = pg.locator("#verdict").bounding_box()
        pg.screenshot(path=str(OUT / "karne.png"), clip={"x": 0, "y": 0, "width": 380, "height": top["y"] + top["height"] + 14})
        for sec, ad in (("#market", "piyasa"), ("#offer", "teklif"), ("#belge-sonuc", "belge"), ("#xray", "kanit"),
                        ("#cost", "maliyet")):
            pg.locator(sec).screenshot(path=str(OUT / f"{ad}.png"))
        pg.click("#tab-havuz")
        pg.wait_for_selector("#compare-result")
        time.sleep(0.6)
        pg.locator("#compare-result").screenshot(path=str(OUT / "karsilastirma.png"))
        ctx.close()
    print("yazıldı:", sorted(f.name for f in OUT.glob("*.png")), top is not None)


if __name__ == "__main__":
    main()
