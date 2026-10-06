"""Giriş kodu ve davet e-postaları (SMTP). Ayar yoksa gönderim YAPILMAZ ve bu açıkça bildirilir (sessiz başarı yok).
Kod/davet içeriği günlüğe yazılmaz."""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from arac_eksper.config.settings import settings

BRAND = "otoXray AI · CyberGene"


class MailUnavailable(Exception):
    pass


def configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def send(to: str, subject: str, body: str) -> None:
    if not configured():
        raise MailUnavailable("E-posta gönderimi yapılandırılmadı (SMTP_HOST / SMTP_FROM).")
    msg = EmailMessage()
    msg["From"] = formataddr((BRAND, settings.smtp_from))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=settings.smtp_from.split("@")[-1])
    msg.set_content(body)
    ctx = ssl.create_default_context()
    try:
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, 465, context=ctx, timeout=20) as s:
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
                s.starttls(context=ctx)
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:      # ayrıntı (sunucu yanıtı) dışarı verilmez
        raise MailUnavailable(f"E-posta gönderilemedi ({type(e).__name__}).") from None


def send_code(to: str, code: str, yonetim: bool = False) -> None:
    yer = "yönetim sayfasına" if yonetim else "otoXray eklentisine"
    send(to, f"otoXray giriş kodunuz: {code}",
         f"Merhaba,\n\n{yer.capitalize()} giriş kodunuz:\n\n    {code}\n\n"
         "Kod 10 dakika geçerlidir ve yalnızca bir kez kullanılabilir. Bu isteği siz yapmadıysanız bu e-postayı "
         "dikkate almayın.\n\n" + BRAND + "\n")


def send_invite(to: str, ad: str | None, haklar: str) -> None:
    store = settings.store_url or "(eklenti bağlantısı ayrıca iletilecektir)"
    send(to, "otoXray AI'ye davet edildiniz",
         f"Merhaba{(' ' + ad) if ad else ''},\n\n"
         "otoXray AI kapalı betasına davet edildiniz. otoXray, araç ilanlarını ekspertize gitmeden önce eler: "
         "açıklamadaki gizli kusurları, piyasa kıyasını ve teklif önerisini gösterir.\n\n"
         f"1) Chrome eklentisini kurun: {store}\n"
         "   (Bu e-posta adresiyle Chrome'a/Google hesabınıza giriş yapmış olmanız gerekebilir.)\n"
         "2) Eklentinin Ayarlar sayfasında bu e-posta adresini yazıp 'Kod gönder'e basın.\n"
         "3) Gelen 6 haneli kodu girin. Hepsi bu.\n\n"
         f"Kullanım hakkınız: {haklar}\n\n"
         "otoXray bir yapay zeka karar destek aracıdır; resmi ekspertiz raporu değildir. 🟢 'ekspertize götürmeye "
         "değer' demektir, 'satın al' değil.\n\n" + BRAND + "\n")
