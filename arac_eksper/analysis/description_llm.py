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

def analyze_description(client: LLMClient, baslik: str, aciklama: str) -> DescriptionFindings:
    jargon_text = load_jargon()
    
    system_prompt = f"""Sen bir oto ekspertiz asistanısın. 
Kullanıcının verdiği ilan başlığı ve açıklamasını analiz et.
Türk ikinci el araç piyasası jargonunu dikkate al:
{jargon_text}

Mümkün olduğunca her bulgun için 'olumlu_sinyaller', 'olumsuz_sinyaller', 'dolandiricilik_sinyalleri' ve 'belirsiz_ifadeler' listelerine kanıt ekle. 
Kanıtlar için orijinal açıklamada GEÇEN KELİMELERİ BİREBİR kullan ('alinti' alanı açıklamada substring olarak geçmek ZORUNDA).
Eğer geçmiyorsa veya emin değilsen bulguyu ekleme.
"""
    user_prompt = f"Başlık: {baslik}\nAçıklama: {aciklama}"
    
    findings = client.parse_structured(system_prompt, user_prompt, DescriptionFindings)
    
    # Kanıt doğrulama (Validation)
    aciklama_lower = aciklama.lower()
    
    def validate_evidences(evidences):
        valid = []
        for ev in evidences:
            if ev.alinti.lower() in aciklama_lower:
                valid.append(ev)
        return valid

    findings.olumlu_sinyaller = validate_evidences(findings.olumlu_sinyaller)
    findings.olumsuz_sinyaller = validate_evidences(findings.olumsuz_sinyaller)
    findings.dolandiricilik_sinyalleri = validate_evidences(findings.dolandiricilik_sinyalleri)
    findings.belirsiz_ifadeler = validate_evidences(findings.belirsiz_ifadeler)
    
    return findings
