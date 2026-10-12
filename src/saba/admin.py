"""SABA 관리 컨트롤 페이지 1단계 (D-067). 표준 라이브러리 로컬 웹 페이지, 이 PC(127.0.0.1) 전용.

시작: python -m saba.admin        (브라우저가 열린다)
종료: python -m saba.admin --stop (또는 실행 창에서 Ctrl+C)

화면은 기존 기능의 상태를 보여 주고, 버튼은 기존 코드 경로를 그대로 부른다.
실제 발송·OpenAI 호출·수동 실행은 하지 않는다 (2단계 이후). Secret 은 있음·없음만 표시한다.
"""

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import SMTP
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
from typing import Callable
from urllib.parse import parse_qs, urlparse
import webbrowser

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "admin.json"
PID_PATH = ROOT / "data" / "admin.pid"
LOOPBACK = {"127.0.0.1", "localhost"}
SECRET_NAMES = ("OPENAI_API_KEY", "SABA_SMTP_HOST", "SABA_SMTP_USER", "SABA_SMTP_PASSWORD")
EXTERNAL_ACTIONS = {"rss_dryrun", "smtp_check"}  # 외부 접속이 있어 확인 창과 confirm=yes 가 필요하다


class AdminError(Exception):
    pass


def load_admin_config(path: Path = CONFIG_PATH) -> tuple[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    host, port = str(data["host"]), int(data["port"])
    # 사내망 접속은 로그인·IP 제한 구현 후 별도 승인 (D-067, D-070).
    if host not in LOOPBACK:
        raise AdminError("1단계 관리 페이지는 127.0.0.1 에서만 열 수 있습니다 (사내망 접속은 로그인·IP 제한 구현 후 별도 승인).")
    if not 1024 <= port <= 65535:
        raise AdminError("port 는 1024~65535 사이여야 합니다.")
    return host, port


def run_command(args: list[str], timeout: int = 120) -> tuple[int, str]:
    """명령 실행 (출력은 표시용으로 마지막 40줄만)."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}  # 하위 Python 출력을 UTF-8 로 받는다 (기본은 cp949)
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout, env=env)
    lines = (result.stdout + result.stderr).strip().splitlines()
    return result.returncode, "\n".join(lines[-40:])


def powershell(command: str) -> tuple[int, str]:
    utf8 = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "  # 기본 cp949 출력이 깨지지 않게
    return run_command(["powershell", "-NoProfile", "-Command", utf8 + command], timeout=60)


@dataclass
class AdminApp:
    """화면 데이터와 버튼 동작. 경로와 외부 명령은 테스트에서 바꿀 수 있다."""
    root: Path = ROOT
    shell: Callable[[str], tuple[int, str]] = powershell
    command: Callable[[list[str]], tuple[int, str]] = run_command
    token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    message: str = ""

    # ---- 데이터 ----
    def latest(self, folder: str, pattern: str) -> Path | None:
        files = sorted((self.root / folder).glob(pattern))
        return files[-1] if files else None

    def last_run(self) -> dict:
        log = self.latest("logs", "daily_*.log")
        if log is None:
            return {"file": None, "lines": [], "ok": None}
        lines = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        tail = lines[-3:]
        ok = None if not tail else not any(" ERROR " in line for line in tail) and any("발송 완료" in l or "send=false" in l for l in tail)
        return {"file": log.name, "lines": tail, "ok": ok}

    def usage(self) -> dict:
        from saba.openai_adapter import MODEL, MONTHLY_LIMIT_USD
        path = self.root / "data" / "openai_usage.json"
        entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        current = [e for e in entries if e.get("month") == month]
        statuses: dict[str, int] = {}
        for entry in current:
            statuses[entry.get("status", "?")] = statuses.get(entry.get("status", "?"), 0) + 1
        return {"model": MODEL, "limit": MONTHLY_LIMIT_USD, "month": month, "calls": len(current),
                "cost": sum(e.get("cost_usd") or 0 for e in current), "statuses": statuses}

    def recent_articles(self) -> int | None:
        db = self.root / "data" / "saba.db"
        if not db.exists():
            return None
        from saba.storage import list_articles
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        return sum(1 for a in list_articles(db) if a.collected_at >= since)

    def task(self) -> dict:
        from saba.daily import TASK_NAME
        code, out = self.shell(f"$t=Get-ScheduledTask -TaskName {TASK_NAME} -ErrorAction SilentlyContinue; "
                               "if ($t) { $i=$t|Get-ScheduledTaskInfo; "
                               "\"$($t.State)|$($i.LastRunTime.ToString('yyyy-MM-dd HH:mm'))|$($i.LastTaskResult)|"
                               "$($i.NextRunTime.ToString('yyyy-MM-dd HH:mm'))\" } else { 'NotRegistered' }")
        if code != 0 or not out.strip():
            return {"상태": "확인 실패"}
        if out.strip() == "NotRegistered":
            return {"상태": "등록 안 됨"}
        state, last, result, next_run = (out.strip().splitlines()[-1].split("|") + ["", "", "", ""])[:4]
        return {"상태": state, "마지막 실행": last, "마지막 결과 코드": result, "다음 실행": next_run}

    def settings(self) -> dict:
        from saba.daily import load_config
        from saba.rss import SOURCES
        from saba.send_mail import TEST_ADDRESS
        path = self.root / "config" / "daily.json"
        config = path.read_text(encoding="utf-8") if path.exists() else "(없음)"
        return {"daily": config, "sources": [(s.source_id, s.source_name, "공식" if s.official else "언론") for s in SOURCES],
                "secrets": {name: bool(os.environ.get(name, "").strip()) for name in SECRET_NAMES},
                "recipient": TEST_ADDRESS, "valid": self._try(lambda: load_config(path))}

    @staticmethod
    def _try(func) -> str:
        try:
            func()
            return "정상"
        except Exception as error:  # 화면 표시용: 종류와 문구만
            return f"오류: {error}" if error.args else f"오류: {type(error).__name__}"

    def newsletter_html(self, name: str | None = None) -> str | None:
        """최근 .eml 의 메일 HTML. CID 이미지는 data URI 로 바꿔 브라우저에서 보이게 한다."""
        eml = (self.root / "output" / name) if name else self.latest("output", "daily_*.eml")
        if eml is None or not eml.exists() or not re.fullmatch(r"daily_[\w-]+\.eml", eml.name):
            return None
        message = message_from_bytes(eml.read_bytes(), _class=EmailMessage, policy=SMTP)
        html = message.get_body(preferencelist=("html",)).get_content()
        for part in message.walk():
            cid = (part.get("Content-ID") or "").strip("<>")
            if cid and part.get_content_maintype() == "image":
                data = base64.b64encode(part.get_payload(decode=True)).decode()
                html = html.replace(f"cid:{cid}", f"data:{part.get_content_type()};base64,{data}")
        return html

    # ---- 버튼 ----
    def act(self, action: str) -> str:
        from saba.daily import TASK_NAME
        if action == "validate_config":
            from saba.daily import load_config
            return f"설정 검증: {self._try(lambda: load_config(self.root / 'config' / 'daily.json'))}"
        if action == "send_dryrun":
            eml = self.latest("output", "daily_*.eml")
            if eml is None:
                return "드라이런: 보낼 메일(.eml) 이 없습니다."
            from saba.send_mail import send_test
            return send_test(message_from_bytes(eml.read_bytes(), _class=EmailMessage, policy=SMTP))
        if action == "rebuild_preview":
            return self.rebuild_preview()
        if action == "rss_dryrun":
            code, out = self.command([sys.executable, "-m", "saba", "--collect-rss", "--dry-run"])
            return f"RSS 수집 dry-run (저장 없음): 종료 코드 {code}\n{out}"
        if action == "smtp_check":
            eml = self.latest("output", "daily_*.eml")
            from saba.send_mail import SendError, send_test
            message = message_from_bytes(eml.read_bytes(), _class=EmailMessage, policy=SMTP) if eml else EmailMessage()
            try:
                return send_test(message, send=True, login_only=True)
            except SendError as error:
                return f"SMTP 확인 실패: {error}"
        if action in ("task_enable", "task_disable"):
            verb = "Enable" if action == "task_enable" else "Disable"
            code, _ = self.shell(f"{verb}-ScheduledTask -TaskName {TASK_NAME} | Out-Null")
            return f"자동 실행 {'켜기' if verb == 'Enable' else '끄기'}: {'완료' if code == 0 else f'실패 (종료 코드 {code})'}"
        raise AdminError("알 수 없는 동작입니다.")

    def rebuild_preview(self) -> str:
        """저장된 분석·시사점만으로 미리보기 .eml 재생성. OpenAI 호출·네트워크·발송 없음."""
        from saba.analysis_storage import DEFAULT_ANALYSIS_DB
        from saba.briefing import build_views
        from saba.mail import build_message, to_mail_html
        from saba.storage import DEFAULT_DB
        now = datetime.now().astimezone()
        views, _selection, _stats = build_views(DEFAULT_DB, DEFAULT_ANALYSIS_DB, now, max_new_calls=0, insight_calls=0)
        if not views:
            return "미리보기 재생성: 기간 안 표시할 기사가 없습니다."
        today = f"{now.year}년 {now.month}월 {now.day}일 {'월화수목금토일'[now.weekday()]}요일"
        path = self.root / "output" / f"daily_{now:%Y%m%d}_preview.eml"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(build_message(to_mail_html(views, today=today), f"[미리보기] Security & AI Briefing · {today}").as_bytes())
        return f"미리보기 재생성 완료: {path.name} (표시 {len(views)}건, 저장 결과만 사용)"


# ---------------- HTML ----------------
CSS = ("body{margin:0;font-family:'Malgun Gothic',Arial,sans-serif;background:#f3f4f6;color:#1f2937}"
       "nav{background:#111827;padding:14px 24px}nav a,nav span{color:#e5e7eb;margin-right:18px;text-decoration:none;font-size:14px}"
       "nav span{color:#6b7280}main{max-width:1000px;margin:24px auto;padding:0 16px}"
       ".card{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:18px 20px;margin-bottom:16px}"
       "h1{font-size:20px}h2{font-size:16px;margin:0 0 10px}table{border-collapse:collapse;width:100%}"
       "td,th{border-bottom:1px solid #eef0f2;padding:6px 4px;text-align:left;font-size:13px}"
       "pre{background:#111827;color:#e5e7eb;padding:12px;border-radius:6px;white-space:pre-wrap;font-size:12px}"
       ".ok{color:#15803d}.bad{color:#b91c1c}.msg{background:#eff6ff;border:1px solid #bfdbfe}"
       "button{margin:4px 6px 4px 0;padding:7px 12px;border:1px solid #d1d5db;border-radius:5px;background:#fff;cursor:pointer}"
       "button.ext{border-color:#f59e0b}")

MENU = [("/", "대시보드"), ("/logs", "실행 이력·로그"), ("/newsletter", "뉴스레터"), ("/settings", "설정")]


def page(title: str, body: str, message: str = "") -> str:
    links = "".join(f'<a href="{href}">{label}</a>' for href, label in MENU)
    links += '<span title="2단계 예정">수신자·발송 관리 (2단계 예정)</span>'
    note = f'<div class="card msg"><pre style="background:none;color:#1f2937">{escape(message)}</pre></div>' if message else ""
    return (f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><title>{escape(title)} · SABA 관리</title>'
            f"<style>{CSS}</style></head><body><nav>{links}</nav><main><h1>{escape(title)}</h1>{note}{body}</main></body></html>")


def button(app: AdminApp, action: str, label: str) -> str:
    external = action in EXTERNAL_ACTIONS
    confirm = ' onsubmit="return confirm(\'외부에 접속합니다. 진행할까요?\')"' if external else ""
    hidden = '<input type="hidden" name="confirm" value="yes">' if external else ""
    return (f'<form method="post" action="/action/{action}" style="display:inline"{confirm}>'
            f'<input type="hidden" name="token" value="{app.token}">{hidden}'
            f'<button class="{"ext" if external else ""}">{escape(label)}</button></form>')


def dashboard(app: AdminApp) -> str:
    run, use, task = app.last_run(), app.usage(), app.task()
    state = {True: '<b class="ok">성공</b>', False: '<b class="bad">실패 또는 미발송</b>', None: "기록 없음"}[run["ok"]]
    lines = escape("\n".join(run["lines"])) or "실행 기록이 없습니다."
    statuses = ", ".join(f"{k} {v}" for k, v in sorted(use["statuses"].items())) or "없음"
    recent = app.recent_articles()
    task_rows = "".join(f"<tr><th>{escape(k)}</th><td>{escape(str(v))}</td></tr>" for k, v in task.items())
    return (f'<div class="card"><h2>마지막 실행 ({escape(run["file"] or "-")}) · {state}</h2><pre>{lines}</pre></div>'
            f'<div class="card"><h2>운영 현황</h2><table>'
            f'<tr><th>최근 24시간 수집 기사</th><td>{"-" if recent is None else recent}건</td></tr>'
            f'<tr><th>이번 달 AI ({escape(use["month"])}, {escape(use["model"])})</th>'
            f'<td>호출 {use["calls"]}건 · 상태 {escape(statuses)} · 비용 ${use["cost"]:.4f} / 상한 ${use["limit"]:.2f}</td></tr>'
            f'<tr><th>발송 대상</th><td>TEST 1명 (고정 주소)</td></tr></table></div>'
            f'<div class="card"><h2>자동 실행 (작업 스케줄러)</h2><table>{task_rows}</table>'
            f'{button(app, "task_enable", "자동 실행 켜기")}{button(app, "task_disable", "자동 실행 끄기")}</div>'
            f'<div class="card"><h2>기능별 테스트</h2><p style="font-size:13px">외부 접속 없음</p>'
            f'{button(app, "send_dryrun", "메일 발송 드라이런")}{button(app, "validate_config", "설정 검증")}'
            f'{button(app, "rebuild_preview", "메일 미리보기 재생성 (저장 결과만)")}'
            f'<p style="font-size:13px">외부 접속 있음 (확인 창)</p>'
            f'{button(app, "rss_dryrun", "RSS 수집 dry-run (저장 없음)")}{button(app, "smtp_check", "SMTP 연결·인증 확인 (발송 없음)")}</div>')


def logs_page(app: AdminApp, name: str | None) -> str:
    files = sorted((app.root / "logs").glob("daily_*.log"), reverse=True)
    items = "".join(f'<li><a href="/logs?name={escape(f.name)}">{escape(f.name)}</a></li>' for f in files) or "<li>로그 없음</li>"
    body = f'<div class="card"><h2>로그 파일</h2><ul>{items}</ul></div>'
    if name and re.fullmatch(r"daily_\d{8}\.log", name) and (app.root / "logs" / name).exists():
        text = (app.root / "logs" / name).read_text(encoding="utf-8", errors="replace")
        body += f'<div class="card"><h2>{escape(name)}</h2><pre>{escape(text)}</pre></div>'
    return body


def newsletter_page(app: AdminApp) -> str:
    files = sorted((app.root / "output").glob("daily_*.eml"), reverse=True)
    items = "".join(f'<li><a href="/newsletter/view?name={escape(f.name)}" target="preview">{escape(f.name)}</a></li>' for f in files)
    return (f'<div class="card"><h2>생성된 메일</h2><ul>{items or "<li>없음</li>"}</ul></div>'
            f'<div class="card"><iframe name="preview" src="/newsletter/view" style="width:100%;height:900px;border:0"></iframe></div>')


def settings_page(app: AdminApp) -> str:
    s = app.settings()
    sources = "".join(f"<tr><td>{escape(i)}</td><td>{escape(n)}</td><td>{escape(k)}</td></tr>" for i, n, k in s["sources"])
    secret_rows = "".join(f"<tr><td>{escape(n)}</td><td>{'있음' if v else '<b class=bad>없음</b>'}</td></tr>" for n, v in s["secrets"].items())
    return (f'<div class="card"><h2>자동 실행 설정 (config/daily.json) · 검증 {escape(s["valid"])}</h2><pre>{escape(s["daily"])}</pre></div>'
            f'<div class="card"><h2>RSS Source</h2><table>{sources}</table></div>'
            f'<div class="card"><h2>Secret (값은 표시하지 않음)</h2><table>{secret_rows}</table></div>'
            f'<div class="card"><h2>발송</h2>TEST 수신자 1명 (고정, {escape(s["recipient"])}). 전사 발송은 4단계 별도 승인.</div>')


def make_handler(app: AdminApp, port: int):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # 요청 로그는 남기지 않는다
            pass

        def _send(self, code: int, body: str, content_type: str = "text/html; charset=utf-8"):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self) -> bool:  # DNS rebinding 방지: 로컬 주소로 들어온 요청만
            return self.headers.get("Host", "") in allowed_hosts

        def do_GET(self):
            try:
                self._get()
            except Exception as error:  # 화면에는 종류만
                self._send(500, page("오류", f"<p>화면을 만들지 못했습니다: {escape(type(error).__name__)}</p>"))

        def _get(self):
            if not self._host_ok():
                return self._send(403, "forbidden", "text/plain; charset=utf-8")
            url = urlparse(self.path)
            query = parse_qs(url.query)
            message, app.message = app.message, ""
            if url.path == "/":
                return self._send(200, page("대시보드", dashboard(app), message))
            if url.path == "/logs":
                return self._send(200, page("실행 이력·로그", logs_page(app, query.get("name", [None])[0])))
            if url.path == "/newsletter":
                return self._send(200, page("뉴스레터 미리보기", newsletter_page(app)))
            if url.path == "/newsletter/view":
                html = app.newsletter_html(query.get("name", [None])[0])
                return self._send(200, html or "<p>생성된 메일이 없습니다.</p>")
            if url.path == "/settings":
                return self._send(200, page("설정", settings_page(app)))
            return self._send(404, page("없는 페이지", "<p>없는 페이지입니다.</p>"))

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, "forbidden", "text/plain; charset=utf-8")
            length = min(int(self.headers.get("Content-Length") or 0), 4096)
            form = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
            action = urlparse(self.path).path.removeprefix("/action/")
            if not secrets.compare_digest(form.get("token", [""])[0], app.token):
                return self._send(403, "forbidden", "text/plain; charset=utf-8")
            if action in EXTERNAL_ACTIONS and form.get("confirm", [""])[0] != "yes":
                return self._send(400, "confirm required", "text/plain; charset=utf-8")
            try:
                app.message = app.act(action)
            except Exception as error:  # 화면에는 종류와 고정 문구만
                app.message = f"실패: {error}" if isinstance(error, AdminError) else f"실패: {type(error).__name__}"
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

    return Handler


def serve(host: str, port: int, app: AdminApp | None = None) -> ThreadingHTTPServer:
    if host not in LOOPBACK:
        raise AdminError("127.0.0.1 에서만 열 수 있습니다.")
    return ThreadingHTTPServer((host, port), make_handler(app or AdminApp(), port))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stop", action="store_true", help="실행 중인 관리 페이지 종료")
    parser.add_argument("--no-browser", action="store_true", help="브라우저를 열지 않음")
    args = parser.parse_args()
    if args.stop:
        if not PID_PATH.exists():
            print("실행 중인 관리 페이지가 없습니다.")
            return 0
        pid = int(PID_PATH.read_text())
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"관리 페이지를 종료했습니다 (PID {pid}).")
        except OSError:
            print("이미 종료된 관리 페이지입니다.")
        PID_PATH.unlink(missing_ok=True)
        return 0
    host, port = load_admin_config()
    server = serve(host, port)
    PID_PATH.parent.mkdir(exist_ok=True)
    PID_PATH.write_text(str(os.getpid()))
    url = f"http://127.0.0.1:{port}/"
    print(f"SABA 관리 페이지: {url} (종료: Ctrl+C 또는 python -m saba.admin --stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        PID_PATH.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
