"""Giriş kodu ve davet e-postaları (SMTP). Ayar yoksa gönderim YAPILMAZ ve bu açıkça bildirilir (sessiz başarı yok).
Kod/davet içeriği günlüğe yazılmaz."""
import smtplib
import ssl
import sys
from datetime import date
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from arac_eksper.config.settings import settings

BRAND = "CyberOto AI · CyberGene"
_env = Environment(loader=FileSystemLoader(str(Path(__file__).resolve().parent / "templates" / "email")),
                   autoescape=select_autoescape(["html"]))


def _html(name: str, **ctx) -> str:
    return _env.get_template(name).render(logo_url=settings.public_url.rstrip("/") + "/yonetim/static/mail-logo.png", **ctx)


class MailUnavailable(Exception):
    pass


def configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def send(to: str, subject: str, body: str, html: str | None = None) -> None:
    """Düz metin her zaman gider; html verilirse aynı iletide alternatif olarak eklenir (multipart/alternative)."""
    if not configured():
        raise MailUnavailable("E-posta gönderimi yapılandırılmadı (SMTP_HOST / SMTP_FROM).")
    msg = EmailMessage()
    msg["From"] = formataddr((BRAND, settings.smtp_from))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=settings.smtp_from.split("@")[-1])
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
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
    except (OSError, smtplib.SMTPException) as e:      # ayrıntı (sunucu yanıtı/adres) dışarı verilmez
        kind = type(e).__name__
        print(f"otoxray mailer: gönderim başarısız ({kind})", file=sys.stderr, flush=True)
        raise MailUnavailable(f"E-posta gönderilemedi ({kind}).") from None


def send_code(to: str, code: str, yonetim: bool = False) -> None:
    yer = "yönetim sayfasına" if yonetim else "CyberOto eklentisine"
    subject = f"CyberOto giriş kodunuz: {code}"
    send(to, subject,
         f"Merhaba,\n\n{yer.capitalize()} giriş kodunuz:\n\n    {code}\n\n"
         "Kod 10 dakika geçerlidir ve yalnızca bir kez kullanılabilir. Bu isteği siz yapmadıysanız bu e-postayı "
         "dikkate almayın.\n\n" + BRAND + "\n",
         html=_html("code.html", subject=subject, preheader="Kod 10 dakika geçerlidir.", code=code,
                    yer="Yönetim sayfası" if yonetim else "CyberOto eklentisi"))


def haklar_kalemleri(m: dict) -> list[tuple[str, str]]:
    bitis = date.fromisoformat(m["bitis"]).strftime("%d.%m.%Y") if m.get("bitis") else None
    return [("Günlük", f"{m['gunluk_kota']} analiz"),
            ("Aylık", f"{m['aylik_kota']} analiz" if m.get("aylik_kota") is not None else "Sınırsız"),
            ("Erişim", f"{bitis} tarihine kadar" if bitis else "Süre sınırı yok")]


ADIMLAR = [("Eklentiyi kurun:", "kurulum sayfasındaki düğmeyle indirip Chrome'a ekleyin (sayfa adım adım gösterir)."),
           ("Giriş yapın:", "eklentinin Ayarlar sayfasına bu e-posta adresini yazın, “Kod gönder”e basın, gelen 6 haneli kodu girin."),
           ("Bir ilan açın:", "araç çubuğundaki CyberOto simgesine tıklayın; yan panel açılır. İlan açmak hak harcamaz.")]


def kurulum_url() -> str:
    return settings.public_url.rstrip("/") + "/kurulum"


def send_invite(to: str, ad: str | None, haklar: str, kalemler: list[tuple[str, str]] | None = None) -> None:
    kurulum = kurulum_url()
    subject = "CyberOto AI'ye davet edildiniz"
    html = _html("invite.html", subject=subject, preheader="Kurulum ve giriş iki dakika: kurulum sayfası adım adım gösterir.",
                 ad=ad, haklar=kalemler or [("Kullanım hakkı", haklar)], adimlar=ADIMLAR, kurulum_url=kurulum)
    send(to, subject,
         f"Merhaba{(' ' + ad) if ad else ''},\n\n"
         "CyberOto AI kapalı betasına davet edildiniz. CyberOto, bilgisayarınızda Chrome'a kurulan bir eklentidir: "
         "açtığınız araç ilanındaki gizli kusurları, piyasa kıyasını ve teklif önerisini yan panelde gösterir.\n\n"
         f"Kurulum ve giriş (tek tık, adım adım): {kurulum}\n\n"
         "1) Eklentiyi kurun: kurulum sayfasındaki düğmeyle indirip Chrome'a ekleyin.\n"
         "2) Giriş yapın: eklentinin Ayarlar sayfasına bu e-posta adresini yazın, 'Kod gönder'e basın, gelen 6 haneli kodu girin.\n"
         "3) Bir araç ilanı açın ve araç çubuğundaki CyberOto simgesine tıklayın; yan panel açılır.\n\n"
         f"Kullanım hakkınız: {haklar}\n\n"
         "CyberOto bir yapay zeka karar destek aracıdır; resmi ekspertiz raporu değildir. 🟢 'ekspertize götürmeye "
         "değer' demektir, 'satın al' değil.\n\n" + BRAND + "\n", html=html)
