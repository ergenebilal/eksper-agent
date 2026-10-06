import os
from pathlib import Path
from typing import List
from sqlalchemy.orm import Session
from arac_eksper.parser import detail_parser
from arac_eksper.storage import repo

def import_from_path(db: Session, path: str) -> List[str]:
    """HTML dosyalarından ilan detaylarını okur ve veritabanına yazar.
    Aktarılan ilan numaralarını döner.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"{path} bulunamadı.")
        
    html_files = []
    if p.is_file():
        if p.suffix == '.html':
            html_files.append(p)
    elif p.is_dir():
        html_files = list(p.glob("*.html"))
        
    imported_ids = []
    
    for html_file in html_files:
        try:
            with open(html_file, "r", encoding="utf-8") as f:
                html = f.read()
            
            detail = detail_parser.parse(html, url=f"file://{html_file.absolute()}")
            repo.create_or_update_listing(db, detail)
            imported_ids.append(detail.ilan_no)
        except Exception as e:
            print(f"Hata: {html_file.name} parse edilemedi. ({str(e)})")
            
    return imported_ids
