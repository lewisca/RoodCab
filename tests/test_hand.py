"""Hand: email delivery to the client's address, CAN-SPAM footer, DRY_RUN gating.

No real network: the SMTP transport is mocked.

    python tests/test_hand.py
"""
import os, sys
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from agent.eyes import ClientScore
from agent.hand import ConsoleSender, SMTPEmailSender, build_sender, compose


def mk(email="maria@acme.com"):
    return ClientScore("C1", "Maria Lopez", email, "+10000000000",
                       638, 640, 642, "Active Client", "In Progress", "2026-06-16T20:30:00Z")


BODY = "Hi Maria, a strong next step could be a subprime auto loan with DriveNow Auto: " \
       "https://drivenow.com/apply?aff=P123&subid=C1-B2-202606"


def test_email_goes_to_client_address_with_canspam_footer():
    msg = SMTPEmailSender(host="smtp.test").build_email(mk("maria@acme.com"), BODY)
    assert msg["To"] == "maria@acme.com"                       # the DisputeFox email
    assert msg["Subject"]
    body = msg.get_content()
    assert "subid=C1-B2-202606" in body                        # the offer link survives
    assert config.UNSUBSCRIBE_URL in body                      # CAN-SPAM: opt-out
    assert config.PHYSICAL_ADDRESS in body                     # CAN-SPAM: physical address
    assert msg["List-Unsubscribe"]                             # one-click unsubscribe header
    assert "Reply STOP" not in body                            # not SMS copy
    print("ok test_email_goes_to_client_address_with_canspam_footer")


def test_missing_recipient_raises():
    try:
        SMTPEmailSender(host="smtp.test").build_email(mk(email=""), BODY)
    except ValueError as e:
        assert "no email" in str(e)
        print("ok test_missing_recipient_raises")
        return
    raise AssertionError("expected ValueError when client has no email")


def test_send_without_smtp_config_raises():
    try:
        SMTPEmailSender(host="").send(mk(), BODY)
    except RuntimeError as e:
        assert "SMTP" in str(e)
        print("ok test_send_without_smtp_config_raises")
        return
    raise AssertionError("expected RuntimeError when SMTP host is unset")


def test_send_transmits_via_smtp_mocked():
    sender = SMTPEmailSender(host="smtp.test", port=587, user="u", password="p", starttls=True)
    with mock.patch("agent.hand.smtplib.SMTP") as SMTP:
        conn = SMTP.return_value.__enter__.return_value
        assert sender.send(mk("maria@acme.com"), BODY) is True
        SMTP.assert_called_once_with("smtp.test", 587, timeout=30)
        conn.starttls.assert_called_once()
        conn.login.assert_called_once_with("u", "p")
        sent_msg = conn.send_message.call_args[0][0]
        assert sent_msg["To"] == "maria@acme.com"
    print("ok test_send_transmits_via_smtp_mocked")


def test_build_sender_respects_dry_run():
    saved_dry, saved_sender = config.DRY_RUN, config.SENDER
    try:
        config.DRY_RUN = True
        assert isinstance(build_sender(), ConsoleSender)       # safe preview by default
        config.DRY_RUN = False
        config.SENDER = "smtp"
        assert isinstance(build_sender(), SMTPEmailSender)     # real email when live
    finally:
        config.DRY_RUN, config.SENDER = saved_dry, saved_sender
    print("ok test_build_sender_respects_dry_run")


if __name__ == "__main__":
    test_email_goes_to_client_address_with_canspam_footer()
    test_missing_recipient_raises()
    test_send_without_smtp_config_raises()
    test_send_transmits_via_smtp_mocked()
    test_build_sender_respects_dry_run()
    print("all tests passed")
