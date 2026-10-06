import yaml
from pathlib import Path
from typing import Optional
from arac_eksper.schemas import DescriptionFindings
from arac_eksper.llm.client import LLMClient

def load_jargon() -> str:
    jargon_path = Path(__file__).parent.parent / "config" / "jargon.yaml"
    if not jargon_path.exists():
        return ""
    with open(jargon_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        jargon_dict = data.get("jargon", {})
        return "\n".join([f"- '{k}': {v}" for k, v in jargon_dict.items()])

def normalize_tr(text: str) -> str:
    if not text:
        return ""
    text = text.replace("İ", "i").replace("I", "ı").replace("Î", "i").lower()
    return " ".join(text.split())

import hashlib
from arac_eksper.config.settings import settings
from arac_eksper.storage.models import LLMCache

def get_cached_findings(db, ilan_no, aciklama, model_name):
    if not db or not ilan_no: return None
    aciklama_hash = hashlib.sha256(aciklama.encode("utf-8")).hexdigest()
    cache = db.query(LLMCache).filter_by(ilan_no=ilan_no, aciklama_hash=aciklama_hash, model_name=model_name).first()
    if cache:
        return DescriptionFindings.model_validate(cache.findings)
    return None

def set_cached_findings(db, ilan_no, aciklama, model_name, findings):
    if not db or not ilan_no: return
    aciklama_hash = hashlib.sha256(aciklama.encode("utf-8")).hexdigest()
    cache = LLMCache(ilan_no=ilan_no, aciklama_hash=aciklama_hash, model_name=model_name, findings=findings.model_dump(mode='json'))
    db.add(cache)
    db.commit()

def _run_pass(client: LLMClient, baslik: str, aciklama: str, model_name: str, db=None, ilan_no=None) -> DescriptionFindings:
    cached = get_cached_findings(db, ilan_no, aciklama, model_name)
    if cached:
        return cached

    jargon_text = load_jargon()
    system_prompt = f"""Sen bir oto ekspertiz asistanısın. 
Kullanıcının verdiği ilan başlığı ve açıklamasını analiz et.
Türk ikinci el araç piyasası jargonunu dikkate al:
{jargon_text}

Hard-fail oluşturan (şase işlemli, airbag açmış, motor sorunlu vb.) durumlar için mutlaka `_alinti` alanlarını doldur ve açıklamada BİREBİR geçen kelimeleri kullan.
"""
    user_prompt = f"Başlık: {baslik}\nAçıklama: {aciklama}"
    
    findings = client.parse_structured(system_prompt, user_prompt, DescriptionFindings, model_name=model_name)
    
    norm_aciklama = normalize_tr(aciklama)
    
    def validate_evidences(evidences):
        valid = []
        for ev in evidences:
            if ev.alinti and normalize_tr(ev.alinti) in norm_aciklama:
                valid.append(ev)
        return valid

    findings.olumlu_sinyaller = validate_evidences(findings.olumlu_sinyaller)
    findings.olumsuz_sinyaller = validate_evidences(findings.olumsuz_sinyaller)
    findings.dolandiricilik_sinyalleri = validate_evidences(findings.dolandiricilik_sinyalleri)
    findings.belirsiz_ifadeler = validate_evidences(findings.belirsiz_ifadeler)
    
    # Hard-fail validasyonu
    if findings.sase_direk_podye_islem == "var":
        if not findings.sase_alinti or normalize_tr(findings.sase_alinti) not in norm_aciklama:
            findings.sase_direk_podye_islem = "belirsiz"
            
    if findings.airbag == "acmis":
        if not findings.airbag_alinti or normalize_tr(findings.airbag_alinti) not in norm_aciklama:
            findings.airbag = "belirsiz"
            
    if findings.motor_sanziman in ["degisen", "sorunlu"]:
        if not findings.motor_alinti or normalize_tr(findings.motor_alinti) not in norm_aciklama:
            findings.motor_sanziman = "belirsiz"
            
    set_cached_findings(db, ilan_no, aciklama, model_name, findings)
    return findings

def analyze_description(client: LLMClient, baslik: str, aciklama: str, db=None, ilan_no=None) -> DescriptionFindings:
    # İLK GEÇİŞ: FAST MODEL
    findings = _run_pass(client, baslik, aciklama, settings.llm_model_fast, db, ilan_no)
    
    # Kırmızı bayrak kontrolü
    red_flag = False
    if findings.sase_direk_podye_islem == "belirsiz" or findings.airbag == "belirsiz" or findings.motor_sanziman == "belirsiz":
        red_flag = True
    if len(findings.olumsuz_sinyaller) > 0 or len(findings.dolandiricilik_sinyalleri) > 0:
        red_flag = True
        
    if red_flag:
        # İKİNCİ GEÇİŞ: STRONG MODEL
        findings = _run_pass(client, baslik, aciklama, settings.llm_model_strong, db, ilan_no)
        
    return findings
