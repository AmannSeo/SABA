"""그룹 개별 발송·잠금·발송 이력 (D-076). 실제 접속 없이 가상 서버와 가상 주소만 쓴다."""

from email.message import EmailMessage
from pathlib import Path
import smtplib
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from saba import recipients as rc
from saba import daily, send_mail, sendlog
from saba.daily import DailyConfig
from saba.send_mail import ENV_HOST, ENV_PASSWORD, ENV_USER, TEST_ADDRESS, SendError, send_group

ENV = {ENV_HOST: "smtp.fictional.invalid", ENV_USER: "fictional-user", ENV_PASSWORD: "FAKE-SECRET-PW-0000"}
PEOPLE = ["virtual.one@tbell.co.kr", "virtual.two@tbell.co.kr", "virtual.three@tbell.co.kr"]
CONFIG = DailyConfig(time="08:00", random_delay_minutes=5, weekdays=("MON",), max_analysis_calls=20,
                     max_insight_calls=20, send=True)


def message():
    m = EmailMessage()
    m["Subject"] = "[TEST] 가상 브리핑"
    m.set_content("본문")
    return m


def factory():
    server = MagicMock()
    server.ehlo.return_value = (250, b"ok")
    server.auth.return_value = (235, b"ok")
    sent_to = []

    def send_message(msg, from_addr, to_addrs):
        sent_to.append((msg["To"], tuple(to_addrs)))
        return {}
    server.send_message.side_effect = send_message
    return MagicMock(return_value=server), server, sent_to


class GroupSendTests(unittest.TestCase):
    def test_locked_by_default_never_connects(self):
        self.assertFalse(send_mail.GROUP_SEND_APPROVED)  # 잠금은 코드에서만 바꾼다 (D-076)
        make, _, _ = factory()
        with self.assertRaises(SendError):
            send_group(message(), PEOPLE, env=ENV, smtp_factory=make)
        make.assert_not_called()

    def test_one_mail_per_recipient_with_pause(self):
        make, server, sent_to = factory()
        sleep = MagicMock()
        results = send_group(message(), PEOPLE, env=ENV, smtp_factory=make, allowed=True, sleep=sleep)
        self.assertEqual(make.call_count, 1)  # 한 번 로그인
        self.assertEqual(sent_to, [(p, (p,)) for p in PEOPLE])  # 받는 사람 칸에는 본인만
        self.assertEqual([r.ok for r in results], [True, True, True])
        self.assertEqual(sleep.call_count, len(PEOPLE) - 1)
        server.quit.assert_called_once()

    def test_failures_recorded_per_recipient(self):
        make, server, _ = factory()
        calls = iter([{}, smtplib.SMTPRecipientsRefused({PEOPLE[1]: (550, b"no")}), {PEOPLE[2]: (550, b"no")}])

        def send_message(msg, from_addr, to_addrs):
            value = next(calls)
            if isinstance(value, Exception):
                raise value
            return value
        server.send_message.side_effect = send_message
        results = send_group(message(), PEOPLE, env=ENV, smtp_factory=make, allowed=True, pause=0)
        self.assertEqual([(r.ok, r.detail) for r in results],
                         [(True, "성공"), (False, "SMTPRecipientsRefused, 응답 코드 없음"), (False, "거부됨")])

    def test_disconnect_reconnects_once(self):
        make, server, _ = factory()
        calls = iter([{}, smtplib.SMTPServerDisconnected(), {}, {}])

        def send_message(msg, from_addr, to_addrs):
            value = next(calls)
            if isinstance(value, Exception):
                raise value
            return value
        server.send_message.side_effect = send_message
        results = send_group(message(), PEOPLE, env=ENV, smtp_factory=make, allowed=True, pause=0)
        self.assertEqual(make.call_count, 2)
        self.assertTrue(all(r.ok for r in results))

    def test_login_failure_raises_without_secret(self):
        make, server, _ = factory()
        server.auth.side_effect = smtplib.SMTPAuthenticationError(535, b"FAKE-SECRET-PW-0000")
        with self.assertRaises(SendError) as caught:
            send_group(message(), PEOPLE, env=ENV, smtp_factory=make, allowed=True, pause=0)
        self.assertNotIn("FAKE-SECRET", str(caught.exception))


class NewsletterSendTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.history = Path(temp.name) / "send_history.db"
        self.people = Path(temp.name) / "recipients.db"
        for i, email in enumerate(PEOPLE):
            rc.save(f"가상 {i}", email, "보안사업팀", ["파일럿"], path=self.people)
        self.eml = message().as_bytes()

    def run_send(self, target, **patches):
        config = DailyConfig(**{**CONFIG.__dict__, "target_group": target})
        # daily 모듈을 다시 읽는 다른 테스트 (test_deploy) 가 있어 실행 시점의 모듈에서 찾는다.
        return daily.send_newsletter(self.eml, "daily_x.eml", config=config, origin="자동 실행 (발송 포함)",
                               history=self.history, recipients_path=self.people)

    def test_locked_group_target_still_test_only(self):
        with patch.object(send_mail, "send_test", return_value="발송 완료 1회") as test, \
                patch.object(send_mail, "send_group") as group:
            text = self.run_send("파일럿")
        test.assert_called_once()
        group.assert_not_called()
        self.assertIn("그룹 발송 잠금: TEST 주소만", text)
        record = sendlog.sends(self.history)[0]
        self.assertEqual((record.target, record.total, record.ok, record.mail_file), ("TEST 주소", 1, 1, "daily_x.eml"))
        self.assertEqual(sendlog.results(record.id, self.history)[0].email, TEST_ADDRESS)

    def test_unlocked_group_sends_individually_and_logs_counts_only(self):
        fake = [sendlog.Result(p, p != PEOPLE[2], "성공" if p != PEOPLE[2] else "거부됨") for p in PEOPLE]
        with patch.object(send_mail, "GROUP_SEND_APPROVED", True), \
                patch.object(send_mail, "send_group", return_value=fake) as group:
            text = self.run_send("파일럿")
        self.assertEqual(sorted(group.call_args.args[1]), sorted(PEOPLE))
        self.assertEqual(text, "그룹 발송 완료: 파일럿 3명 · 성공 2 · 실패 1")
        self.assertNotIn("virtual", text)  # 로그로 가는 문구에 주소 없음
        record = sendlog.sends(self.history)[0]
        self.assertEqual((record.target, record.ok, record.failed), ("파일럿 그룹", 2, 1))

    def test_unlocked_empty_group_fails_before_sending(self):
        with patch.object(send_mail, "GROUP_SEND_APPROVED", True), patch.object(send_mail, "send_group") as group, \
                self.assertRaises(daily.DailyError):
            self.run_send("없는그룹")
        group.assert_not_called()

    def test_test_send_failure_is_recorded(self):
        with patch.object(send_mail, "send_test", side_effect=SendError("SMTP 인증 실패")), self.assertRaises(SendError):
            self.run_send("TEST")
        record = sendlog.sends(self.history)[0]
        self.assertEqual((record.ok, record.failed), (0, 1))
        self.assertEqual(sendlog.results(record.id, self.history)[0].detail, "SMTP 인증 실패")


if __name__ == "__main__":
    unittest.main()
