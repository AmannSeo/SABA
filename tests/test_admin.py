from datetime import datetime, timedelta
from email.message import EmailMessage
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from saba import admin
from saba.admin import TOOLS, AdminApp, AdminError, load_admin_config, serve
from saba.daily import DailyConfig, load_config

TODAY = datetime.now()
ORIGINAL_IDS = ("cert-eu-security-advisories", "boho-security-notice", "cisa-cybersecurity-advisories",
                "the-hacker-news", "boannews", "boho-report-guide")
RSS = (b'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>t</title>'
       b'<item><title>Example advisory</title><link>https://example.com/a</link><guid>a1</guid>'
       b'<pubDate>Mon, 12 Oct 2026 03:00:00 +0000</pubDate></item></channel></rss>')
STAMP = TODAY.strftime("%Y-%m-%d")


class FakeShell:
    """PowerShell 대신 명령만 기록한다. 작업 상태와 등록 성공 여부를 바꿀 수 있다."""

    def __init__(self, state="Ready", register_code=0):
        self.calls, self.state, self.register_code = [], state, register_code

    def __call__(self, command):
        self.calls.append(command)
        if "Register-ScheduledTask" in command:
            return self.register_code, ""
        return 0, f"{self.state}|{STAMP} 10:15|0|{STAMP} 23:59"


class AdminBase(unittest.TestCase):
    log_text = (f"{STAMP} 10:15:05,000 INFO 실행 시작: 자동 실행 (발송 포함)\n"
                f"{STAMP} 10:15:06,000 INFO RSS 수집 완료\n"
                f"{STAMP} 10:15:13,000 INFO 메일 생성 완료: daily_{TODAY:%Y%m%d}_1015.eml · 표시 7건 · 분석 재사용 1 · 신규 2"
                f" · 실패 0 · 시사점 재사용 1 · 신규 3 · 실패 0 · 113,000 bytes\n"
                f"{STAMP} 10:15:14,000 INFO 발송 완료 1회: 받는 사람 1명 · 메시지 113,050 bytes\n")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for folder in ("logs", "output", "data", "config"):
            (self.root / folder).mkdir()
        self.log = self.root / "logs" / f"daily_{TODAY:%Y%m%d}.log"
        self.log.write_text(self.log_text, encoding="utf-8")
        for name in ("daily.json", "departments.json"):
            (self.root / "config" / name).write_bytes((admin.ROOT / "config" / name).read_bytes())
        # RSS Source 는 설정 파일 (관리 화면에서 바뀜) 과 무관하게 처음 6곳으로 고정한다.
        rows = json.loads((admin.ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
        six = [row for row in rows if row["id"] in ORIGINAL_IDS]
        (self.root / "config" / "sources.json").write_text(json.dumps(six, ensure_ascii=False), encoding="utf-8")
        self.shell, self.commands, self.launched, self.fetched = FakeShell(), [], [], []
        self.app = AdminApp(root=self.root, shell=self.shell, launch=self.launched.append,
                            command=lambda args: (self.commands.append(args) or (0, "ok")),
                            fetch=lambda source: (self.fetched.append(source.feed_url) or RSS))
        self.server = serve("127.0.0.1", 0, self.app)
        self.port = self.server.server_address[1]
        self.server.RequestHandlerClass = admin.make_handler(self.app, self.port)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        return response.status, response.read().decode("utf-8"), response.getheader("Location")

    def post(self, action, confirm=True, **fields):
        data = {"token": self.app.token, **fields}
        if confirm:
            data["confirm"] = "yes"
        return self.request("POST", f"/action/{action}", urlencode(data, doseq=True))

    def get(self, path):
        status, html, _ = self.request("GET", path)
        self.assertEqual(status, 200, path)
        return html


class AdminTests(AdminBase):
    def test_config_allows_loopback_only(self):
        path = self.root / "config" / "admin.json"
        for host, ok in (("127.0.0.1", True), ("localhost", True), ("0.0.0.0", False), ("192.168.0.10", False)):
            path.write_text(json.dumps({"host": host, "port": 8765}), encoding="utf-8")
            if ok:
                self.assertEqual(load_admin_config(path), (host, 8765))
            else:
                self.assertRaises(AdminError, load_admin_config, path)
        self.assertRaises(AdminError, serve, "0.0.0.0", 0)
        self.assertEqual(load_admin_config()[0], "127.0.0.1")  # 저장소 기본 설정

    def test_all_pages_render_with_new_terms(self):  # D-072, D-073 용어·화면
        for path in ("/", "/test", "/schedule", "/sources", "/recipients", "/recipients?edit=new", "/sources?edit=new", "/sources?edit=boannews", "/logs",
                     "/logs?tab=detail", "/logs?tab=changes", "/newsletter", "/settings"):
            html = self.get(path)
            self.assertIn('href="/recipients"', html)  # 수신자·그룹 메뉴 (D-075)
        html = self.get("/")
        for text in ("예약 발송", "마지막 실행", "운영 현황", "최근 실행", 'class="switch"'):
            self.assertIn(text, html)
        for old in ("오늘 분량 실행", "발송 없이 실행", "자동 실행 켜기", "기능별 테스트", "점검 도구", "재발송", 'type="radio" name="state"'):
            self.assertNotIn(old, html)
        test = self.get("/test")
        for text in ("즉시 테스트 발송", "시각 지정 테스트 발송", "테스트 발송 기록", "점검 도구"):
            self.assertIn(text, test)

    def test_dashboard_summary_steps_and_switch(self):
        html = self.get("/")
        self.assertIn("기사 7건으로 메일을 만들어 TEST 1명에게 보냈습니다", html)
        self.assertIn("1. 기사 수집", html)
        self.assertIn('<div class="step done"><b>3. 발송</b>완료 10:15 · TEST 1명</div>', html)
        self.assertIn('type="checkbox" checked', html)  # 예약 발송 토글 켜짐
        self.assertNotIn("/action/run_send", html)  # 오늘 이미 발송 → 지금 발송 숨김
        test = self.get("/test")
        self.assertEqual(test.count("<dialog id=\"help-"), len(TOOLS))  # 점검 도구마다 설명 팝업
        self.assertIn("메일은 보내지 않습니다", test)

    def test_second_server_on_same_port_refused(self):  # Windows 포트 중복 방지
        with self.assertRaises(OSError):
            serve("127.0.0.1", self.port, self.app)

    def test_switch_off_shows_notice_instead_of_schedule(self):  # D-074
        self.shell.state = "Disabled"
        html = self.get("/")
        self.assertIn("예약 발송이 꺼져 있습니다.", html)
        self.assertNotIn("<th>다음 예약</th>", html)
        self.assertIn('type="checkbox" onchange', html)  # 스위치 꺼짐

    def test_foreign_host_header_rejected(self):  # DNS rebinding 방지
        self.assertEqual(self.request("GET", "/", host="evil.example:80")[0], 403)

    def test_settings_show_secret_presence_only(self):
        fake = {"OPENAI_API_KEY": "sk-FAKE-KEY-0000", "SABA_SMTP_PASSWORD": "FAKE-SECRET-PW-0000"}
        with patch.dict("os.environ", fake):
            html = self.get("/settings")
        self.assertIn("있음", html)
        for value in fake.values():
            self.assertNotIn(value, html)

    def test_post_requires_token_and_confirm(self):
        self.assertEqual(self.request("POST", "/action/task_state", "token=wrong&state=off")[0], 403)
        self.assertEqual(self.shell.calls, [])
        self.assertEqual(self.post("rss_dryrun", confirm=False)[0], 400)
        self.assertEqual(self.commands, [])
        self.assertEqual(self.post("rss_dryrun")[0], 303)
        self.assertEqual(self.commands[0][-3:], ["saba", "--collect-rss", "--dry-run"])

    def test_redirect_back_only_to_internal_pages(self):
        self.assertEqual(self.post("validate_config", back="/schedule")[2], "/schedule")
        self.assertEqual(self.post("validate_config", back="https://evil.example/")[2], "/")

    def test_task_state_radio(self):
        self.assertEqual(self.post("task_state", confirm=False, state="off")[0], 303)
        self.assertIn("Disable-ScheduledTask -TaskName SABA_Daily_Briefing", self.shell.calls[-1])
        self.post("task_state", confirm=False, state="on")
        self.assertIn("Enable-ScheduledTask -TaskName SABA_Daily_Briefing", self.shell.calls[-1])

    def test_send_check_never_connects(self):
        message = EmailMessage()
        message["Subject"] = "가상"
        message.set_content("본문")
        (self.root / "output" / f"daily_{TODAY:%Y%m%d}_1015.eml").write_bytes(message.as_bytes())
        with patch("smtplib.SMTP_SSL") as smtp:
            result = self.app.act("send_dryrun")
        smtp.assert_not_called()
        self.assertIn("드라이런", result)

    def test_smtp_check_is_login_only(self):
        with patch("saba.send_mail.send_test", return_value="확인") as send:
            self.app.act("smtp_check")
        self.assertTrue(send.call_args.kwargs["login_only"])

    def test_preview_rebuild_no_new_calls_and_keeps_one(self):
        with patch("saba.briefing.build_views", return_value=([], None, None)) as build:
            self.assertIn("없습니다", self.app.act("rebuild_preview"))
        self.assertEqual((build.call_args.kwargs["max_new_calls"], build.call_args.kwargs["insight_calls"]), (0, 0))
        (self.root / "output" / "daily_20261001_preview.eml").write_text("old", encoding="utf-8")
        with patch("saba.briefing.build_views", return_value=(["view"], None, None)), \
                patch("saba.mail.to_mail_html", return_value="<html></html>"), \
                patch("saba.mail.build_message", return_value=EmailMessage()):
            self.app.act("rebuild_preview")
        previews = list((self.root / "output").glob("*preview*"))
        self.assertEqual(len(previews), 1)
        self.assertNotEqual(previews[0].name, "daily_20261001_preview.eml")

    def test_newsletter_kinds_and_cid_inline(self):
        from saba.mail import build_message
        html = '<html><body><img src="cid:saba-logo"></body></html>'
        (self.root / "output" / f"daily_{TODAY:%Y%m%d}_1015.eml").write_bytes(build_message(html, "가상").as_bytes())
        (self.root / "output" / f"daily_{TODAY:%Y%m%d}_1100_preview.eml").write_bytes(build_message(html, "가상").as_bytes())
        page = self.get("/newsletter")
        self.assertIn("발송본", page)
        self.assertIn("미리보기", page)
        view = self.get(f"/newsletter/view?name=daily_{TODAY:%Y%m%d}_1015.eml")
        self.assertNotIn("cid:", view)
        self.assertIn("data:image/png;base64,", view)
        self.assertEqual(self.get("/newsletter/view?name=../config/admin.json"), "<p>생성된 메일이 없습니다.</p>")

    def test_logs_tabs_tables(self):
        runs = self.get("/logs")
        self.assertIn("자동 실행 (발송 포함)", runs)
        self.assertIn("보관: 실행 로그 90일", runs)
        detail = self.get(f"/logs?tab=detail&day={TODAY:%Y%m%d}")
        self.assertIn("RSS 수집 완료", detail)
        self.assertIn("<option", detail)


class ScheduleTests(AdminBase):
    """예약 발송 설정 저장 (D-072)."""

    form = {"mode": "dates", "dates": "2026-10-20\n2026-10-12", "time": "15:00", "random_delay_minutes": "0",
            "max_analysis_calls": "20", "max_insight_calls": "20", "send": "on", "log_days": "90", "mail_days": "30",
            "back": "/schedule"}

    def config(self):
        return load_config(self.root / "config" / "daily.json")

    def test_save_needs_confirm(self):
        self.assertEqual(self.post("save_schedule", confirm=False, **self.form)[0], 400)
        self.assertEqual(self.config().mode, "weekly")

    def test_schedule_change_saves_reregisters_and_logs(self):
        status, _, location = self.post("save_schedule", **self.form)
        self.assertEqual((status, location), (303, "/schedule"))
        config = self.config()
        self.assertEqual((config.mode, config.dates, config.time, config.random_delay_minutes),
                         ("dates", ("2026-10-12", "2026-10-20"), "15:00", 0))
        register = [c for c in self.shell.calls if "Register-ScheduledTask" in c]
        self.assertEqual(len(register), 1)
        self.assertIn("-Daily -At 15:00", register[0])
        self.assertIn("저장 완료", self.app.message)
        changes = self.get("/logs?tab=changes")
        self.assertIn("특정 날짜", changes)
        self.assertIn("15:00", changes)

    def test_caps_only_change_does_not_reregister(self):
        form = {**self.form, "mode": "weekly", "weekdays": ["MON", "TUE", "WED", "THU", "FRI"], "dates": "",
                "time": "08:00", "random_delay_minutes": "5", "max_analysis_calls": "30"}
        self.post("save_schedule", **form)
        self.assertEqual(self.config().max_analysis_calls, 30)
        self.assertFalse(any("Register-ScheduledTask" in c for c in self.shell.calls))

    def test_invalid_values_not_saved(self):
        before = (self.root / "config" / "daily.json").read_bytes()
        for bad in ({"time": "25:00"}, {"mode": "monthly"}, {"max_analysis_calls": "99"}, {"dates": "2026-13-40"}):
            self.post("save_schedule", **{**self.form, **bad})
            self.assertEqual((self.root / "config" / "daily.json").read_bytes(), before, bad)
        self.assertFalse(any("Register-ScheduledTask" in c for c in self.shell.calls))

    def test_register_failure_rolls_back(self):
        self.shell.register_code = 1
        before = (self.root / "config" / "daily.json").read_bytes()
        self.post("save_schedule", **self.form)
        self.assertEqual((self.root / "config" / "daily.json").read_bytes(), before)
        self.assertFalse((self.root / "logs" / "settings_changes.log").exists())

    def test_disabled_task_stays_disabled(self):
        self.shell.state = "Disabled"
        self.post("save_schedule", **self.form)
        self.assertIn("Disable-ScheduledTask", self.shell.calls[-1])


class ManualRunTests(AdminBase):
    """지금 발송 (D-071, D-073): 오늘 실패·미발송일 때만 보인다. 실제 실행은 하지 않고 띄울 명령만 확인."""

    def set_config(self, **changes):
        from saba.daily import save_config
        config = load_config(self.root / "config" / "daily.json")
        save_config(DailyConfig(**{**config.__dict__, **changes}), self.root / "config" / "daily.json")

    def test_send_now_shown_when_missed_and_launches(self):
        self.set_config(mode="daily", time="00:00", random_delay_minutes=0)
        self.log.unlink()
        if datetime.now().hour == 0 and datetime.now().minute < 16:
            self.skipTest("예약 시각 직후 15분 안")
        html = self.get("/")
        self.assertIn("오늘 뉴스레터가 발송되지 않았습니다", html)
        self.assertIn("/action/run_send", html)
        self.assertEqual(self.post("run_send", confirm=False)[0], 400)
        self.assertEqual(self.launched, [])
        self.assertEqual(self.post("run_send")[0], 303)
        self.assertEqual(self.launched[0][2:], ["saba.daily", "--run", "--manual"])

    def test_not_shown_before_schedule_or_when_sent(self):
        self.assertIn("이미 발송", self.app.act("run_send"))  # 오늘 10:15 발송 기록
        self.assertEqual(self.launched, [])
        self.log.unlink()
        self.set_config(mode="dates", dates=("2000-01-01",))  # 오늘은 예약일 아님
        self.assertNotIn("/action/run_send", self.get("/"))

    def test_failed_today_shows_send_now(self):
        self.log.write_text(f"{STAMP} 08:01:00,000 INFO 실행 시작: 자동 실행 (발송 포함)\n"
                            f"{STAMP} 08:01:05,000 ERROR RSS 수집 단계 실패: RSS 수집 실패 (종료 코드 1) · 오늘은 발송하지 않음\n",
                            encoding="utf-8")
        html = self.get("/")
        self.assertIn("오늘 뉴스레터가 발송되지 않았습니다", html)
        self.assertIn("RSS 수집 단계: RSS 수집 실패 (종료 코드 1)", html)
        self.assertIn("/action/run_send", html)

    def test_test_sends_do_not_count_as_newsletter(self):
        self.log.write_text(self.log_text.replace("자동 실행 (발송 포함)", "테스트 발송 (즉시) (발송 포함)"), encoding="utf-8")
        self.set_config(mode="daily", time="00:00", random_delay_minutes=0)
        if datetime.now().hour == 0 and datetime.now().minute < 16:
            self.skipTest("예약 시각 직후 15분 안")
        self.assertIn("/action/run_send", self.get("/"))

    def test_running_blocks_new_run_and_refreshes(self):
        from saba.daily import run_lock
        with run_lock(self.root / "data" / "daily.lock"):
            self.assertIn("이미 실행 중", self.app.act("run_send"))
            self.assertIn("이미 실행 중", self.app.act("test_now"))
            html = self.get("/")
        self.assertEqual(self.launched, [])
        self.assertIn("실행 중", html)
        self.assertIn('http-equiv="refresh"', html)


class TestPageTests(AdminBase):
    """테스트 화면 (D-073): 즉시·시각 지정 테스트 발송과 기록."""

    def test_test_now_needs_confirm_and_launches(self):
        self.assertEqual(self.post("test_now", confirm=False)[0], 400)
        self.assertEqual(self.post("test_now", back="/test")[2], "/test")
        self.assertEqual(self.launched[0][2:], ["saba.daily", "--run", "--manual", "--test"])

    def test_schedule_registers_separate_one_time_task(self):
        at = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M")
        self.post("test_schedule", at=at, back="/test")
        register = [c for c in self.shell.calls if "Register-ScheduledTask" in c]
        self.assertEqual(len(register), 1)
        self.assertIn("-Once -At", register[0])
        self.assertIn("SABA_Test_Send", register[0])
        self.assertIn("--run --test", register[0])
        self.assertNotIn("SABA_Daily_Briefing", register[0])  # 평소 예약 일정은 그대로
        self.assertIn("테스트 발송 예약", self.app.message)

    def test_schedule_rejects_past_or_far_time(self):
        for value in ((datetime.now() - timedelta(minutes=5)), (datetime.now() + timedelta(days=8))):
            self.post("test_schedule", at=value.strftime("%Y-%m-%dT%H:%M"))
            self.assertIn("1분 뒤 ~ 7일 안", self.app.message)
        self.assertFalse(any("Register-ScheduledTask" in c for c in self.shell.calls))

    def test_cancel_unregisters_test_task(self):
        self.post("test_cancel")
        self.assertIn("Unregister-ScheduledTask -TaskName SABA_Test_Send", self.shell.calls[-1])

    def test_history_lists_only_test_runs(self):
        self.log.write_text(self.log_text + self.log_text.replace("10:15", "11:20").replace(
            "자동 실행 (발송 포함)", "테스트 발송 (예약) (발송 포함)"), encoding="utf-8")
        html = self.get("/test")
        history = html[html.index("테스트 발송 기록"):html.index("점검 도구")]
        self.assertIn("11:20", history)
        self.assertNotIn(f"{STAMP} 10:15", history)
        self.assertIn("<td>예약</td>", history)


class SourceTests(AdminBase):
    """RSS Source 관리 (D-073). 주소 확인 접속은 가짜 fetch 로 바꾼다."""

    form = {"mode": "new", "id": "example-feed", "name": "예시 피드", "url": "https://example.com/rss.xml",
            "region": "해외", "kind": "공식 기관", "enabled": "on", "back": "/sources"}

    def entries(self):
        from saba.rss import load_source_entries
        return load_source_entries(self.root / "config" / "sources.json")

    def test_add_requires_check_then_saves_and_logs(self):
        self.post("source_save", **self.form)
        self.assertIn("주소 확인", self.app.message)
        self.assertEqual(len(self.entries()), 6)
        self.post("source_check", **self.form)
        self.assertIn("주소 확인 성공: 항목 1건", self.app.message)
        self.assertEqual(self.fetched, ["https://example.com/rss.xml"])
        self.post("source_save", **self.form)
        self.assertIn("추가 완료", self.app.message)
        added = self.entries()[-1]
        self.assertEqual((added.source.source_id, added.source.official, added.enabled), ("example-feed", True, True))
        self.assertIn("RSS Source example-feed", self.get("/logs?tab=changes"))

    def test_invalid_or_duplicate_rejected(self):
        for bad in ({"id": "Bad ID"}, {"url": "http://example.com/rss"}, {"name": ""}, {"id": "boannews"}):
            self.post("source_check", **{**self.form, **bad})
            self.post("source_save", **{**self.form, **bad})
            self.assertEqual(len(self.entries()), 6, bad)

    def test_check_failure_blocks_save(self):
        from saba.rss import RssError

        def broken(source):
            raise RssError("예상한 RSS 2.0 channel 형식이 아닙니다.")
        self.app.fetch = broken
        self.post("source_check", **self.form)
        self.assertIn("주소 확인 실패", self.app.message)
        self.post("source_save", **self.form)
        self.assertEqual(len(self.entries()), 6)

    def test_edit_without_url_change_needs_no_check(self):
        self.post("source_save", mode="edit", id="boannews", name="보안뉴스 (수정)", url="https://www.boannews.com/rss/allArticle.xml",
                  region="국내", kst="on", enabled="on")
        source = next(e for e in self.entries() if e.source.source_id == "boannews").source
        self.assertEqual(source.source_name, "보안뉴스 (수정)")
        self.assertEqual(self.fetched, [])

    def test_toggle_and_delete_keep_one_enabled(self):
        self.post("source_toggle", id="boannews")
        self.assertFalse(next(e for e in self.entries() if e.source.source_id == "boannews").enabled)
        self.post("source_delete", id="cisa-cybersecurity-advisories")
        self.assertNotIn("cisa-cybersecurity-advisories", [e.source.source_id for e in self.entries()])
        for entry in self.entries()[1:]:
            if entry.enabled:
                self.post("source_toggle", id=entry.source.source_id)
        self.post("source_toggle", id=self.entries()[0].source.source_id)  # 마지막 사용 Source
        self.assertIn("하나 이상", self.app.message)
        self.assertTrue(self.entries()[0].enabled)


class RecipientPageTests(AdminBase):
    """수신자·그룹 화면 (D-074, D-075). 가상 주소만 쓴다."""

    def test_add_list_and_change_log_has_counts_only(self):
        self.post("recipient_save", confirm=False, name="가상 사용자", email="virtual.user@tbell.co.kr",
                  department="보안사업팀", groups=["TEST", "파일럿"], enabled="on", back="/recipients")
        self.assertIn("수신자 추가 완료", self.app.message)
        html = self.get("/recipients")
        self.assertIn("virtual.user@tbell.co.kr", html)
        self.assertIn("TEST 로 잠금", html)
        changes = (self.root / "logs" / "settings_changes.log").read_text(encoding="utf-8")
        self.assertIn("1명", changes)
        self.assertNotIn("virtual.user", changes)  # 개인정보는 기록하지 않음
        self.assertNotIn("가상 사용자", changes)

    def test_rejects_other_domain(self):
        self.post("recipient_save", confirm=False, name="외부", email="someone@gmail.com", department="보안사업팀")
        self.assertIn("허용되지 않은 도메인", self.app.message)
        self.assertNotIn("someone@gmail.com", self.get("/recipients"))

    def test_csv_preview_then_apply(self):
        text = "이름,메일,부서,그룹\n가상 하나,virtual.one@tbell.co.kr,STE본부,TEST\n가상 둘,virtual.two@naver.com,STE본부,\n"
        self.post("csv_preview", confirm=False, csv=text, back="/recipients")
        self.assertIn("신규 1명", self.app.message)
        html = self.get("/recipients")
        self.assertIn("CSV 미리보기 (아직 저장 안 됨)", html)
        self.assertNotIn("<td>virtual.one@tbell.co.kr</td><td>STE본부</td><td><span", html)  # 아직 목록에 없음
        self.assertEqual(self.post("csv_apply", confirm=False)[0], 400)  # 확인 창 필요
        self.post("csv_apply", back="/recipients")
        self.assertIn("신규 1명", self.app.message)
        status, csv_text, _ = self.request("GET", "/recipients/export.csv")
        self.assertEqual(status, 200)
        self.assertIn("가상 하나,virtual.one@tbell.co.kr,STE본부,TEST,사용", csv_text)

    def test_groups_and_departments(self):
        self.post("group_add", confirm=False, name="임원")
        self.post("department_add", confirm=False, name="인사팀")
        html = self.get("/recipients")
        self.assertIn("임원", html)
        self.assertIn("인사팀", html)
        self.post("group_delete", name="TEST")
        self.assertIn("지울 수 없습니다", self.app.message)


class CriteriaTests(AdminBase):
    """부서별 분류 기준 편집 (D-075)."""

    def form(self, **changes):
        from saba.insights import DEPARTMENT_NAMES, load_departments
        scopes, examples = load_departments(self.root / "config" / "departments.json")
        data = {}
        for i, name in enumerate(DEPARTMENT_NAMES):
            data[f"scope_{i}"], data[f"examples_{i}"] = scopes[name], examples[name]
        return {**data, **changes, "back": "/settings"}

    def test_save_updates_file_and_logs(self):
        self.assertIn("부서별 분류 기준", self.get("/settings"))
        self.post("criteria_save", **self.form(examples_1="가상 판단 예시"))
        self.assertIn("기술개발연구소", self.app.message)
        from saba.insights import load_departments
        self.assertEqual(load_departments(self.root / "config" / "departments.json")[1]["기술개발연구소"], "가상 판단 예시")
        self.assertIn("부서 기준 기술개발연구소", self.get("/logs?tab=changes"))

    def test_empty_rejected(self):
        before = (self.root / "config" / "departments.json").read_bytes()
        self.post("criteria_save", **self.form(scope_0=""))
        self.assertIn("저장하지 않음", self.app.message)
        self.assertEqual((self.root / "config" / "departments.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
