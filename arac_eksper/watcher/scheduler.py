from apscheduler.schedulers.blocking import BlockingScheduler
from arac_eksper.storage.db import SessionLocal
from arac_eksper.storage.models import Watch
from datetime import datetime

def check_watches():
    db = SessionLocal()
    try:
        watches = db.query(Watch).filter(Watch.is_active == True).all()
        for w in watches:
            # Sadece aktif saatler içindeyse çalış
            now_str = datetime.now().strftime("%H:%M")
            start, end = w.active_hours.split("-")
            if start <= now_str <= end:
                print(f"[{datetime.now()}] Radar çalışıyor: {w.name}")
                # 1. build_search_url(w.criteria)
                # 2. fetch_list
                # 3. diff.py ile yeni ilan bul
                # 4. detay çek, analiz et, telegram at
                # (Sıcak kod CLI içindeki search akışına benzer)
    finally:
        db.close()

def run_scheduler():
    scheduler = BlockingScheduler()
    # Her 30 dakikada bir kontrol et
    scheduler.add_job(check_watches, 'interval', minutes=30)
    print("Radar zamanlayıcısı başlatıldı (Ctrl+C ile durdurun)...")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
