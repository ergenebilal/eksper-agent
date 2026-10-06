# otoXray — Ürün ve Ar-Ge Planı

_Son güncelleme: 6 Ekim 2026_

## Karar (6 Ekim 2026)
- **Geniş ticari lansman şimdilik yok.** Önce tanıdık çevreden davetli kullanıcılarla **kapalı B2C beta**:
  kullanım deneyimi ve geri bildirim toplanacak, yayına bu verilere göre karar verilecek.
- **Sistem kopyalanamamalı.** Analiz beyni yalnızca bizim sunucumuzda durur. Kullanıcıya yalnızca ince istemci
  (eklenti) ve kişisel, iptal edilebilir, kotalı bir anahtar verilir.
- Bu yöntem **B2B değil, B2C**: müşteri bireysel alıcı. B2B (ekspertiz firmaları, galeriler, sigorta) ileride ayrı bir kanal.

## Konumlandırma
"Ekspertize gitmeden önceki 2 dakika." Ekspertizin yerini almaz; boşa yapılacak ekspertiz masrafını keser.
🟢 = "ekspertize götürmeye değer", "al" değil.

## Fazlar

### F0 — Doğrulama ✓ büyük kısmı tamam (`feat/f0-eval`)
- [x] Jargon sözlüğü düzeltildi. Yanlış tanımlar ölçüm setiyle kanıtlandı: eski sözlükle recall %94,4, precision %85.
- [x] Etiketli ölçüm seti (50 sentetik vaka) ve `arac eval` (recall < %90 → hata kodu).
- [x] Ölçümün yakaladığı üretim hataları düzeltildi:
  - Model iç alanı kendisi doldurduğu için temiz ilanlar 🟢 alamıyordu.
  - "23.450,00 TL" ve "18,5 bin" biçimindeki tramer tutarları doğrulanamıyordu.
  - Satıcı metni `</ilan>` ile prompt bloğunu kapatabiliyordu.
- [x] `arac fixture sanitize`: kaydedilen gerçek sayfaları kişisel veriden arındırır.
- [ ] **Senden:** 15–20 gerçek ilan sayfası. Okuma kuralları (seçiciler) bunlarla doğrulanacak, açıklamalar ölçüm setine girecek.
- [ ] Gerçek vakalarla `arac eval` (hedef ≥150 gerçek vaka).

### F1 — Kapalı beta altyapısı (başladı)
- [x] Kişi başı anahtar, iptal ve günlük kota (`arac xray user add|list|revoke|quota`).
- [x] Rozet ve ön hesap için ayrı kota: toplu sorguyla çıktı biriktirmeyi zorlaştırır.
- [x] Kural ağırlıkları (puan dökümü) yalnızca sahibe gider.
- [x] Eklentide geri bildirim: 👍/👎, ekspertiz sonucu, not (`arac xray feedback`).
- [x] Barındırma dosyaları: Caddy (HTTPS) + systemd (`deploy/`).
- [x] Canlı: `https://otoxray.cybergene.co` (Hermes, nginx, HTTPS); CyberGene markası.
- [x] E-postaya bağlı üyelik: e-posta koduyla giriş, kişiye özel günlük/aylık hak, bitiş tarihi, rozet izni, durdur/iptal.
- [x] Yönetim sayfası `/yonetim` (e-posta koduyla giriş) + CyberGene kimliğinde arayüz (`design/cybergene-dna.json`).
- [ ] **Senden:** sunucu `.env` dosyasına SMTP ayarları ve `ADMIN_EMAILS`; Chrome Web Store geliştirici hesabı
  ("Özel" görünürlük + güvenilir test kullanıcıları listesi = davetlilerin e-postaları), sonra `STORE_URL`.
- [ ] Davetliler için kısa kullanım koşulları (tersine mühendislik ve toplu kullanım yasak) ve KVKK aydınlatma metni.
- [ ] "otoXray" marka araştırması ve tescil başvurusu (TÜRKPATENT).
- [ ] 10–30 davetli; haftalık geri bildirim özeti.

### F2 — Beta öğrenimleri (geri bildirime göre)
- Gerçek "ekspertize gittim" sonuçlarıyla kalibrasyon: hangi kural en çok yanlış 🟢/🔴 üretiyor?
- Tramer yapıştırma: kullanıcı kendi SBM sorgu sonucunu yapıştırır, ilandaki beyanla karşılaştırılır.
- `models_kb`: en çok bakılan 30 model için kronik arızalar.
- Hız: ilk sonuç < 5 sn (akış, tek çağrı, model karşılaştırması).

### F3 — Yayın kararı (geri bildirim olumluysa)
- Gelir modeli: freemium + analiz paketi, **ve/veya** ekspertiz yönlendirme komisyonu.
- Hukuk: ilan sitesinin kullanım şartları, KVKK yurt dışı aktarım (LLM), avukat görüşü.
- Platform riskine karşı ikinci ilan sitesi desteği.
- Ar-Ge: fotoğraf röntgeni (boya tonu farkı, panel boşlukları, gösterge km tutarlılığı).

## Kopyalanmaya karşı ilkeler
1. Değerli olan her şey (prompt, jargon, kurallar, `models_kb`, ölçüm seti) **sunucuda** kalır; depo **özel** kalır.
2. Eklenti yalnızca okur ve gösterir. JavaScript gizlenemez, bu yüzden eklentide değer tutulmaz.
3. Kişi başı anahtar ve kota: sızan anahtar tek başına iptal edilir, toplu kopyalama yavaşlar.
4. API yanıtları karar için gereken kadar bilgi verir; kural ağırlıkları ve puan dökümü verilmez.
5. Hukuki katman: kullanım koşulları, marka tescili. Yazılımın kodu FSEK ile korunur.

Ayrıntılar: [deploy/README.md](deploy/README.md) · ölçüm: [tests/data/README.md](tests/data/README.md)
