import sys
import json
from arac_eksper.storage.db import SessionLocal, engine
from arac_eksper.llm.client import OpenAIClient
from arac_eksper.analysis.description_llm import analyze_description
from pydantic import BaseModel
from typing import TypeVar, Type
from arac_eksper.storage.models import Base

Base.metadata.create_all(bind=engine)

T = TypeVar('T', bound=BaseModel)

class TrackingClient:
    def __init__(self):
        self.client = OpenAIClient()
        self.calls = []
        
    def parse_structured(self, system_prompt: str, user_prompt: str, response_model: Type[T], model_name: str | None = None) -> T:
        self.calls.append(model_name)
        return self.client.parse_structured(system_prompt, user_prompt, response_model, model_name)

examples = [
    ("Temiz Aile Aracı", "Aracımız çok temizdir. Sadece sol çamurluk lokal boyalı. Tramer kaydı yoktur. Masrafsız."),
    ("Acil Satılık", "Aracım acil satılıktır, ilk gelen alır. Şase podye direk işlemli, airbag açık, motor bitik, çekme belgeli pert."),
    ("Memurdan", "Kaputta taş izlerinden dolayı ince boya var. Kapora yollamayın. 3200 TL tramer. Değişensiz."),
    ("Fırsat Aracı", "Araç gümrükten alınmıştır. Yurt dışındayım. Sadece motor kaputu değişen. Gerisi hatasız."),
    ("Orjinal km", "Aracın kafa yapıldı. Sandık motor takıldı. 550.000 km'de, ama göstergede 125.000 yazıyor.")
]

def run():
    db = SessionLocal()
    tracker = TrackingClient()
    
    for i, (baslik, aciklama) in enumerate(examples):
        print(f"\n--- ÖRNEK {i+1} ---")
        print(f"Başlık: {baslik}")
        tracker.calls.clear()
        
        from arac_eksper.storage.models import LLMCache
        db.query(LLMCache).filter_by(ilan_no=str(i)).delete()
        db.commit()

        findings = analyze_description(tracker, baslik, aciklama, db=db, ilan_no=str(i))
        
        print("ÇAĞRILAR:")
        for call in tracker.calls:
            print(f" - Model: {call}")
            
        print("HAM ÇIKTI:")
        print(findings.model_dump_json(indent=2))

if __name__ == "__main__":
    run()
