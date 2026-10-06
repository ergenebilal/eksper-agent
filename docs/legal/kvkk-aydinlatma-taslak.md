# CyberOto AI — Kişisel Verilerin Korunması Aydınlatma Metni (TASLAK)

> ⚠ **Taslak, hukuki tavsiye değildir.** Claude tarafından 2026-10-07'de sistemin **gerçekte sakladığı** verilere bakılarak
> hazırlandı (`arac_eksper/web/accounts.py`, `arac_eksper/web/api.py`). Yayından önce bir avukat incelemelidir.
> Köşeli parantezli `[...]` alanları sahibi doldurur. Sistem değişirse bu metin de güncellenir.

## 1. Veri sorumlusu
[Ticari unvan / şahıs adı], [adres], [e-posta: ...] ("CyberGene"). Bu metin, davetli kullanıcılara sunulan CyberOto AI
tarayıcı eklentisi ve ona bağlı sunucu hizmeti için hazırlanmıştır.

## 2. Hangi verileri işliyoruz
| Veri | Neden | Nerede |
|---|---|---|
| E-posta adresi, (isteğe bağlı) ad | Davet, giriş kodu gönderimi, hesap ve hak yönetimi | Sunucu (hesap veritabanı) |
| Cihaz anahtarının tek yönlü özeti (SHA-256), cihaz adı | Eklentinin hesabınıza bağlı çalışması; çıkış/iptal | Sunucu |
| Giriş kodunun özeti, gönderim zamanları | Giriş güvenliği, kötüye kullanımın önlenmesi | Sunucu (kısa süreli) |
| Günlük/aylık kullanım sayaçları | Analiz haklarının uygulanması | Sunucu |
| İlan numarası + açıklama metninin tek yönlü özeti | Aynı ilanın 7 gün içinde tekrar analizinin ücretsiz olması | Sunucu (özet; metin değil) |
| Bilerek gönderdiğiniz geri bildirim (oy, ekspertiz sonucu, kısa not, ilan numarası, gösterilen etiket) | Ürünün doğruluğunu ölçmek ve geliştirmek | Sunucu |
| Davet gönderim kayıtları | Davetin ulaşıp ulaşmadığını izlemek | Sunucu |

**Saklamadıklarımız:** İlan metni, başlığı, fotoğrafı, bağlantısı ve analiz sonucu sunucuda saklanmaz; her istek bellekte
işlenir ve unutulur. **Satıcıya ait ad, telefon ve profil bilgisi hiçbir yerde tutulmaz**; ilan metnindeki telefon
numaraları analizden önce maskelenir. Yüklediğiniz ekspertiz raporu / hasar kaydı belgesi saklanmaz; ad, plaka, şasi no,
kimlik no, telefon ve e-posta analizden önce maskelenir.

**Yalnız tarayıcınızda kalanlar:** Gördüğünüz ilanların fiyat/yıl/km emsalleri, havuzunuz (en fazla 10 ilan), son
analiz sonuçları. Bunları eklenti ayarlarından tek tuşla silebilirsiniz.

## 3. Hukuki sebepler (KVKK m.5)
- Hizmet sözleşmesinin kurulması ve ifası (m.5/2-c): hesap, giriş, haklar.
- Meşru menfaat (m.5/2-f): kötüye kullanımın önlenmesi, güvenlik kayıtları, ürün doğruluğunun ölçülmesi.
- Açık rıza gerektiren bir işleme **yapılmamaktadır**. [Avukat teyit etsin.]

## 4. Aktarım
- E-posta gönderimi için e-posta hizmet sağlayıcısı: [Spaceship / ...].
- Yapay zeka analizi: ilan **açıklama metni** (telefonlar maskelenmiş) analiz için [LLM sağlayıcısı / kendi sunucumuz]
  üzerinde işlenir. **Belge fotoğrafı / ekran görüntüsü** yüklenirse görsel, okunabilmesi için aynı sağlayıcıya **olduğu gibi**
  gönderilir (üzerindeki ad, plaka, şasi no görünür olabilir); okunan metinden bu bilgiler maskelenir ve görsel saklanmaz.
  Kullanıcıya bu alanları kapatarak çekebileceği panelde söylenir. [Sağlayıcı yurt dışındaysa KVKK m.9 kapsamında ayrıca değerlendirilmelidir — avukat.]
- Sunucu barındırma: [Hermes sunucusu — konum / sağlayıcı].
- Üçüncü kişilere satış, reklam ya da profil oluşturma amacıyla aktarım yapılmaz.

## 5. Saklama süreleri
| Kayıt | Süre |
|---|---|
| Hesap (e-posta, ad), cihaz anahtarı özetleri, geri bildirim | Üyelik sürdükçe; üyelik sona erince [N gün] içinde silinir |
| Giriş kodları, yönetim oturumları | Süresi dolunca (en fazla 12 saat) otomatik silinir |
| Kod gönderim kayıtları | 2 gün |
| Tekrar-ücretsiz özetleri | 30 gün |
| Kullanım sayaçları | 400 gün |

Süreler kodda tanımlıdır (`accounts.SAKLAMA`) ve süresi dolan kayıtlar sunucu tarafından günde bir silinir.
[Üyelik sona erince hesabın silinmesi şu an yönetim panelinden elle yapılır — otomatikleştirilecekse burada belirtin.]

## 6. Haklarınız (KVKK m.11)
Verilerinizin işlenip işlenmediğini öğrenme, bilgi isteme, düzeltme, silme, itiraz ve zararın giderilmesini isteme
haklarına sahipsiniz. Başvuru: [e-posta]. Başvurular en geç 30 gün içinde yanıtlanır.
