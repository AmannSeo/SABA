from email.message import EmailMessage
import smtplib
import unittest
from unittest.mock import MagicMock, patch

from saba.send_mail import ENV_HOST, ENV_PASSWORD, ENV_USER, PORT, TEST_ADDRESS, SendError, send_test

ENV = {ENV_HOST: "smtp.fictional.invalid", ENV_USER: "fictional-user", ENV_PASSWORD: "FAKE-SECRET-PW-0000"}


def message(**headers):
    m = EmailMessage()
    m["Subject"] = "[TEST] 가상 브리핑"
    for name, value in headers.items():
        m[name] = value
    m.set_content("본문")
    return m


def factory():
    server = MagicMock()
    server.send_message.return_value = {}
    server.ehlo.return_value = (250, b"ok")
    server.login.return_value = (235, b"ok")
    server.esmtp_features = {"auth": "LOGIN PLAIN"}
    return MagicMock(return_value=server), server


class SendMailTests(unittest.TestCase):
    def test_dry_run_default_never_connects(self):
        make, _ = factory()
        result = send_test(message(), env=ENV, smtp_factory=make)
        make.assert_not_called()
        self.assertIn("드라이런", result)
        self.assertIn(f"{ENV_PASSWORD} 있음", result)
        for secret in ENV.values():
            self.assertNotIn(secret, result)

    def test_send_once_to_fixed_address_over_ssl(self):
        make, server = factory()
        sent = message()
        result = send_test(sent, send=True, env=ENV, smtp_factory=make)
        self.assertEqual(make.call_count, 1)
        args, kwargs = make.call_args
        self.assertEqual(args, ("smtp.fictional.invalid", PORT))
        self.assertIn("context", kwargs)
        server.login.assert_called_once_with("fictional-user", "FAKE-SECRET-PW-0000")
        server.send_message.assert_called_once()
        self.assertEqual(server.send_message.call_args.kwargs["to_addrs"], [TEST_ADDRESS])
        self.assertEqual((sent["From"], sent["To"]), (TEST_ADDRESS, TEST_ADDRESS))
        server.starttls.assert_not_called()  # 465 SSL/TLS, STARTTLS 아님
        self.assertIn("발송 완료 1회", result)
        self.assertNotIn("FAKE-SECRET", result)

    def test_other_recipients_rejected_before_connect(self):
        for header in ("To", "Cc", "Bcc", "From"):
            with self.subTest(header=header):
                make, _ = factory()
                with self.assertRaises(SendError):
                    send_test(message(**{header: "someone@example.com"}), send=True, env=ENV, smtp_factory=make)
                make.assert_not_called()

    def test_missing_env_does_not_connect(self):
        make, _ = factory()
        with self.assertRaises(SendError) as caught:
            send_test(message(), send=True, env={ENV_HOST: "h"}, smtp_factory=make)
        make.assert_not_called()
        self.assertIn(f"{ENV_PASSWORD} 없음", str(caught.exception))

    def test_errors_mapped_without_secrets_and_no_retry(self):
        cases = [(smtplib.SMTPAuthenticationError(535, b"bad FAKE-SECRET-PW-0000"), "인증 실패"),
                 (smtplib.SMTPServerDisconnected("FAKE-SECRET-PW-0000"), "SMTP 오류"),
                 (ConnectionRefusedError("smtp.fictional.invalid"), "연결 실패")]
        for error, expected in cases:
            with self.subTest(expected=expected):
                make, server = factory()
                server.login.side_effect = error
                with self.assertRaises(SendError) as caught:
                    send_test(message(), send=True, env=ENV, smtp_factory=make)
                self.assertIn(expected, str(caught.exception))
                for secret in ENV.values():
                    self.assertNotIn(secret, str(caught.exception))
                self.assertEqual(make.call_count, 1)

    def test_response_error_reports_stage_and_code_only(self):
        for stage, method in (("로그인", "login"), ("발송", "send_message")):
            with self.subTest(stage=stage):
                make, server = factory()
                getattr(server, method).side_effect = smtplib.SMTPResponseException(
                    552, b"size limit for fictional-user FAKE-SECRET-PW-0000")
                with self.assertRaises(SendError) as caught:
                    send_test(message(), send=True, env=ENV, smtp_factory=make)
                text = str(caught.exception)
                self.assertIn(f"{stage} 단계", text)
                self.assertIn("응답 코드 552", text)
                for private in ("size limit", "fictional-user", "FAKE-SECRET"):
                    self.assertNotIn(private, text)
                self.assertEqual(make.call_count, 1)

    def test_quit_error_after_send_reported_as_sent_with_warning(self):
        make, server = factory()
        server.quit.side_effect = smtplib.SMTPResponseException(451, b"fictional-user")
        result = send_test(message(), send=True, env=ENV, smtp_factory=make)
        server.send_message.assert_called_once()
        self.assertIn("발송 완료 1회", result)
        self.assertIn("종료(QUIT) 응답 비정상 (응답 코드 451)", result)
        self.assertNotIn("fictional-user", result)

    def test_quit_error_does_not_hide_send_error(self):
        # 실제 사례: 발송 오류 뒤 QUIT 이 250 으로 응답해 원래 오류가 가려졌다 (D-047).
        make, server = factory()
        server.send_message.side_effect = smtplib.SMTPDataError(552, b"too big FAKE-SECRET-PW-0000")
        server.quit.side_effect = smtplib.SMTPResponseException(250, b"ok")
        with self.assertRaises(SendError) as caught:
            send_test(message(), send=True, env=ENV, smtp_factory=make)
        self.assertIn("발송 단계, SMTPDataError, 응답 코드 552", str(caught.exception))
        self.assertNotIn("FAKE-SECRET", str(caught.exception))
        server.quit.assert_called_once()
        server.close.assert_called_once()

    def test_connection_closed_after_success(self):
        make, server = factory()
        send_test(message(), send=True, env=ENV, smtp_factory=make)
        server.quit.assert_called_once()

    def test_auth_503_not_treated_as_login_success(self):
        # 실제 사례: AUTH 503 을 smtplib 이 성공으로 보고, 이후 MAIL FROM 이 503 으로 거부됐다 (D-048).
        make, server = factory()
        server.login.return_value = (503, b"fictional-user FAKE-SECRET-PW-0000")
        with self.assertRaises(SendError) as caught:
            send_test(message(), send=True, env=ENV, smtp_factory=make)
        text = str(caught.exception)
        self.assertIn("EHLO 응답 코드 250, AUTH 응답 코드 503", text)
        self.assertIn("['LOGIN', 'PLAIN']", text)
        self.assertNotIn("FAKE-SECRET", text)
        self.assertNotIn("fictional-user", text)
        server.send_message.assert_not_called()
        server.quit.assert_called_once()

    def test_trace_records_verbs_and_codes_only(self):
        from saba.send_mail import trace_codes

        class Fake:
            def __init__(self):
                self.replies = iter([(250, b"hi"), (334, b"VXNlcm5hbWU6"), (235, b"ok"), (503, b"bad fictional-user")])

            def putcmd(self, cmd, args=""):
                pass

            def getreply(self):
                return next(self.replies)

        fake = Fake()
        trace = trace_codes(fake)
        for cmd in ("ehlo fictional.host", "AUTH LOGIN", "RkFLRS1TRUNSRVQtUFctMDAwMA==", "mail FROM:<a@b>"):
            fake.putcmd(cmd)
            fake.getreply()
        self.assertEqual(trace, ["EHLO", "250", "AUTH", "334", "(인증 데이터)", "235", "MAIL", "503"])
        self.assertNotIn("RkFLRS", " ".join(trace))

    def test_refused_recipient_reported(self):
        make, server = factory()
        server.send_message.return_value = {TEST_ADDRESS: (550, b"no")}
        with self.assertRaises(SendError):
            send_test(message(), send=True, env=ENV, smtp_factory=make)

    def test_main_is_dry_run_without_flag(self):
        from saba import send_mail
        with patch.object(send_mail.smtplib, "SMTP_SSL") as ssl_cls, patch("sys.argv", ["send_mail"]), \
                patch("builtins.print") as printed:
            self.assertEqual(send_mail.main(), 0)
        ssl_cls.assert_not_called()
        self.assertIn("드라이런", printed.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
