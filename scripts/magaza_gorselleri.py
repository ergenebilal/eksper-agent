"""Chrome Web Store görselleri: 1280x800 ekran görüntüleri + 440x280 küçük tanıtım kutusu.
Kaynak: scripts/tanitim_gorselleri.py'nin ürettiği gerçek panel ekranları. Çalıştırma: uv run python scripts/magaza_gorselleri.py
Çıktı: design/magaza/*.png"""
import base64
import pathlib

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "arac_eksper" / "web" / "static"
OUT = ROOT / "design" / "magaza"
FONT = SRC / "fonts"


def b64(p: pathlib.Path) -> str:
    return base64.b64encode(p.read_bytes()).decode()


def font_css() -> str:
    return "".join(f'@font-face{{font-family:"{ad}";src:url(data:font/woff2;base64,{b64(FONT / dosya)}) format("woff2");font-weight:300 700}}'
                   for ad, dosya in (("SG", "space-grotesk-latin.woff2"), ("SG", "space-grotesk-latin-ext.woff2"),
                                     ("IN", "inter-latin.woff2"), ("IN", "inter-latin-ext.woff2")))


SAHNE = """<!doctype html><html><head><meta charset="utf-8"><style>{font}
*{{box-sizing:border-box;margin:0}}
body{{width:{w}px;height:{h}px;overflow:hidden;background:radial-gradient(900px 600px at 80% 30%,rgba(255,154,36,.10),transparent 60%),
 radial-gradient(800px 600px at 70% 40%,rgba(168,85,247,.16),transparent 65%),#07090e;color:#f4f4f6;font-family:IN,sans-serif}}
.marka{{position:absolute;left:72px;top:60px;display:flex;align-items:center;gap:12px;font:500 22px SG}}
.marka img{{width:36px;height:36px;border-radius:9px}} .oto{{color:#ff9a24}}
h1{{position:absolute;left:72px;top:250px;width:460px;font:500 52px/1.04 SG;letter-spacing:-.045em}}
p{{position:absolute;left:72px;top:{p_top}px;width:470px;font-size:21px;line-height:1.5;color:#c2c1cf}}
.ekran{{position:absolute;right:80px;top:{e_top}px;width:440px;border-radius:20px;border:1px solid rgba(255,255,255,.12);overflow:hidden;
 background:#07090e;padding:14px 14px 0;box-shadow:0 40px 90px rgba(0,0,0,.6),0 0 70px rgba(168,85,247,.2)}}
.ekran img{{display:block;width:100%}}
.ekran2{{right:400px;top:{e2_top}px;width:330px;opacity:.5;transform:rotate(-3deg)}}
</style></head><body>
<div class="marka"><img src="data:image/png;base64,{ikon}"><span>Cyber<span class="oto">Oto</span> AI</span></div>
<h1>{baslik}</h1><p>{metin}</p>{ekler}
</body></html>"""

KUTU = """<!doctype html><html><head><meta charset="utf-8"><style>{font}
*{{margin:0}}body{{width:440px;height:280px;overflow:hidden;background:radial-gradient(420px 300px at 85% 20%,rgba(255,154,36,.16),transparent 60%),
 radial-gradient(400px 300px at 70% 60%,rgba(168,85,247,.22),transparent 65%),#07090e;color:#f4f4f6;font-family:SG,sans-serif}}
.m{{position:absolute;left:32px;top:30px;display:flex;align-items:center;gap:10px;font:500 20px SG}}.m img{{width:32px;height:32px;border-radius:8px}}
.oto{{color:#ff9a24}} h1{{position:absolute;left:32px;bottom:34px;font:500 40px/1.02 SG;letter-spacing:-.045em}}
</style></head><body><div class="m"><img src="data:image/png;base64,{ikon}"><span>Cyber<span class="oto">Oto</span> AI</span></div>
<h1>Her ilan<br>ekspertize değmez.</h1></body></html>"""

EKRANLAR = [
    ("1-karne", "Her ilan ekspertize değmez.", "Açtığınız ilanı yan panelde okur ve ekspertize götürmeye değip değmediğini söyler.",
     "karne.png", "kanit.png"),
    ("2-kanit", "Her bulgu ilandan alıntıyla.", "Gizli kusurlar, belirsiz ifadeler ve hasar kaydı; kanıtı olmayan bulgu gösterilmez.",
     "kanit.png", None),
    ("3-piyasa", "Fiyatı benzerleriyle kıyaslar.", "Piyasa ortalaması, tahmini gerçek maliyet ve pazarlık için açılış teklifi.",
     "piyasa.png", "teklif.png"),
    ("4-karsilastirma", "Adayları yan yana koyar.", "Fiyat/performans galibi, en riskli ilan ve ekspertize gitme sırası.",
     "karsilastirma.png", None),
    ("5-belge", "Ekspertiz raporunu ilanla karşılaştırır.", "Rapor ya da hasar kaydı fotoğrafı yeterli: çelişkiler, onarım aralığı, üst sınır.",
     "belge.png", None),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    font, ikon = font_css(), b64(SRC / "cg-ikon.png")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 800})
        for ad, baslik, metin, ana, ikinci in EKRANLAR:
            satir = 2 if len(baslik) > 18 else 1
            ekler = f'<div class="ekran" ><img src="data:image/png;base64,{b64(SRC / "tanitim" / ana)}"></div>'
            if ikinci:
                ekler = f'<div class="ekran ekran2"><img src="data:image/png;base64,{b64(SRC / "tanitim" / ikinci)}"></div>' + ekler
            pg.set_content(SAHNE.format(font=font, w=1280, h=800, ikon=ikon, baslik=baslik, metin=metin, ekler=ekler,
                                        p_top=250 + satir * 62 + 34, e_top=110, e2_top=70))
            pg.wait_for_timeout(200)
            pg.screenshot(path=str(OUT / f"ekran-{ad}.png"))
        pg = b.new_page(viewport={"width": 440, "height": 280})
        pg.set_content(KUTU.format(font=font, ikon=ikon))
        pg.wait_for_timeout(200)
        pg.screenshot(path=str(OUT / "tanitim-kutusu-440x280.png"))
        b.close()
    print(sorted(f.name for f in OUT.glob("*.png")))


if __name__ == "__main__":
    main()
