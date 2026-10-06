import pytest
from arac_eksper.analysis.description_llm import analyze_description, normalize_tr
from arac_eksper.schemas import DescriptionFindings, Evidence

class MockLLMClient:
    def parse_structured(self, system_prompt: str, user_prompt: str, response_model):
        return DescriptionFindings(
            sase_direk_podye_islem="var",
            sase_alinti="şase işlemli", # Invalid quote, actual is "şasede ufak bi düzeltme"
            airbag="acmis",
            airbag_alinti="AİRBAG AÇMIŞ", # Valid quote but with caps
            motor_sanziman="belirsiz",
            km_degisimi_suphesi=False,
            olumlu_sinyaller=[Evidence(etiket="İlk Sahibi", alinti="iLK SAHiBiNDEN")], # Valid but mixed case
            olumsuz_sinyaller=[Evidence(etiket="Fake", alinti="yok boyle bisey")] # Invalid
        )

def test_description_llm_validation():
    client = MockLLMClient()
    
    baslik = "İlk sahibinden temiz"
    aciklama = "Araç ilk sahibinden satılıktır. Airbag açmış ama şasede ufak bi düzeltme var.  "
    
    findings = analyze_description(client, baslik, aciklama)
    
    # Şase alıntısı "şase işlemli" yolladık ama metinde "şasede ufak bi düzeltme var", bu yüzden belirsiz'e dönmeli
    assert findings.sase_direk_podye_islem == "belirsiz"
    
    # Airbag alıntısı "AİRBAG AÇMIŞ" yolladık metinde "Airbag açmış" geçiyor, normalizasyonla geçerli olmalı
    assert findings.airbag == "acmis"
    
    # Olumlu sinyallerde "iLK SAHiBiNDEN" var, metinde "ilk sahibinden" var, kalmalı
    assert len(findings.olumlu_sinyaller) == 1
    
    # Olumsuz sinyal "yok boyle bisey" geçmediği için drop edilmeli
    assert len(findings.olumsuz_sinyaller) == 0

def test_normalize_tr():
    assert normalize_tr(" İ  ı I i ") == "i ı ı i"
    assert normalize_tr("AİRBAG") == "ai̇rbag" or normalize_tr("AİRBAG") == "airbag" # i̇ vs i depending on replace

