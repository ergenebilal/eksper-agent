import pytest
from unittest.mock import MagicMock, patch
from pydantic import BaseModel, ValidationError
from arac_eksper.llm.client import OpenAIClient, LLMUnavailable
from arac_eksper.analysis.description_llm import analyze_description
from arac_eksper.schemas import DescriptionFindings, Evidence
from openai import RateLimitError
import httpx

class DummySchema(BaseModel):
    sonuc: str

def test_llm_valid_json():
    client = OpenAIClient()
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"sonuc": "basarili"}'
    
    with patch.object(client.client.chat.completions, 'create', return_value=mock_response):
        res = client.parse_structured("sys", "user", DummySchema)
        assert res.sonuc == "basarili"

def test_llm_fenced_json():
    client = OpenAIClient()
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '```json\n{"sonuc": "temiz"}\n```'
    
    with patch.object(client.client.chat.completions, 'create', return_value=mock_response):
        res = client.parse_structured("sys", "user", DummySchema)
        assert res.sonuc == "temiz"

def test_llm_invalid_json_retry_then_error():
    client = OpenAIClient()
    
    # İlk seferde bozuk JSON, ikinci seferde de bozuk JSON dönsün
    mock_response1 = MagicMock()
    mock_response1.choices[0].message.content = '{"sonuc": "eksik'
    mock_response2 = MagicMock()
    mock_response2.choices[0].message.content = 'hala bozuk'
    
    with patch.object(client.client.chat.completions, 'create', side_effect=[mock_response1, mock_response2]) as mock_create:
        with pytest.raises(ValidationError):
            client.parse_structured("sys", "user", DummySchema)
        assert mock_create.call_count == 2 # 1 retry yapıldı

def test_llm_rate_limit_backoff():
    client = OpenAIClient()
    
    # RateLimitError (quota değil) simüle edelim. Tenacity 5 kere deneyecek.
    err_response = httpx.Response(429, request=httpx.Request("POST", "url"))
    err = RateLimitError("Rate limit", response=err_response, body=None)
    
    with patch.object(client.client.chat.completions, 'create', side_effect=err) as mock_create:
        # Hızlandırmak için sleep mocklayalım
        with patch('time.sleep'):
            with pytest.raises(LLMUnavailable) as exc_info:
                client.parse_structured("sys", "user", DummySchema)
            
            assert "LLM havuzuna erişilemiyor" in str(exc_info.value)
            assert mock_create.call_count == 5

def test_llm_quota_error():
    client = OpenAIClient()
    
    err_response = httpx.Response(429, request=httpx.Request("POST", "url"))
    err = RateLimitError("insufficient_quota", response=err_response, body=None)
    
    with patch.object(client.client.chat.completions, 'create', side_effect=err) as mock_create:
        with pytest.raises(LLMUnavailable) as exc_info:
            client.parse_structured("sys", "user", DummySchema)
        
        assert "kotası doldu" in str(exc_info.value)
        assert mock_create.call_count == 1 # Hızlıca çıkmalı

def test_description_llm_two_pass(monkeypatch):
    class MockClient:
        def __init__(self):
            self.calls = []
        def parse_structured(self, sys, user, schema, model_name):
            self.calls.append(model_name)
            # Eğer fast ise red flag döndür, değilse temiz döndür
            if model_name == "gpt-4o-mini":
                return DescriptionFindings(
                    olumsuz_sinyaller=[Evidence(etiket="podye", alinti="Test aciklama")],  # kanıtlı kırmızı bayrak
                    sase_direk_podye_islem="belirsiz",
                    airbag="orijinal_beyan",
                    motor_sanziman="sorunsuz_beyan",
                    km_degisimi_suphesi=False
                )
            else:
                return DescriptionFindings(
                    sase_direk_podye_islem="yok_beyan",
                    airbag="orijinal_beyan",
                    motor_sanziman="sorunsuz_beyan",
                    km_degisimi_suphesi=False
                )
                
    client = MockClient()
    # monkeypatch config
    monkeypatch.setattr("arac_eksper.analysis.description_llm.settings.llm_model_fast", "gpt-4o-mini")
    monkeypatch.setattr("arac_eksper.analysis.description_llm.settings.llm_model_strong", "gpt-4o")
    
    res = analyze_description(client, "Test", "Test aciklama")
    
    assert len(client.calls) == 2
    assert client.calls[0] == "gpt-4o-mini"
    assert client.calls[1] == "gpt-4o"
    assert res.sase_direk_podye_islem == "yok_beyan"


def test_llm_connection_error_is_unavailable():
    """Proxy kapalıyken ham APIConnectionError sızmamalı (K3)."""
    from openai import APIConnectionError
    client = OpenAIClient()
    err = APIConnectionError(request=httpx.Request("POST", "http://x"))
    with patch.object(client.client.chat.completions, 'create', side_effect=err):
        with patch('time.sleep'):
            with pytest.raises(LLMUnavailable):
                client.parse_structured("sys", "user", DummySchema)


def test_llm_api_error_message_does_not_leak_body():
    from openai import AuthenticationError
    client = OpenAIClient()
    resp = httpx.Response(401, request=httpx.Request("POST", "http://x"))
    err = AuthenticationError("Incorrect API key provided: sk-SECRET123", response=resp, body=None)
    with patch.object(client.client.chat.completions, 'create', side_effect=err):
        with pytest.raises(LLMUnavailable) as ei:
            client.parse_structured("sys", "user", DummySchema)
    assert "SECRET" not in str(ei.value) and "SECRET" not in repr(ei.value.__cause__)
