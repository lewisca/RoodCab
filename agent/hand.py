"""Hand (action): deliver the message.

ConsoleSender is the dry-run sender. TwilioSMSSender / SendGridEmailSender are
production stubs -- implement them when DRY_RUN=false. SMS requires a 10DLC-registered
A2P number (TCPA); email requires a CAN-SPAM unsubscribe + physical mailing address.
"""
from abc import ABC, abstractmethod


class Sender(ABC):
    @abstractmethod
    def send(self, client, message) -> bool: ...


class ConsoleSender(Sender):
    def send(self, client, message):
        print(f"\n--- WOULD SEND -> {client.name} <{client.email}> ---\n{message}\n"
              f"{'-' * 48}")
        return True


class TwilioSMSSender(Sender):
    """TODO: pip install twilio; number must be 10DLC/A2P registered."""
    def __init__(self, account_sid, auth_token, from_number):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number

    def send(self, client, message):
        # from twilio.rest import Client
        # Client(self.account_sid, self.auth_token).messages.create(
        #     to=client.phone, from_=self.from_number, body=message)
        raise NotImplementedError("Wire Twilio here (see README).")


class SendGridEmailSender(Sender):
    """TODO: pip install sendgrid; include unsubscribe link + physical address."""
    def __init__(self, api_key, from_email):
        self.api_key = api_key
        self.from_email = from_email

    def send(self, client, message):
        raise NotImplementedError("Wire SendGrid here (see README).")
