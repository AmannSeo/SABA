from datetime import datetime
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
from saba.daily import load_config

TODAY = datetime.now()
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
        (self.root / "config" / "daily.json").write_bytes((admin.ROOT / "config" / "daily.json").read_bytes())
        self.shell, self.commands, self.launched = FakeShell(), [], []
        self.app = AdminApp(root=self.root, shell=self.shell, launch=self.launched.append,
                            command=lambda args: (self.commands.append(args) or (0, "ok")))
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

    def test_all_pages_render_with_new_terms(self):  # D-072 용어
        for path in ("/", "/schedule", "/logs", "/logs?tab=detail", "/logs?tab=changes", "/newsletter", "/settings"):
            html = self.get(path)
            self.assertIn("수신자·발송 관리 (2단계 예정)", html)
        html = self.get("/")
        for text in ("예약 발송", "지금 발송", "재발송", "점검 도구", "운영 현황", "마지막 실행"):
            self.assertIn(text, html)
        for old in ("오늘 분량 실행", "발송 없이 실행", "자동 실행 켜기", "기능별 테스트"):
            self.assertNotIn(old, html)

    def test_dashboard_tables_radio_and_help(self):
        html = self.get("/")
        self.assertIn("<td>발송</td><td>10:15</td>", html)  # 마지막 실행 단계 표
        self.assertIn("기사 7건 · AI 신규 호출 5건", html)
        self.assertIn('type="radio" name="state" value="on" checked', html)
        self.assertEqual(html.count("<dialog id=\"help-"), len(TOOLS))  # 점검 도구마다 설명 팝업
        self.assertIn("메일은 보내지 않습니다", html)

    def test_second_server_on_same_port_refused(self):  # Windows 포트 중복 방지
        with self.assertRaises(OSError):
            serve("127.0.0.1", self.port, self.app)

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
    """지금 발송·재발송 (D-071, D-072): 실제 실행은 하지 않고 띄울 명령만 확인한다."""

    def test_send_now_needs_confirm_and_launches_daily_run(self):
        self.log.unlink()
        self.assertEqual(self.post("run_send", confirm=False)[0], 400)
        self.assertEqual(self.launched, [])
        self.assertEqual(self.post("run_send")[0], 303)
        self.assertEqual(self.launched[0][2:], ["saba.daily", "--run", "--manual"])
        html = self.get("/")
        self.assertIn("아직 발송 안 함", html)
        self.assertNotIn("/action/run_resend", html)

    def test_already_sent_today_needs_resend(self):
        self.assertIn("10:15 에 이미 발송", self.app.act("run_send"))
        self.assertEqual(self.launched, [])
        html = self.get("/")
        self.assertIn("10:15 발송 완료", html)
        self.assertIn("/action/run_resend", html)
        self.app.act("run_resend")
        self.assertEqual(self.launched[0][2:], ["saba.daily", "--run", "--manual"])

    def test_failed_today_shows_alert(self):
        self.log.write_text(f"{STAMP} 08:01:00,000 INFO 실행 시작: 자동 실행 (발송 포함)\n"
                            f"{STAMP} 08:01:05,000 ERROR RSS 수집 단계 실패: RSS 수집 실패 (종료 코드 1) · 오늘은 발송하지 않음\n",
                            encoding="utf-8")
        html = self.get("/")
        self.assertIn("실행이 실패해 발송하지 않았습니다", html)
        self.assertIn("RSS 수집 단계: RSS 수집 실패 (종료 코드 1)", html)

    def test_running_blocks_new_run_and_refreshes(self):
        from saba.daily import run_lock
        with run_lock(self.root / "data" / "daily.lock"):
            self.assertIn("이미 실행 중", self.app.act("run_send"))
            html = self.get("/")
        self.assertEqual(self.launched, [])
        self.assertIn("실행 중", html)
        self.assertIn('http-equiv="refresh"', html)
        self.assertNotIn("/action/run_send", html)


if __name__ == "__main__":
    unittest.main()
