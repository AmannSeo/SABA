from datetime import datetime, timedelta
from email.message import EmailMessage
from dataclasses import replace
from html.parser import HTMLParser
import http.client
import json
import os
import re
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlparse

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
        self.env_writes = []  # 실제 레지스트리에 쓰지 않는다 (작업 5)
        self.app = AdminApp(root=self.root, shell=self.shell, launch=self.launched.append,
                            command=lambda args: (self.commands.append(args) or (0, "ok")),
                            fetch=lambda source: (self.fetched.append(source.feed_url) or RSS),
                            env_writer=lambda name, value: self.env_writes.append((name, value)))
        # 로그인 (작업 5): 테스트는 기본으로 관리자 세션을 쓴다. 해시 반복은 줄인다.
        iterations = patch.object(admin.auth, "ITERATIONS", 1000)
        iterations.start()
        self.addCleanup(iterations.stop)
        self.app.users.add("tester", "admin", "virtual-pass-1")
        self.cookie = "saba_session=" + self.app.sessions.create("tester", "admin")
        self.server = serve("127.0.0.1", 0, self.app)
        self.port = self.server.server_address[1]
        self.server.RequestHandlerClass = admin.make_handler(self.app, self.port)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, host=None, cookie=...):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        cookie = self.cookie if cookie is ... else cookie
        if cookie:
            headers["Cookie"] = cookie
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


class LoginTests(AdminBase):
    """작업 5: 로그인·세션·조회자 권한·Secret 변경. 실제 레지스트리 대신 env_writer 를 기록만 한다."""

    def login(self, user, password):
        status, _, location = self.request("POST", "/login", urlencode({"token": self.app.token, "user": user, "password": password}),
                                           cookie=None)
        return status, location

    def test_viewer_cannot_read_admin_csv_preview(self):
        self.post('csv_preview', csv='이름,메일,부서,그룹\n가상,private@example.com,STE본부,TEST', back='/recipients')
        self.assertTrue(self.app.csv_rows)
        self.app.users.add('viewer1', 'viewer', 'virtual-pass-1')
        cookie = 'saba_session=' + self.app.sessions.create('viewer1', 'viewer')
        html = self.request('GET', '/recipients', cookie=cookie)[1]
        self.assertNotIn('private@example.com', html)
        self.assertNotIn('CSV 미리보기 (아직 저장 안 됨)', html)

    def test_unicode_csrf_and_invalid_request_lengths_are_rejected(self):
        status, _, _ = self.request('POST', '/action/rss_dryrun', urlencode({'token': '잘못된 토큰', 'confirm': 'yes'}))
        self.assertEqual(status, 403)
        for length, expected in (('-1', 400), ('invalid', 400), ('262145', 413)):
            conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
            conn.request('POST', '/action/rss_dryrun', body=b'', headers={'Host': f'127.0.0.1:{self.port}', 'Content-Length': length})
            response = conn.getresponse()
            self.assertEqual(response.status, expected)
            response.read()
            conn.close()
        self.assertEqual(self.commands, [])

    def test_account_post_storage_error_is_sanitized(self):
        with patch.object(self.app.users, 'verify', side_effect=OSError('virtual-secret-in-error')):
            status, html, _ = self.request('POST', '/login', urlencode({'token': self.app.token, 'user': 'tester', 'password': 'virtual-pass-1'}), cookie=None)
        self.assertEqual(status, 500)
        self.assertIn('OSError', html)
        self.assertNotIn('virtual-secret-in-error', html)

    def test_pages_require_login_and_login_flow(self):
        status, _, location = self.request("GET", "/", cookie=None)
        self.assertEqual((status, location), (303, "/login"))
        self.assertIn("비밀번호", self.request("GET", "/login", cookie=None)[1])
        self.assertEqual(self.login("tester", "wrong-pass-12"), (303, "/login"))
        self.assertIn("맞지 않습니다", self.request("GET", "/login", cookie=None)[1])
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/login", body=urlencode({"token": self.app.token, "user": "tester", "password": "virtual-pass-1"}),
                     headers={"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/x-www-form-urlencoded"})
        response = conn.getresponse()
        cookie = response.getheader("Set-Cookie")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        status, html, _ = self.request("GET", "/", cookie=cookie.split(";")[0])
        self.assertEqual(status, 200)
        self.assertIn("tester · 관리자", html)
        self.assertIn("로그인", (self.root / "logs" / "settings_changes.log").read_text(encoding="utf-8"))

    def test_lockout_after_repeated_failures(self):
        for _ in range(admin.auth.MAX_FAILURES):
            self.login("tester", "wrong-pass-12")
        self.login("tester", "virtual-pass-1")  # 맞아도 잠금 중에는 거부
        self.assertIn("막았습니다", self.request("GET", "/login", cookie=None)[1])

    def test_expired_session_and_logout(self):
        now = [0.0]
        self.app.sessions.clock = lambda: now[0]
        cookie = "saba_session=" + self.app.sessions.create("tester", "admin")
        self.assertEqual(self.request("GET", "/", cookie=cookie)[0], 200)
        now[0] += admin.auth.SESSION_IDLE + 1
        self.assertEqual(self.request("GET", "/", cookie=cookie)[2], "/login")
        cookie = "saba_session=" + self.app.sessions.create("tester", "admin")
        status, _, location = self.request("POST", "/logout", urlencode({"token": self.app.token}), cookie=cookie)
        self.assertEqual((status, location), (303, "/login"))
        self.assertEqual(self.request("GET", "/", cookie=cookie)[2], "/login")

    def test_first_admin_setup_when_no_accounts(self):
        (self.root / "data" / "admin_users.json").unlink()
        self.assertEqual(self.request("GET", "/", cookie=None)[2], "/setup")
        status, _, location = self.request("POST", "/setup", urlencode({"token": self.app.token, "user": "boss", "password": "virtual-pass-9",
                                                                        "password2": "virtual-pass-9"}), cookie=None)
        self.assertEqual((status, location), (303, "/"))
        self.assertEqual(self.app.users.verify("boss", "virtual-pass-9"), "admin")
        # 계정이 생긴 뒤에는 /setup 으로 계정을 더 만들 수 없다
        self.request("POST", "/setup", urlencode({"token": self.app.token, "user": "intruder", "password": "virtual-pass-9",
                                                  "password2": "virtual-pass-9"}), cookie=None)
        self.assertIsNone(self.app.users.verify("intruder", "virtual-pass-9"))

    def test_viewer_sees_masked_data_and_cannot_act(self):
        from saba import recipients as rc
        rc.save("가상 사람", "someone.virtual@tbell.co.kr", rc.departments(self.app.recipients_path)[0][0], ["TEST"],
                path=self.app.recipients_path)
        self.app.users.add("viewer1", "viewer", "virtual-pass-1")
        viewer = "saba_session=" + self.app.sessions.create("viewer1", "viewer")
        html = self.request("GET", "/recipients", cookie=viewer)[1]
        self.assertIn("조회 전용 계정", html)
        self.assertNotIn("someone.virtual@", html)
        self.assertEqual(self.request("GET", "/recipients/export.csv", cookie=viewer)[0], 403)
        self.assertIn("disabled", self.request("GET", "/sources", cookie=viewer)[1])
        status, _, _ = self.request("POST", "/action/rss_dryrun", urlencode({"token": self.app.token, "confirm": "yes", "back": "/"}), cookie=viewer)
        self.assertEqual(status, 303)
        self.assertEqual(self.commands, [])  # 실행되지 않음
        self.request("POST", "/action/secret_set", urlencode({"token": self.app.token, "confirm": "yes", "name": "OPENAI_API_KEY",
                                                              "value": "sk-virtual-viewer"}), cookie=viewer)
        self.assertEqual(self.env_writes, [])

    def test_admin_changes_secret_without_exposing_value(self):
        self.post("secret_set", name="SABA_SMTP_PASSWORD", value="virtual-secret-VALUE-123", back="/settings")
        self.assertEqual(self.env_writes, [("SABA_SMTP_PASSWORD", "virtual-secret-VALUE-123")])
        html = self.get("/settings")
        self.assertIn("저장 완료", html)
        self.assertNotIn("virtual-secret-VALUE-123", html)
        self.assertNotIn("virtual-secret-VALUE-123", (self.root / "logs" / "settings_changes.log").read_text(encoding="utf-8"))
        self.post("secret_set", name="PATH", value="x", back="/settings")
        self.post("secret_set", name="OPENAI_API_KEY", value="has space", back="/settings")
        self.assertEqual(len(self.env_writes), 1)
        self.assertIn("SABA_DATA_GO_KR_KEY", self.get("/settings"))

    def test_admin_manages_accounts(self):
        self.post("user_add", confirm=False, user="viewer2", role="viewer", password="virtual-pass-3", password2="virtual-pass-3", back="/settings")
        self.assertEqual(self.app.users.verify("viewer2", "virtual-pass-3"), "viewer")
        viewer = self.app.sessions.create("viewer2", "viewer")
        self.post("user_password", confirm=False, user="viewer2", password="virtual-pass-4", password2="virtual-pass-4", back="/settings")
        self.assertIsNone(self.app.sessions.get(viewer))  # 비밀번호가 바뀌면 다시 로그인
        self.post("user_delete", user="viewer2", back="/settings")
        self.assertIsNone(self.app.users.verify("viewer2", "virtual-pass-4"))
        self.post("user_delete", user="tester", back="/settings")
        self.assertEqual(self.app.users.verify("tester", "virtual-pass-1"), "admin")  # 마지막 관리자는 남는다
        self.assertNotIn("virtual-pass", (self.root / "logs" / "settings_changes.log").read_text(encoding="utf-8"))


class LoginOffTests(AdminBase):
    """config/admin.json "login": false (사용자 결정 2026-10-14): 로그인 없이 관리자, Secret·계정 변경은 막는다."""

    def setUp(self):
        super().setUp()
        self.app.login_required = False

    def test_no_login_needed_but_secret_and_accounts_blocked(self):
        status, html, _ = self.request("GET", "/", cookie=None)
        self.assertEqual(status, 200)
        self.assertIn("로그인 꺼짐", html)
        self.assertEqual(self.request("GET", "/login", cookie=None)[2], "/")
        self.request("POST", "/action/secret_set", urlencode({"token": self.app.token, "confirm": "yes", "name": "OPENAI_API_KEY",
                                                              "value": "sk-virtual"}), cookie=None)
        self.assertEqual(self.env_writes, [])
        settings = self.request("GET", "/settings", cookie=None)[1]
        self.assertIn("로그인이 꺼져 있어", settings)
        self.request("POST", "/action/rss_dryrun", urlencode({"token": self.app.token, "confirm": "yes", "back": "/"}), cookie=None)
        self.assertEqual(len(self.commands), 1)  # 다른 실행은 그대로 된다

    def test_login_setting_in_config(self):
        path = self.root / "config" / "admin.json"
        path.write_text('{"host": "127.0.0.1", "port": 8765, "login": false}', encoding="utf-8")
        self.assertFalse(admin.login_enabled(path))
        path.write_text('{"host": "127.0.0.1", "port": 8765}', encoding="utf-8")
        self.assertTrue(admin.login_enabled(path))
        path.write_text('{"host": "127.0.0.1", "port": 8765, "login": "no"}', encoding="utf-8")
        with self.assertRaises(AdminError):
            admin.login_enabled(path)

    def test_api_keywords_saved_from_settings(self):
        self.post("api_keywords_save", confirm=False, g2b="정보보호, 모의해킹", kstartup="AI", law="근로, 소득세", back="/settings")
        from saba.public_api import load_keywords
        self.assertEqual(load_keywords(self.root / "config" / "public_api.json"),
                         {"g2b": ["정보보호", "모의해킹"], "kstartup": ["AI"], "law": ["근로", "소득세"]})


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
        self.assertIn("예약 발송 꺼져 있습니다", html)
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
        monthly = self.root / "output" / "26/10/daily_20261001_preview.eml"
        monthly.parent.mkdir(parents=True)
        monthly.write_bytes(b"old monthly preview")
        with patch("saba.briefing.build_views", return_value=(["view"], None, None)), \
                patch("saba.mail.to_mail_html", return_value="<html></html>"), \
                patch("saba.mail.build_message", return_value=EmailMessage()):
            self.app.act("rebuild_preview")
        previews = list((self.root / "output").glob("*preview*"))
        self.assertEqual(len(previews), 1)
        self.assertNotEqual(previews[0].name, "daily_20261001_preview.eml")
        self.assertFalse(monthly.exists())

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

    def test_status_departments_and_method_shown_and_kept(self):
        """F10 최근 수집·F11 담당 부서·웹페이지 수집 방식 표시, 수정 저장 때 수집 방식 유지 (D-078)."""
        import json as js
        (self.root / "data" / "source_status.json").write_text(js.dumps({
            "cert-eu-security-advisories": {"last_attempt": "2026-10-13T08:03:00+09:00", "ok": False, "error": "목록 페이지 요청 실패",
                                            "last_success": "2026-10-12T08:03:00+09:00", "fetched": 6, "new": 0},
            "boannews": {"last_attempt": "2026-10-13T08:03:00+09:00", "ok": True, "fetched": 30, "new": 4,
                         "last_success": "2026-10-13T08:03:00+09:00", "error": ""}}, ensure_ascii=False), encoding="utf-8")
        rows = js.loads((self.root / "config" / "sources.json").read_text(encoding="utf-8"))
        rows.append({"id": "virtual-moel", "name": "가상 보도자료", "url": "https://www.example.go.kr/list.do", "region": "국내",
                     "kind": "공식 기관", "topic": "경영", "method": "crawl:moel", "kst": True, "date_only": True, "enabled": True})
        (self.root / "config" / "sources.json").write_text(js.dumps(rows, ensure_ascii=False), encoding="utf-8")
        html = self.get("/sources")
        for text in ("목록 페이지 요청 실패", "마지막 성공 10-12 08:03", "신규 4건", "기록 없음", "보안사업팀",
                     "경영전략팀 · 사업지원팀", "웹페이지", "data-health='실패'"):
            self.assertIn(text, html)
        self.post("source_save", mode="edit", id="virtual-moel", name="가상 보도자료 (수정)", url="https://www.example.go.kr/list.do",
                  region="국내", kind="공식 기관", topic="경영", method="crawl:moel", kst="on", date_only="on", enabled="on", back="/sources")
        edited = next(e for e in self.entries() if e.source.source_id == "virtual-moel")
        self.assertEqual((edited.source.source_name, edited.source.method), ("가상 보도자료 (수정)", "crawl:moel"))

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


class SendHistoryTests(AdminBase):
    """발송 이력 탭과 발송 대상 잠금 (D-076). 가상 주소만."""

    def test_history_tab_lists_sends_and_results(self):
        from saba import sendlog
        path = self.root / "data" / "send_history.db"
        send_id = sendlog.record("자동 실행 (발송 포함)", "TEST 주소",
                                 [sendlog.Result("virtual.one@tbell.co.kr", "성공", "성공")], "daily_x.eml", path)
        html = self.get("/logs?tab=sends")
        self.assertIn("TEST 주소", html)
        self.assertIn("수신자별 결과", html)
        detail = self.get(f"/logs?tab=sends&day={send_id}")
        self.assertIn("virtual.one@tbell.co.kr", detail)

    def test_empty_history_message(self):
        self.assertIn("아직 발송 이력이 없습니다", self.get("/logs?tab=sends"))

    def test_target_locked_on_schedule_page_and_kept_on_save(self):
        html = self.get("/schedule")
        self.assertIn("TEST 주소 1명", html)
        self.assertIn("잠금", html)
        self.assertNotIn('<select name="target_group"', html)  # 잠금 중에는 고를 수 없음
        form = {"mode": "weekly", "weekdays": ["MON"], "time": "08:00", "random_delay_minutes": "5",
                "max_analysis_calls": "25", "max_insight_calls": "20", "send": "on", "log_days": "90", "mail_days": "30",
                "target_group": "TEST", "back": "/schedule"}
        self.post("save_schedule", **form)
        self.assertEqual(load_config(self.root / "config" / "daily.json").target_group, "TEST")


class ResendPageTests(AdminBase):
    """실패 수신자 재발송 화면 (D-077). 실제 발송은 띄우지 않고 명령만 확인한다."""

    def setUp(self):
        super().setUp()
        import hashlib
        from saba import recipients as rc, sendlog
        self.sendlog = sendlog
        mail = self.root / "output" / "daily_20261013_0803.eml"
        mail.write_bytes(b"EML")
        for i, email in enumerate(("virtual.one@tbell.co.kr", "virtual.two@tbell.co.kr")):
            rc.save(f"가상 {i}", email, "보안사업팀", ["파일럿"], path=self.app.recipients_path)
        path = self.root / "data" / "send_history.db"
        self.send_id = sendlog.start("자동 실행", "파일럿 그룹", ["virtual.one@tbell.co.kr", "virtual.two@tbell.co.kr"],
                                     mail_file=mail.name, mail_sha256=hashlib.sha256(b"EML").hexdigest(), path=path)
        sendlog.mark(self.send_id, "virtual.one@tbell.co.kr", "성공", path=path)
        sendlog.mark(self.send_id, "virtual.two@tbell.co.kr", "실패", "SMTPDataError", path=path)
        sendlog.finish(self.send_id, path)

    def test_locked_shows_note_and_refuses(self):
        html = self.get(f"/logs?tab=sends&day={self.send_id}")
        self.assertIn("그룹 발송 잠금 중에는 재발송할 수 없습니다", html)
        self.assertNotIn("/action/resend_failed", html)
        self.post("resend_failed", id=str(self.send_id), back="/logs")
        self.assertIn("재발송하지 않음", self.app.message)
        self.assertEqual(self.launched, [])

    def test_unlocked_needs_confirm_and_launches(self):
        from saba import send_mail
        with patch.object(send_mail, "GROUP_SEND_APPROVED", True):
            html = self.get(f"/logs?tab=sends&day={self.send_id}")
            self.assertIn("실패한 1명만 다시 보내기", html)
            self.assertEqual(self.post("resend_failed", confirm=False, id=str(self.send_id))[0], 400)
            self.post("resend_failed", id=str(self.send_id), back="/logs")
        self.assertEqual(self.launched[0][2:], ["saba.daily", "--resend", str(self.send_id)])

    def test_running_refused(self):
        from saba import send_mail
        from saba.daily import run_lock
        with patch.object(send_mail, "GROUP_SEND_APPROVED", True), run_lock(self.root / "data" / "daily.lock"):
            self.post("resend_failed", id=str(self.send_id))
        self.assertIn("진행 중", self.app.message)
        self.assertEqual(self.launched, [])

    def test_unlocked_refusals_over_http(self):  # 버튼이 없는 회차를 직접 POST 해도 띄우지 않는다
        from saba import send_mail
        path = self.root / "data" / "send_history.db"
        test_id = self.sendlog.record("자동 실행", "TEST 주소", [self.sendlog.Result("ch.seo@tbell.co.kr", "실패", "x")],
                                      path=path)
        child = self.sendlog.start("실패 재발송", "파일럿 그룹", ["virtual.two@tbell.co.kr"], parent_id=self.send_id, path=path)
        self.sendlog.mark(child, "virtual.two@tbell.co.kr", "성공", path=path)
        self.sendlog.finish(child, path)
        with patch.object(send_mail, "GROUP_SEND_APPROVED", True):
            for send_id, words in ((test_id, "TEST 주소 회차"), (self.send_id, "다시 보낼 수신자가 없습니다"),
                                   (9999, "없는 회차"), ("abc", "")):
                with self.subTest(send_id=send_id):
                    html = self.get(f"/logs?tab=sends&day={send_id}") if send_id != "abc" else ""
                    self.assertNotIn("/action/resend_failed", html)
                    status, _, _ = self.post("resend_failed", id=str(send_id), back="/logs")
                    self.assertIn(status, (303, 400))
                    self.assertIn(words, self.app.message)
        self.assertEqual(self.launched, [])

    def test_partial_run_shown_on_dashboard(self):
        self.log.write_text(f"{STAMP} 08:03:00,000 INFO 실행 시작: 자동 실행 (발송 포함)\n"
                            f"{STAMP} 08:03:02,000 ERROR 발송 단계 부분 실패: 파일럿 그룹 2명 중 성공 1 · 실패 1 · 불명확 0 · 미시도 0\n",
                            encoding="utf-8")
        html = self.get("/")
        self.assertIn("부분 발송", html)
        self.assertNotIn("/action/run_send", html)  # 일부 보낸 날에 전원 재발송을 권하지 않음


class UiFeedbackTests(AdminBase):
    def test_schedule_state_and_send_setting_are_distinct(self):
        config = self.app.config()
        for state in ("Ready", "Disabled", "확인 실패"):
            for send in (True, False):
                with self.subTest(state=state, send=send), patch.object(self.app, "config", return_value=replace(config, send=send)):
                    self.shell.state = state
                    html = self.get("/")
                    if state == "Ready":
                        self.assertIn("<th>다음 예약</th>", html)
                        self.assertIn("TEST 1명에게 발송" if send else "메일 생성까지만", html)
                    else:
                        self.assertNotIn("<th>다음 예약</th>", html)
                        self.assertIn("예약 발송 꺼져 있습니다" if state == "Disabled" else "예약 발송 상태를 확인하지 못했습니다", html)
                    self.assertIn("<h2>운영 현황</h2>", html)
        with patch.object(self.app, "shell", return_value=(1, "")):
            self.assertIn("확인 불가", self.get("/"))

    def test_sent_newsletter_is_on_right_and_uses_its_file(self):
        name = f"daily_{TODAY:%Y%m%d}_1015.eml"
        message = EmailMessage()
        message.set_content("가상 뉴스레터")
        message.add_alternative("<html><body><h1>가상 뉴스레터</h1></body></html>", subtype="html")
        (self.root / "output" / name).write_bytes(message.as_bytes())
        html = self.get("/")
        self.assertIn('class="grid dashboard"', html)
        self.assertLess(html.index("<h2>운영 현황</h2>"), html.index("<h2>오늘 보내진 뉴스레터</h2>"))
        self.assertIn(f'src="/newsletter/view?name={name}"', html)
        self.assertIn('title="오늘 보내진 뉴스레터 미리보기"', html)
        self.assertIn('sandbox="allow-popups"', html)
        self.assertIn("<h1>가상 뉴스레터</h1>", self.get(f"/newsletter/view?name={name}"))

    def test_latest_generated_mail_does_not_replace_sent_preview(self):
        from saba.history import Run
        name = f"daily_{TODAY:%Y%m%d}_1015.eml"
        (self.root / "output" / name).write_bytes(b"virtual")
        sent = Run(f"{STAMP} 10:15:00", "자동 실행", result="성공", sent=True, mail_file=name)
        generated = Run(f"{STAMP} 11:00:00", "자동 실행", result="성공 (발송 안 함)", mail_file="daily_new.eml")
        with patch.object(self.app, "real_runs_today", return_value=[generated, sent]):
            html = self.get("/")
        self.assertIn(f'src="/newsletter/view?name={name}"', html)
        self.assertNotIn('src="/newsletter/view?name=daily_new.eml"', html)

    def test_unsent_generated_mail_shown_when_nothing_sent(self):
        from saba.history import Run
        from saba.mail import build_message
        name = "26/10/daily_unsent.eml"
        (self.root / "output" / "26" / "10").mkdir(parents=True, exist_ok=True)
        (self.root / "output" / name).write_bytes(build_message("<p>UNSENT</p>", "가상").as_bytes())
        html = admin.today_newsletter(self.app, [Run(STAMP + " 08:00:00", "자동 실행", result="성공 (발송 안 함)", mail_file=name)])
        self.assertIn("미발송", html)
        self.assertIn("오늘 뉴스레터 (미발송)", html)
        self.assertIn(f'src="/newsletter/view?name={name}"', html)

    def test_preview_empty_failed_unclear_generated_and_missing_states(self):
        from saba.history import Run
        cases = [([], "오늘 보내진 뉴스레터가 없습니다"),
                 ([Run(STAMP + " 08:00:00", "자동 실행", result="성공 (발송 안 함)")], "생성했지만 발송하지 않았습니다"),
                 ([Run(STAMP + " 08:00:00", "자동 실행", result="실패")], "확인된 발송 성공 기록이 없습니다"),
                 ([Run(STAMP + " 08:00:00", "자동 실행", result="실패", error="발송 여부 불명확")], "발송 여부가 불명확합니다"),
                 ([Run(STAMP + " 08:00:00", "자동 실행", result="부분 발송", sent=True, mail_file="daily_missing.eml")], "메일 파일이 없습니다"),
                 ([Run(STAMP + " 08:00:00", "자동 실행", result="성공", sent=True, mail_file="../config/daily.json")], "메일 파일이 없습니다")]
        for runs, text in cases:
            with self.subTest(text=text):
                html = admin.today_newsletter(self.app, runs)
                self.assertIn(text, html)
                self.assertNotIn("<iframe", html)

    def test_unclear_send_does_not_offer_whole_run_again(self):
        self.log.write_text(f"{STAMP} 08:00:00,000 INFO 실행 시작: 자동 실행 (발송 포함)\n"
                            f"{STAMP} 08:00:01,000 ERROR 발송 단계 실패: SendLogError · 발송 여부 불명확 (발송 이력·받은 편지함 확인)\n",
                            encoding="utf-8")
        html = self.get("/")
        self.assertIn("발송 여부 불명확", html)
        self.assertNotIn("/action/run_send", html)
        self.assertNotIn("때문에 발송하지 않았습니다", html)

    def test_table_action_links_keep_href_and_use_buttons(self):
        from saba import sendlog
        sendlog.record("가상 실행", "TEST 주소", [sendlog.Result("virtual@tbell.co.kr", "성공")],
                       "daily_virtual.eml", self.root / "data" / "send_history.db")

        class TableLinks(HTMLParser):
            def __init__(self):
                super().__init__()
                self.depth, self.links = 0, []

            def handle_starttag(self, tag, attrs):
                if tag == "table":
                    self.depth += 1
                if tag == "a" and self.depth:
                    self.links.append(dict(attrs))

            def handle_endtag(self, tag):
                if tag == "table":
                    self.depth -= 1

        links = []
        for path in ("/logs", "/test", "/logs?tab=sends", "/newsletter", "/sources", "/recipients"):
            parser = TableLinks()
            parser.feed(self.get(path))
            links.extend(parser.links)
        self.assertTrue(links)
        for attrs in links:
            self.assertTrue(attrs.get("href", "").startswith("/"))
            self.assertIn("btn", attrs.get("class", "").split())
        self.assertEqual(self.commands, [])
        self.assertEqual(self.launched, [])
        self.assertEqual(self.fetched, [])

    def test_shared_table_and_control_rules(self):
        css = admin.CSS
        table = re.search(r"(?<![\w.])table\{([^}]+)\}", css).group(1)
        cells = re.search(r"th,td\{([^}]+)\}", css).group(1)
        self.assertIn("border:1px solid var(--line)", table)
        self.assertIn("border:1px solid var(--line)", cells)
        self.assertIn("vertical-align:middle", cells)
        self.assertIn("padding:", cells)
        self.assertIn(".dashboard{align-items:stretch}", css)  # 우측 뉴스레터가 좌측 높이만큼 채운다
        self.assertIn(".dashboard>.card .newsletter-preview{flex:1", css)
        self.assertIn("main{max-width:1920px", css)  # 메뉴 여백도 같은 1920px 기준
        self.assertIn("calc((100% - 1920px) / 2 + 32px)", css)
        self.assertIn("@media (max-width:1000px)", css)
        self.assertIn("prefers-reduced-motion", css)


class ListManagementTests(AdminBase):
    def test_monthly_and_legacy_same_basename_keep_exact_links(self):
        from saba.history import Run
        from saba.mail import build_message
        name = f"daily_{TODAY:%Y%m%d}_1015.eml"
        relative = f"{TODAY:%y/%m}/{name}"
        legacy = self.root / "output" / name
        monthly = self.root / "output" / relative
        monthly.parent.mkdir(parents=True)
        legacy.write_bytes(build_message('<p>LEGACY</p>', '가상').as_bytes())
        monthly.write_bytes(build_message('<p>MONTHLY</p>', '가상').as_bytes())
        old = Run(STAMP + " 08:00:00", "레거시", "성공 (발송 안 함)", mail_file=name)
        new = Run(STAMP + " 09:00:00", "월별 발송", "성공", mail_file=relative, sent=True)
        with patch.object(self.app, "runs", return_value=[new, old]):
            rows = {r['name']: r for r in self.app.mail_files()}
            self.assertEqual((rows[name]['kind'], rows[relative]['kind']), ("생성만 (발송 안 함)", "발송본"))
            html = self.get('/newsletter?year=all&month=all')
            self.assertEqual(set(self.table_names(html)), {name, relative})
            self.assertIn('MONTHLY', self.get('/newsletter/view?' + urlencode({'name': relative})))
            self.assertIn('LEGACY', self.get('/newsletter/view?' + urlencode({'name': name})))
            today = admin.today_newsletter(self.app, [new])
            self.assertIn('/newsletter/view?name=' + relative, today)
            self.assertIn(relative, self.get('/logs'))
            self.assertIn('scrollIntoView', self.get('/logs?' + urlencode({'tab': 'mail', 'name': relative})))  # 고른 메일로 바로 이동
            self.assertNotIn('scrollIntoView', self.get('/logs?tab=mail'))
        for invalid in ('../daily_x.eml', '26/10/../../daily_x.eml', 'C:/daily_x.eml'):
            self.assertEqual(self.get('/newsletter/view?' + urlencode({'name': invalid})), '<p>생성된 메일이 없습니다.</p>')

    def test_gitignore_only_daily_mail_paths(self):
        import subprocess
        paths = ['output/daily_20261013.eml', 'output/26/10/daily_20261013.eml',
                 'output/prompts/daily_20261013.eml', 'output/26/10/user.eml', 'output/user.eml']
        # bytes 로 보낸다: Windows 텍스트 모드는 \n 을 \r\n 으로 바꿔 git 이 경로를 못 맞춘다
        result = subprocess.run(['git', 'check-ignore', '--no-index', '--stdin'], input=('\n'.join(paths) + '\n').encode(),
                                capture_output=True, cwd=admin.ROOT, check=True)
        self.assertEqual(result.stdout.decode().splitlines(), paths[:2])

    def mails(self, count, *, date=None):
        date = date or TODAY.replace(day=1)
        stamp = date.timestamp()
        names = []
        for i in range(count):
            name = f"daily_{date:%Y%m%d}_{i:04}.eml"
            path = self.root / "output" / name
            path.write_bytes(b"virtual mail")
            os.utime(path, (stamp, stamp))
            names.append(name)
        return names

    def table_names(self, html):
        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.names = []

            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                if tag == "a" and "name=" in values.get("href", ""):
                    self.names.append(parse_qs(urlparse(values["href"]).query)["name"][0])
        parser = Links()
        parser.feed(html)
        return parser.names

    def test_mail_boundaries_and_stable_order(self):
        for count in (0, 25, 26):
            with self.subTest(count=count):
                for p in (self.root / "output").glob("*.eml"):
                    p.unlink()
                names = self.mails(count)
                first = self.get("/logs?tab=mail")
                self.assertEqual(self.table_names(first), sorted(names, reverse=True)[:25])
                self.assertIn(f"총 {count}개", first)
                second = self.get("/logs?tab=mail&page=2")
                self.assertEqual(self.table_names(second), sorted(names, reverse=True)[25:] if count == 26 else sorted(names, reverse=True))
                if not count:
                    self.assertNotIn("<iframe", first)
                    self.assertIn("조건에 맞는 파일 없음", first)

    def test_mail_month_search_and_link_context(self):
        names = self.mails(26)
        old = self.mails(1, date=TODAY.replace(year=TODAY.year - 1))[0]
        self.assertNotIn(old, self.table_names(self.get("/newsletter")))
        html = self.get("/logs?" + urlencode({"tab": "mail", "year": TODAY.year - 1, "month": f"{TODAY.month:02}", "q": "기록 없음"}))
        self.assertEqual(self.table_names(html), [old])
        self.assertIn(f"year={TODAY.year - 1}", html)
        self.assertIn(f"month={TODAY.month:02}", html)
        self.assertIn("q=%EA%B8%B0%EB%A1%9D", html)
        matched = self.get("/logs?" + urlencode({"tab": "mail", "q": names[0]}))
        self.assertEqual(self.table_names(matched), [names[0]])
        all_years = self.get("/newsletter?year=all&month=all&page=2")
        self.assertEqual(len(self.table_names(all_years)), 2)
        self.assertIn('name="year"', all_years)
        self.assertNotIn('name="page"', all_years)  # 필터 폼은 페이지를 이어 보내지 않는다.

    def test_empty_current_month_and_direct_mail_selection(self):
        old = self.mails(1, date=TODAY.replace(year=TODAY.year - 1))[0]
        html = self.get("/newsletter")
        self.assertEqual(self.table_names(html), [])
        self.assertIn(f'>{TODAY.year - 1}년</option>', html)
        self.assertNotIn("<iframe", html)
        selected = self.get("/logs?" + urlencode({"tab": "mail", "name": old}))
        self.assertIn("현재 목록 조건 밖", selected)
        self.assertIn(f"/newsletter/view?name={old}", selected)
        for name in ("../config/admin.json", "daily_missing.eml", '\"><script>alert(1)</script>'):
            html = self.get("/logs?" + urlencode({"tab": "mail", "name": name}))
            self.assertNotIn("<iframe", html)
            self.assertNotIn("<script>alert(1)</script>", html)

    def test_bad_filters_pages_and_escaping(self):
        self.mails(26)
        for page in ("0", "-1", "abc", "9" * 500):
            html = self.get("/logs?" + urlencode({"tab": "mail", "page": page}))
            self.assertIn("1 / 2 페이지", html)
            self.assertIn("페이지 값", html)
        self.assertIn("2 / 2 페이지", self.get("/logs?tab=mail&page=999"))
        bad = self.get("/logs?" + urlencode({"tab": "mail", "year": "bad", "month": "13", "q": '\"><script>alert(1)</script>'}))
        self.assertIn("연도 필터", bad)
        self.assertIn("월 필터", bad)
        self.assertIn("&lt;script&gt;", bad)
        self.assertNotIn('<script>alert(1)</script>', bad)
        self.assertIn("200자", self.get("/logs?" + urlencode({"q": "가" * 201})))
        for params in ({"start": "2026-02-30"}, {"start": "2026-10-14", "end": "2026-10-13"}, {"year": "0000"}):
            self.assertIn("필터" if "end" not in params else "초기화", self.get("/logs?" + urlencode(params)))

    def test_day_group_boundaries(self):
        from saba.history import Run
        for count in (0, 25, 26):
            runs = [Run((TODAY - timedelta(days=i)).strftime("%Y-%m-%d 08:00:00"), f"가상 회차 {i}", "성공") for i in range(count)]
            with patch.object(self.app, "runs", return_value=runs):
                html = self.get("/logs")
                self.assertIn(f"총 {count}일", html)
                self.assertEqual(html.count('<details class="guide">'), min(count, 25))
                second = self.get("/logs?page=2")
                self.assertEqual(second.count('<details class="guide">'), 1 if count == 26 else count)

    def test_run_search_preserves_full_day_and_rounds(self):
        from saba.history import Run
        from saba import sendlog
        filename = self.mails(1)[0]
        runs = [Run(f"{STAMP} 08:00:00", "실패 재발송 (회차 1)", "부분 발송", sent=True,
                    mail_file=filename, error="불명확 1명", stages=[("발송", "08:01", "실패", "불명확 1명")]),
                Run(f"{STAMP} 07:00:00", "자동 실행", "실패", error="수집 오류"),
                Run(f"{TODAY.year - 1}-01-01 08:00:00", "예전 실행", "성공")]
        db = self.root / "data" / "send_history.db"
        first = sendlog.record("자동 실행", "TEST 주소", [sendlog.Result("virtual@tbell.co.kr", "실패")], filename, db)
        child = sendlog.start("재발송", "TEST 주소", ["virtual@tbell.co.kr"], mail_file=filename, path=db, parent_id=first)
        sendlog.mark(child, "virtual@tbell.co.kr", "성공", "", db)
        sendlog.finish(child, db)
        with patch.object(self.app, "runs", return_value=runs):
            html = self.get("/logs?" + urlencode({"year": TODAY.year, "start": STAMP, "end": STAMP, "q": "재발송"}))
            self.assertIn("총 1일", html)
            for value in ("자동 실행", "수집 오류", "부분 발송", "불명확 1명", "진행 단계", filename):
                self.assertIn(value, html)
            # 실행 주체 선택 목록 (F14) 에는 모든 주체가 나오므로, 목록 본문 (필터 form 뒤) 에서만 확인한다
            self.assertNotIn("예전 실행", html.split('action="/logs"', 1)[1].split("</form>", 1)[1])
            self.assertIn(f"tab=detail&day={TODAY:%Y%m%d}", html)
            only_auto = self.get("/logs?" + urlencode({"year": "all", "origin": "자동 실행"}))
            self.assertNotIn("예전 실행", only_auto.split('action="/logs"', 1)[1].split("</form>", 1)[1])  # 항목별 필터
            sends = self.get("/logs?tab=sends")
            self.assertIn(f"회차 {first} 재발송", sends)
            self.assertIn("수신자별 결과", sends)
            self.assertIn("TEST 주소 회차는 재발송 대상이 아닙니다", self.get(f"/logs?tab=sends&day={first}"))

    def test_read_failures_are_not_empty_success(self):
        for attribute, path in (("mail_files", "/newsletter"), ("runs", "/logs")):
            with patch.object(self.app, attribute, side_effect=PermissionError("private")):
                status, html, _ = self.request("GET", path)
                self.assertEqual(status, 500)
                self.assertIn("화면을 만들지 못했습니다: PermissionError", html)
                self.assertNotIn("private", html)
                self.assertNotIn("총 0", html)

    def test_listing_does_not_write_or_call_services(self):
        self.mails(2)
        files = [p for p in self.root.rglob("*") if p.is_file()]
        before = {p: p.read_bytes() for p in files}
        for path in ("/logs", "/newsletter", "/logs?" + urlencode({"tab": "mail", "q": "기록"}), "/logs?year=all&page=999"):
            self.get(path)
        self.assertEqual(before, {p: p.read_bytes() for p in files})
        self.assertEqual(set(files), {p for p in self.root.rglob("*") if p.is_file()})
        self.assertEqual((self.commands, self.launched, self.fetched, self.shell.calls), ([], [], [], []))


class RssEvidenceTests(unittest.TestCase):
    def test_fixture_funnel_keeps_missing_analysis_and_separates_exclusions(self):
        from types import SimpleNamespace
        from saba import briefing
        from saba.analysis import analysis_input
        from saba.issues import select_issues
        from saba.storage import save_articles
        from test_issues import NOW, article, build

        rows = [article("a0", "the-hacker-news", "CVE-2026-12345"),
                article("a1", "the-hacker-news", "CVE-2026-12345")]
        rows += [article(f"b{i}", "the-hacker-news", f"가상 뉴스 {i}") for i in range(6)]
        rows.append(article("old", "the-hacker-news", "기간 밖", days_ago=7))
        articles = build(*rows)
        selection = select_issues(articles, NOW)
        self.assertEqual((selection.in_window, len(selection.issues), selection.excluded_by_source_cap), (8, 5, 2))
        representative = selection.issues[0].representative
        stored = {(representative.article_id, analysis_input(representative)[2]): SimpleNamespace(status=briefing.OUT_OF_SCOPE)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "articles.db"
            save_articles(db, articles)
            before = db.read_bytes()
            with patch.object(briefing, "stored_results", return_value=stored):
                views, selected, stats = briefing.build_views(db, root / "analysis.db", NOW,
                                                            body_cache=root / "bodies.json", insight_db=root / "insights.db",
                                                            max_new_calls=0, insight_calls=0)
            self.assertEqual((len(selected.issues), stats.out_of_scope, len(views)), (5, 1, 4))
            self.assertTrue(all(not view.has_full_analysis for view in views))
            self.assertNotIn("openai-news", {issue.representative.source_id for issue in selected.issues})
            self.assertEqual(db.read_bytes(), before)
            self.assertFalse((root / "analysis.db").exists())
            self.assertFalse((root / "bodies.json").exists())


if __name__ == "__main__":
    unittest.main()
