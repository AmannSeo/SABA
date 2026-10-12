"""SABA 관리 컨트롤 페이지 (1단계 D-067, 수동 실행 D-071, 화면 개편·예약 설정 D-072).
표준 라이브러리 로컬 웹 페이지, 이 PC(127.0.0.1) 전용.

시작: 관리페이지_열기.bat 더블클릭, 또는 python -m saba.admin (브라우저가 열린다)
종료: 실행 창 닫기, 또는 python -m saba.admin --stop

버튼은 기존 명령과 같은 코드 경로를 부른다. Secret 은 있음·없음만 표시한다.
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
from urllib.parse import parse_qs, quote, urlparse
import webbrowser

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "admin.json"
PID_PATH = ROOT / "data" / "admin.pid"
LOOPBACK = {"127.0.0.1", "localhost"}
SECRET_NAMES = ("OPENAI_API_KEY", "SABA_SMTP_HOST", "SABA_SMTP_USER", "SABA_SMTP_PASSWORD")
COST_PER_CALL = 0.0004  # 실제 사용량 기록 평균 (분석·시사점 1건 약 $0.0003~0.0005), 예상 비용 표시용
# 확인 창과 confirm=yes 가 필요한 동작 (외부 접속·AI 호출·발송·설정 변경)
CONFIRM_TEXT = {
    "run_send": "지금 발송: RSS 수집 → AI 분석 (하루 상한 안) → 메일 생성 → TEST 1명 발송을 실행합니다. 진행할까요?",
    "run_resend": "재발송: 오늘 이미 발송했습니다. 다시 실행해 TEST 1명에게 한 번 더 보낼까요?",
    "rss_dryrun": "RSS 수집 점검: Source 6곳에 접속합니다 (저장 없음). 진행할까요?",
    "smtp_check": "메일 서버 로그인 점검: 회사 메일 서버에 접속해 로그인만 확인합니다 (발송 없음). 진행할까요?",
    "save_schedule": "예약 발송 설정을 저장합니다. 일정이 바뀌면 작업 스케줄러에 다시 등록합니다. 진행할까요?",
}
MODE_LABEL = {"daily": "매일", "weekly": "매주", "monthly": "매월", "dates": "특정 날짜"}
DAY_LABEL = dict(zip(("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"), "월화수목금토일"))
FIELD_LABEL = {"mode": "반복", "time": "시각", "random_delay_minutes": "무작위 지연(분)", "weekdays": "요일",
               "month_days": "매월 날짜", "dates": "특정 날짜", "max_analysis_calls": "하루 AI 분석 상한",
               "max_insight_calls": "하루 AI 시사점 상한", "send": "발송", "log_days": "로그 보관(일)",
               "mail_days": "메일 보관(일)"}
SCHEDULE_FIELDS = {"mode", "time", "random_delay_minutes", "weekdays", "month_days", "dates"}  # 바뀌면 재등록

# 점검 도구: (동작, 이름, 외부 접속, 설명 팝업 내용)
TOOLS = [
    ("send_dryrun", "발송 준비 점검", "없음",
     "가장 최근 메일 파일로 발송 준비가 되었는지 확인합니다.<br>받는 사람 (TEST 1명 고정), 메일 크기, 메일 서버 접속 정보 "
     "(환경 변수) 가 있는지만 봅니다.<br><b>메일 서버에 접속하지 않고 메일도 보내지 않습니다.</b>"),
    ("validate_config", "설정 파일 점검", "없음",
     "예약 발송 설정 파일 (config/daily.json) 의 값이 올바른지 확인합니다.<br>시각 형식, 요일·날짜, 호출 상한 범위 등을 검사합니다."),
    ("rebuild_preview", "미리보기 다시 만들기", "없음",
     "이미 저장된 기사와 AI 분석 결과만으로 메일 미리보기를 다시 만듭니다.<br><b>AI 를 새로 호출하지 않습니다.</b> "
     "그래서 아직 분석하지 않은 새 기사는 요약 없이 나오거나 빠질 수 있습니다.<br>결과는 뉴스레터 화면의 \"미리보기\" 에서 봅니다."),
    ("rss_dryrun", "RSS 수집 점검", "있음",
     "RSS Source 6곳에 실제로 접속해 기사를 가져올 수 있는지 확인합니다.<br><b>가져온 기사는 저장하지 않습니다.</b> "
     "Source 별 예상 신규 건수가 나옵니다.<br>수집이 실패할 때 원인 (어느 Source 인지) 을 찾는 데 씁니다."),
    ("smtp_check", "메일 서버 로그인 점검", "있음",
     "회사 메일 서버에 접속해 아이디·비밀번호로 로그인되는지만 확인합니다.<br><b>메일은 보내지 않습니다.</b><br>"
     "발송이 실패할 때 접속 정보 문제인지 찾는 데 씁니다."),
]


class AdminError(Exception):
    pass


def load_admin_config(path: Path = CONFIG_PATH) -> tuple[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    host, port = str(data["host"]), int(data["port"])
    # 사내망 접속은 로그인·IP 제한 구현 후 별도 승인 (D-067, D-070).
    if host not in LOOPBACK:
        raise AdminError("관리 페이지는 127.0.0.1 에서만 열 수 있습니다 (사내망 접속은 로그인·IP 제한 구현 후 별도 승인).")
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


def spawn(args: list[str]) -> None:
    """지금 발송은 백그라운드로 띄우고 바로 돌아온다 (결과는 로그·대시보드에서 확인)."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(args, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags)


def powershell(command: str) -> tuple[int, str]:
    utf8 = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "  # 기본 cp949 출력이 깨지지 않게
    return run_command(["powershell", "-NoProfile", "-Command", utf8 + command], timeout=60)


def kst_label(at: datetime) -> str:
    return f"{at:%Y-%m-%d} ({'월화수목금토일'[at.weekday()]}) {at:%H:%M}"


@dataclass
class AdminApp:
    """화면 데이터와 버튼 동작. 경로와 외부 명령은 테스트에서 바꿀 수 있다."""
    root: Path = ROOT
    shell: Callable[[str], tuple[int, str]] = powershell
    command: Callable[[list[str]], tuple[int, str]] = run_command
    launch: Callable[[list[str]], None] = spawn
    token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    message: str = ""

    # ---- 경로 ----
    @property
    def config_path(self) -> Path:
        return self.root / "config" / "daily.json"

    @property
    def changes_path(self) -> Path:
        return self.root / "logs" / "settings_changes.log"

    def config(self):
        from saba.daily import load_config
        return load_config(self.config_path)

    # ---- 데이터 ----
    def latest_mail(self) -> Path | None:
        files = [p for p in (self.root / "output").glob("daily_*.eml") if "preview" not in p.name]
        return max(files, key=lambda p: p.stat().st_mtime) if files else None

    def runs(self):
        from saba.history import load_runs
        return load_runs(self.root / "logs")

    def today_runs(self):
        today = datetime.now().strftime("%Y-%m-%d")
        return [run for run in self.runs() if run.start.startswith(today)]

    def running(self) -> bool:
        from saba.daily import is_running
        return is_running(self.root / "data" / "daily.lock")

    def sent_today(self) -> str | None:
        """오늘 마지막 발송 시각 (HH:MM)."""
        sent = [run for run in self.today_runs() if run.sent]
        return next((stage[1] for stage in sent[0].stages if stage[0] == "발송"), None) if sent else None

    def usage(self) -> dict:
        from saba.openai_adapter import MODEL, MONTHLY_LIMIT_USD
        path = self.root / "data" / "openai_usage.json"
        entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        current = [e for e in entries if e.get("month") == month]
        ok = sum(1 for e in current if e.get("status") == "valid")
        return {"model": MODEL, "limit": MONTHLY_LIMIT_USD, "month": month, "calls": len(current), "ok": ok,
                "failed": len(current) - ok, "cost": sum(e.get("cost_usd") or 0 for e in current)}

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
            return {"state": "확인 실패"}
        if out.strip() == "NotRegistered":
            return {"state": "등록 안 됨"}
        state, last, result, next_run = (out.strip().splitlines()[-1].split("|") + ["", "", "", ""])[:4]
        return {"state": state, "last": last, "result": result, "next": next_run}

    def secrets_present(self) -> dict[str, bool]:
        return {name: bool(os.environ.get(name, "").strip()) for name in SECRET_NAMES}

    @staticmethod
    def _try(func) -> str:
        try:
            func()
            return "정상"
        except Exception as error:  # 화면 표시용: 종류와 문구만
            return f"오류: {error}" if error.args else f"오류: {type(error).__name__}"

    def mail_files(self) -> list[dict]:
        """뉴스레터 파일 목록과 종류 (발송본·생성만·미리보기)."""
        by_file = {}
        for run in reversed(self.runs()):  # 같은 이름이면 최근 실행이 이긴다 (D-072 이전에는 같은 날 덮어씀)
            if run.mail_file:
                by_file[run.mail_file] = run
        files = []
        for path in sorted((self.root / "output").glob("daily_*.eml"), key=lambda p: p.stat().st_mtime, reverse=True):
            run = by_file.get(path.name)
            if "preview" in path.name:
                kind = "미리보기"
            elif run is None:
                kind = "기록 없음"
            else:
                kind = "발송본" if run.sent else "생성만 (발송 안 함)"
            files.append({"name": path.name, "kind": kind, "size": path.stat().st_size,
                          "made": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                          "origin": run.origin if run else "-"})
        return files

    def newsletter_html(self, name: str | None = None) -> str | None:
        """메일 HTML. CID 이미지는 data URI 로 바꿔 브라우저에서 보이게 한다."""
        if name is None:
            eml = self.latest_mail()
        elif re.fullmatch(r"daily_[\w-]+\.eml", name):
            eml = self.root / "output" / name
        else:
            return None
        if eml is None or not eml.exists():
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
    def act(self, action: str, form: dict | None = None) -> str:
        form = form or {}
        if action == "validate_config":
            return f"설정 파일 점검: {self._try(self.config)}"
        if action == "send_dryrun":
            eml = self.latest_mail()
            if eml is None:
                return "발송 준비 점검: 보낼 메일 파일이 없습니다."
            from saba.send_mail import send_test
            return "발송 준비 점검 · " + send_test(message_from_bytes(eml.read_bytes(), _class=EmailMessage, policy=SMTP))
        if action == "rebuild_preview":
            return self.rebuild_preview()
        if action == "rss_dryrun":
            code, out = self.command([sys.executable, "-m", "saba", "--collect-rss", "--dry-run"])
            return f"RSS 수집 점검 (저장 없음): {'정상' if code == 0 else f'실패 (종료 코드 {code})'}\n{out}"
        if action == "smtp_check":
            eml = self.latest_mail()
            from saba.send_mail import SendError, send_test
            message = message_from_bytes(eml.read_bytes(), _class=EmailMessage, policy=SMTP) if eml else EmailMessage()
            try:
                return "메일 서버 로그인 점검 · " + send_test(message, send=True, login_only=True)
            except SendError as error:
                return f"메일 서버 로그인 점검 실패: {error}"
        if action in ("run_send", "run_resend"):
            return self.run_now(action)
        if action == "task_state":
            return self.set_task_state(_first(form, "state") == "on")
        if action == "save_schedule":
            return self.save_schedule(form)
        raise AdminError("알 수 없는 동작입니다.")

    def run_now(self, action: str) -> str:
        """작업 스케줄러와 같은 daily --run 경로 (D-071). 동시 실행은 daily 의 잠금이 막는다."""
        if self.running():
            return "이미 실행 중입니다. 끝난 뒤 다시 시도하세요."
        sent = self.sent_today()
        if action == "run_send" and sent:
            return f"오늘 {sent} 에 이미 발송했습니다. 한 번 더 보내려면 \"재발송\" 버튼을 누르세요."
        self.launch([sys.executable, "-m", "saba.daily", "--run", "--manual"])
        return ("재발송" if action == "run_resend" else "지금 발송") + "을 시작했습니다. 1~2분 걸리며, 끝나면 \"마지막 실행\" 표에 결과가 나옵니다."

    def set_task_state(self, on: bool) -> str:
        from saba.daily import TASK_NAME
        code, _ = self.shell(f"{'Enable' if on else 'Disable'}-ScheduledTask -TaskName {TASK_NAME} | Out-Null")
        return f"예약 발송 {'켜기' if on else '끄기'}: {'완료' if code == 0 else f'실패 (종료 코드 {code})'}"

    def save_schedule(self, form: dict) -> str:
        """검증 → 저장 → 일정이 바뀌었으면 작업 스케줄러 재등록 (실패하면 원복) → 변경 기록 (D-072)."""
        from saba.daily import DailyError, config_dict, parse_config, register_command, save_config
        from saba.history import append_change
        old = self.config()
        data = {
            "mode": _first(form, "mode"), "time": _first(form, "time"),
            "random_delay_minutes": _first(form, "random_delay_minutes"),
            "weekdays": form.get("weekdays", []), "month_days": form.get("month_days", []),
            "dates": sorted({d.strip() for d in re.split(r"[\s,]+", _first(form, "dates")) if d.strip()}),
            "max_analysis_calls": _first(form, "max_analysis_calls"), "max_insight_calls": _first(form, "max_insight_calls"),
            "send": _first(form, "send") == "on", "log_days": _first(form, "log_days"), "mail_days": _first(form, "mail_days"),
        }
        try:
            new = parse_config(data)
        except DailyError as error:
            raise AdminError(f"저장하지 않음 · {error}") from None
        before, after = config_dict(old), config_dict(new)
        changes = {key: (before[key], after[key]) for key in after if before[key] != after[key]}
        if not changes:
            return "변경 사항이 없습니다."
        original = self.config_path.read_bytes()
        save_config(new, self.config_path)
        reregister = bool(SCHEDULE_FIELDS & changes.keys())
        if reregister:
            was_disabled = self.task().get("state") == "Disabled"
            code, _ = self.shell(register_command(new))
            if code == 0 and was_disabled:  # 재등록은 켜진 상태로 만들므로 꺼져 있었으면 다시 끈다
                from saba.daily import TASK_NAME
                code, _ = self.shell(f"Disable-ScheduledTask -TaskName {TASK_NAME} | Out-Null")
            if code != 0:
                self.config_path.write_bytes(original)
                raise AdminError("저장하지 않음 · 작업 스케줄러 재등록에 실패해 설정을 원래대로 되돌렸습니다.")
        append_change(self.changes_path, changes, reregister)
        names = ", ".join(FIELD_LABEL.get(key, key) for key in changes)
        return f"저장 완료: {names}" + (" · 작업 스케줄러 재등록 완료" if reregister else " (다음 실행부터 적용)")

    def rebuild_preview(self) -> str:
        """저장된 분석·시사점만으로 미리보기 재생성. OpenAI 호출·네트워크·발송 없음. 미리보기는 최신 1개만 둔다."""
        from saba.analysis_storage import DEFAULT_ANALYSIS_DB
        from saba.briefing import build_views
        from saba.mail import build_message, to_mail_html
        from saba.storage import DEFAULT_DB
        now = datetime.now().astimezone()
        views, _selection, _stats = build_views(DEFAULT_DB, DEFAULT_ANALYSIS_DB, now, max_new_calls=0, insight_calls=0)
        if not views:
            return "미리보기 다시 만들기: 기간 안 표시할 기사가 없습니다."
        today = f"{now.year}년 {now.month}월 {now.day}일 {'월화수목금토일'[now.weekday()]}요일"
        output = self.root / "output"
        output.mkdir(exist_ok=True)
        for old in output.glob("daily_*preview*.eml"):
            old.unlink()
        path = output / f"daily_{now:%Y%m%d_%H%M}_preview.eml"
        path.write_bytes(build_message(to_mail_html(views, today=today), f"[미리보기] Security & AI Briefing · {today}").as_bytes())
        return f"미리보기 다시 만들기 완료: {path.name} (기사 {len(views)}건, 저장된 분석만 사용) · 뉴스레터 화면에서 확인"


def _first(form: dict, key: str) -> str:
    return (form.get(key) or [""])[0]


# ---------------- HTML ----------------
CSS = """
:root{--bg:#f4f6f9;--card:#fff;--line:#e3e7ee;--text:#1f2937;--muted:#6b7280;--brand:#1d4ed8;--ok:#15803d;--bad:#b91c1c;--warn:#b45309}
*{box-sizing:border-box}
body{margin:0;font-family:'Malgun Gothic','Apple SD Gothic Neo',Arial,sans-serif;background:var(--bg);color:var(--text);font-size:14px}
header{background:#0f172a;color:#fff;padding:0 24px;display:flex;align-items:center;gap:28px;min-height:56px;flex-wrap:wrap}
header .logo{font-weight:700;font-size:16px;letter-spacing:.3px}
header nav{display:flex;gap:20px;flex-wrap:wrap}
header nav a{color:#cbd5e1;text-decoration:none;padding:17px 2px;border-bottom:3px solid transparent}
header nav a.on{color:#fff;border-color:#60a5fa}
header nav span{color:#64748b;padding:17px 2px}
main{max-width:1120px;margin:24px auto;padding:0 16px}
h1{font-size:20px;margin:0 0 16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin-bottom:16px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.tile .k{color:var(--muted);font-size:12px}.tile .v{font-size:18px;font-weight:700;margin-top:6px}.tile .s{color:var(--muted);font-size:12px;margin-top:4px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-bottom:16px}
.card h2{font-size:15px;margin:0 0 12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.card h2 .right{margin-left:auto}
table{border-collapse:collapse;width:100%}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:#f8fafc;color:#475569;font-weight:600;font-size:13px;white-space:nowrap}
tr:last-child td{border-bottom:none}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap}
.b-ok{background:#dcfce7;color:var(--ok)}.b-bad{background:#fee2e2;color:var(--bad)}.b-warn{background:#fef3c7;color:var(--warn)}.b-mute{background:#f1f5f9;color:#475569}.b-info{background:#dbeafe;color:var(--brand)}
.btn{display:inline-block;padding:8px 14px;border-radius:6px;border:1px solid #cbd5e1;background:#fff;color:var(--text);cursor:pointer;font-size:13px;text-decoration:none}
.btn.primary{background:var(--brand);color:#fff;border-color:var(--brand)}
.btn:disabled{opacity:.5;cursor:not-allowed}
.help{width:22px;height:22px;border-radius:50%;border:1px solid #94a3b8;background:#fff;color:#475569;font-weight:700;cursor:pointer;font-size:12px;padding:0;margin-left:6px}
.msg{background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:12px 16px;margin-bottom:16px;white-space:pre-wrap}
.alert{background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:12px 16px;margin-bottom:16px;color:#7f1d1d}
.muted{color:var(--muted);font-size:12px}
.tabs{display:flex;gap:4px;margin-bottom:-1px}
.tabs a{padding:9px 16px;border:1px solid var(--line);border-bottom:none;border-radius:8px 8px 0 0;background:#f8fafc;color:#475569;text-decoration:none}
.tabs a.on{background:#fff;color:var(--text);font-weight:700}
.tabbody{border-top-left-radius:0}
form.inline{display:inline}
.row{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin:8px 0}
.field{margin-bottom:16px}.field>label.t{display:block;font-weight:600;margin-bottom:6px}
.chips label{display:inline-block;margin:0 6px 6px 0;padding:4px 10px;border:1px solid var(--line);border-radius:6px;background:#f8fafc}
input[type=number]{width:90px}input,textarea,select{font:inherit;padding:6px 8px;border:1px solid #cbd5e1;border-radius:6px}
dialog{border:none;border-radius:12px;max-width:540px;padding:22px 26px;box-shadow:0 12px 32px rgba(0,0,0,.25);line-height:1.6}
dialog h3{margin:0 0 10px}
pre.log{background:#0f172a;color:#e2e8f0;padding:12px;border-radius:8px;white-space:pre-wrap;font-size:12px}
"""

MENU = [("/", "대시보드"), ("/schedule", "예약 발송 설정"), ("/logs", "실행 이력·로그"), ("/newsletter", "뉴스레터"), ("/settings", "설정")]
RESULT_BADGE = {"성공": "b-ok", "성공 (발송 안 함)": "b-info", "실패": "b-bad", "건너뜀": "b-warn", "진행 중": "b-mute"}
STAGE_BADGE = {"완료": "b-ok", "실패": "b-bad", "안 함": "b-info", "건너뜀": "b-warn"}


def badge(text: str, cls: str) -> str:
    return f'<span class="badge {cls}">{escape(text)}</span>'


def page(title: str, body: str, message: str = "", refresh: bool = False, active: str = "/") -> str:
    links = "".join(f'<a href="{href}"{" class=on" if href == active else ""}>{label}</a>' for href, label in MENU)
    links += '<span title="2단계 예정">수신자·발송 관리 (2단계 예정)</span>'
    note = f'<div class="msg">{escape(message)}</div>' if message else ""
    meta = '<meta http-equiv="refresh" content="10">' if refresh else ""
    return (f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">{meta}'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)} · SABA 관리</title>'
            f'<style>{CSS}</style></head><body><header><div class="logo">SABA 관리</div><nav>{links}</nav></header>'
            f'<main><h1>{escape(title)}</h1>{note}{body}</main></body></html>')


def button(app: AdminApp, action: str, label: str, primary: bool = False, back: str = "/") -> str:
    text = CONFIRM_TEXT.get(action)
    confirm = f' onsubmit="return confirm(\'{escape(text)}\')"' if text else ""  # 작은따옴표 없는 고정 문구만
    hidden = '<input type="hidden" name="confirm" value="yes">' if text else ""
    return (f'<form method="post" action="/action/{action}" class="inline"{confirm}>'
            f'<input type="hidden" name="token" value="{app.token}"><input type="hidden" name="back" value="{escape(back)}">{hidden}'
            f'<button class="btn{" primary" if primary else ""}">{escape(label)}</button></form>')


def help_button(key: str, title: str, body: str) -> str:
    return (f'<button type="button" class="help" title="설명 보기" onclick="document.getElementById(\'help-{key}\').showModal()">?</button>'
            f'<dialog id="help-{key}"><h3>{escape(title)}</h3><div>{body}</div>'
            f'<form method="dialog" style="text-align:right;margin-top:14px"><button class="btn">닫기</button></form></dialog>')


def schedule_summary(config) -> str:
    if config.mode == "weekly":
        detail = "·".join(DAY_LABEL[d] for d in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN") if d in config.weekdays)
    elif config.mode == "monthly":
        detail = ", ".join(f"{d}일" for d in sorted(config.month_days))
    elif config.mode == "dates":
        detail = ", ".join(config.dates[:5]) + (f" 외 {len(config.dates) - 5}개" if len(config.dates) > 5 else "")
    else:
        detail = "모든 요일"
    return f"{MODE_LABEL[config.mode]} {detail} {config.time} (무작위 지연 최대 {config.random_delay_minutes}분)"


def stage_table(run) -> str:
    rows = "".join(f"<tr><td>{escape(name)}</td><td>{escape(clock)}</td><td>{badge(result, STAGE_BADGE.get(result, 'b-mute'))}</td>"
                   f"<td>{escape(detail) or '-'}</td></tr>" for name, clock, result, detail in run.stages)
    return f"<table><tr><th>단계</th><th>시각</th><th>결과</th><th>내용</th></tr>{rows}</table>"


def dashboard(app: AdminApp) -> str:
    from saba.daily import next_runs
    config, task, use, runs = app.config(), app.task(), app.usage(), app.runs()
    now = datetime.now().astimezone()
    today = now.strftime("%Y-%m-%d")
    today_runs = [run for run in runs if run.start.startswith(today)]
    on = task.get("state") not in ("Disabled", "등록 안 됨", "확인 실패")
    upcoming = next_runs(config, now, 3)
    running = app.running()
    sent = app.sent_today()
    recent = app.recent_articles()

    tile_task = (badge("켜짐", "b-ok") if on else badge("꺼짐", "b-mute")) + (
        f'<div class="s">다음 예약 {escape(kst_label(upcoming[0]))}</div>' if on and upcoming else '<div class="s">예약 발송이 꺼져 있습니다</div>')
    if running:
        today_state, today_sub = badge("실행 중", "b-info"), "끝나면 결과가 표시됩니다"
    elif sent:
        today_state, today_sub = badge(f"{sent} 발송 완료", "b-ok"), escape(today_runs[0].origin) if today_runs else ""
    elif today_runs and today_runs[0].result == "실패":
        today_state, today_sub = badge("실패", "b-bad"), escape(today_runs[0].error)
    else:
        today_state, today_sub = badge("아직 발송 안 함", "b-mute"), ""
    tiles = (f'<div class="tiles"><div class="tile"><div class="k">예약 발송</div><div class="v">{tile_task}</div></div>'
             f'<div class="tile"><div class="k">오늘 발송</div><div class="v">{today_state}</div><div class="s">{today_sub}</div></div>'
             f'<div class="tile"><div class="k">이번 달 AI 비용</div><div class="v">${use["cost"]:.3f} / ${use["limit"]:.0f}</div>'
             f'<div class="s">호출 {use["calls"]}건 (성공 {use["ok"]} · 실패 {use["failed"]})</div></div>'
             f'<div class="tile"><div class="k">최근 24시간 수집 기사</div><div class="v">{"-" if recent is None else recent}건</div>'
             f'<div class="s">RSS Source 6곳</div></div></div>')

    alert = ""
    if not running and not sent and today_runs and today_runs[0].result == "실패":
        alert = (f'<div class="alert"><b>오늘 {escape(today_runs[0].start[11:16])} 실행이 실패해 발송하지 않았습니다.</b><br>'
                 f'{escape(today_runs[0].error)}<br>원인을 확인한 뒤 아래 "지금 발송" 으로 다시 시도할 수 있습니다.</div>')

    if running:
        send_body = '<p>지금 실행 중입니다. 10초마다 화면이 새로 고침되며, 끝나면 아래 "마지막 실행" 표에 결과가 나옵니다.</p>'
    else:
        send_body = ('<p class="muted">예약 시각을 기다리지 않고 지금 바로 RSS 수집 → AI 분석 (하루 상한 안) → 메일 생성 → TEST 1명 발송을 합니다.</p>'
                     + button(app, "run_send", "지금 발송", primary=True) + (" " + button(app, "run_resend", "재발송") if sent else ""))
    send_card = f'<div class="card"><h2>지금 발송</h2>{send_body}</div>'

    if runs:
        last = runs[0]
        last_card = (f'<div class="card"><h2>마지막 실행 {badge(last.result, RESULT_BADGE.get(last.result, "b-mute"))}'
                     f'<span class="muted">{escape(last.start)} · {escape(last.origin)}</span>'
                     f'<a class="btn right" href="/logs">전체 이력 보기</a></h2>{stage_table(last)}</div>')
    else:
        last_card = '<div class="card"><h2>마지막 실행</h2><p class="muted">실행 기록이 없습니다.</p></div>'

    checked_on, checked_off = (" checked", "") if on else ("", " checked")
    radio = (f'<form method="post" action="/action/task_state" class="row">'
             f'<input type="hidden" name="token" value="{app.token}"><input type="hidden" name="back" value="/">'
             f'<label><input type="radio" name="state" value="on"{checked_on} onchange="if(confirm(\'예약 발송을 켤까요?\'))this.form.submit();else location.reload()"> 켜기</label>'
             f'<label><input type="radio" name="state" value="off"{checked_off} onchange="if(confirm(\'예약 발송을 끌까요? 꺼져 있는 동안 정해진 시각에 발송하지 않습니다.\'))this.form.submit();else location.reload()"> 끄기</label></form>')
    upcoming_rows = "".join(f"<li>{escape(kst_label(at))}</li>" for at in upcoming) or "<li>예정 없음</li>"
    schedule_card = (f'<div class="card"><h2>예약 발송<a class="btn right" href="/schedule">예약 설정 변경</a></h2>{radio}'
                     f'<table><tr><th style="width:180px">일정</th><td>{escape(schedule_summary(config))}</td></tr>'
                     f'<tr><th>다음 예약 (3회)</th><td><ul style="margin:0;padding-left:18px">{upcoming_rows}</ul></td></tr>'
                     f'<tr><th>발송</th><td>{"TEST 1명에게 발송" if config.send else "메일 생성까지만 (발송 안 함)"}</td></tr></table></div>')

    status_rows = [
        ("최근 24시간 수집 기사", f'{"-" if recent is None else recent}건', "RSS Source 6곳에서 모은 기사 수"),
        ("이번 달 AI 호출", f'{use["calls"]}건 (성공 {use["ok"]} · 실패 {use["failed"]})', f'{use["month"]} · 모델 {use["model"]}'),
        ("이번 달 AI 비용", f'${use["cost"]:.4f} / 상한 ${use["limit"]:.2f}', "상한에 닿으면 AI 호출을 멈춥니다"),
        ("하루 AI 호출 상한", f"분석 {config.max_analysis_calls}건 · 시사점 {config.max_insight_calls}건", "예약 발송 설정에서 변경"),
        ("발송 대상", "TEST 1명 (고정 주소)", "수신자·그룹 관리는 2단계 예정"),
        ("작업 스케줄러", f'{task.get("state", "-")} · 마지막 결과 코드 {task.get("result", "-") or "-"}', "0 이면 정상 종료"),
    ]
    status_card = ('<div class="card"><h2>운영 현황</h2><table><tr><th>항목</th><th>현재 값</th><th>설명</th></tr>'
                   + "".join(f"<tr><td>{escape(a)}</td><td>{escape(b)}</td><td class=muted>{escape(c)}</td></tr>" for a, b, c in status_rows)
                   + "</table></div>")

    tool_rows = "".join(
        f"<tr><td>{escape(name)}{help_button(key, name, body)}</td>"
        f"<td>{badge('외부 접속 있음', 'b-warn') if external == '있음' else badge('외부 접속 없음', 'b-mute')}</td>"
        f"<td>{button(app, key, '실행')}</td></tr>" for key, name, external, body in TOOLS)
    tools_card = ('<div class="card"><h2>점검 도구<span class="muted">문제가 생겼을 때 원인을 찾는 도구입니다. ? 를 누르면 설명이 나옵니다.</span></h2>'
                  f'<table><tr><th>도구</th><th>외부 접속</th><th style="width:90px">실행</th></tr>{tool_rows}</table></div>')
    return tiles + alert + send_card + last_card + schedule_card + status_card + tools_card


def schedule_page(app: AdminApp) -> str:
    from saba.daily import next_runs
    config = app.config()
    days = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    mode_radios = "".join(f'<label><input type="radio" name="mode" value="{m}"{" checked" if config.mode == m else ""} onchange="showMode()"> {label}</label> '
                          for m, label in MODE_LABEL.items())
    weekday_boxes = "".join(f'<label><input type="checkbox" name="weekdays" value="{d}"{" checked" if d in config.weekdays else ""}> {DAY_LABEL[d]}</label>' for d in days)
    month_boxes = "".join(f'<label><input type="checkbox" name="month_days" value="{d}"{" checked" if d in config.month_days else ""}> {d}</label>' for d in range(1, 32))
    per_day = config.max_analysis_calls + config.max_insight_calls
    form = f"""
<form method="post" action="/action/save_schedule" onsubmit="return confirm('{escape(CONFIRM_TEXT['save_schedule'])}')">
<input type="hidden" name="token" value="{app.token}"><input type="hidden" name="back" value="/schedule"><input type="hidden" name="confirm" value="yes">
<div class="card"><h2>반복</h2>
 <div class="row chips">{mode_radios}</div>
 <div id="m-weekly" class="field"><label class="t">요일</label><div class="chips">{weekday_boxes}</div></div>
 <div id="m-monthly" class="field"><label class="t">매월 날짜</label><div class="chips">{month_boxes}</div>
  <div class="muted">그 달에 없는 날짜 (예: 31일) 는 건너뜁니다.</div></div>
 <div id="m-dates" class="field"><label class="t">특정 날짜</label>
  <div class="row"><input type="date" id="pick"> <button type="button" class="btn" onclick="addDate()">날짜 추가</button></div>
  <textarea name="dates" id="dates" rows="4" cols="30" placeholder="한 줄에 하나 (예: 2026-10-20)">{escape(chr(10).join(config.dates))}</textarea>
  <div class="muted">지난 날짜는 무시됩니다. 줄을 지우면 날짜가 빠집니다.</div></div>
</div>
<div class="card"><h2>시각</h2>
 <div class="row"><label>발송 시각 <input type="time" name="time" value="{escape(config.time)}" required></label>
 <label>무작위 지연 최대 <input type="number" name="random_delay_minutes" min="0" max="30" value="{config.random_delay_minutes}"> 분</label></div>
 <div class="muted">무작위 지연: 정해진 시각부터 이 시간 안에서 아무 때나 실행합니다 (0 이면 정각). 정확한 시각 확인이 필요하면 0 으로 두세요.</div>
</div>
<div class="card"><h2>AI 호출과 발송</h2>
 <div class="row"><label>하루 AI 분석 상한 <input type="number" name="max_analysis_calls" min="0" max="50" value="{config.max_analysis_calls}"> 건</label>
 <label>하루 AI 시사점 상한 <input type="number" name="max_insight_calls" min="0" max="50" value="{config.max_insight_calls}"> 건</label></div>
 <div class="muted">현재 하루 최대 {per_day}건 · 매일 발송해도 한 달 최대 약 ${per_day * COST_PER_CALL * 31:.2f} (월 상한 $3, 변경 불가). 이미 분석한 기사는 다시 호출하지 않습니다.</div>
 <div class="row"><label><input type="radio" name="send" value="on"{" checked" if config.send else ""}> 예약 시각에 TEST 1명에게 발송</label>
 <label><input type="radio" name="send" value="off"{"" if config.send else " checked"}> 메일 생성까지만 (발송 안 함)</label></div>
</div>
<div class="card"><h2>보관 기간</h2>
 <div class="row"><label>실행 로그 <input type="number" name="log_days" min="7" max="3650" value="{config.log_days}"> 일</label>
 <label>메일 파일 <input type="number" name="mail_days" min="1" max="3650" value="{config.mail_days}"> 일</label></div>
 <div class="muted">기간이 지난 logs/daily_*.log, output/daily_*.eml 은 매일 실행 때 자동으로 지웁니다.</div>
</div>
<div style="margin-bottom:24px"><button class="btn primary">저장</button> <span class="muted">일정 (반복·시각·지연) 이 바뀌면 작업 스케줄러에 다시 등록합니다.</span></div>
</form>
<script>
function showMode(){{var m=(document.querySelector('input[name=mode]:checked')||{{}}).value;
 ['weekly','monthly','dates'].forEach(function(k){{document.getElementById('m-'+k).style.display=(m===k)?'':'none'}});}}
function addDate(){{var v=document.getElementById('pick').value;if(!v)return;var t=document.getElementById('dates');
 var list=t.value.split(/\\s+/).filter(Boolean);if(list.indexOf(v)<0)list.push(v);list.sort();t.value=list.join('\\n');}}
showMode();
</script>"""
    upcoming = "".join(f"<tr><td>{i}</td><td>{escape(kst_label(at))}</td></tr>" for i, at in enumerate(next_runs(config, datetime.now().astimezone(), 5), 1))
    return (f'<div class="card"><h2>현재 일정</h2><table><tr><th style="width:180px">일정</th><td>{escape(schedule_summary(config))}</td></tr></table>'
            f'<h2 style="margin-top:14px">다음 예약 5회</h2><table><tr><th style="width:60px">순서</th><th>시각 (무작위 지연 전)</th></tr>'
            f'{upcoming or "<tr><td colspan=2>예정 없음</td></tr>"}</table></div>' + form)


def logs_page(app: AdminApp, tab: str, day: str | None) -> str:
    from saba.history import log_files, read_changes, read_log, storage_status
    config = app.config()
    store = storage_status(app.root)
    tabs = "".join(f'<a href="/logs?tab={key}"{" class=on" if tab == key else ""}>{label}</a>'
                   for key, label in (("runs", "실행 이력"), ("detail", "상세 로그"), ("changes", "설정 변경 이력")))
    keep = (f'<div class="muted" style="margin-bottom:12px">보관: 실행 로그 {config.log_days}일 (현재 {store["logs"]["count"]}개 파일 · '
            f'{store["logs"]["bytes"] / 1024:.1f} KB · 가장 오래된 날짜 {store["logs"]["oldest"]}) · 메일 파일 {config.mail_days}일 '
            f'(현재 {store["mails"]["count"]}개 · {store["mails"]["bytes"] / 1024 / 1024:.2f} MB). 기간이 지나면 매일 실행 때 자동 삭제.</div>')
    if tab == "detail":
        files = log_files(app.root / "logs")
        names = [p.name[6:14] for p in files]
        day = day if day in names else (names[0] if names else None)
        options = "".join(f'<option value="{d}"{" selected" if d == day else ""}>{d[:4]}-{d[4:6]}-{d[6:]}</option>' for d in names)
        picker = (f'<form method="get" action="/logs" class="row"><input type="hidden" name="tab" value="detail">'
                  f'<label>날짜 <select name="day" onchange="this.form.submit()">{options}</select></label></form>')
        rows = ""
        if day:
            level = {"INFO": ("정보", "b-mute"), "WARNING": ("경고", "b-warn"), "ERROR": ("오류", "b-bad")}
            rows = "".join(f"<tr><td style='white-space:nowrap'>{escape(line.time[11:])}</td><td>{badge(*level[line.level])}</td>"
                           f"<td>{escape(line.message)}</td></tr>" for line in read_log(app.root / "logs" / f"daily_{day}.log"))
        body = picker + f"<table><tr><th style='width:90px'>시각</th><th style='width:70px'>수준</th><th>내용</th></tr>{rows or '<tr><td colspan=3>로그 없음</td></tr>'}</table>"
    elif tab == "changes":
        records = read_changes(app.changes_path)
        rows = "".join(f"<tr><td style='white-space:nowrap'>{escape(r['at'])}</td><td>{escape(FIELD_LABEL.get(k, k))}</td>"
                       f"<td>{escape(_show(v[0]))}</td><td>{escape(_show(v[1]))}</td><td>{'예' if r.get('reregistered') else '-'}</td></tr>"
                       for r in records for k, v in r.get("changes", {}).items())
        body = ("<table><tr><th>시각</th><th>항목</th><th>이전 값</th><th>새 값</th><th>스케줄러 재등록</th></tr>"
                f"{rows or '<tr><td colspan=5>변경 기록 없음</td></tr>'}</table>")
    else:
        rows = ""
        for run in app.runs():
            day_key = run.start[:10].replace("-", "")
            rows += (f"<tr><td style='white-space:nowrap'>{escape(run.start[:16])}</td><td>{escape(run.origin)}</td>"
                     f"<td>{badge(run.result, RESULT_BADGE.get(run.result, 'b-mute'))}</td>"
                     f"<td>{'-' if run.articles is None else run.articles}</td><td>{'-' if run.ai_calls is None else run.ai_calls}</td>"
                     f"<td>{escape(run.mail_bytes or '-')}</td><td>{'발송' if run.sent else '-'}</td>"
                     f"<td>{escape(run.error) or '-'}</td><td><a href='/logs?tab=detail&day={day_key}'>로그</a></td></tr>")
        body = ("<table><tr><th>시작</th><th>실행 주체</th><th>결과</th><th>기사</th><th>AI 신규 호출</th><th>메일 크기 (bytes)</th>"
                f"<th>발송</th><th>실패 사유</th><th></th></tr>{rows or '<tr><td colspan=9>실행 기록 없음</td></tr>'}</table>")
    return f'<div class="tabs">{tabs}</div><div class="card tabbody">{keep}{body}</div>'


def _show(value) -> str:
    if isinstance(value, bool):
        return "발송" if value else "발송 안 함"
    if isinstance(value, list):
        return ", ".join(DAY_LABEL.get(str(v), str(v)) for v in value) or "(없음)"
    return MODE_LABEL.get(str(value), str(value))


def newsletter_page(app: AdminApp, name: str | None) -> str:
    files = app.mail_files()
    kind_badge = {"발송본": "b-ok", "생성만 (발송 안 함)": "b-info", "미리보기": "b-warn"}
    rows = "".join(f"<tr><td><a href='/newsletter?name={quote(f['name'])}'>{escape(f['name'])}</a></td>"
                   f"<td>{badge(f['kind'], kind_badge.get(f['kind'], 'b-mute'))}</td><td>{escape(f['made'])}</td>"
                   f"<td>{escape(f['origin'])}</td><td>{f['size'] / 1024:.0f} KB</td></tr>" for f in files)
    name = name or (files[0]["name"] if files else None)
    guide = ('<div class="muted" style="margin-bottom:10px">발송본: 실제로 TEST 수신자에게 보낸 메일 · 생성만: 만들었지만 보내지 않은 메일 · '
             '미리보기: 점검 도구 "미리보기 다시 만들기" 로 만든 확인용 (최신 1개만 보관). 메일은 만든 시각 기준 최근 24시간 (월요일 72시간) 기사로 '
             '구성되므로 만든 시각이 다르면 기사 구성이 다릅니다. 미리보기는 AI 를 새로 호출하지 않아 새 기사의 요약이 빠질 수 있습니다.</div>')
    frame = (f'<iframe src="/newsletter/view?name={quote(name)}" style="width:100%;height:900px;border:0"></iframe>'
             if name else "<p>생성된 메일이 없습니다.</p>")
    return (f'<div class="card"><h2>메일 파일</h2>{guide}<table><tr><th>파일</th><th>종류</th><th>만든 시각</th><th>실행 주체</th><th>크기</th></tr>'
            f'{rows or "<tr><td colspan=5>없음</td></tr>"}</table></div>'
            f'<div class="card"><h2>{escape(name or "")}</h2>{frame}</div>')


def settings_page(app: AdminApp) -> str:
    from saba.rss import SOURCES
    from saba.send_mail import TEST_ADDRESS
    config, valid = app.config(), app._try(app.config)
    sources = "".join(f"<tr><td>{escape(s.source_name)}</td><td>{escape(s.region)}</td><td>{'공식' if s.official else '언론'}</td>"
                      f"<td class=muted>{escape(s.source_id)}</td></tr>" for s in SOURCES)
    secret_rows = "".join(f"<tr><td>{escape(n)}</td><td>{badge('있음', 'b-ok') if v else badge('없음', 'b-bad')}</td></tr>"
                          for n, v in app.secrets_present().items())
    return (f'<div class="card"><h2>예약 발송<a class="btn right" href="/schedule">변경</a></h2><table>'
            f'<tr><th style="width:200px">일정</th><td>{escape(schedule_summary(config))}</td></tr>'
            f'<tr><th>하루 AI 호출 상한</th><td>분석 {config.max_analysis_calls}건 · 시사점 {config.max_insight_calls}건</td></tr>'
            f'<tr><th>발송</th><td>{"발송" if config.send else "메일 생성까지만"}</td></tr>'
            f'<tr><th>보관 기간</th><td>로그 {config.log_days}일 · 메일 파일 {config.mail_days}일</td></tr>'
            f'<tr><th>설정 파일 점검</th><td>{escape(valid)}</td></tr></table></div>'
            f'<div class="card"><h2>RSS Source<span class="muted">추가·수정·삭제는 다음 작업 예정 (D-072)</span></h2>'
            f'<table><tr><th>이름</th><th>구분</th><th>종류</th><th>ID</th></tr>{sources}</table></div>'
            f'<div class="card"><h2>Secret (값은 표시하지 않음)<span class="muted">변경 기능은 로그인·권한 작업과 함께 예정</span></h2>'
            f'<table><tr><th>이름</th><th>상태</th></tr>{secret_rows}</table></div>'
            f'<div class="card"><h2>발송 대상<span class="muted">수신자·그룹 (전체 인원) 관리는 2단계 예정</span></h2>'
            f'<table><tr><th style="width:200px">현재</th><td>TEST 1명 (고정, {escape(TEST_ADDRESS)})</td></tr></table></div>')


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
                return self._send(200, page("대시보드", dashboard(app), message, refresh=app.running(), active="/"))
            if url.path == "/schedule":
                return self._send(200, page("예약 발송 설정", schedule_page(app), message, active="/schedule"))
            if url.path == "/logs":
                tab = _first(query, "tab") or "runs"
                return self._send(200, page("실행 이력·로그", logs_page(app, tab, _first(query, "day") or None), message, active="/logs"))
            if url.path == "/newsletter":
                return self._send(200, page("뉴스레터", newsletter_page(app, _first(query, "name") or None), message, active="/newsletter"))
            if url.path == "/newsletter/view":
                html = app.newsletter_html(_first(query, "name") or None)
                return self._send(200, html or "<p>생성된 메일이 없습니다.</p>")
            if url.path == "/settings":
                return self._send(200, page("설정", settings_page(app), message, active="/settings"))
            return self._send(404, page("없는 페이지", "<p>없는 페이지입니다.</p>"))

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, "forbidden", "text/plain; charset=utf-8")
            length = min(int(self.headers.get("Content-Length") or 0), 16384)
            form = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"), keep_blank_values=True)
            action = urlparse(self.path).path.removeprefix("/action/")
            if not secrets.compare_digest(_first(form, "token"), app.token):
                return self._send(403, "forbidden", "text/plain; charset=utf-8")
            if action in CONFIRM_TEXT and _first(form, "confirm") != "yes":
                return self._send(400, "confirm required", "text/plain; charset=utf-8")
            try:
                app.message = app.act(action, form)
            except Exception as error:  # 화면에는 종류와 고정 문구만
                app.message = f"실패: {error}" if isinstance(error, AdminError) else f"실패: {type(error).__name__}"
            back = _first(form, "back")
            self.send_response(303)
            self.send_header("Location", back if back in {href for href, _ in MENU} else "/")  # 내부 화면으로만
            self.end_headers()

    return Handler


class Server(ThreadingHTTPServer):
    # Windows 에서는 주소 재사용을 켜면 같은 포트에 서버가 두 개 붙는다 (예전 화면이 응답). 두 번째 시작은 실패시킨다.
    allow_reuse_address = False


def serve(host: str, port: int, app: AdminApp | None = None) -> ThreadingHTTPServer:
    if host not in LOOPBACK:
        raise AdminError("127.0.0.1 에서만 열 수 있습니다.")
    return Server((host, port), make_handler(app or AdminApp(), port))


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
    url = f"http://127.0.0.1:{port}/"
    try:
        server = serve(host, port)
    except OSError:  # 이미 열려 있다 (bat 를 두 번 누른 경우 등): 새로 띄우지 않고 열려 있는 화면을 보여 준다
        print(f"관리 페이지가 이미 열려 있습니다: {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0
    PID_PATH.parent.mkdir(exist_ok=True)
    PID_PATH.write_text(str(os.getpid()))
    print(f"SABA 관리 페이지: {url} (종료: 이 창을 닫거나 Ctrl+C)")
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
