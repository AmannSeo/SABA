import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from saba import admin
from saba.admin import AdminApp, AdminError, load_admin_config, serve


class FakeShell:
    def __init__(self, output="Ready|2026-10-12 10:15|0|2026-10-13 08:03"):
        self.calls, self.output = [], output

    def __call__(self, command):
        self.calls.append(command)
        return 0, self.output


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for folder in ("logs", "output", "data", "config"):
            (self.root / folder).mkdir()
        (self.root / "logs" / "daily_20261012.log").write_text(
            "2026-10-12 10:15:05 INFO RSS 수집 완료\n2026-10-12 10:15:14 INFO 발송 완료 1회: 받는 사람 1명\n", encoding="utf-8")
        (self.root / "config" / "daily.json").write_bytes((admin.ROOT / "config" / "daily.json").read_bytes())
        self.shell, self.commands = FakeShell(), []
        self.app = AdminApp(root=self.root, shell=self.shell, command=lambda args: (self.commands.append(args) or (0, "ok")))
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
        return response.status, response.read().decode("utf-8")

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

    def test_pages_render_and_phase3_menu_disabled(self):
        for path in ("/", "/logs?name=daily_20261012.log", "/newsletter", "/settings"):
            status, html = self.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertIn("수신자·발송 관리 (3단계 예정)", html)
            self.assertNotIn('href="/recipients"', html)
        status, html = self.request("GET", "/")
        self.assertIn("발송 완료 1회", html)
        self.assertIn("TEST 1명", html)
        self.assertIn("<th>다음 실행</th><td>2026-10-13 08:03</td>", html)

    def test_foreign_host_header_rejected(self):  # DNS rebinding 방지
        self.assertEqual(self.request("GET", "/", host="evil.example:80")[0], 403)

    def test_settings_show_secret_presence_only(self):
        fake = {"OPENAI_API_KEY": "sk-FAKE-KEY-0000", "SABA_SMTP_PASSWORD": "FAKE-SECRET-PW-0000"}
        with patch.dict("os.environ", fake):
            _, html = self.request("GET", "/settings")
        self.assertIn("있음", html)
        for value in fake.values():
            self.assertNotIn(value, html)

    def test_post_requires_token_and_external_needs_confirm(self):
        self.assertEqual(self.request("POST", "/action/task_disable", "token=wrong")[0], 403)
        self.assertEqual(self.shell.calls, [])
        status, _ = self.request("POST", "/action/rss_dryrun", f"token={self.app.token}")
        self.assertEqual(status, 400)
        self.assertEqual(self.commands, [])
        status, _ = self.request("POST", "/action/rss_dryrun", f"token={self.app.token}&confirm=yes")
        self.assertEqual(status, 303)
        self.assertEqual(self.commands[0][-3:], ["saba", "--collect-rss", "--dry-run"])

    def test_task_on_off_uses_scheduled_task_commands(self):
        for action, verb in (("task_enable", "Enable-ScheduledTask"), ("task_disable", "Disable-ScheduledTask")):
            status, _ = self.request("POST", f"/action/{action}", f"token={self.app.token}")
            self.assertEqual(status, 303)
            self.assertIn(f"{verb} -TaskName SABA_Daily_Briefing", self.shell.calls[-1])

    def test_send_dryrun_never_connects(self):
        from email.message import EmailMessage
        message = EmailMessage()
        message["Subject"] = "가상"
        message.set_content("본문")
        (self.root / "output" / "daily_20261012.eml").write_bytes(message.as_bytes())
        with patch("smtplib.SMTP_SSL") as smtp:
            result = self.app.act("send_dryrun")
        smtp.assert_not_called()
        self.assertIn("드라이런", result)

    def test_smtp_check_is_login_only(self):
        with patch("saba.send_mail.send_test", return_value="확인") as send:
            self.app.act("smtp_check")
        self.assertTrue(send.call_args.kwargs["login_only"])

    def test_preview_rebuild_makes_no_new_calls(self):
        with patch("saba.briefing.build_views", return_value=([], None, None)) as build:
            self.assertIn("없습니다", self.app.act("rebuild_preview"))
        self.assertEqual((build.call_args.kwargs["max_new_calls"], build.call_args.kwargs["insight_calls"]), (0, 0))

    def test_newsletter_view_inlines_cid_images(self):
        from saba.mail import build_message
        html = '<html><body><img src="cid:saba-logo"></body></html>'
        (self.root / "output" / "daily_20261012.eml").write_bytes(build_message(html, "가상").as_bytes())
        status, page = self.request("GET", "/newsletter/view")
        self.assertEqual(status, 200)
        self.assertNotIn("cid:", page)
        self.assertIn("data:image/png;base64,", page)
        self.assertEqual(self.request("GET", "/newsletter/view?name=../config/admin.json")[1], "<p>생성된 메일이 없습니다.</p>")


if __name__ == "__main__":
    unittest.main()
