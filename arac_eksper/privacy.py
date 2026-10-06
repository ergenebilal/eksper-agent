"""Satıcı telefon numaralarını maskeler (CLAUDE.md kural 5: satıcı adı/telefonu saklanmaz).
Yalnızca telefon biçimini (10-11 hane, ayraçlı olabilir) yakalar; fiyat/km gibi sayılara dokunmaz."""
import re

_PHONE = re.compile(
    r"(?<![\d.,])(?:\+?90[\s.\-]*)?\(?0?\s*[2-5]\d{2}\)?[\s.\-]*\d{3}[\s.\-]*\d{2}[\s.\-]*\d{2}(?![\d])")


def mask_phones(text: str) -> str:
    return _PHONE.sub("[telefon]", text) if text else text
