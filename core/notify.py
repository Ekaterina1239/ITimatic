import logging
from .models import Notification, SMSLog

log = logging.getLogger(__name__)


def render_text(template, params, lang):
    from .translations import TR
    t = TR.get(lang, {}).get(template, template)
    try:
        return t.format(**params)
    except (KeyError, IndexError):
        return t


def send_sms(phone, text):
    SMSLog.objects.create(phone=phone, text=text[:300])
    log.info("SMS to %s: %s", phone, text)


def notify(user, template, sms=True, **params):
    """In-app notification + SMS (in the recipient's language). `template` is an English key from translations.py."""
    if not user:
        return
    params = {k: str(v) for k, v in params.items()}
    Notification.objects.create(user=user, template=template, params=params)
    prof = getattr(user, "profile", None)
    if sms and prof and prof.phone:
        send_sms(prof.phone, render_text(template, params, prof.lang))
