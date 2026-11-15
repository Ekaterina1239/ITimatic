"""Delivery services: how messages and SMS codes leave the system.

UML: «interface» Notifier is realised by InAppNotifier and SmsNotifier.
NotificationService holds one or more notifiers and sends every message
through each of them (strategy pattern), so a new channel such as Telegram
only needs a new Notifier class.
"""

import logging
from abc import ABC, abstractmethod

from django.conf import settings

log = logging.getLogger("itmatic.sms")


class SmsGateway:
    """Adapter for the SMS provider (Eskiz / Playmobile). In the prototype
    nothing is sent: messages are logged and the code is the demo code."""

    def __init__(self):
        self.outbox = []

    def send_code(self, phone):
        code = settings.SMS_DEMO_CODE
        self.send_text(phone, f"ITmatic code: {code}")
        return code

    def verify(self, phone, code):
        return code == settings.SMS_DEMO_CODE

    def send_text(self, phone, text):
        self.outbox.append((phone, text))
        log.info("SMS to +998%s: %s", phone, text)


class Notifier(ABC):
    channel = ""

    @abstractmethod
    def send(self, user, kind, text):
        """Deliver one message to one user."""


class InAppNotifier(Notifier):
    """Shows the message in the user's account (Messages from the center)."""

    channel = "in_app"

    def send(self, user, kind, text):
        from .models import Notification

        return Notification.objects.create(user=user, kind=kind, text=text)


class SmsNotifier(Notifier):
    channel = "sms"

    def __init__(self, gateway):
        self.gateway = gateway

    def send(self, user, kind, text):
        if user.phone:
            self.gateway.send_text(user.phone, text)


class NotificationService:
    def __init__(self, notifiers):
        self.notifiers = list(notifiers)

    def notify(self, user, kind, text):
        for notifier in self.notifiers:
            notifier.send(user, kind, text)


sms_gateway = SmsGateway()
notification_service = NotificationService([InAppNotifier(), SmsNotifier(sms_gateway)])