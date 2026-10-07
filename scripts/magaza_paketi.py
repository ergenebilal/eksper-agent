"""Chrome Web Store yükleme paketi: dist/cyberoto-eklenti-<sürüm>.zip
Mağaza sürümünde host_permissions yalnız canlı sunucudur (yerel test adresleri ve eski alan adı çıkarılır; kurulum
uyarısında gereksiz site görünmesin). Testler ve .md dosyaları pakete girmez. Çalıştırma: uv run python scripts/magaza_paketi.py"""
import json
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
KOK = ROOT / "extension"
CANLI = "https://cyberoto.cybergene.co/*"


def main():
    m = json.loads((KOK / "manifest.json").read_text("utf-8"))
    m["host_permissions"] = [CANLI]
    out = ROOT / "dist" / f"cyberoto-eklenti-{m['version']}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(KOK.rglob("*")):
            rel = f.relative_to(KOK)
            if not f.is_file() or f.suffix == ".md" or "tests" in rel.parts:
                continue
            if rel.as_posix() == "manifest.json":
                z.writestr("manifest.json", json.dumps(m, ensure_ascii=False, indent=2) + "\n")
            else:
                z.write(f, rel.as_posix())
    print(out, out.stat().st_size, "bayt;", len(zipfile.ZipFile(out).namelist()), "dosya; izinler:", m["host_permissions"])


if __name__ == "__main__":
    main()
