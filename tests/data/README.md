# Açıklama röntgeni değerlendirme seti

`aciklamalar.jsonl`: her satır bir vaka. `uv run arac eval` gerçek LLM ile ölçer. Kabul eşiği: kırmızı bayrak recall ≥ %90 (SPEC §4.1).

```json
{"id": "g001", "kaynak": "gercek", "baslik": "...", "aciklama": "...",
 "beklenen": {"bayraklar": ["sase"], "tramer_tutari": 18000, "olumsuz_var": false}, "not": "isteğe bağlı"}
```

| Alan | Anlam |
|---|---|
| `bayraklar` | Beklenen kırmızı bayrakların **tam kümesi**: `sase`, `airbag`, `motor`, `agir_hasar`, `dolandiricilik`, `km_suphesi`. Fazlası yanlış alarm, eksiği kaçırma sayılır. |
| `tramer_tutari` | Açıklamada yazan tutar (TL). `0` = "tramer yok" beyanı, `null` = tramerden hiç söz edilmiyor (model tutar uydurmamalı). |
| `olumsuz_var` | En az bir olumsuz ya da belirsiz sinyal (ör. "hatasız gibi", "ufak tefek") bekleniyorsa `true`. |

## Etiketleme kuralları
- Bayrak yalnızca **metinde yazana** göre konur. "Bence şasesi işlemlidir" tahmini etiket değildir.
- Olumsuzlama bayrak değildir: "pert değildir", "airbag açmamış" → bayraksız.
- Şüpheli vakada iki kişi bağımsız etiketlesin. Anlaşamazsanız vakayı `not` ile işaretleyip dışarıda bırakın.

## Gerçek vaka taslakları
`aciklamalar_gercek_taslak.jsonl`: 18 gerçek ilanın (tests/fixtures/real) **taslak** etiketleri (Claude, 2026-10-07). Kullanıcı onaylayınca
`not` alanındaki "TASLAK" ifadesi kaldırılıp satırlar `aciklamalar.jsonl`a taşınır. Sınırda vakalar `not` alanında "SINIRDA" ile işaretli.
Taslakla ölçüm: `uv run arac eval --dataset tests/data/aciklamalar_gercek_taslak.jsonl`

## Gerçek vaka ekleme (hedef: ≥150 gerçek vaka)
1. Açıklamayı ilandan kopyalayın. **Satıcı adı, telefon, plaka, şasi no, adres, e-posta silinsin** (testler telefonu denetler, diğerleri size kalmış).
2. `kaynak: "gercek"`, `id: "gNNN"` verin. Sentetik vakalar (`sNN`) jargon ve tuzak kapsamı içindir, gerçeğin yerini tutmaz.
3. Model veya prompt değişikliğinden önce ve sonra `uv run arac eval --json > eval-<tarih>.json` alıp karşılaştırın.
