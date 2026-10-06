import asyncio
import json
import re
from pathlib import Path
from typing import Optional

import typer
import yaml

app = typer.Typer(help="Sahibinden Araç Analiz Ajanı")

# Çıkış kodları (Jeff/otomasyon sözleşmesi)
EXIT_OK, EXIT_ERROR, EXIT_BLOCKED, EXIT_BAD_INPUT = 0, 1, 2, 3


def say(msg: str = "", json_mode: bool = False, **kw):
    """--json modunda stdout yalnızca JSON olmalı; insan okunur çıktı stderr'e gider."""
    typer.echo(msg, err=json_mode, **kw)


def emit_json(obj) -> None:
    typer.echo(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def exit_code_for(status: str) -> int:
    return {"OK": EXIT_OK, "BLOCKED": EXIT_BLOCKED}.get(status, EXIT_ERROR)


def _session():
    from arac_eksper.storage.db import SessionLocal
    return SessionLocal()


# ---------------------------------------------------------------- search
@app.command()
def search(
    marka: str = typer.Option(..., help="Araç markası"),
    model: str = typer.Option(..., help="Araç modeli"),
    max_butce: int = typer.Option(..., help="Maksimum bütçe (TL)"),
    seri: Optional[str] = typer.Option(None, help="Araç serisi / paket (kategori haritasında seri varsa)"),
    min_yil: Optional[int] = typer.Option(None, help="Minimum yıl"),
    max_km: Optional[int] = typer.Option(None, help="Maksimum KM"),
    vites: Optional[str] = typer.Option(None, help="manuel | otomatik | yari_otomatik"),
    yakit: Optional[str] = typer.Option(None, help="benzin | dizel | lpg | hibrit | elektrik"),
    pages: Optional[int] = typer.Option(None, help="Taranacak liste sayfası sayısı"),
    max_detay: Optional[int] = typer.Option(None, help="En fazla kaç ilanın detayı çekilsin"),
    json_out: bool = typer.Option(False, "--json", help="stdout'a yalnızca JSON yaz"),
):
    """Anlık arama: piyasayı tarar, ilanları değerlendirir, en iyi fırsatları raporlar."""
    from pydantic import ValidationError
    from arac_eksper import pipeline
    from arac_eksper.collector.playwright_collector import PlaywrightCollector
    from arac_eksper.llm.client import OpenAIClient
    from arac_eksper.schemas import SearchCriteria

    try:
        criteria = SearchCriteria(marka=marka, model=model, seri=seri, max_butce=max_butce, min_yil=min_yil,
                                  max_km=max_km, vites=vites, yakit=yakit)
    except ValidationError as e:
        say(f"Geçersiz kriter: {e.errors()[0]['loc']} {e.errors()[0]['msg']}", json_out)
        raise typer.Exit(EXIT_BAD_INPUT)

    db = _session()
    try:
        from arac_eksper.collector.url_builder import build_search_url
        try:
            build_search_url(criteria)
        except ValueError as e:
            say(str(e) + " — `arac map add` ile kategori ekleyin.", json_out)
            raise typer.Exit(EXIT_BAD_INPUT)

        result = asyncio.run(pipeline.run_search(db, PlaywrightCollector(db), OpenAIClient(), criteria,
                                                 pages=pages, max_details=max_detay))
        if json_out:
            emit_json(result.to_json_dict())
        else:
            _print_search(result)
        raise typer.Exit(exit_code_for(result.status))
    finally:
        db.close()


def _print_search(result) -> None:
    from arac_eksper import pipeline
    ordered = pipeline.ranked(result.outcomes)
    greens = [o for o in ordered if o.verdict.etiket == "ALINIR" and not o.verdict.beklemede]
    yellows = [o for o in ordered if o.verdict.etiket == "DUSUNULEBILIR"][:3]
    for o in greens + yellows:
        typer.echo("\n" + "=" * 50 + "\n" + pipeline.card_for(o) + "\n" + "=" * 50)
    c = result.counts
    typer.echo(f"\nÖzet: 🟢 {c['alinir']} · 🟡 {c['dusunulebilir']} · 🔴 {c['alinmaz']} (kartı yalnızca özet) · "
               f"⏳ {c['beklemede']} · çekilen sayfa: {result.pages_fetched}")
    for err in result.errors:
        typer.secho(f"! {err}", fg=typer.colors.YELLOW, err=True)
    if result.status == "BLOCKED":
        typer.secho("Doğrulama/engel sayfası: otomatik deneme durduruldu. Manuel müdahale gerekli.",
                    fg=typer.colors.RED, err=True)


# ---------------------------------------------------------------- report / explain / feedback
@app.command()
def report(ilan_no: str = typer.Argument(...), json_out: bool = typer.Option(False, "--json")):
    """Bir ilanın son karnesini (kayıtlı karardan) gösterir."""
    from arac_eksper import pipeline
    from arac_eksper.storage import repo
    db = _session()
    try:
        row = repo.latest_verdict_row(db, ilan_no)
        if not row:
            say(f"{ilan_no} için kayıtlı karar yok. Önce `arac search` ya da `arac import-html` çalıştırın.", json_out)
            raise typer.Exit(EXIT_ERROR)
        detail, findings = repo.row_to_inputs(row)
        verdict = repo.row_to_verdict(row)
        if json_out:
            emit_json(verdict.model_dump(mode="json"))
        else:
            typer.echo(pipeline.generate_markdown_card(detail, findings, verdict))
    finally:
        db.close()


@app.command()
def explain(ilan_no: str = typer.Argument(...)):
    """Kararın tam dökümü: hangi kural kaç puan düşürdü."""
    from arac_eksper.storage import repo
    db = _session()
    try:
        row = repo.latest_verdict_row(db, ilan_no)
        if not row:
            typer.echo(f"{ilan_no} için kayıtlı karar yok.", err=True)
            raise typer.Exit(EXIT_ERROR)
        v = repo.row_to_verdict(row)
        typer.echo(f"İlan {v.ilan_no} → {v.etiket} · skor {v.guven_skoru}/10 · veri tamlığı %{v.veri_tamlik*100:.0f}")
        if v.beklemede:
            typer.echo("Analiz bekliyor: LLM havuzuna erişilemedi; bir sonraki radar turunda yeniden denenecek.")
        typer.echo("\nHard fail:" + (" yok" if not v.hard_fails else ""))
        for h in v.hard_fails:
            typer.echo(f"  ✗ {h}")
        typer.echo("\nPuan dökümü:\n  10.0  başlangıç")
        running = 10.0
        for t in v.trace:
            running += t["puan"]
            typer.echo(f"  {t['puan']:+.2f}  {t['kural']}  (→ {max(0.0, min(10.0, running)):.1f})")
        if v.piyasa:
            typer.echo(f"\nPiyasa: n={v.piyasa.n}, medyan={v.piyasa.medyan:,} TL, güven={v.piyasa.guven}".replace(",", "."))
        if v.tavsiye_teklif:
            typer.echo(f"Teklif: {v.tavsiye_teklif:,} TL (üst sınır {v.ust_sinir:,} TL)".replace(",", "."))
    finally:
        db.close()


@app.command()
def feedback(ilan_no: str = typer.Argument(...), sonuc: str = typer.Argument(..., help="pos | neg")):
    """Geri bildirim kaydı (Jeff/CLI üzerinden; Telegram butonlarıyla aynı tabloya yazar)."""
    from arac_eksper.storage import repo
    if sonuc not in ("pos", "neg"):
        typer.echo("sonuc pos ya da neg olmalı", err=True)
        raise typer.Exit(EXIT_BAD_INPUT)
    db = _session()
    try:
        repo.add_feedback(db, ilan_no, sonuc == "pos")
        typer.echo("Kaydedildi.")
    finally:
        db.close()


@app.command("import-html")
def import_html(path: str = typer.Argument(..., help="HTML dosya veya klasör yolu")):
    """Tarayıcıdan kaydedilmiş ilan sayfalarını içe aktarır (engel durumunda yedek yol)."""
    from arac_eksper.collector import manual_import
    db = _session()
    try:
        imported = manual_import.import_from_path(db, path)
        typer.echo(f"Başarıyla içe aktarılan ilan sayısı: {len(imported)}")
        if imported:
            typer.echo(f"İlan No'lar: {', '.join(imported)}")
    except Exception as e:  # noqa: BLE001
        typer.echo(f"Hata oluştu: {e}", err=True)
        raise typer.Exit(EXIT_ERROR)
    finally:
        db.close()


# ---------------------------------------------------------------- db / map
db_app = typer.Typer(help="Veritabanı işlemleri")
app.add_typer(db_app, name="db")


@db_app.command("init")
def db_init():
    """Veritabanını ve tabloları oluşturur / günceller (alembic upgrade head)."""
    from alembic import command
    from alembic.config import Config
    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(cfg, "head")
    typer.echo("Veritabanı hazır.")


map_app = typer.Typer(help="Kategori haritası işlemleri")
app.add_typer(map_app, name="map")


@map_app.command("add")
def map_add(marka: str = typer.Argument(...), model: str = typer.Argument(...), url: str = typer.Argument(...)):
    """Elle yapılmış bir sahibinden arama URL'sinden kategori slug'ını çıkarıp haritaya ekler."""
    match = re.search(r"sahibinden\.com/([^/?]+)", url)
    if not match:
        typer.echo("Geçersiz URL", err=True)
        raise typer.Exit(EXIT_BAD_INPUT)
    slug = match.group(1)
    path = Path(__file__).parent / "config" / "category_map.yaml"
    data = {"categories": {}}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {"categories": {}}
    data.setdefault("categories", {}).setdefault(marka, {})[model] = slug
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    typer.echo(f"Eklendi: {marka} {model} -> {slug}")


# ---------------------------------------------------------------- watch (radar)
watch_app = typer.Typer(help="Radar işlemleri")
app.add_typer(watch_app, name="watch")


@watch_app.command("add")
def watch_add(
    name: str = typer.Option(..., help="Radar adı"),
    marka: str = typer.Option(...), model: str = typer.Option(...), max_butce: int = typer.Option(...),
    min_yil: Optional[int] = typer.Option(None), max_km: Optional[int] = typer.Option(None),
    interval: int = typer.Option(30, help="Dakika (en az 15)"),
    saatler: str = typer.Option("08:00-23:00", help="Aktif saatler, örn. 08:00-23:00"),
):
    """Yeni radar ekler."""
    from arac_eksper.config.settings import settings
    from arac_eksper.schemas import SearchCriteria
    from arac_eksper.storage.models import Watch
    criteria = SearchCriteria(marka=marka, model=model, max_butce=max_butce, min_yil=min_yil, max_km=max_km)
    interval = max(interval, settings.min_watch_interval_minutes)
    db = _session()
    try:
        db.add(Watch(name=name, criteria=criteria.model_dump(exclude_none=True), interval_minutes=interval,
                     active_hours=saatler))
        db.commit()
        typer.echo(f"Radar eklendi: {name} (her {interval} dk, {saatler})")
    finally:
        db.close()


@watch_app.command("list")
def watch_list():
    from arac_eksper.storage.models import Watch
    db = _session()
    try:
        for w in db.query(Watch).all():
            typer.echo(f"{w.id:>3}  {'AKTİF ' if w.is_active else 'DURDU '} {w.name}  {w.interval_minutes}dk  "
                       f"{w.active_hours}  {w.criteria}")
    finally:
        db.close()


@watch_app.command("pause")
def watch_pause(name: str = typer.Argument(...)):
    _set_active(name, False)


@watch_app.command("resume")
def watch_resume(name: Optional[str] = typer.Argument(None, help="Boşsa tüm radarlar")):
    """Radarı (ya da hepsini) yeniden başlatır. Engel sonrası otomatik duraklatmayı da kaldırır."""
    _set_active(name, True)


def _set_active(name: Optional[str], active: bool):
    from arac_eksper.storage.models import Watch
    db = _session()
    try:
        q = db.query(Watch)
        if name:
            q = q.filter(Watch.name == name)
        ws = q.all()
        for w in ws:
            w.is_active = active
        db.commit()
        typer.echo(f"{len(ws)} radar {'başlatıldı' if active else 'duraklatıldı'}.")
    finally:
        db.close()


@watch_app.command("run")
def watch_run(
    once: bool = typer.Option(False, "--once", help="Tüm aktif radarları bir kez çalıştırıp çık (cron/Jeff için)"),
    force: bool = typer.Option(False, "--force", help="Aktif saat kısıtını yoksay"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Radarları çalıştırır. SCHEDULER_MODE=external ya da --once: tek tur; aksi halde sürekli zamanlayıcı."""
    from arac_eksper.config.settings import settings
    from arac_eksper.storage.models import Watch
    from arac_eksper.watcher import scheduler

    if not once and settings.scheduler_mode != "external":
        scheduler.run_scheduler()
        return

    db = _session()
    try:
        ids = [w.id for w in db.query(Watch).filter(Watch.is_active == True).all()]  # noqa: E712
    finally:
        db.close()

    runs, worst = [], EXIT_OK
    for wid in ids:
        r = scheduler.run_watch_once(wid, force=force, enforce_interval=True)
        if r is None:
            continue
        runs.append(r)
        say(f"Radar #{wid}: {r.status} · {r.counts} · hata: {r.errors}", json_out)
        worst = max(worst, exit_code_for(r.status)) if r.status != "OK" else worst
    if json_out:
        emit_json({"runs": [r.to_json_dict() for r in runs],
                   "events": [e for r in runs for e in r.events]})
    raise typer.Exit(worst)


@watch_app.command("summary")
def watch_summary():
    """Günlük özet mesajını üretir ve bildirim kanalına gönderir."""
    from arac_eksper.watcher import scheduler
    scheduler.send_daily_summary()
    typer.echo("Özet gönderildi.")


# ---------------------------------------------------------------- events / status / telegram
@app.command()
def events(since: int = typer.Option(0, help="Bu id'den büyük olaylar"),
           json_out: bool = typer.Option(True, "--json/--text"),
           types: str = typer.Option("alinir,blocked,watch_paused,daily_summary",
                                     help="Virgülle ayrılmış olay türleri")):
    """Bildirim olayları (NOTIFY_MODE=jeff iken Jeff bunu okur)."""
    from arac_eksper.storage.models import Event
    db = _session()
    try:
        wanted = [t.strip() for t in types.split(",") if t.strip()]
        rows = db.query(Event).filter(Event.id > since, Event.type.in_(wanted)).order_by(Event.id).all()
        out = [{"id": e.id, "type": e.type, "ilan_no": e.ilan_no, "watch_id": e.watch_id, "text": e.text,
                "payload": e.payload, "created_at": e.created_at.isoformat() if e.created_at else None} for e in rows]
        if json_out:
            emit_json({"events": out, "last_id": out[-1]["id"] if out else since})
        else:
            for e in out:
                typer.echo(f"#{e['id']} [{e['type']}] {e['text']}")
    finally:
        db.close()


@app.command()
def status(json_out: bool = typer.Option(False, "--json")):
    """Sağlık: son BAŞARILI çekim, engel durumu, saatlik kullanım, radar son çalışmaları.
    ('Çalışıyor' demek için sunucunun ayakta olması değil, son başarılı çekim zamanı bakılır.)"""
    from datetime import datetime, timedelta, timezone
    from arac_eksper.collector import guard
    from arac_eksper.config.settings import settings
    from arac_eksper.storage.models import Event, FetchLog, Watch
    db = _session()
    try:
        last_ok = db.query(FetchLog).filter(FetchLog.status == "OK").order_by(FetchLog.id.desc()).first()
        hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        used = db.query(FetchLog).filter(FetchLog.timestamp >= hour_ago).count()
        until = guard.is_blocked_now(db)
        watches = []
        for w in db.query(Watch).all():
            last = (db.query(Event).filter(Event.type == "watch_run", Event.watch_id == w.id)
                    .order_by(Event.id.desc()).first())
            watches.append({"id": w.id, "name": w.name, "active": w.is_active,
                            "last_run_at": last.created_at.isoformat() if last and last.created_at else None,
                            "last_status": (last.payload or {}).get("status") if last else None})
        info = {"last_successful_fetch_at": guard.as_utc(last_ok.timestamp).isoformat() if last_ok else None,
                "blocked_until": until.isoformat() if until else None,
                "pages_used_this_hour": used, "pages_limit": settings.max_pages_per_hour, "watchers": watches}
        if json_out:
            emit_json(info)
        else:
            typer.echo(f"Son başarılı çekim : {info['last_successful_fetch_at'] or 'HİÇ'}")
            typer.echo(f"Engel              : {info['blocked_until'] or 'yok'}")
            typer.echo(f"Saatlik kullanım   : {used}/{settings.max_pages_per_hour}")
            for w in watches:
                typer.echo(f"Radar {w['name']}: {'aktif' if w['active'] else 'DURDU'} · son tur {w['last_run_at'] or 'hiç'} ({w['last_status']})")
    finally:
        db.close()


panel_app = typer.Typer(help="Yönetim paneli")
app.add_typer(panel_app, name="panel")


@panel_app.command("serve")
def panel_serve():
    """Paneli başlatır (PANEL_HOST/PANEL_PORT env'den; varsayılan 127.0.0.1:8990). PANEL_TOKEN yoksa başlamaz."""
    from arac_eksper.web import app as web
    web.serve()


xray_app_cli = typer.Typer(help="otoXray AI (Chrome eklentisi) API'si")
app.add_typer(xray_app_cli, name="xray")


@xray_app_cli.command("serve")
def xray_serve():
    """Durumsuz eklenti API'sini başlatır (XRAY_HOST/XRAY_PORT; varsayılan 127.0.0.1:8991). EXTENSION_TOKEN zorunlu."""
    from arac_eksper.web import xray_app
    xray_app.serve()


@app.command("eval")
def eval_cmd(
    dataset: Optional[Path] = typer.Option(None, help="JSONL veri seti (varsayılan: tests/data/aciklamalar.jsonl)"),
    second_pass: str = typer.Option("hard", help="all | hard | off (üretimdeki XRAY_SECOND_PASS ile aynı anlam)"),
    limit: Optional[int] = typer.Option(None, help="Yalnız ilk N vaka (hızlı deneme)"),
    min_recall: float = typer.Option(0.90, help="Kabul eşiği: kırmızı bayrak recall (SPEC §4.1)"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Açıklama röntgenini etiketli veri setiyle ölçer (gerçek LLM çağrısı yapar, önbellek kullanmaz).
    Çıkış: 0 = recall eşiği geçti, 1 = geçmedi ya da LLM hatası, 3 = geçersiz veri seti/girdi."""
    from arac_eksper.analysis import evaluation
    from arac_eksper.llm import client as llm_client
    if second_pass not in ("all", "hard", "off"):
        say("--second-pass yalnızca all | hard | off olabilir.", json_out)
        raise typer.Exit(EXIT_BAD_INPUT)
    try:
        cases = evaluation.load_dataset(dataset or evaluation.DEFAULT_DATASET)
    except (OSError, ValueError) as e:
        say(f"Veri seti okunamadı: {e}", json_out)
        raise typer.Exit(EXIT_BAD_INPUT)
    cases = cases[:limit] if limit else cases
    say(f"{len(cases)} vaka ölçülüyor (ikinci geçiş: {second_pass})...", True)
    def progress(i, n, r):
        ok = not (r.hata or r.kacirilan or r.yanlis_alarm)
        say(f"[{i}/{n}] {r.id} {'✓' if ok else '✗'} {r.sure_sn} sn", True)

    rep = evaluation.evaluate(llm_client.OpenAIClient(), cases, second_pass, on_case=progress)
    gecti = rep.recall is not None and rep.recall >= min_recall and rep.hatali == 0
    if json_out:
        emit_json({**rep.model_dump(), "min_recall": min_recall, "gecti": gecti})
    else:
        pct = lambda v: "—" if v is None else f"%{v * 100:.1f}"
        say(f"Kırmızı bayrak recall: {pct(rep.recall)} (eşik {pct(min_recall)}) · precision: {pct(rep.precision)}")
        say(f"Temiz vakada yanlış alarm: {pct(rep.temiz_yanlis_alarm_orani)} · tramer doğruluğu: "
            f"{pct(rep.tramer_dogruluk)} · olumsuz sinyal recall: {pct(rep.olumsuz_recall)}")
        say(f"Temiz vakada 🟢 engeli (doğrulanamayan iddia): {pct(rep.temiz_engel_orani)}")
        say(f"Ortalama süre: {rep.ort_sure_sn} sn · LLM hatası: {rep.hatali}/{rep.n}")
        for fl, c in rep.bayrak_bazinda.items():
            if any(c.values()):
                say(f"  {fl:15} TP {c['tp']:>2}  FN {c['fn']:>2}  FP {c['fp']:>2}")
        for r in rep.vakalar:
            engel = r.dogrulanamayan_iddia and not r.beklenen
            if r.hata or r.kacirilan or r.yanlis_alarm or r.tramer_dogru is False or r.olumsuz_dogru is False or engel:
                say(f"  ✗ {r.id}: kaçırılan={r.kacirilan} yanlış_alarm={r.yanlis_alarm} "
                    f"tramer_doğru={r.tramer_dogru} olumsuz_doğru={r.olumsuz_dogru}" + (" 🟢-engeli" if engel else "")
                    + (f" HATA: {r.hata}" if r.hata else ""))
        say("GEÇTİ ✓" if gecti else "GEÇMEDİ ✗")
    raise typer.Exit(EXIT_OK if gecti else EXIT_ERROR)


fixture_app = typer.Typer(help="Test fixture'ları")
app.add_typer(fixture_app, name="fixture")


@fixture_app.command("sanitize")
def fixture_sanitize(
    paths: list[Path] = typer.Argument(..., help="Tarayıcıdan kaydedilmiş .html dosyaları"),
    out: Path = typer.Option(Path("tests/fixtures/real"), help="Çıktı klasörü"),
    remove: list[str] = typer.Option([], "--remove", help="Silinecek CSS seçicisi (satıcı kutusu vb.), tekrarlanabilir"),
):
    """Kaydedilmiş ilan sayfasını kişisel veriden arındırıp fixture klasörüne yazar. Kaynak dosyaya dokunmaz.
    Satıcı adı biçimden tanınamaz: 'şüpheli blok' raporuna bakıp gerekirse --remove ile yeniden çalıştırın."""
    from arac_eksper import fixture_sanitizer
    out.mkdir(parents=True, exist_ok=True)
    for p in paths:
        if not p.is_file():
            say(f"Bulunamadı: {p}")
            raise typer.Exit(EXIT_BAD_INPUT)
        target = out / p.name
        if target.resolve() == p.resolve():
            say(f"Kaynak ile hedef aynı dosya: {p}. Farklı bir --out verin.")
            raise typer.Exit(EXIT_BAD_INPUT)
        html, rep = fixture_sanitizer.sanitize(p.read_text(encoding="utf-8", errors="replace"), remove)
        target.write_text(html, encoding="utf-8")
        m = rep["maskelenen"]
        say(f"✓ {p.name} → {target}  (silinen etiket: {rep['silinen_etiket']}, maskelenen telefon/eposta/plaka "
            f"alanı: {m['telefon']}/{m['eposta']}/{m['plaka']})")
        for sel, n in rep["silinen_secici"].items():
            say(f"   --remove {sel!r}: {n} öğe silindi" + ("  ⚠ eşleşme yok" if n == 0 else ""))
        for b in rep["supheli_bloklar"]:
            say(f"   ⚠ şüpheli blok (elle kontrol et): {b['secici']}  [{b['metin_uzunlugu']} karakter metin]")
    say("Satıcı adı/kullanıcı adı kalmadığını dosyayı açıp kontrol etmeden commit etmeyin.")


telegram_app = typer.Typer(help="Telegram")
app.add_typer(telegram_app, name="telegram")


@telegram_app.command("poll")
def telegram_poll():
    """👍/👎 butonlarını dinler ve feedbacks tablosuna yazar (NOTIFY_MODE=arac)."""
    from arac_eksper.report import feedback as fb
    db = _session()
    try:
        typer.echo("Telegram geri bildirimi dinleniyor (Ctrl+C ile durdur)...")
        fb.poll_forever(db)
    finally:
        db.close()


if __name__ == "__main__":
    app()
