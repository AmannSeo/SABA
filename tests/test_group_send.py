"""그룹 개별 발송·결과 보존·부분 실패·실패 재발송·메일 파일 보존 (D-076, D-077).

실제 접속 없이 가상 서버·가상 주소·임시 DB 만 쓴다. 잠금 해제는 이 테스트 안에서만 (코드 기본값은 False 확인).
"""

from datetime import datetime, timezone
from email.message import EmailMessage
from functools import partial
import hashlib
import logging
from pathlib import Path
import smtplib
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from saba import daily, history
from saba import recipients as rc
from saba import send_mail, sendlog
from saba.daily import DailyConfig
from saba.send_mail import ENV_HOST, ENV_PASSWORD, ENV_USER, TEST_ADDRESS, SendError

ENV = {ENV_HOST: "smtp.fictional.invalid", ENV_USER: "fictional-user", ENV_PASSWORD: "FAKE-SECRET-PW-0000"}
PEOPLE = ["virtual.one@tbell.co.kr", "virtual.two@tbell.co.kr", "virtual.three@tbell.co.kr"]
CONFIG = DailyConfig(time="08:00", random_delay_minutes=5, weekdays=("MON",), max_analysis_calls=20,
                     max_insight_calls=20, send=True)
REAL_SEND_GROUP = send_mail.send_group


def message():
    m = EmailMessage()
    m["Subject"] = "[TEST] 가상 브리핑"
    m.set_content("본문")
    return m


def factory(plan=None):
    """plan: 보내는 순서대로 반환값 또는 예외. 없으면 모두 성공."""
    plan = list(plan or [])
    server = MagicMock()
    server.ehlo.return_value = (250, b"ok")
    server.auth.return_value = (235, b"ok")
    sent_to = []

    def send_message(msg, from_addr, to_addrs):
        sent_to.append((msg["To"], tuple(to_addrs)))
        value = plan.pop(0) if plan else {}
        if isinstance(value, BaseException):
            raise value
        return value
    server.send_message.side_effect = send_message
    return MagicMock(return_value=server), server, sent_to


class Recorder:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def __call__(self, email, status, detail):
        self.calls.append((email, status))
        if self.fail_on == (email, status):
            raise sendlog.SendLogError("발송 이력 저장 실패: OperationalError")


def group(plan=None, emails=PEOPLE, log=None, **kwargs):
    make, server, sent_to = factory(plan)
    log = log or Recorder()
    results = REAL_SEND_GROUP(message(), emails, log=log, env=ENV, smtp_factory=make, allowed=True, pause=0, **kwargs)
    return results, make, server, sent_to, log


class GroupSendTests(unittest.TestCase):
    def test_locked_by_default_never_connects(self):
        self.assertFalse(send_mail.GROUP_SEND_APPROVED)  # 잠금은 코드에서만 바꾼다 (D-076)
        make, _, _ = factory()
        with self.assertRaises(SendError):
            REAL_SEND_GROUP(message(), PEOPLE, log=Recorder(), env=ENV, smtp_factory=make)
        make.assert_not_called()

    def test_one_mail_per_recipient_with_pause_and_marks(self):
        make, server, sent_to = factory()
        sleep, log = MagicMock(), Recorder()
        results = REAL_SEND_GROUP(message(), PEOPLE, log=log, env=ENV, smtp_factory=make, allowed=True, sleep=sleep)
        self.assertEqual(make.call_count, 1)
        self.assertEqual(sent_to, [(p, (p,)) for p in PEOPLE])  # 받는 사람 칸에는 본인만
        self.assertEqual([r.status for r in results], ["성공"] * 3)
        self.assertEqual(log.calls[:2], [(PEOPLE[0], "전송 중"), (PEOPLE[0], "성공")])  # 보내기 전에 전송 중 기록
        self.assertEqual(sleep.call_count, 2)

    def test_explicit_rejections_are_failures(self):
        plan = [{PEOPLE[0]: (550, b"no")}, smtplib.SMTPRecipientsRefused({PEOPLE[1]: (550, b"no")}),
                smtplib.SMTPDataError(552, b"too big")]
        results = group(plan)[0]
        self.assertEqual([r.status for r in results], ["실패", "실패", "실패"])

    def test_temporary_rejection_retried_once(self):
        results, _, _, sent_to, _ = group([smtplib.SMTPDataError(451, b"later"), {}], emails=PEOPLE[:1])
        self.assertEqual((results[0].status, len(sent_to)), ("성공", 2))
        results = group([smtplib.SMTPDataError(451, b"later"), smtplib.SMTPDataError(451, b"later")], emails=PEOPLE[:1])[0]
        self.assertEqual(results[0].status, "실패")

    def test_disconnect_or_timeout_is_unclear_and_not_resent(self):
        for error in (smtplib.SMTPServerDisconnected(), TimeoutError(), ConnectionResetError()):
            with self.subTest(error=type(error).__name__):
                results, make, _, sent_to, _ = group([{}, error, {}])
                self.assertEqual([r.status for r in results], ["성공", "불명확", "성공"])  # 앞선 성공 보존
                self.assertEqual(len(sent_to), 3)  # 불명확한 사람에게 다시 보내지 않음
                self.assertEqual(make.call_count, 2)  # 다음 사람을 위해 다시 로그인

    def test_login_failure_records_not_tried(self):
        make, server, _ = factory()
        server.auth.side_effect = smtplib.SMTPAuthenticationError(535, b"FAKE-SECRET-PW-0000")
        log = Recorder()
        results = REAL_SEND_GROUP(message(), PEOPLE, log=log, env=ENV, smtp_factory=make, allowed=True, pause=0)
        self.assertEqual([r.status for r in results], ["미시도"] * 3)
        self.assertNotIn("FAKE-SECRET", " ".join(r.detail for r in results))
        server.send_message.assert_not_called()

    def test_reconnect_failure_marks_rest_not_tried(self):
        make, server, _ = factory([{}, smtplib.SMTPServerDisconnected()])
        servers = [server, OSError("down")]
        make.side_effect = lambda *a, **k: (lambda v: (_ for _ in ()).throw(v) if isinstance(v, BaseException) else v)(servers.pop(0))
        results = REAL_SEND_GROUP(message(), PEOPLE, log=Recorder(), env=ENV, smtp_factory=make, allowed=True, pause=0)
        self.assertEqual([r.status for r in results], ["성공", "불명확", "미시도"])

    def test_record_failure_stops_further_sending(self):
        log = Recorder(fail_on=(PEOPLE[0], "성공"))  # 보낸 뒤 기록이 실패
        make, _, sent_to = factory()
        with self.assertRaises(sendlog.SendLogError):
            REAL_SEND_GROUP(message(), PEOPLE, log=log, env=ENV, smtp_factory=make, allowed=True, pause=0)
        self.assertEqual(len(sent_to), 1)  # 더 보내지 않음

    def test_quit_failure_keeps_results(self):
        make, server, _ = factory()
        server.quit.side_effect = smtplib.SMTPServerDisconnected()
        results = REAL_SEND_GROUP(message(), PEOPLE, log=Recorder(), env=ENV, smtp_factory=make, allowed=True, pause=0)
        self.assertTrue(all(r.ok for r in results))


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.history = self.dir / "send_history.db"
        self.people = self.dir / "recipients.db"
        self.output = self.dir / "output"
        self.output.mkdir()
        for i, email in enumerate(PEOPLE):
            rc.save(f"가상 {i}", email, "보안사업팀", ["파일럿"], path=self.people)
        self.eml = message().as_bytes()

    def unlocked(self, plan=None):
        make, _, sent_to = factory(plan)
        self.sent_to = sent_to
        fake = partial(REAL_SEND_GROUP, env=ENV, smtp_factory=make, allowed=True, pause=0)
        return patch.multiple(send_mail, GROUP_SEND_APPROVED=True, send_group=fake)

    def newsletter(self, target="파일럿"):
        config = DailyConfig(**{**CONFIG.__dict__, "target_group": target})
        return daily.send_newsletter(self.eml, "daily_x.eml", config=config, origin="자동 실행 (발송 포함)",
                                     history=self.history, recipients_path=self.people)


class NewsletterSendTests(Base):
    def test_locked_group_target_still_test_only(self):
        with patch.object(send_mail, "send_test", return_value="발송 완료 1회") as test, \
                patch.object(send_mail, "send_group") as grp:
            text = self.newsletter()
        test.assert_called_once()
        grp.assert_not_called()
        self.assertIn("그룹 발송 잠금: TEST 주소만", text)
        record = sendlog.sends(self.history)[0]
        self.assertEqual((record.target, record.total, record.ok, record.mail_file), ("TEST 주소", 1, 1, "daily_x.eml"))
        self.assertEqual(sendlog.results(record.id, self.history)[0].email, TEST_ADDRESS)

    def test_all_success(self):
        with self.unlocked():
            text = self.newsletter()
        self.assertEqual(text, "그룹 발송 완료: 파일럿 그룹 3명 중 성공 3 · 실패 0 · 불명확 0 · 미시도 0")
        self.assertNotIn("virtual", text)  # 로그로 가는 문구에 주소 없음
        record = sendlog.sends(self.history)[0]
        self.assertEqual((record.ok, record.failed, record.mail_sha256), (3, 0, hashlib.sha256(self.eml).hexdigest()))

    def test_partial_and_all_failed_raise_but_keep_successes(self):
        for plan, ok in (([{}, {PEOPLE[1]: (550, b"no")}, smtplib.SMTPServerDisconnected()], 1),
                         ([smtplib.SMTPDataError(552, b"x")] * 3, 0)):
            with self.subTest(ok=ok), self.unlocked(plan), self.assertRaises(daily.PartialSendError):
                self.newsletter()
            self.assertEqual(sendlog.sends(self.history)[0].ok, ok)

    def test_empty_group_fails_before_sending(self):
        with self.unlocked(), self.assertRaises(daily.DailyError):
            self.newsletter("없는그룹")
        self.assertEqual(sendlog.sends(self.history), [])

    def test_history_start_failure_sends_nothing(self):
        with self.unlocked(), patch.object(sendlog, "start", side_effect=sendlog.SendLogError("발송 이력 저장 실패")), \
                self.assertRaises(daily.DailyError):  # 보내기 전 실패: "보내지 않음" 이 확실한 오류로 바꾼다
            self.newsletter()
        self.assertEqual(self.sent_to, [])

    def test_test_send_failure_classified(self):
        for message_text, status in (("SMTP 인증 실패", "실패"), ("SMTP 오류: 발송 단계, SMTPDataError", "불명확")):
            with self.subTest(status=status), patch.object(send_mail, "send_test", side_effect=SendError(message_text)), \
                    self.assertRaises(SendError):
                self.newsletter("TEST")
            self.assertEqual(sendlog.results(sendlog.sends(self.history)[0].id, self.history)[0].status, status)

    def test_interrupted_round_reads_as_unclear(self):  # 프로세스가 보내는 도중 끝난 경우
        send_id = sendlog.start("자동 실행", "파일럿 그룹", PEOPLE, path=self.history)
        sendlog.mark(send_id, PEOPLE[0], "성공", path=self.history)
        sendlog.mark(send_id, PEOPLE[1], "전송 중", path=self.history)
        record = sendlog.sends(self.history)[0]
        self.assertEqual(record.counts, {"성공": 1, "불명확": 1, "미시도": 1})
        self.assertEqual(sendlog.resend_targets(send_id, self.history), [PEOPLE[2]])  # 불명확은 재발송 대상 아님


class RunDailyStatusTests(Base):
    def run_with(self, deliver):
        with self.assertLogs(level="INFO") as logs:
            code = daily.run_daily(datetime(2026, 10, 13, 8, 3, tzinfo=timezone.utc), CONFIG, output_dir=self.output,
                                   collect=lambda: None, build=lambda now, config: (b"EML", "표시 1건"), deliver=deliver)
        return code, logs.output

    def test_partial_send_exit_1_and_history_reads_partial(self):
        def deliver(eml, mail_file):
            raise daily.PartialSendError("그룹 발송 부분 실패: 파일럿 그룹 3명 중 성공 2 · 실패 1 · 불명확 0 · 미시도 0")
        code, output = self.run_with(deliver)
        self.assertEqual(code, 1)
        line = next(o for o in output if "부분 실패" in o)
        self.assertNotIn("발송하지 않음", line)
        log = self.dir / "daily.log"
        log.write_text("2026-10-13 08:03:00,000 INFO 실행 시작: 자동 실행 (발송 포함)\n"
                       "2026-10-13 08:03:01,000 INFO RSS 수집 완료\n"
                       "2026-10-13 08:03:02,000 ERROR 발송 단계 부분 실패: 파일럿 그룹 3명 중 성공 2 · 실패 1 · 불명확 0 · 미시도 0\n",
                       encoding="utf-8")
        run = history.parse_runs(history.read_log(log))[0]
        self.assertEqual((run.result, run.sent), ("부분 발송", True))

    def test_group_success_line_reads_success(self):
        log = self.dir / "daily.log"
        log.write_text("2026-10-13 08:03:00,000 INFO 실행 시작: 자동 실행 (발송 포함)\n"
                       "2026-10-13 08:03:02,000 INFO 그룹 발송 완료: 파일럿 그룹 3명 중 성공 3 · 실패 0 · 불명확 0 · 미시도 0\n",
                       encoding="utf-8")
        run = history.parse_runs(history.read_log(log))[0]
        self.assertEqual((run.result, run.sent), ("성공", True))


class MailFileTests(Base):
    def test_same_minute_does_not_overwrite(self):
        first = daily.save_mail_file(self.output, "daily_20261013_0803", b"ONE")
        second = daily.save_mail_file(self.output, "daily_20261013_0803", b"TWO")
        third = daily.save_mail_file(self.output, "daily_20261013_0803", b"THREE")
        self.assertEqual([p.name for p in (first, second, third)],
                         ["daily_20261013_0803.eml", "daily_20261013_0803-2.eml", "daily_20261013_0803-3.eml"])
        self.assertEqual(first.read_bytes(), b"ONE")  # 기존 파일 바이트 보존
        self.assertEqual(history.cleanup(self.dir, 90, 30, datetime(2026, 12, 31).date()), (0, 3))  # 보관 정리 대상 인식

    def test_run_daily_logs_actual_name(self):
        (self.output / "daily_20261013_0803.eml").write_bytes(b"OLD")
        seen = []
        with self.assertLogs(level="INFO") as logs:
            daily.run_daily(datetime(2026, 10, 13, 8, 3, tzinfo=timezone.utc).astimezone(), CONFIG, output_dir=self.output,
                            collect=lambda: None, build=lambda now, config: (b"NEW", "표시 1건"),
                            deliver=lambda eml, name: seen.append(name) or "발송 완료 1회")
        name = seen[0]
        self.assertNotEqual(name, "daily_20261013_0803.eml")
        self.assertIn(f"메일 생성 완료: {name}", "\n".join(logs.output))
        self.assertEqual((self.output / "daily_20261013_0803.eml").read_bytes(), b"OLD")

    def test_save_failure_means_no_send(self):
        blocked = self.dir / "blocked"
        blocked.write_text("파일", encoding="utf-8")  # 폴더 자리에 파일이 있어 저장 실패
        sent = []
        with self.assertLogs(level="INFO"):
            code = daily.run_daily(datetime(2026, 10, 13, 8, 3, tzinfo=timezone.utc), CONFIG, output_dir=blocked,
                                   collect=lambda: None, build=lambda now, config: (b"X", "표시 1건"),
                                   deliver=lambda eml, name: sent.append(name))
        self.assertEqual((code, sent), (1, []))


class ResendTests(Base):
    def setUp(self):
        super().setUp()
        self.mail = self.output / "daily_20261013_0803.eml"
        self.mail.write_bytes(self.eml)
        extra = "virtual.four@tbell.co.kr"
        rc.save("가상 3", extra, "보안사업팀", ["파일럿"], path=self.people)
        self.all = PEOPLE + [extra]
        self.send_id = sendlog.start("자동 실행", "파일럿 그룹", self.all, mail_file=self.mail.name,
                                     mail_sha256=hashlib.sha256(self.eml).hexdigest(), path=self.history)
        for email, status in zip(self.all, ("성공", "실패", "미시도", "불명확")):
            sendlog.mark(self.send_id, email, status, path=self.history)
        sendlog.finish(self.send_id, self.history)
        self.options = dict(history=self.history, recipients_path=self.people, output_dir=self.output)

    def test_locked_refused_without_test_substitute(self):
        with patch.object(send_mail, "send_test") as test, self.assertRaises(daily.DailyError):
            daily.resend_failed(self.send_id, **self.options)
        test.assert_not_called()
        self.assertEqual(len(sendlog.sends(self.history)), 1)

    def test_only_clear_failures_resent_once(self):
        with self.unlocked():
            text = daily.resend_failed(self.send_id, **self.options)
        self.assertEqual(sorted(to for to, _ in self.sent_to), sorted([PEOPLE[1], PEOPLE[2]]))  # 성공·불명확 제외
        self.assertIn("성공 2", text)
        child = sendlog.sends(self.history)[0]
        self.assertEqual((child.parent_id, child.mail_file), (self.send_id, self.mail.name))
        with self.unlocked(), self.assertRaises(daily.DailyError):  # 반복 요청: 다시 보낼 사람 없음
            daily.resend_failed(self.send_id, **self.options)
        self.assertEqual(self.sent_to, [])

    def test_disabled_excluded(self):
        person = next(r for r in rc.recipients(self.people) if r.email == PEOPLE[1])
        rc.set_enabled(person.id, False, self.people)
        with self.unlocked():
            text = daily.resend_failed(self.send_id, **self.options)
        self.assertEqual([to for to, _ in self.sent_to], [PEOPLE[2]])
        self.assertIn("제외 1명", text)

    def test_deleted_excluded(self):
        person = next(r for r in rc.recipients(self.people) if r.email == PEOPLE[2])
        rc.delete(person.id, self.people)
        with self.unlocked():
            text = daily.resend_failed(self.send_id, **self.options)
        self.assertEqual([to for to, _ in self.sent_to], [PEOPLE[1]])
        self.assertIn("제외 1명", text)

    def test_domain_no_longer_allowed_excluded(self):
        with patch.object(rc, "domains", return_value=["other.invalid"]), self.unlocked(), \
                self.assertRaises(daily.DailyError):  # 둘 다 허용 도메인이 아니면 보낼 사람이 없다
            daily.resend_failed(self.send_id, **self.options)
        self.assertEqual(self.sent_to, [])

    def test_all_excluded_conditions_together(self):
        for email in PEOPLE[1:3]:
            person = next(r for r in rc.recipients(self.people) if r.email == email)
            rc.set_enabled(person.id, False, self.people)
        with self.unlocked(), self.assertRaises(daily.DailyError):
            daily.resend_failed(self.send_id, **self.options)
        self.assertEqual(self.sent_to, [])

    def test_mail_file_missing_or_changed_stops(self):
        self.mail.write_bytes(self.eml + b"changed")
        with self.unlocked(), self.assertRaises(daily.DailyError):
            daily.resend_failed(self.send_id, **self.options)
        self.mail.unlink()
        with self.unlocked(), self.assertRaises(daily.DailyError):
            daily.resend_failed(self.send_id, **self.options)
        self.assertEqual(self.sent_to, [])

    def test_test_round_not_resendable(self):
        test_id = sendlog.record("자동 실행", "TEST 주소", [sendlog.Result(TEST_ADDRESS, "실패", "x")], path=self.history)
        with self.unlocked(), self.assertRaises(daily.DailyError):
            daily.resend_failed(test_id, **self.options)


class ResendLineageTests(Base):
    """재발송의 재발송까지 모든 후손 회차를 본다 (D-077 잔여 결함 1)."""

    def round(self, statuses, parent=None):
        send_id = sendlog.start("x", "파일럿 그룹", list(statuses), mail_file="m.eml", parent_id=parent, path=self.history)
        for email, status in statuses.items():
            sendlog.mark(send_id, email, status, path=self.history)
        sendlog.finish(send_id, self.history)
        return send_id

    def test_grandchild_success_and_unclear_not_reselected(self):
        a, b, c = PEOPLE
        root = self.round({a: "실패", b: "실패", c: "미시도"})
        child = self.round({a: "성공", b: "실패", c: "실패"}, root)
        self.assertCountEqual(sendlog.resend_targets(root, self.history), [b, c])
        self.round({b: "성공", c: "불명확"}, child)
        self.assertEqual(sendlog.resend_targets(root, self.history), [])  # 손자 회차의 성공·불명확도 제외
        self.assertEqual(sendlog.resend_targets(child, self.history), [])

    def test_still_failing_down_the_line_stays_target(self):
        a, b, _ = PEOPLE
        root = self.round({a: "실패", b: "실패"})
        child = self.round({a: "실패", b: "미시도"}, root)
        self.round({a: "실패"}, child)
        self.assertCountEqual(sendlog.resend_targets(root, self.history), [a, b])

    def test_sibling_round_and_unrelated_round_ignored(self):
        a, b, _ = PEOPLE
        root = self.round({a: "실패", b: "실패"})
        other = self.round({a: "실패"})
        self.round({a: "성공"}, other)  # 다른 원회차의 후손
        self.round({b: "전송 중"}, root)  # 중단된 재발송: 불명확
        self.assertEqual(sendlog.resend_targets(root, self.history), [a])


class StatusMatrixTests(Base):
    """로그 → 실행 결과 표시. 성공 1명 이상일 때만 "부분 발송" (D-077 잔여 결함 2)."""

    def parse(self, counts):
        log = self.dir / "daily.log"
        log.write_text("2026-10-13 08:03:00,000 INFO 실행 시작: 자동 실행 (발송 포함)\n"
                       f"2026-10-13 08:03:02,000 ERROR 발송 단계 부분 실패: 파일럿 그룹 3명 중 {counts}\n", encoding="utf-8")
        return history.parse_runs(history.read_log(log))[0]

    def test_matrix(self):
        cases = [("성공 2 · 실패 1 · 불명확 0 · 미시도 0", "부분 발송", True, "일부만 보냄"),
                 ("성공 1 · 실패 0 · 불명확 2 · 미시도 0", "부분 발송", True, "일부만 보냄"),
                 ("성공 0 · 실패 3 · 불명확 0 · 미시도 0", "실패", False, "아무도 받지 못함"),
                 ("성공 0 · 실패 0 · 불명확 0 · 미시도 3", "실패", False, "아무도 받지 못함"),
                 ("성공 0 · 실패 1 · 불명확 1 · 미시도 1", "실패", False, "불명확"),
                 ("성공 0 · 실패 0 · 불명확 3 · 미시도 0", "실패", False, "불명확")]
        for counts, result, sent, words in cases:
            with self.subTest(counts=counts):
                run = self.parse(counts)
                self.assertEqual((run.result, run.sent), (result, sent))
                self.assertIn(words, run.error)
                if "불명확 0" not in counts:
                    self.assertNotIn("받지 못함", run.error)  # 불명확이 있으면 안 받았다고 단정하지 않는다

    def test_real_messages_round_trip(self):  # deliver_group 이 만든 문구 그대로
        for plan, result in (([smtplib.SMTPDataError(552, b"x")] * 3, "실패"),
                             ([{}, smtplib.SMTPDataError(552, b"x"), {}], "부분 발송")):
            with self.subTest(result=result), self.unlocked(plan), self.assertRaises(daily.PartialSendError) as caught:
                self.newsletter()
            self.assertEqual(self.parse(str(caught.exception).split(": ", 1)[1].split(" 중 ", 1)[1].split(" (")[0]).result, result)


class RecordErrorTests(Base):
    """보낸 뒤 기록 실패는 "발송하지 않음" 으로 쓰지 않는다 (D-077 잔여 결함 3)."""

    def run_with(self, error):
        def deliver(eml, mail_file):
            raise error
        with self.assertLogs(level="INFO") as logs:
            code = daily.run_daily(datetime(2026, 10, 13, 8, 3, tzinfo=timezone.utc), CONFIG, output_dir=self.output,
                                   collect=lambda: None, build=lambda now, config: (b"EML", "표시 1건"), deliver=deliver)
        self.assertEqual(code, 1)
        return next(o for o in logs.output if "단계 실패" in o)

    def test_messages(self):
        cases = [(sendlog.SendLogError("발송 이력 저장 실패: OperationalError"), "발송 여부 불명확"),
                 (SendError("SMTP 오류: 발송 단계, SMTPServerDisconnected, 코드 없음"), "발송 여부 불명확"),
                 (SendError("SMTP 인증 실패 (아이디·비밀번호·SMTP 사용 설정 확인)"), "오늘은 발송하지 않음"),
                 (daily.DailyError("발송 이력 저장 실패 (보내기 전이라 아무에게도 보내지 않음)"), "오늘은 발송하지 않음"),
                 (RuntimeError("x"), "오늘은 발송하지 않음")]
        for error, words in cases:
            with self.subTest(error=type(error).__name__, words=words):
                line = self.run_with(error)
                self.assertIn(words, line)
                if words != "오늘은 발송하지 않음":
                    self.assertNotIn("발송하지 않음", line)

    def test_group_mark_failure_mid_send_is_unclear(self):
        real = sendlog.mark
        calls = []

        def flaky(send_id, email, status, detail="", path=sendlog.DEFAULT_PATH):
            calls.append(status)
            if status == "성공" and calls.count("성공") == 2:
                raise sendlog.SendLogError("발송 이력 저장 실패: OperationalError")
            return real(send_id, email, status, detail, path)
        with self.unlocked(), patch.object(sendlog, "mark", flaky):
            line = self.run_with_real()
        self.assertIn("발송 여부 불명확", line)
        self.assertEqual(len(self.sent_to), 2)  # 기록 실패 뒤에는 더 보내지 않는다
        self.assertEqual(sendlog.sends(self.history)[0].counts, {"성공": 1, "불명확": 1, "미시도": 1})

    def run_with_real(self):
        config = DailyConfig(**{**CONFIG.__dict__, "target_group": "파일럿"})
        deliver = partial(daily.send_newsletter, config=config, origin="자동 실행", history=self.history,
                          recipients_path=self.people)
        with self.assertLogs(level="INFO") as logs:
            daily.run_daily(datetime(2026, 10, 13, 8, 3, tzinfo=timezone.utc), config, output_dir=self.output,
                            collect=lambda: None, build=lambda now, c: (self.eml, "표시 1건"), deliver=deliver)
        return next(o for o in logs.output if "단계 실패" in o)

    def test_resend_uses_same_wording(self):
        self.assertIn("발송 여부 불명확", daily.failure_text("발송", sendlog.SendLogError("x"), "재발송하지 않음"))
        self.assertIn("재발송하지 않음", daily.failure_text("발송", daily.DailyError("잠금 중"), "재발송하지 않음"))


class TestPathProtectionTests(Base):
    """TEST 주소도 회차 → 전송 중 → 보내기 순서 (D-077 잔여 결함 4)."""

    def status(self):
        record = sendlog.sends(self.history)[0]
        return record.finished, sendlog.results(record.id, self.history)[0].status

    def test_success_order(self):
        seen = []

        def fake_send(message, send):
            seen.append(self.status())
            return "발송 완료 1회"
        with patch.object(send_mail, "send_test", side_effect=fake_send):
            self.newsletter("TEST")
        self.assertEqual(seen, [(False, "불명확")])  # 보내는 순간에는 "전송 중" (화면에는 불명확으로 읽힘)
        self.assertEqual(self.status(), (True, "성공"))
        self.assertEqual(sendlog.sends(self.history)[0].mail_sha256, hashlib.sha256(self.eml).hexdigest())

    def test_start_failure_never_calls_smtp(self):
        with patch.object(sendlog, "start", side_effect=sendlog.SendLogError("발송 이력 저장 실패: OperationalError")), \
                patch.object(send_mail, "send_test") as test, self.assertRaises(daily.DailyError):
            self.newsletter("TEST")
        test.assert_not_called()

    def test_sending_mark_failure_never_calls_smtp(self):
        real = sendlog.mark

        def flaky(send_id, email, status, detail="", path=sendlog.DEFAULT_PATH):
            if status == "전송 중":
                raise sendlog.SendLogError("발송 이력 저장 실패: OperationalError")
            return real(send_id, email, status, detail, path)
        with patch.object(sendlog, "mark", flaky), patch.object(send_mail, "send_test") as test, \
                self.assertRaises(daily.DailyError):
            self.newsletter("TEST")
        test.assert_not_called()
        self.assertEqual(self.status(), (True, "미시도"))

    def test_record_failure_after_send_is_unclear(self):
        real = sendlog.mark

        def flaky(send_id, email, status, detail="", path=sendlog.DEFAULT_PATH):
            if status == "성공":
                raise sendlog.SendLogError("발송 이력 저장 실패: OperationalError")
            return real(send_id, email, status, detail, path)
        with patch.object(sendlog, "mark", flaky), patch.object(send_mail, "send_test", return_value="발송 완료 1회"), \
                self.assertRaises(sendlog.SendLogError):
            self.newsletter("TEST")
        self.assertEqual(self.status(), (True, "불명확"))

    def test_failure_record_failure_keeps_original_error(self):
        real = sendlog.mark

        def flaky(send_id, email, status, detail="", path=sendlog.DEFAULT_PATH):
            if status != "전송 중":
                raise sendlog.SendLogError("발송 이력 저장 실패: OperationalError")
            return real(send_id, email, status, detail, path)
        with patch.object(sendlog, "mark", flaky), \
                patch.object(send_mail, "send_test", side_effect=SendError("SMTP 오류: 발송 단계, SMTPDataError")), \
                self.assertRaises(SendError):
            self.newsletter("TEST")
        self.assertEqual(self.status(), (True, "불명확"))

    def test_interrupted_after_send_is_unclear(self):
        with patch.object(send_mail, "send_test", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.newsletter("TEST")
        self.assertEqual(self.status(), (True, "불명확"))

    def test_killed_process_reads_unclear(self):  # finish 도 못 한 경우 (강제 종료)
        with patch.object(sendlog, "finish"), patch.object(send_mail, "send_test", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                self.newsletter("TEST")
        self.assertEqual(self.status(), (False, "불명확"))

    def test_old_format_db_stops_safely(self):
        import sqlite3
        with sqlite3.connect(self.history) as c:  # 예전 구조: results 에 status 없음
            c.execute("CREATE TABLE results (send_id INTEGER, email TEXT, ok INTEGER, detail TEXT)")
        c.close()
        before = self.history.read_bytes()
        with patch.object(send_mail, "send_test") as test, self.assertRaises(daily.DailyError) as caught:
            self.newsletter("TEST")
        test.assert_not_called()
        self.assertIn("예전 형식", str(caught.exception))
        with sqlite3.connect(self.history) as c:  # 마이그레이션하지 않았다
            self.assertNotIn("status", {row[1] for row in c.execute("PRAGMA table_info(results)")})
        c.close()
        self.assertEqual(self.history.read_bytes(), before)  # 표도 더하지 않았다


class PartialFileTests(Base):
    """메일 파일 쓰기 실패: 반쯤 쓴 파일을 남기지 않고 보내지 않는다 (D-077)."""

    def test_write_failure_removes_partial_file(self):
        (self.output / "daily_20261013_0803.eml").write_bytes(b"OLD")
        real_open = Path.open

        class Broken:
            def __init__(self, handle):
                self.handle = handle

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.handle.close()

            def write(self, data):
                self.handle.write(data[:2])
                self.handle.flush()
                raise OSError("디스크 가득 참")

        def fake_open(path, mode="r", *args, **kwargs):
            handle = real_open(path, mode, *args, **kwargs)
            return Broken(handle) if mode == "xb" else handle
        with patch.object(Path, "open", fake_open), self.assertRaises(OSError):
            daily.save_mail_file(self.output, "daily_20261013_0803", b"NEWDATA")
        self.assertEqual(sorted(p.name for p in self.output.iterdir()), ["daily_20261013_0803.eml"])
        self.assertEqual((self.output / "daily_20261013_0803.eml").read_bytes(), b"OLD")
        sent = []
        with patch.object(Path, "open", fake_open), self.assertLogs(level="INFO") as logs:
            code = daily.run_daily(datetime(2026, 10, 13, 8, 3, tzinfo=timezone.utc), CONFIG, output_dir=self.output,
                                   collect=lambda: None, build=lambda now, config: (b"NEWDATA", "표시 1건"),
                                   deliver=lambda eml, name: sent.append(name))
        self.assertEqual((code, sent), (1, []))
        self.assertIn("오늘은 발송하지 않음", "\n".join(logs.output))
        self.assertEqual(len(list(self.output.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
