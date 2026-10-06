import typer

app = typer.Typer(help="Sahibinden Araç Analiz Ajanı")

@app.command()
@app.command()
def search(
    marka: str = typer.Option(..., help="Araç markası"),
    model: str = typer.Option(..., help="Araç modeli"),
    seri: str = typer.Option(None, help="Araç serisi"),
    max_butce: int = typer.Option(..., help="Maksimum bütçe"),
    min_yil: int = typer.Option(None, help="Minimum yıl"),
    max_km: int = typer.Option(None, help="Maksimum KM"),
    vites: str = typer.Option(None, help="Vites türü"),
    yakit: str = typer.Option(None, help="Yakıt türü")
):
    """Anlık arama yapar."""
    import asyncio
    from arac_eksper.schemas import SearchCriteria
    from arac_eksper.collector.url_builder import build_search_url
    from arac_eksper.collector.playwright_collector import PlaywrightCollector
    from arac_eksper.parser import list_parser, detail_parser
    from arac_eksper.analysis import description_llm, market, rules_engine
    from arac_eksper.llm.client import OpenAIClient
    from arac_eksper.storage.db import SessionLocal
    from arac_eksper.report.card import generate_markdown_card
    from arac_eksper.storage import repo
    
    criteria = SearchCriteria(
        marka=marka, model=model, seri=seri, 
        max_butce=max_butce, min_yil=min_yil, max_km=max_km,
        vites=vites, yakit=yakit
    )
    
    db = SessionLocal()
    llm_client = OpenAIClient()
    collector = PlaywrightCollector(db)
    
    async def run_search():
        url = build_search_url(criteria)
        typer.echo(f"Liste sayfası çekiliyor: {url}")
        
        list_res = await collector.fetch_list(url)
        if list_res.status != "OK" or not list_res.html:
            typer.echo(f"Liste sayfası alınamadı! Durum: {list_res.status}", err=True)
            return
            
        summaries, _ = list_parser.parse(list_res.html)
        typer.echo(f"{len(summaries)} ilan bulundu.")
        
        # Sadece piyasa örneği olarak sakla
        for s in summaries:
            repo.create_or_update_listing_summary(db, s, marka, model)
            
        # Ön Eleme
        filtered = []
        for s in summaries:
            if s.fiyat > max_butce: continue
            if min_yil and s.yil < min_yil: continue
            if max_km and s.km > max_km: continue
            filtered.append(s)
            
        typer.echo(f"Ön elemeden geçen ilan sayısı: {len(filtered)}")
        
        for s in filtered[:3]: # Rate limit ve test için ilk 3
            typer.echo(f"\nİlan detayı çekiliyor: {s.ilan_no}")
            det_res = await collector.fetch_detail(s.url)
            if det_res.status != "OK" or not det_res.html:
                typer.echo(f"Atlandı: {det_res.status}")
                continue
                
            detail = detail_parser.parse(det_res.html, url=s.url)
            detail.raw_html_path = det_res.saved_path
            
            repo.create_or_update_listing(db, detail)
            
            typer.echo(f"Açıklama LLM'e gönderiliyor...")
            try:
                findings = description_llm.analyze_description(llm_client, detail.baslik, detail.aciklama, db=db, ilan_no=detail.ilan_no)
            except Exception as e:
                from arac_eksper.llm.client import LLMUnavailable
                if isinstance(e, LLMUnavailable):
                    typer.secho(f"LLM Hatası: {e}. İlan analiz bekliyor olarak işaretleniyor.", fg=typer.colors.YELLOW)
                    findings = None
                else:
                    typer.echo(f"LLM Hatası: {e}")
                    continue
                    
            stats = market.get_market_stats(db, detail)
            
            if findings:
                verdict = rules_engine.determine_verdict(detail, findings, stats)
            else:
                from arac_eksper.schemas import Verdict
                verdict = Verdict(
                    ilan_no=detail.ilan_no,
                    etiket="DUSUNULEBILIR",
                    guven_skoru=0.0,
                    veri_tamlik=0.0,
                    hard_fails=["LLM Analizi Bekliyor"],
                    artilar=[], eksiler=[], ekspertiz_kontrol_listesi=[]
                )
            
            card = generate_markdown_card(detail, findings, verdict)
            typer.echo("\n" + "="*50 + "\n" + card + "\n" + "="*50)
            
    try:
        asyncio.run(run_search())
    finally:
        db.close()

@app.command("import-html")
def import_html(
    path: str = typer.Argument(..., help="HTML dosya veya klasör yolu")
):
    """HTML dosyalarından import yapar."""
    from arac_eksper.storage.db import SessionLocal
    from arac_eksper.collector import manual_import
    
    db = SessionLocal()
    try:
        imported = manual_import.import_from_path(db, path)
        typer.echo(f"Başarıyla içe aktarılan ilan sayısı: {len(imported)}")
        if imported:
            typer.echo(f"İlan No'lar: {', '.join(imported)}")
    except Exception as e:
        typer.echo(f"Hata oluştu: {str(e)}", err=True)
    finally:
        db.close()

# Daha sonra watch gibi alt komutlar da eklenecek.
db_app = typer.Typer(help="Veritabanı işlemleri")
app.add_typer(db_app, name="db")

@db_app.command("init")
def db_init():
    """Veritabanını ve tabloları oluşturur."""
    import os
    os.system("alembic upgrade head")
    typer.echo("Veritabanı tabloları oluşturuldu.")

map_app = typer.Typer(help="Kategori haritası işlemleri")
app.add_typer(map_app, name="map")

@map_app.command("add")
def map_add(
    marka: str = typer.Argument(...),
    model: str = typer.Argument(...),
    url: str = typer.Argument(...)
):
    """Sahibinden kategori URL'sini ekler."""
    import yaml
    from pathlib import Path
    
    # URL'den slug çıkarma (örn: https://www.sahibinden.com/renault-megane? -> renault-megane)
    import re
    match = re.search(r'sahibinden\.com/([^/?]+)', url)
    if not match:
        typer.echo("Geçersiz URL", err=True)
        return
        
    slug = match.group(1)
    
    path = Path(__file__).parent / "config" / "category_map.yaml"
    data = {"categories": {}}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {"categories": {}}
            
    if marka not in data["categories"]:
        data["categories"][marka] = {}
        
    data["categories"][marka][model] = slug
    
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True)
        
    typer.echo(f"Eklendi: {marka} {model} -> {slug}")

watch_app = typer.Typer(help="Radar işlemleri")
app.add_typer(watch_app, name="watch")

@watch_app.command("add")
def watch_add(
    name: str = typer.Option(..., help="Radar adı"),
    marka: str = typer.Option(...),
    model: str = typer.Option(...),
    max_butce: int = typer.Option(...)
):
    """Yeni radar ekler."""
    from arac_eksper.storage.db import SessionLocal
    from arac_eksper.storage.models import Watch
    import json
    
    db = SessionLocal()
    try:
        criteria = {"marka": marka, "model": model, "max_butce": max_butce}
        watch = Watch(name=name, criteria=criteria)
        db.add(watch)
        db.commit()
        typer.echo(f"Radar eklendi: {name}")
    finally:
        db.close()

@watch_app.command("run")
def watch_run():
    """Tüm aktif radarları zamanlanmış şekilde çalıştırır."""
    from arac_eksper.watcher.scheduler import run_scheduler
    run_scheduler()

if __name__ == "__main__":
    app()
