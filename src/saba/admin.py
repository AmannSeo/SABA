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
import time
from typing import Callable
from urllib.parse import parse_qs, quote, urlencode, urlparse
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
    "test_now": "즉시 테스트 발송: RSS 수집 → AI 분석 (하루 상한 안) → 메일 생성 → TEST 1명 발송을 지금 실행합니다. 진행할까요?",
    "test_schedule": "정한 시각에 테스트 발송을 1회 예약합니다 (평소 예약 발송 일정은 그대로). 진행할까요?",
    "test_cancel": "예약된 테스트 발송을 취소할까요?",
    "source_check": "RSS 주소 확인: 입력한 주소에 1회 접속합니다 (저장 없음). 진행할까요?",
    "source_save": "RSS Source 를 저장합니다. 다음 실행부터 수집에 반영됩니다. 진행할까요?",
    "source_toggle": "이 RSS Source 의 사용·중지를 바꿀까요? 이미 수집한 기사는 그대로 둡니다.",
    "source_delete": "이 RSS Source 를 목록에서 삭제할까요? 수집한 기사·분석은 DB 에 남지만 메일에는 더 이상 나오지 않습니다.",
    "rss_dryrun": "RSS 수집 점검: 사용 중인 RSS Source 에 접속합니다 (저장 없음). 진행할까요?",
    "recipient_delete": "이 수신자를 삭제할까요? 되돌릴 수 없습니다 (잠시 빼려면 중지를 쓰세요).",
    "csv_apply": "미리보기의 신규·갱신 행을 저장합니다 (오류 행은 건너뜀). 진행할까요?",
    "group_delete": "이 그룹을 삭제할까요? 수신자는 그대로 두고 그룹 소속만 지웁니다.",
    "department_delete": "이 부서를 목록에서 삭제할까요?",
    "domain_delete": "이 도메인을 허용 목록에서 삭제할까요?",
    "resend_failed": "이 회차에서 실패·미시도인 사람에게만 원본 메일을 다시 보냅니다 (성공·불명확 제외). 진행할까요?",
    "criteria_save": "부서별 분류 기준을 저장합니다. 다음 실행부터 새 기준으로 시사점을 만듭니다 (이미 만든 시사점도 다시 만듦, 하루 상한 안). 진행할까요?",
    "smtp_check": "메일 서버 로그인 점검: 회사 메일 서버에 접속해 로그인만 확인합니다 (발송 없음). 진행할까요?",
    "save_schedule": "예약 발송 설정을 저장합니다. 일정이 바뀌면 작업 스케줄러에 다시 등록합니다. 진행할까요?",
}
MODE_LABEL = {"daily": "매일", "weekly": "매주", "monthly": "매월", "dates": "특정 날짜"}
DAY_LABEL = dict(zip(("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"), "월화수목금토일"))
FIELD_LABEL = {"mode": "주기", "time": "시각", "random_delay_minutes": "무작위 지연(분)", "weekdays": "요일",
               "month_days": "매월 날짜", "dates": "특정 날짜", "max_analysis_calls": "하루 AI 분석 상한",
               "max_insight_calls": "하루 AI 시사점 상한", "send": "발송", "log_days": "로그 보관(일)",
               "mail_days": "메일 보관(일)", "target_group": "발송 대상"}
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
     "사용 중인 RSS Source 에 실제로 접속해 기사를 가져올 수 있는지 확인합니다.<br><b>가져온 기사는 저장하지 않습니다.</b> "
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
    fetch: Callable | None = None  # RSS 주소 확인용 (기본 rss.fetch_feed, 테스트에서 바꿈)
    token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    message: str = ""
    checked: dict[str, float] = field(default_factory=dict)  # 주소 확인을 통과한 RSS 주소와 시각 (30분 유효)
    draft: dict = field(default_factory=dict)  # 주소 확인 뒤 저장할 때까지 입력 값을 유지
    csv_rows: list = field(default_factory=list)  # 수신자 CSV 미리보기 (저장 전, 메모리에만)

    # ---- 경로 ----
    @property
    def config_path(self) -> Path:
        return self.root / "config" / "daily.json"

    @property
    def sources_path(self) -> Path:
        return self.root / "config" / "sources.json"

    def source_entries(self):
        from saba.rss import load_source_entries
        return load_source_entries(self.sources_path)

    @property
    def recipients_path(self) -> Path:
        return self.root / "data" / "recipients.db"

    @property
    def departments_path(self) -> Path:
        return self.root / "config" / "departments.json"

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

    def real_runs_today(self):
        """테스트 발송을 뺀 오늘 실행 (예약·지금 발송), 최신 순."""
        return [run for run in self.today_runs() if not run.origin.startswith("테스트")]

    def send_needed(self) -> str | None:
        """오늘 뉴스레터가 실패했거나 예약 시각이 지났는데 발송되지 않았으면 그 이유 (D-073). 아니면 None."""
        from saba.daily import scheduled_on
        config = self.config()
        runs = self.real_runs_today()
        if not config.send or any(run.sent for run in runs) or self.running():
            return None
        if any("불명확" in run.error for run in runs):
            return None
        if runs and runs[0].result == "실패":
            return f"오늘 {runs[0].start[11:16]} 실행이 실패해 발송하지 않았습니다. {runs[0].error}"
        now = datetime.now().astimezone()
        hour, minute = map(int, config.time.split(":"))
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(minutes=config.random_delay_minutes + 15)
        if scheduled_on(config, now.date()) and now > due:
            return f"오늘 예약 시각 ({config.time}) 이 지났는데 발송 기록이 없습니다. PC 가 꺼져 있었거나 예약 발송이 꺼져 있었을 수 있습니다."
        return None

    def test_task(self) -> dict:
        from saba.daily import TEST_TASK_NAME
        code, out = self.shell(f"$t=Get-ScheduledTask -TaskName {TEST_TASK_NAME} -ErrorAction SilentlyContinue; "
                               "if ($t) { $i=$t|Get-ScheduledTaskInfo; "
                               "$n = if ($i.NextRunTime) { $i.NextRunTime.ToString('yyyy-MM-dd HH:mm') } else { '' }; "
                               "\"$($t.State)|$n\" } else { 'NotRegistered' }")
        if code != 0 or not out.strip() or out.strip() == "NotRegistered":
            return {}
        state, next_run = (out.strip().splitlines()[-1].split("|") + [""])[:2]
        return {"state": state, "next": next_run}

    def running(self) -> bool:
        from saba.daily import is_running
        return is_running(self.root / "data" / "daily.lock")

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
        for path in sorted((self.root / "output").glob("daily_*.eml"), key=lambda p: (p.stat().st_mtime, p.name), reverse=True):
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
        if action == "run_send":
            return self.run_now()
        if action == "test_now":
            return self.test_now()
        if action == "test_schedule":
            return self.test_schedule(_first(form, "at"))
        if action == "test_cancel":
            from saba.daily import TEST_TASK_NAME
            code, _ = self.shell(f"Unregister-ScheduledTask -TaskName {TEST_TASK_NAME} -Confirm:$false")
            return "테스트 발송 예약을 취소했습니다." if code == 0 else f"취소 실패 (종료 코드 {code})"
        if action == "source_check":
            return self.check_source(form)
        if action == "source_save":
            return self.save_source(form)
        if action in ("source_toggle", "source_delete"):
            return self.change_source(_first(form, "id"), delete=action == "source_delete")
        if action.startswith(("recipient_", "group_", "department_", "domain_", "csv_")):
            return self.recipient_action(action, form)
        if action == "resend_failed":
            return self.resend_failed(_first(form, "id"))
        if action == "criteria_save":
            return self.save_criteria(form)
        if action == "task_state":
            return self.set_task_state(_first(form, "state") == "on")
        if action == "save_schedule":
            return self.save_schedule(form)
        raise AdminError("알 수 없는 동작입니다.")

    def run_now(self) -> str:
        """지금 발송 (D-071, D-073): 오늘 뉴스레터가 실패·미발송일 때 대시보드에 나온다. 같은 daily --run 경로."""
        if self.running():
            return "이미 실행 중입니다. 끝난 뒤 다시 시도하세요."
        sent = next((r for r in self.real_runs_today() if r.sent), None)
        if sent:
            return f"오늘 {sent.start[11:16]} 에 이미 발송했습니다. 한 번 더 확인하려면 테스트 화면의 \"즉시 테스트 발송\" 을 쓰세요."
        self.launch([sys.executable, "-m", "saba.daily", "--run", "--manual"])
        return "지금 발송을 시작했습니다. 1~2분 걸리며, 끝나면 \"마지막 실행\" 에 결과가 나옵니다."

    def test_now(self) -> str:
        if self.running():
            return "이미 실행 중입니다. 끝난 뒤 다시 시도하세요."
        self.launch([sys.executable, "-m", "saba.daily", "--run", "--manual", "--test"])
        return "즉시 테스트 발송을 시작했습니다. 1~2분 뒤 아래 \"테스트 발송 기록\" 에 결과가 나옵니다."

    def test_schedule(self, value: str) -> str:
        """시각 지정 테스트 발송 (D-073): 별도 1회용 작업. 평소 예약 일정은 바꾸지 않는다."""
        from saba.daily import test_task_command
        try:
            at = datetime.strptime(value.strip(), "%Y-%m-%dT%H:%M")
        except ValueError:
            raise AdminError("테스트 시각을 입력해 주세요.") from None
        now = datetime.now()
        if not now + timedelta(minutes=1) <= at <= now + timedelta(days=7):
            raise AdminError("테스트 시각은 지금부터 1분 뒤 ~ 7일 안이어야 합니다.")
        code, _ = self.shell(test_task_command(at))
        if code != 0:
            raise AdminError(f"테스트 발송 예약 실패 (종료 코드 {code})")
        return f"테스트 발송 예약: {kst_label(at)} (평소 예약 발송 일정은 그대로입니다)"

    # ---- RSS Source (D-073) ----
    def _source_form(self, form: dict):
        """입력 값을 검증해 SourceEntry 하나로 만든다 (형식 검증은 rss.parse_sources 와 같다)."""
        from saba.rss import RssError, parse_sources
        row = {"id": _first(form, "id").strip().lower(), "name": _first(form, "name"), "url": _first(form, "url"),
               "region": _first(form, "region") or "해외", "kind": _first(form, "kind") or "보안 전문 매체",
               "kst": _first(form, "kst") == "on", "date_only": _first(form, "date_only") == "on",
               "enabled": _first(form, "enabled") == "on"}
        self.draft = {**row, "mode": _first(form, "mode")}
        try:
            return parse_sources([row])[0]
        except RssError as error:
            raise AdminError(str(error).replace("Source 설정 오류: ", "")) from None

    def check_source(self, form: dict) -> str:
        """RSS 주소에 1회 접속해 형식·항목 수·날짜 해석을 미리 본다. 저장하지 않는다."""
        from saba.rss import RssError, fetch_feed, parse_feed
        entry = self._source_form(form)
        now = datetime.now(timezone.utc)
        try:
            articles = parse_feed((self.fetch or fetch_feed)(entry.source), now, entry.source)
        except RssError as error:
            self.checked.pop(entry.source.feed_url, None)
            raise AdminError(f"주소 확인 실패 · {error}") from None
        if not articles:
            raise AdminError("주소 확인 실패 · RSS 항목이 0건입니다.")
        dated = sorted((a for a in articles if a.published_at), key=lambda a: a.published_at, reverse=True)
        self.checked[entry.source.feed_url] = time.time()
        lines = [f"주소 확인 성공: 항목 {len(articles)}건 · 날짜 해석 {len(dated)}건 · 날짜 미확인 {len(articles) - len(dated)}건",
                 "최근 기사 (한국 시간):"]
        lines += [f"  {a.published_at.astimezone(timezone(timedelta(hours=9))):%Y-%m-%d %H:%M}  {a.original_title[:70]}"
                  for a in dated[:3]]
        if len(dated) < len(articles):
            lines.append("날짜가 해석되지 않은 항목이 있습니다. 날짜에 시간대가 없으면 \"한국 시간으로 해석\" 을 켜고 다시 확인하세요.")
        lines.append("이상이 없으면 \"저장\" 을 누르세요 (30분 안).")
        return "\n".join(lines)

    def _save_entries(self, entries, changes: dict) -> None:
        from saba.history import append_change
        from saba.rss import RssError, SOURCES_PATH, reload_sources, save_source_entries
        try:
            save_source_entries(entries, self.sources_path)
        except RssError as error:
            raise AdminError(str(error).replace("Source 설정 오류: ", "")) from None
        if self.sources_path == SOURCES_PATH:  # 이 프로세스의 표시용 목록도 바로 바꾼다
            reload_sources(self.sources_path)
        append_change(self.changes_path, changes, False)

    def save_source(self, form: dict) -> str:
        from saba.rss import MAX_SOURCES
        entry = self._source_form(form)
        entries = self.source_entries()
        index = next((i for i, e in enumerate(entries) if e.source.source_id == entry.source.source_id), None)
        editing = _first(form, "mode") == "edit"
        if editing != (index is not None):
            raise AdminError("이미 있는 ID 입니다. 다른 ID 를 쓰세요." if index is not None else "수정할 Source 를 찾지 못했습니다.")
        old = entries[index] if editing else None
        url_changed = old is None or old.source.feed_url != entry.source.feed_url
        if url_changed and time.time() - self.checked.get(entry.source.feed_url, 0) > 1800:
            raise AdminError("저장하지 않음 · 새 주소는 먼저 \"주소 확인\" 을 통과해야 합니다 (30분 안).")
        if editing:
            entries[index] = entry
        else:
            if len(entries) >= MAX_SOURCES:
                raise AdminError(f"저장하지 않음 · RSS Source 는 최대 {MAX_SOURCES}곳입니다.")
            entries.append(entry)
        if not any(e.enabled for e in entries):
            raise AdminError("저장하지 않음 · 사용 중인 Source 가 하나 이상 있어야 합니다.")
        self._save_entries(entries, {f"RSS Source {entry.source.source_id}": (_source_text(old), _source_text(entry))})
        self.draft = {}
        return f"RSS Source {'수정' if editing else '추가'} 완료: {entry.source.source_name} (다음 실행부터 반영)"

    def change_source(self, source_id: str, delete: bool) -> str:
        from dataclasses import replace as replace_entry
        entries = self.source_entries()
        index = next((i for i, e in enumerate(entries) if e.source.source_id == source_id), None)
        if index is None:
            raise AdminError("Source 를 찾지 못했습니다.")
        old = entries[index]
        if delete:
            entries.pop(index)
            new = None
        else:
            new = entries[index] = replace_entry(old, enabled=not old.enabled)
        if not any(e.enabled for e in entries):
            raise AdminError("변경하지 않음 · 사용 중인 Source 가 하나 이상 있어야 합니다.")
        self._save_entries(entries, {f"RSS Source {source_id}": (_source_text(old), _source_text(new))})
        verb = "삭제" if delete else ("사용" if new.enabled else "중지")
        return f"RSS Source {verb}: {old.source.source_name} (다음 실행부터 반영, 수집한 기사는 DB 에 유지)"

    # ---- 수신자·그룹 (D-074, D-075). 명단은 화면에만, 기록에는 건수만 ----
    def recipient_action(self, action: str, form: dict) -> str:
        from saba import recipients as rc
        from saba.history import append_change
        path = self.recipients_path
        before = rc.counts(path)["total"]
        value = _first(form, "name").strip()
        try:
            if action == "recipient_save":
                rid = _first(form, "id")
                done = rc.save(_first(form, "name"), _first(form, "email"), _first(form, "department"), form.get("groups", []),
                               enabled=_first(form, "enabled") == "on", recipient_id=int(rid) if rid else None, path=path)
                message = f"수신자 {done} 완료"
            elif action in ("recipient_toggle", "recipient_delete"):
                rid = int(_first(form, "id") or 0)
                person = next((r for r in rc.recipients(path) if r.id == rid), None)
                if person is None:
                    raise AdminError("수신자를 찾지 못했습니다.")
                if action == "recipient_delete":
                    rc.delete(rid, path)
                    done = "삭제"
                else:
                    rc.set_enabled(rid, not person.enabled, path)
                    done = "중지" if person.enabled else "사용"
                message = f"수신자 {done} 완료"
            elif action == "csv_preview":
                self.csv_rows = rc.parse_csv(_first(form, "csv"), path)
                if not self.csv_rows:
                    return "CSV 에 읽을 행이 없습니다."
                n = {k: sum(r["status"] == k for r in self.csv_rows) for k in ("신규", "갱신", "오류")}
                return f"미리보기: 신규 {n['신규']}명 · 갱신 {n['갱신']}명 · 오류 {n['오류']}행. 아래 표를 확인하고 \"저장\" 을 누르세요 (아직 저장 안 됨)."
            elif action == "csv_apply":
                if not self.csv_rows:
                    raise AdminError("먼저 CSV 미리보기를 하세요.")
                added, updated, skipped = rc.apply_csv(self.csv_rows, path)
                self.csv_rows = []
                done = f"CSV 신규 {added} · 갱신 {updated} · 건너뜀 {skipped}"
                message = f"CSV 저장 완료: 신규 {added}명 · 갱신 {updated}명 · 건너뜀 {skipped}행"
            elif action == "csv_cancel":
                self.csv_rows = []
                return "CSV 미리보기를 취소했습니다."
            elif action == "group_add":
                rc.add_group(value, path)
                done = message = f"그룹 추가: {value}"
            elif action == "group_delete":
                rc.delete_group(value, path)
                done = message = f"그룹 삭제: {value}"
            elif action == "department_add":
                rc.add_department(value, path)
                done = message = f"부서 추가: {value}"
            elif action == "department_delete":
                rc.delete_department(value, path)
                done = message = f"부서 삭제: {value}"
            elif action == "domain_add":
                rc.add_domain(value, path)
                done = message = f"허용 도메인 추가: {value}"
            elif action == "domain_delete":
                rc.delete_domain(value, path)
                done = message = f"허용 도메인 삭제: {value}"
            else:
                raise AdminError("알 수 없는 동작입니다.")
        except rc.RecipientError as error:
            raise AdminError(f"저장하지 않음 · {error}") from None
        after = rc.counts(path)["total"]
        # 개인정보: 이름·메일은 남기지 않고 인원 수와 동작만 기록한다.
        append_change(self.changes_path, {"수신자 명단": (f"{before}명", f"{after}명 ({done if action != 'recipient_save' else '수신자 ' + done})")}, False)
        return message

    def resend_failed(self, value: str) -> str:
        """실패 수신자 재발송 (D-077): 여기서 먼저 검사하고, 실제 발송은 매일 실행과 같은 잠금 안의 별도 프로세스로."""
        from saba import daily, sendlog
        if not value.isdigit():
            raise AdminError("회차 번호가 필요합니다.")
        if self.running():
            return "다른 실행이 진행 중입니다. 끝난 뒤 다시 시도하세요."
        try:
            _original, emails, _data, skipped = daily.resend_check(
                int(value), history=self.root / "data" / "send_history.db", recipients_path=self.recipients_path,
                output_dir=self.root / "output")
        except (daily.DailyError, sendlog.SendLogError) as error:
            raise AdminError(f"재발송하지 않음 · {error}") from None
        self.launch([sys.executable, "-m", "saba.daily", "--resend", value])
        return f"회차 {value} 실패 재발송을 시작했습니다: {len(emails)}명" + (f" (제외 {skipped}명)" if skipped else "")

    def save_criteria(self, form: dict) -> str:
        """부서별 분류 기준 (D-075). 이름 4개 고정, 담당 업무·판단 예시만 편집."""
        from saba.history import append_change
        from saba.insights import DEPARTMENT_NAMES, DepartmentError, department_rows, load_departments, parse_departments
        old_scopes, old_examples = load_departments(self.departments_path)
        rows = [{"name": name, "scope": _first(form, f"scope_{i}"), "examples": _first(form, f"examples_{i}")}
                for i, name in enumerate(DEPARTMENT_NAMES)]
        try:
            scopes, examples = parse_departments(rows)
        except DepartmentError as error:
            raise AdminError(f"저장하지 않음 · {str(error).replace('부서 기준 오류: ', '')}") from None
        changes = {}
        for name in DEPARTMENT_NAMES:
            if (old_scopes[name], old_examples[name]) != (scopes[name], examples[name]):
                changes[f"부서 기준 {name}"] = (f"{old_scopes[name]} / {old_examples[name]}", f"{scopes[name]} / {examples[name]}")
        if not changes:
            return "변경 사항이 없습니다."
        self.departments_path.write_text(json.dumps(department_rows(scopes, examples), ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
        append_change(self.changes_path, changes, False)
        return f"부서별 분류 기준 저장: {', '.join(k.removeprefix('부서 기준 ') for k in changes)} (다음 실행부터 적용)"

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
            "target_group": _first(form, "target_group") or old.target_group,
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


def _source_text(entry) -> str:
    if entry is None:
        return "(없음)"
    s = entry.source
    return (f"{s.source_name} · {s.feed_url} · {s.region} · {s.kind}"
            f"{' · 한국 시간' if s.local_offset else ''}{' · 날짜만' if s.date_only else ''} · {'사용' if entry.enabled else '중지'}")


def _first(form: dict, key: str) -> str:
    return (form.get(key) or [""])[0]


# ---------------- HTML ----------------
CSS = """
:root{
 --bg:#f4f5f7;--surface:#fff;--subtle:#f8f9fb;--line:#e3e6eb;--text:#151a23;--muted:#596273;
 --accent:#2457d6;--accent-strong:#1d47b3;--accent-soft:#e8eefc;
 --ok:#15703a;--ok-soft:#e5f4ea;--warn:#9a5200;--warn-soft:#fdf1e1;--bad:#b42318;--bad-soft:#fdecea;
 --r-card:12px;--r-ctl:8px;--shadow:0 1px 2px rgba(21,26,35,.05)}
/* 모서리 규칙: 카드 12px, 버튼·입력 8px, 배지 둥근 알약. 색 규칙: 강조색은 --accent 하나, 초록·주황·빨강은 상태를 뜻할 때만. */
*{box-sizing:border-box}
body{margin:0;font-family:'Pretendard','Malgun Gothic','Apple SD Gothic Neo',system-ui,sans-serif;background:var(--bg);color:var(--text);
 font-size:14px;line-height:1.55;font-variant-numeric:tabular-nums}
header{background:var(--surface);border-bottom:1px solid var(--line);padding:0 32px;display:flex;align-items:center;gap:36px;height:64px}
header .logo{font-weight:800;font-size:16px;letter-spacing:-.2px}
header nav{display:flex;gap:4px;overflow-x:auto}
header nav a{color:var(--muted);text-decoration:none;padding:8px 12px;border-radius:var(--r-ctl);white-space:nowrap;font-weight:500}
header nav a:hover{background:var(--subtle);color:var(--text)}
header nav a.on{background:var(--accent-soft);color:var(--accent);font-weight:700}
main{max-width:1440px;margin:28px auto 48px;padding:0 32px}
h1{font-size:22px;letter-spacing:-.3px;margin:0 0 20px}
.tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin-bottom:16px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-card);padding:18px 20px;box-shadow:var(--shadow)}
.tile .k{color:var(--muted);font-size:13px;font-weight:600}.tile .v{font-size:20px;font-weight:800;margin-top:8px;letter-spacing:-.3px}
.tile .s{color:var(--muted);font-size:12.5px;margin-top:6px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-card);padding:20px 24px;margin-bottom:16px;box-shadow:var(--shadow)}
.card h2{font-size:15.5px;margin:0 0 14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.card h2 .right{margin-left:auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
table{border-collapse:collapse;width:100%;border:1px solid var(--line)}
.tw{overflow-x:auto;max-width:100%}
th,td{padding:10px 12px;border:1px solid var(--line);text-align:left;vertical-align:middle}
th{background:var(--subtle);color:var(--muted);font-weight:600;font-size:12.5px;white-space:nowrap}
tr:first-child th{border-top:1px solid var(--line)}
tr.group td{background:var(--subtle);color:var(--text);font-weight:700;font-size:13px}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap}
.b-ok{background:var(--ok-soft);color:var(--ok)}.b-bad{background:var(--bad-soft);color:var(--bad)}.b-warn{background:var(--warn-soft);color:var(--warn)}
.b-mute{background:var(--subtle);color:var(--muted);box-shadow:inset 0 0 0 1px var(--line)}.b-info{background:var(--accent-soft);color:var(--accent)}
.btn{display:inline-flex;align-items:center;justify-content:center;vertical-align:middle;min-height:36px;padding:7px 14px;border-radius:var(--r-ctl);border:1px solid var(--line);background:var(--surface);color:var(--text);
 cursor:pointer;font:inherit;font-size:13px;font-weight:600;text-decoration:none;white-space:nowrap;transition:background-color .15s,border-color .15s}
.btn:hover{background:var(--subtle)}.btn:active{transform:translateY(1px)}
.btn:focus-visible,a:focus-visible,summary:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.btn.primary{background:var(--accent);color:#fff;border-color:var(--accent)}.btn.primary:hover{background:var(--accent-strong)}
.btn.success{color:var(--ok);border-color:#a8d8b9}.btn.warn{color:var(--warn);border-color:#f0c48a}.btn.danger{color:var(--bad);border-color:#f3b1aa}
.btn:disabled{opacity:.55;cursor:not-allowed}
.help{width:24px;height:24px;border-radius:50%;border:1px solid var(--line);background:var(--surface);color:var(--muted);font-weight:700;cursor:pointer;font-size:12px;padding:0;margin-left:6px}
.msg{background:var(--accent-soft);border:1px solid #c9d7f7;border-radius:var(--r-card);padding:12px 16px;margin-bottom:16px;white-space:pre-wrap}
.info{background:var(--subtle);border:1px solid var(--line);border-radius:var(--r-ctl);padding:14px 16px;color:var(--muted)}
.muted{color:var(--muted);font-size:12.5px}
.tabs{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px}
.tabs a{padding:8px 14px;border-radius:var(--r-ctl);color:var(--muted);text-decoration:none;font-weight:600}
.tabs a:hover{background:var(--surface)}.tabs a.on{background:var(--surface);color:var(--accent);box-shadow:inset 0 0 0 1px var(--line)}
form.inline{display:inline-block;vertical-align:middle}
td .btn{margin:2px 0}
.row{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin:8px 0}
.field{margin-bottom:16px}.field>label.t{display:block;font-weight:700;margin-bottom:6px}
.chips label{display:inline-block;margin:0 6px 6px 0;padding:6px 12px;border:1px solid var(--line);border-radius:var(--r-ctl);background:var(--surface);cursor:pointer}
.chips label:has(input:checked){border-color:var(--accent);background:var(--accent-soft);color:var(--accent);font-weight:600}
input[type=number]{width:90px}input,textarea,select{font:inherit;padding:7px 9px;border:1px solid #cdd2da;border-radius:var(--r-ctl);background:var(--surface);color:var(--text)}
select:disabled{background:var(--subtle);color:var(--muted)}
dialog{border:none;border-radius:var(--r-card);max-width:560px;padding:22px 26px;box-shadow:0 12px 32px rgba(21,26,35,.22);line-height:1.6}
dialog h3{margin:0 0 10px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;align-items:stretch;margin-bottom:16px}
.grid>.card{margin-bottom:0}
.dashboard{align-items:start}
.dashboard>div{min-width:0}
.newsletter-preview{width:100%;height:680px;border:1px solid var(--line);border-radius:var(--r-ctl);background:var(--surface)}
.newsletter-file{overflow-wrap:anywhere;margin-bottom:12px}
.side{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:16px;align-items:start}
.sticky{position:sticky;top:16px}
@media (max-width:1000px){.grid,.side,.tiles{grid-template-columns:minmax(0,1fr)}main{padding:0 16px}header{padding:0 16px;gap:16px}}
.switch{position:relative;display:inline-block;width:48px;height:26px;vertical-align:middle;margin-right:8px}
.switch input{opacity:0;width:0;height:0}
.slider{position:absolute;cursor:pointer;inset:0;background:#c3c9d2;border-radius:26px;transition:background-color .2s}
.slider:before{content:"";position:absolute;height:20px;width:20px;left:3px;top:3px;background:#fff;border-radius:50%;transition:transform .2s}
.switch input:checked+.slider{background:var(--ok)}.switch input:checked+.slider:before{transform:translateX(22px)}
.switch input:focus-visible+.slider{outline:2px solid var(--accent);outline-offset:2px}
.steps{display:flex;gap:6px;align-items:stretch;margin-top:14px}
.step{flex:1;border:1px solid var(--line);border-radius:var(--r-ctl);padding:10px 12px;background:var(--subtle);color:var(--muted)}
.step b{display:block;color:var(--text);margin-bottom:2px}
.step.done{border-color:#bfe2cb;background:var(--ok-soft)}.step.fail{border-color:#f3c2bc;background:var(--bad-soft)}
.arrow{align-self:center;color:#9aa3b0}
.summary{font-size:15px;line-height:1.65}
.need{background:var(--warn-soft);border:1px solid #f0d3a8;border-radius:var(--r-ctl);padding:12px 14px;margin-top:12px}
.lock{background:var(--subtle);border:1px dashed #c3c9d2;border-radius:var(--r-ctl);padding:12px 14px;color:var(--muted)}
td.url{max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.search{width:300px;max-width:100%}
details.guide summary{cursor:pointer;font-weight:700;color:var(--accent)}
details.guide ol{margin:10px 0 0;padding-left:20px;line-height:1.8}
input[type=checkbox],input[type=radio]{width:18px;height:18px;vertical-align:-3px;accent-color:var(--accent)}
@media (max-width:640px){header{height:auto;flex-wrap:wrap;padding:10px 16px;gap:4px 16px}header nav{width:100%;flex-wrap:wrap;overflow:visible}header nav a{padding:8px 10px}main{margin-top:20px}.card{padding:16px}.steps{flex-direction:column}.arrow{transform:rotate(90deg);align-self:flex-start;margin-left:16px}.tile{padding:14px 16px}.card h2 .right{margin-left:0;width:100%}.search{width:100%}input[type=file]{max-width:100%}}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

MENU = [("/", "대시보드"), ("/test", "테스트"), ("/schedule", "예약 발송 설정"), ("/sources", "RSS Source"),
        ("/recipients", "수신자·그룹"), ("/logs", "실행 이력·뉴스레터"), ("/settings", "설정")]
RESULT_BADGE = {"성공": "b-ok", "성공 (발송 안 함)": "b-info", "부분 발송": "b-bad", "실패": "b-bad", "건너뜀": "b-warn",
                "진행 중": "b-mute"}
SEND_STATUS_BADGE = {"성공": "b-ok", "실패": "b-bad", "미시도": "b-warn", "불명확": "b-warn", "전송 중": "b-mute"}


def badge(text: str, cls: str) -> str:
    return f'<span class="badge {cls}">{escape(text)}</span>'


def page(title: str, body: str, message: str = "", refresh: bool = False, active: str = "/") -> str:
    links = "".join(f'<a href="{href}"{" class=on" if href == active else ""}>{label}</a>' for href, label in MENU)
    note = f'<div class="msg">{escape(message)}</div>' if message else ""
    meta = '<meta http-equiv="refresh" content="10">' if refresh else ""
    return (f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">{meta}'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)} · SABA 관리</title>'
            f'<style>{CSS}</style></head><body><header><div class="logo">SABA 관리</div><nav>{links}</nav></header>'
            f'<main><h1>{escape(title)}</h1>{note}{body.replace("<table", "<div class=tw><table").replace("</table>", "</table></div>")}</main></body></html>')


def button(app: AdminApp, action: str, label: str, style: str = "", back: str = "/", fields: dict | None = None) -> str:
    """style: primary(실행) · success(사용) · warn(외부 접속·중지) · danger(삭제) · 빈 값(보조)."""
    text = CONFIRM_TEXT.get(action)
    confirm = f' onsubmit="return confirm(\'{escape(text)}\')"' if text else ""  # 작은따옴표 없는 고정 문구만
    hidden = '<input type="hidden" name="confirm" value="yes">' if text else ""
    hidden += "".join(f'<input type="hidden" name="{escape(k)}" value="{escape(v)}">' for k, v in (fields or {}).items())
    return (f'<form method="post" action="/action/{action}" class="inline"{confirm}>'
            f'<input type="hidden" name="token" value="{app.token}"><input type="hidden" name="back" value="{escape(back)}">{hidden}'
            f'<button class="btn {style}">{escape(label)}</button></form>')


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


STEP_NAMES = (("RSS 수집", "기사 수집"), ("메일 생성", "메일 만들기"), ("발송", "발송"))


def run_sentence(run) -> str:
    """마지막 실행을 한 문장으로 (D-073)."""
    head = f"{run.start[5:10].replace('-', '/')} {run.start[11:16]} {run.origin}"
    if run.result == "진행 중":
        return f"{head}: 실행 중입니다."
    if run.result == "건너뜀":
        return f"{head}: 다른 실행이 진행 중이라 건너뛰었습니다."
    if run.result == "부분 발송":
        return f"{head}: 일부만 보냈습니다. 발송 이력에서 실패한 사람을 확인하세요."
    if run.result == "실패":
        if "불명확" in run.error:
            return f"{head}: {run.error}. 발송 이력과 받은 편지함을 확인하세요."
        return f"{head}: {run.error} 때문에 발송하지 않았습니다."
    if run.result == "성공 (발송 안 함)":
        return f"{head}: 기사 {run.articles}건으로 메일을 만들었습니다 (발송 안 함 설정)."
    return f"{head}: 기사 {run.articles}건으로 메일을 만들어 TEST 1명에게 보냈습니다."


def run_steps(run) -> str:
    """기사 수집 → 메일 만들기 → 발송 진행 막대."""
    by_name = {}
    for name, clock, result, detail in run.stages:
        key = "메일 생성" if "메일" in name or "분석" in name else name
        by_name[key] = (clock, result, detail)
    boxes = []
    failed = False
    for key, label in STEP_NAMES:
        clock, result, detail = by_name.get(key, ("", "", ""))
        if result == "실패":
            cls, text, failed = "fail", f"실패 {clock}", True
        elif result in ("완료", "안 함"):
            cls, text = "done", f"{'완료' if result == '완료' else '발송 안 함'} {clock}"
        else:
            cls, text = "", "안 함" if failed or run.closed else "대기"
        extra = ""
        if key == "메일 생성" and run.articles is not None and result == "완료":
            extra = f" · 기사 {run.articles}건"
        if key == "발송" and result == "완료":
            extra = " · TEST 1명"
        boxes.append(f'<div class="step {cls}"><b>{len(boxes) + 1}. {label}</b>{escape(text + extra)}</div>')
    return '<div class="steps">' + '<div class="arrow">&rarr;</div>'.join(boxes) + "</div>"


def task_switch(app: AdminApp, on: bool, back: str = "/") -> str:
    return (f'<form method="post" action="/action/task_state" class="row" style="margin:0 0 12px">'
            f'<input type="hidden" name="token" value="{app.token}"><input type="hidden" name="back" value="{back}">'
            f'<input type="hidden" name="state" value="{"on" if on else "off"}">'
            f'<label class="switch"><input type="checkbox"{" checked" if on else ""} onchange="var on=this.checked;'
            f"if(confirm(on?'예약 발송을 켤까요?':'예약 발송을 끌까요? 꺼져 있는 동안 정해진 시각에 발송하지 않습니다.'))"
            f"{{this.form.state.value=on?'on':'off';this.form.submit()}}else{{this.checked=!on}}\">"
            f'<span class="slider"></span></label><b>{"켜짐" if on else "꺼짐"}</b></form>')


def dashboard(app: AdminApp) -> str:
    from saba.daily import next_runs
    config, task, use, runs = app.config(), app.task(), app.usage(), app.runs()
    now = datetime.now().astimezone()
    real_today = app.real_runs_today()
    on = task.get("state") in ("Ready", "Running", "Enabled")
    task_unknown = task.get("state") not in ("Ready", "Running", "Enabled", "Disabled", "등록 안 됨")
    upcoming = next_runs(config, now, 3)
    running = app.running()
    sent = next((r for r in real_today if r.sent), None)
    need = app.send_needed()
    recent = app.recent_articles()
    enabled_sources = sum(1 for e in app.source_entries() if e.enabled)

    tile_task = (badge("켜짐", "b-ok") if on else badge("꺼짐", "b-mute")) + (
        f'<div class="s">다음 예약 {escape(kst_label(upcoming[0]))}</div>' if on and upcoming else '<div class="s">예약 발송이 꺼져 있습니다</div>')
    if task_unknown:
        tile_task = badge("확인 불가", "b-warn") + '<div class="s">예약 발송 상태를 확인하지 못했습니다.</div>'
    if running:
        today_state, today_sub = badge("실행 중", "b-info"), "끝나면 결과가 표시됩니다"
    elif sent and sent.result == "부분 발송":
        today_state, today_sub = badge(f"{sent.start[11:16]} 부분 발송", "b-bad"), "실행 이력·뉴스레터의 발송 이력에서 확인"
    elif sent:
        today_state, today_sub = badge(f"{sent.start[11:16]} 발송 완료", "b-ok"), escape(sent.origin)
    elif any("불명확" in r.error for r in real_today):
        today_state, today_sub = badge("발송 여부 불명확", "b-warn"), "발송 이력과 받은 편지함을 확인하세요"
    elif need:
        today_state, today_sub = badge("발송 안 됨", "b-bad"), "아래 \"지금 발송\" 으로 보낼 수 있습니다"
    else:
        today_state, today_sub = badge("예약 대기", "b-mute"), escape(f"오늘 {config.time} 예정" if upcoming and upcoming[0].date() == now.date() else "오늘은 예약 없음")
    tiles = (f'<div class="tiles"><div class="tile"><div class="k">예약 발송</div><div class="v">{tile_task}</div></div>'
             f'<div class="tile"><div class="k">오늘 뉴스레터</div><div class="v">{today_state}</div><div class="s">{today_sub}</div></div>'
             f'<div class="tile"><div class="k">이번 달 AI 비용</div><div class="v">${use["cost"]:.3f} / ${use["limit"]:.0f}</div>'
             f'<div class="s">호출 {use["calls"]}건 (성공 {use["ok"]} · 실패 {use["failed"]})</div></div>'
             f'<div class="tile"><div class="k">최근 24시간 수집 기사</div><div class="v">{"-" if recent is None else recent}건</div>'
             f'<div class="s">사용 중인 RSS Source {enabled_sources}곳</div></div></div>')

    last = runs[0] if runs else None
    body = (f'<div class="summary">{escape(run_sentence(last))}</div>{run_steps(last)}' if last
            else '<p class="muted">아직 실행 기록이 없습니다.</p>')
    if running:
        body += '<p class="muted" style="margin-top:12px">실행 중입니다. 10초마다 화면이 새로 고침됩니다.</p>'
    elif need:
        body += (f'<div class="need"><b>오늘 뉴스레터가 발송되지 않았습니다.</b><br>{escape(need)}<br><br>'
                 + button(app, "run_send", "지금 발송", "primary")
                 + ' <span class="muted">RSS 수집 → AI 분석 (하루 상한 안) → 메일 생성 → TEST 1명 발송</span></div>')
    today_card = (f'<div class="card"><h2>마지막 실행{" " + badge(last.result, RESULT_BADGE.get(last.result, "b-mute")) if last else ""}'
                  f'<a class="btn right" href="/logs">전체 이력</a></h2>{body}</div>')

    if on:
        upcoming_rows = "".join(f"<li>{escape(kst_label(at))}</li>" for at in upcoming) or "<li>예정 없음</li>"
        schedule_body = (f'<table><tr><th>일정</th><td>{escape(schedule_summary(config))}</td></tr>'
                         f'<tr><th>다음 예약</th><td><ul style="margin:0;padding-left:18px">{upcoming_rows}</ul></td></tr>'
                         f'<tr><th>발송</th><td>{"TEST 1명에게 발송" if config.send else "메일 생성까지만"}</td></tr></table>')
    elif task_unknown:
        schedule_body = '<div class="info">예약 발송 상태를 확인하지 못했습니다. 예약 설정과 작업 스케줄러 접근 권한을 확인하세요.</div>'
    else:
        schedule_body = (f'<div class="info"><b>예약 발송 꺼져 있습니다</b><br>정해진 시각에 뉴스레터를 보내지 않습니다. '
                         f'스위치를 켜면 저장된 일정 ({escape(schedule_summary(config))}) 으로 다시 발송합니다.</div>')
    schedule_card = (f'<div class="card"><h2>예약 발송<a class="btn right" href="/schedule">설정 변경</a></h2>'
                     f'{"" if task_unknown else task_switch(app, on)}{schedule_body}</div>')

    status_rows = [
        ("이번 달 AI 호출", f'{use["calls"]}건 (성공 {use["ok"]} · 실패 {use["failed"]})'),
        ("이번 달 AI 비용", f'${use["cost"]:.4f} / 상한 ${use["limit"]:.2f}'),
        ("하루 AI 호출 상한", f"분석 {config.max_analysis_calls}건 · 시사점 {config.max_insight_calls}건"),
        ("발송 대상", "TEST 주소 1명 (그룹 발송 잠금)"),
        ("작업 스케줄러", f'{task.get("state", "-")} · 마지막 결과 코드 {task.get("result", "-") or "-"}'),
    ]
    status_card = ('<div class="card"><h2>운영 현황</h2><table>'
                   + "".join(f"<tr><th style='width:160px'>{escape(a)}</th><td>{escape(b)}</td></tr>" for a, b in status_rows)
                   + "</table></div>")
    recent_rows = "".join(f"<tr><td style='white-space:nowrap'>{escape(r.start[5:16])}</td><td>{escape(r.origin)}</td>"
                          f"<td>{badge(r.result, RESULT_BADGE.get(r.result, 'b-mute'))}</td></tr>" for r in runs[:5])
    recent_card = ('<div class="card"><h2>최근 실행<a class="btn right" href="/logs">더 보기</a></h2>'
                   f'<table><tr><th>시각</th><th>실행 주체</th><th>결과</th></tr>{recent_rows or "<tr><td colspan=3>기록 없음</td></tr>"}</table></div>')
    return (tiles + f'<div class="grid dashboard"><div>{today_card}{schedule_card}{recent_card}{status_card}</div>'
            + today_newsletter(app, real_today) + '</div>')


def today_newsletter(app: AdminApp, runs: list) -> str:
    sent = next((run for run in runs if run.sent), None)
    body = '<p class="muted">오늘 보내진 뉴스레터가 없습니다.</p>'
    if sent is not None:
        body = (f'<p>{badge(sent.result, RESULT_BADGE.get(sent.result, "b-mute"))} '
                f'{escape(sent.start[11:16])} · {escape(sent.origin)}</p>')
        name = sent.mail_file
        if name and re.fullmatch(r"daily_[\w-]+\.eml", name) and (app.root / "output" / name).is_file():
            body += (f'<div class="newsletter-file"><a class="btn" href="/logs?tab=mail&name={quote(name)}">뉴스레터 열기</a> '
                     f'<span class="muted">{escape(name)}</span></div>'
                     f'<iframe class="newsletter-preview" title="오늘 보내진 뉴스레터 미리보기" '
                     f'src="/newsletter/view?name={quote(name)}" loading="lazy" sandbox="allow-popups"></iframe>')
        else:
            body += '<p class="muted">발송 기록은 있으나 메일 파일이 없습니다. 보관 기간과 파일 경로를 확인하세요.</p>'
    elif any("불명확" in run.error for run in runs):
        body = '<p class="info">발송 여부가 불명확합니다. 발송 이력과 받은 편지함을 먼저 확인하세요.</p>'
    elif runs:
        latest = runs[0]
        if latest.result == "성공 (발송 안 함)":
            body = '<p class="muted">오늘 메일은 생성했지만 발송하지 않았습니다.</p>'
        elif latest.result == "실패":
            body = '<p class="muted">오늘 실행이 실패했으며 확인된 발송 성공 기록이 없습니다.</p>'
        elif latest.result == "진행 중":
            body = '<p class="muted">실행 중입니다. 발송 결과가 확인되면 표시합니다.</p>'
    return f'<section class="card"><h2>오늘 보내진 뉴스레터</h2>{body}</section>'


def test_page(app: AdminApp) -> str:
    """테스트 발송·점검 도구 (D-073)."""
    from saba.history import load_runs
    now = datetime.now()
    pending = app.test_task()
    running = app.running()
    if running:
        now_body = '<p>지금 실행 중입니다. 10초마다 새로 고침되며, 끝나면 아래 기록에 결과가 나옵니다.</p>'
    else:
        now_body = ('<p class="muted">지금 바로 RSS 수집 → AI 분석 (하루 상한 안) → 메일 생성 → TEST 1명 발송을 합니다. '
                    '오늘 이미 발송했어도 보냅니다. 평소 예약 발송과는 별개로 기록됩니다.</p>'
                    + button(app, "test_now", "즉시 테스트 발송", "primary", back="/test"))
    scheduled = ""
    if pending.get("next"):
        scheduled = (f'<div class="need">예약된 테스트 발송: <b>{escape(pending["next"])}</b> '
                     + button(app, "test_cancel", "예약 취소", "danger", back="/test") + "</div>")
    default_at = (now + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M")
    schedule_body = (f'<form method="post" action="/action/test_schedule" class="row" '
                     f'onsubmit="return confirm(\'{escape(CONFIRM_TEXT["test_schedule"])}\')">'
                     f'<input type="hidden" name="token" value="{app.token}"><input type="hidden" name="back" value="/test">'
                     f'<input type="hidden" name="confirm" value="yes">'
                     f'<label>발송 시각 <input type="datetime-local" name="at" value="{default_at}" min="{now:%Y-%m-%dT%H:%M}" required></label>'
                     f'<button class="btn primary">이 시각에 테스트 발송</button></form>'
                     '<p class="muted">작업 스케줄러에 1회용 테스트 작업으로 등록합니다. 오늘 이미 발송했어도 보내며, 평소 예약 발송 일정은 바뀌지 않습니다. '
                     '정한 시각에 PC 가 켜져 있고 로그인되어 있어야 합니다.</p>' + scheduled)
    tests = [r for r in load_runs(app.root / "logs") if r.origin.startswith("테스트")]
    rows = "".join(
        f"<tr><td style='white-space:nowrap'>{escape(r.start[:16])}</td><td>{'즉시' if '즉시' in r.origin else '예약'}</td>"
        f"<td>{badge(r.result, RESULT_BADGE.get(r.result, 'b-mute'))}</td><td>{'-' if r.articles is None else r.articles}</td>"
        f"<td>{escape(r.mail_bytes or '-')}</td><td>{'발송' if r.sent else '-'}</td><td>{escape(r.error) or '-'}</td>"
        f"<td>{f'<a class=btn href=/logs?tab=mail&name={quote(r.mail_file)}>메일 보기</a>' if r.mail_file else ''}</td></tr>" for r in tests)
    history = ('<div class="card"><h2>테스트 발송 기록</h2><table><tr><th>시각</th><th>종류</th><th>결과</th><th>기사</th>'
               f'<th>메일 크기 (bytes)</th><th>발송</th><th>실패 사유</th><th></th></tr>{rows or "<tr><td colspan=8>아직 테스트 발송 기록이 없습니다.</td></tr>"}</table></div>')
    tool_rows = "".join(
        f"<tr><td>{escape(name)}{help_button(key, name, body)}</td>"
        f"<td>{badge('외부 접속 있음', 'b-warn') if external == '있음' else badge('외부 접속 없음', 'b-mute')}</td>"
        f"<td>{button(app, key, '실행', 'warn' if external == '있음' else '', back='/test')}</td></tr>" for key, name, external, body in TOOLS)
    tools = ('<div class="card"><h2>점검 도구<span class="muted">문제가 생겼을 때 원인을 찾는 도구입니다. ? 를 누르면 설명이 나옵니다.</span></h2>'
             f'<table><tr><th>도구</th><th>외부 접속</th><th style="width:90px">실행</th></tr>{tool_rows}</table></div>')
    return (f'<div class="grid"><div class="card"><h2>즉시 테스트 발송</h2>{now_body}</div>'
            f'<div class="card"><h2>시각 지정 테스트 발송</h2>{schedule_body}</div></div>' + history + tools)


def target_field(config) -> str:
    """발송 대상 그룹 (D-076). 그룹 발송 잠금이 꺼져 있으면 TEST 주소 1명으로 고정하고 선택을 막는다."""
    from saba import recipients as rc
    from saba.send_mail import GROUP_SEND_APPROVED, TEST_ADDRESS
    names = [g for g, _ in rc.groups()] if GROUP_SEND_APPROVED else []
    if not GROUP_SEND_APPROVED:
        return (f'<input type="hidden" name="target_group" value="{escape(config.target_group)}">'
                f'<div class="lock"><b>TEST 주소 1명 ({escape(TEST_ADDRESS)}) 으로 잠금</b><br>'
                '그룹 발송 (수신자마다 1통 개별 발송) 은 만들어 두었지만, 회사 IT·보안 정책 확인과 별도 승인 전까지 잠겨 있습니다. '
                '수신자·그룹은 미리 등록해 둘 수 있습니다.</div>')
    options = "".join(f'<option{" selected" if g == config.target_group else ""}>{escape(g)}</option>' for g in names)
    return f'<select name="target_group">{options}</select> <span class="muted">수신자마다 1통씩 개별 발송합니다.</span>'


def schedule_page(app: AdminApp) -> str:
    """예약 발송 설정 (D-072, 배치 정리 D-074): 왼쪽 입력, 오른쪽 현재 일정·다음 예약."""
    from saba.daily import next_runs
    config = app.config()
    days = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    mode_radios = "".join(f'<label><input type="radio" name="mode" value="{m}"{" checked" if config.mode == m else ""} onchange="showMode()"> {label}</label>'
                          for m, label in MODE_LABEL.items())
    weekday_boxes = "".join(f'<label><input type="checkbox" name="weekdays" value="{d}"{" checked" if d in config.weekdays else ""}> {DAY_LABEL[d]}</label>' for d in days)
    month_boxes = "".join(f'<label><input type="checkbox" name="month_days" value="{d}"{" checked" if d in config.month_days else ""}> {d}</label>' for d in range(1, 32))
    per_day = config.max_analysis_calls + config.max_insight_calls
    form = f"""
<form method="post" action="/action/save_schedule" onsubmit="return confirm('{escape(CONFIRM_TEXT['save_schedule'])}')">
<input type="hidden" name="token" value="{app.token}"><input type="hidden" name="back" value="/schedule"><input type="hidden" name="confirm" value="yes">
<div class="card"><h2>주기</h2>
 <div class="field"><div class="chips">{mode_radios}</div></div>
 <div id="m-weekly" class="field"><label class="t">요일</label><div class="chips">{weekday_boxes}</div></div>
 <div id="m-monthly" class="field"><label class="t">매월 날짜</label><div class="chips">{month_boxes}</div>
  <div class="muted">그 달에 없는 날짜 (예: 31일) 는 건너뜁니다.</div></div>
 <div id="m-dates" class="field"><label class="t">특정 날짜</label>
  <div class="row"><input type="date" id="pick" aria-label="추가할 날짜"> <button type="button" class="btn" onclick="addDate()">날짜 추가</button></div>
  <textarea name="dates" id="dates" aria-label="특정 날짜 목록" rows="4" cols="30" placeholder="한 줄에 하나 (예: 2026-10-20)">{escape(chr(10).join(config.dates))}</textarea>
  <div class="muted">지난 날짜는 무시됩니다. 줄을 지우면 날짜가 빠집니다.</div></div>
</div>
<div class="card"><h2>시각</h2>
 <div class="row"><label>발송 시각 <input type="time" name="time" value="{escape(config.time)}" required></label>
 <label>무작위 지연 최대 <input type="number" name="random_delay_minutes" min="0" max="30" value="{config.random_delay_minutes}"> 분</label></div>
 <div class="muted">무작위 지연: 정해진 시각부터 이 시간 안에서 아무 때나 실행합니다 (0 이면 정각).</div>
</div>
<div class="card"><h2>AI 호출과 발송</h2>
 <div class="row"><label>하루 AI 분석 상한 <input type="number" name="max_analysis_calls" min="0" max="50" value="{config.max_analysis_calls}"> 건</label>
 <label>하루 AI 시사점 상한 <input type="number" name="max_insight_calls" min="0" max="50" value="{config.max_insight_calls}"> 건</label></div>
 <div class="muted">현재 하루 최대 {per_day}건 · 매일 발송해도 한 달 최대 약 ${per_day * COST_PER_CALL * 31:.2f} (월 상한 $3, 변경 불가). 하루 상한은 같은 날의 예약·지금·테스트 실행이 함께 씁니다. 이미 분석한 기사는 다시 호출하지 않습니다.</div>
 <div class="row"><label><input type="radio" name="send" value="on"{" checked" if config.send else ""}> 예약 시각에 발송</label>
 <label><input type="radio" name="send" value="off"{"" if config.send else " checked"}> 메일 생성까지만 (발송 안 함)</label></div>
</div>
<div class="card"><h2>발송 대상</h2>{target_field(config)}</div>
<div class="card"><h2>보관 기간</h2>
 <div class="row"><label>실행 로그 <input type="number" name="log_days" min="7" max="3650" value="{config.log_days}"> 일</label>
 <label>메일 파일 <input type="number" name="mail_days" min="1" max="3650" value="{config.mail_days}"> 일</label></div>
 <div class="muted">기간이 지난 실행 로그·메일 파일은 매일 실행 때 자동으로 지웁니다.</div>
</div>
<div style="margin-bottom:24px"><button class="btn primary">저장</button> <span class="muted">주기·시각·지연이 바뀌면 작업 스케줄러에 다시 등록합니다.</span></div>
</form>
<script>
function showMode(){{var m=(document.querySelector('input[name=mode]:checked')||{{}}).value;
 ['weekly','monthly','dates'].forEach(function(k){{document.getElementById('m-'+k).style.display=(m===k)?'':'none'}});}}
function addDate(){{var v=document.getElementById('pick').value;if(!v)return;var t=document.getElementById('dates');
 var list=t.value.split(/\\s+/).filter(Boolean);if(list.indexOf(v)<0)list.push(v);list.sort();t.value=list.join('\\n');}}
showMode();
</script>"""
    upcoming = "".join(f"<tr><td>{i}</td><td>{escape(kst_label(at))}</td></tr>" for i, at in enumerate(next_runs(config, datetime.now().astimezone(), 5), 1))
    side = (f'<div class="card sticky"><h2>현재 일정</h2><div class="summary">{escape(schedule_summary(config))}</div>'
            f'<h2 style="margin-top:16px">다음 예약 5회</h2><table><tr><th style="width:50px">순서</th><th>시각 (무작위 지연 전)</th></tr>'
            f'{upcoming or "<tr><td colspan=2>예정 없음</td></tr>"}</table>'
            '<p class="muted">시각을 정해 한 번만 확인하려면 테스트 화면의 "시각 지정 테스트 발송" 을 쓰세요 (이 일정은 바뀌지 않음).</p></div>')
    return f'<div class="side"><div>{form}</div><div>{side}</div></div>'


LOG_TABS = (("runs", "실행 이력"), ("sends", "발송 이력"), ("mail", "뉴스레터"), ("detail", "상세 로그"), ("changes", "설정 변경 이력"))


def list_filters(query: dict, years: set[str], *, mail: bool = False) -> tuple[dict, str]:
    now = datetime.now().astimezone()
    state = {"tab": "mail" if mail else "runs", "year": _first(query, "year") or (str(now.year) if mail else "all"),
             "q": _first(query, "q").strip()}
    errors = []
    if state["year"] != "all" and not re.fullmatch(r"[0-9]{4}", state["year"]):
        errors.append("연도 필터가 올바르지 않습니다.")
        state["year"] = str(now.year) if mail else "all"
    if state["year"] == "0000":
        errors.append("연도 필터가 올바르지 않습니다.")
        state["year"] = str(now.year) if mail else "all"
    if mail:
        state["month"] = _first(query, "month") or f"{now.month:02}"
        if state["month"] != "all" and state["month"] not in {f"{m:02}" for m in range(1, 13)}:
            errors.append("월 필터가 올바르지 않습니다.")
            state["month"] = f"{now.month:02}"
    else:
        for key in ("start", "end"):
            state[key] = _first(query, key)
            try:
                if state[key]:
                    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", state[key]):
                        raise ValueError
                    datetime.strptime(state[key], "%Y-%m-%d")
            except ValueError:
                errors.append("기간 필터가 올바르지 않습니다.")
                state[key] = ""
        if state["start"] and state["end"] and state["start"] > state["end"]:
            errors.append("시작 날짜가 종료 날짜보다 늦어 기간을 초기화했습니다.")
            state["start"] = state["end"] = ""
    if len(state["q"]) > 200:
        errors.append("검색어는 200자 이내로 입력하세요. 검색을 초기화했습니다.")
        state["q"] = ""
    years = (years | {str(now.year), state["year"]}) - {"all"}
    options = '<option value="all"' + (' selected' if state["year"] == "all" else '') + '>전체 연도</option>'
    options += "".join(f'<option value="{escape(y)}"{" selected" if state["year"] == y else ""}>{escape(y)}년</option>' for y in sorted(years, reverse=True))
    fields = f'<label>연도 <select name="year">{options}</select></label>'
    if mail:
        months = '<option value="all"' + (' selected' if state["month"] == "all" else '') + '>전체 월</option>'
        months += "".join(f'<option value="{m:02}"{" selected" if state["month"] == f"{m:02}" else ""}>{m}월</option>' for m in range(1, 13))
        fields += f'<label>월 <select name="month">{months}</select></label>'
    else:
        fields += ''.join(f'<label>{label} <input type="date" name="{key}" value="{escape(state[key], quote=True)}"></label>' for key, label in (("start", "시작"), ("end", "종료")))
    hint = "파일명·종류·실행 주체" if mail else "날짜·실행 주체·결과·메일명"
    fields += f'<label>검색 <input type="search" name="q" maxlength="200" value="{escape(state["q"], quote=True)}" placeholder="{hint}"></label>'
    form = (f'<form method="get" action="/logs" class="row"><input type="hidden" name="tab" value="{state["tab"]}">{fields}'
            '<button class="btn">적용</button></form>')
    return state, ''.join(f'<p class="info">{escape(e)}</p>' for e in errors) + form


def list_page(items: list, query: dict, state: dict, *, unit: str) -> tuple[list, str, dict]:
    pages = max(1, (len(items) + 24) // 25)
    raw = _first(query, "page") or "1"
    valid = bool(re.fullmatch(r"[0-9]{1,8}", raw)) and int(raw) >= 1
    number = min(int(raw), pages) if valid else 1
    warning = '<p class="info">페이지 값이 범위를 벗어나 조정했습니다.</p>' if not valid or int(raw) > pages else ''
    context = {**state, "page": str(number)}
    links = ''
    for label, target in (("이전", number - 1), ("다음", number + 1)):
        if 1 <= target <= pages:
            links += f'<a class="btn" href="/logs?{escape(urlencode({**state, "page": target}), quote=True)}">{label}</a> '
        else:
            links += f'<button class="btn" disabled>{label}</button> '
    nav = warning + f'<nav class="row" aria-label="목록 페이지"><span>총 {len(items)}{unit} · {number} / {pages} 페이지</span>{links}</nav>'
    return items[(number - 1) * 25:number * 25], nav, context


def logs_page(app: AdminApp, tab: str, day: str | None, name: str | None = None, query: dict | None = None) -> str:
    """실행 이력·뉴스레터 (D-074 합침): 탭 실행 이력 · 뉴스레터 · 상세 로그 · 설정 변경 이력."""
    from saba.history import log_files, read_changes, read_log, storage_status
    config = app.config()
    store = storage_status(app.root)
    tabs = "".join(f'<a href="/logs?tab={key}"{" class=on" if tab == key else ""}>{label}</a>' for key, label in LOG_TABS)
    keep = (f'<div class="muted" style="margin-bottom:12px">보관: 실행 로그 {config.log_days}일 (현재 {store["logs"]["count"]}개 파일 · '
            f'{store["logs"]["bytes"] / 1024:.1f} KB · 가장 오래된 날짜 {store["logs"]["oldest"]}) · 메일 파일 {config.mail_days}일 '
            f'(현재 {store["mails"]["count"]}개 · {store["mails"]["bytes"] / 1024 / 1024:.2f} MB). 기간이 지나면 매일 실행 때 자동 삭제.</div>')
    if tab == "sends":
        return f'<div class="tabs">{tabs}</div><div class="card tabbody">{sends_body(app, day)}</div>'
    if tab == "mail":
        return f'<div class="tabs">{tabs}</div><div class="card tabbody">{keep}{newsletter_body(app, name, query)}</div>'
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
        runs = sorted(app.runs(), key=lambda r: r.start, reverse=True)
        state, picker = list_filters(query or {}, {r.start[:4] for r in runs})
        grouped = {}
        for run in runs:
            grouped.setdefault(run.start[:10], []).append(run)
        needle = state["q"].casefold()
        days = [d for d, group in grouped.items() if (state["year"] == "all" or d[:4] == state["year"])
                and (not state["start"] or d >= state["start"]) and (not state["end"] or d <= state["end"])
                and any(needle in ' '.join((r.start, r.origin, r.result, r.mail_file or '')).casefold() for r in group)]
        days, nav, _ = list_page(days, query or {}, state, unit="일")
        rows = ""
        for date in days:
            detail = ""
            group = grouped[date]
            counts = ' · '.join(f'{escape(result)} {sum(r.result == result for r in group)}회' for result in sorted({r.result for r in group}))
            for run in group:
                day_key = run.start[:10].replace("-", "")
                mail = f"<a class='btn' href='/logs?tab=mail&name={quote(run.mail_file)}'>메일</a> " if run.mail_file else ""
                stages = ''.join(f'<li>{escape(stage)} · {escape(clock)} · {escape(result)} · {escape(text)}</li>' for stage, clock, result, text in run.stages)
                detail += (f"<tr><td style='white-space:nowrap'>{escape(run.start[:16])}</td><td>{escape(run.origin)}</td>"
                     f"<td>{badge(run.result, RESULT_BADGE.get(run.result, 'b-mute'))}</td>"
                     f"<td>{'-' if run.articles is None else run.articles}</td><td>{'-' if run.ai_calls is None else run.ai_calls}</td>"
                     f"<td>{escape(run.mail_bytes or '-')}</td><td>{'발송' if run.sent else '-'}</td>"
                      f"<td>{escape(run.error) or '-'}</td><td>{mail}<a class='btn' href='/logs?tab=detail&day={day_key}'>로그</a>"
                      f"<details><summary>진행 단계</summary><ul>{stages or '<li>단계 기록 없음</li>'}</ul></details></td></tr>")
            rows += (f'<details class="guide"><summary>{escape(date)} · {len(group)}회 · {counts}</summary><div class="tw">'
                     '<table><tr><th>시작</th><th>실행 주체</th><th>결과</th><th>기사</th><th>AI 신규 호출</th><th>메일 크기 (bytes)</th>'
                     f'<th>발송</th><th>실패 사유</th><th>보기</th></tr>{detail}</table></div></details>')
        body = picker + '<p class="muted">검색에 맞는 실행이 있는 날짜를 표시하며, 상세에는 그 날짜의 모든 실행을 보존합니다. 발송 회차와 재발송 관계는 발송 이력 탭에서 확인하세요.</p>' + nav + (rows or '<p>조건에 맞는 실행 기록이 없습니다.</p>')
    return f'<div class="tabs">{tabs}</div><div class="card tabbody">{keep}{body}</div>'


def sends_body(app: AdminApp, selected: str | None) -> str:
    """발송 이력 (D-076, D-077): 회차별 결과 구분, 회차를 고르면 수신자별 결과와 실패 재발송. 주소는 이 화면에만."""
    from saba import sendlog
    from saba.send_mail import GROUP_SEND_APPROVED
    path = app.root / "data" / "send_history.db"
    rows = ""
    rounds = sendlog.sends(path)
    for send in rounds:
        counts = " ".join(badge(f"{name} {n}", SEND_STATUS_BADGE.get(name, "b-mute")) for name, n in sorted(send.counts.items()) if n)
        origin = escape(send.origin) + (f" <span class=muted>(회차 {send.parent_id} 재발송)</span>" if send.parent_id else "")
        rows += (f"<tr><td style='white-space:nowrap'>{send.id}</td><td style='white-space:nowrap'>{escape(send.at[:16])}</td>"
                 f"<td>{origin}</td><td>{escape(send.target)}</td><td>{send.total}명</td><td>{counts or '-'}</td>"
                 f"<td style='white-space:nowrap'>{'<a class=btn href=/logs?tab=mail&name=' + quote(send.mail_file) + '>메일</a> ' if send.mail_file else ''}"
                 f"<a class='btn' href='/logs?tab=sends&day={send.id}'>수신자별 결과</a></td></tr>")
    body = ('<p class="muted" style="margin-top:0">결과 구분: 성공 (서버가 받음) · 실패 (서버가 거부) · 미시도 (보내지 않음) · '
            '불명확 (보내는 도중 끊김, 받았을 수도 있어 받은 편지함 확인 필요, 재발송 대상 아님). 주소는 이 화면에서만 보입니다.</p>'
            '<table><tr><th>회차</th><th>시각</th><th>실행 주체</th><th>대상</th><th>인원</th><th>결과</th><th>보기</th></tr>'
            f'{rows or "<tr><td colspan=7>아직 발송 이력이 없습니다. 다음 발송부터 쌓입니다.</td></tr>"}</table>')
    if selected and selected.isdigit():
        send_id = int(selected)
        detail = "".join(f"<tr><td>{escape(r.email)}</td><td>{badge(r.status, SEND_STATUS_BADGE.get(r.status, 'b-mute'))}</td>"
                         f"<td>{escape(r.detail)}</td></tr>" for r in sendlog.results(send_id, path))
        targets = sendlog.resend_targets(send_id, path)
        if any(r.id == send_id and r.target == "TEST 주소" for r in rounds):
            resend = '<p class="muted">TEST 주소 회차는 재발송 대상이 아닙니다. 테스트 화면의 즉시 테스트 발송을 쓰세요.</p>'
        elif not targets:
            resend = '<p class="muted">다시 보낼 사람 (실패·미시도) 이 없습니다.</p>'
        elif not GROUP_SEND_APPROVED:
            resend = (f'<div class="lock">실패·미시도 {len(targets)}명. 그룹 발송 잠금 중에는 재발송할 수 없습니다 '
                      '(TEST 주소로 대신 보내지 않음).</div>')
        else:
            resend = (button(app, "resend_failed", f"실패한 {len(targets)}명만 다시 보내기", "primary", back="/logs",
                             fields={"id": str(send_id)})
                      + ' <span class="muted">원본 메일 파일을 그대로 다시 씁니다. 성공·불명확한 사람은 보내지 않습니다.</span>')
        body += (f'<h2 style="margin-top:22px">회차 {send_id} 수신자별 결과</h2>{resend}'
                 f'<table style="margin-top:10px"><tr><th>메일</th><th>결과</th><th>내용</th></tr>'
                 f'{detail or "<tr><td colspan=3>결과가 없습니다.</td></tr>"}</table>')
    return body


def _show(value) -> str:
    if isinstance(value, bool):
        return "발송" if value else "발송 안 함"
    if isinstance(value, list):
        return ", ".join(DAY_LABEL.get(str(v), str(v)) for v in value) or "(없음)"
    return MODE_LABEL.get(str(value), str(value))


def newsletter_body(app: AdminApp, name: str | None, query: dict | None = None) -> str:
    files = app.mail_files()
    state, picker = list_filters(query or {}, {f["made"][:4] for f in files}, mail=True)
    needle = state["q"].casefold()
    filtered = [f for f in files if (state["year"] == "all" or f["made"][:4] == state["year"])
                and (state["month"] == "all" or f["made"][5:7] == state["month"])
                and needle in ' '.join((f["name"], f["kind"], f["origin"])).casefold()]
    shown, nav, context = list_page(filtered, query or {}, state, unit="개")
    kind_badge = {"발송본": "b-ok", "생성만 (발송 안 함)": "b-info", "미리보기": "b-warn"}
    rows = "".join(f"<tr><td><a class='btn' href='/logs?{escape(urlencode({**context, 'name': f['name']}), quote=True)}'>{escape(f['name'])}</a></td>"
                   f"<td>{badge(f['kind'], kind_badge.get(f['kind'], 'b-mute'))}</td><td>{escape(f['made'])}</td>"
                   f"<td>{escape(f['origin'])}</td><td>{f['size'] / 1024:.0f} KB</td></tr>" for f in shown)
    requested = name
    name = name if name in {f["name"] for f in files} else (shown[0]["name"] if shown and not requested else None)
    guide = ('<div class="muted" style="margin-bottom:10px">발송본: 실제로 TEST 수신자에게 보낸 메일 · 생성만: 만들었지만 보내지 않은 메일 · '
             '미리보기: 점검 도구 "미리보기 다시 만들기" 로 만든 확인용 (최신 1개만 보관). 메일은 만든 시각 기준 최근 24시간 (월요일 72시간) 기사로 '
             '구성되므로 만든 시각이 다르면 기사 구성이 다릅니다.</div>')
    note = '<p class="info">선택한 메일은 현재 목록 조건 밖의 파일입니다.</p>' if name and name not in {f["name"] for f in shown} else ''
    frame = (f'{note}<h2 style="margin-top:18px">{escape(name)}</h2><iframe title="선택한 뉴스레터 미리보기" sandbox="allow-popups" src="/newsletter/view?name={quote(name)}" style="width:100%;height:900px;border:1px solid var(--line);border-radius:8px"></iframe>'
             if name else "<p>선택한 메일 파일이 없거나 허용되지 않는 이름입니다.</p>" if requested else "<p>조건에 맞는 메일 파일이 없습니다.</p>")
    return (f'{guide}{picker}{nav}<table><tr><th>파일</th><th>종류</th><th>만든 시각</th><th>실행 주체</th><th>크기</th></tr>'
            f'{rows or "<tr><td colspan=5>조건에 맞는 파일 없음</td></tr>"}</table>{frame}')


SOURCE_GUIDE = """
<details class="guide"><summary>Source 추가 방법 (처음이면 펼쳐 보세요)</summary>
<ol>
<li><b>RSS 주소 찾기</b>: 뉴스 사이트에서 RSS 아이콘이나 "RSS" 메뉴를 찾습니다. 없으면 사이트 주소 뒤에 <code>/feed</code>, <code>/rss</code>, <code>/rss.xml</code> 을 붙여 보거나,
 페이지 소스에서 <code>application/rss+xml</code> 을 검색합니다. 사이트 첫 화면 주소가 아니라 <b>RSS 주소</b> 를 넣어야 합니다.</li>
<li><b>ID</b>: 프로그램 안에서 Source 를 구분하는 이름입니다. 영문 소문자·숫자·하이픈으로 짧게 (예: <code>bleepingcomputer</code>, <code>etnews-ai-sw</code>). 저장한 뒤에는 바꿀 수 없습니다.</li>
<li><b>이름</b>: 메일에 출처로 표시될 이름입니다 (예: 전자신문 AI·SW).</li>
<li><b>구분</b>: 출처 국가 기준 국내·해외. 메일의 국내·해외 섹션이 정해집니다.</li>
<li><b>종류</b>: 공식 기관 (같은 사건이면 대표 기사로 우선) · 보안 전문 매체 · IT 언론 · 기업·벤더.</li>
<li><b>주소 확인</b> 을 누르면 1번 접속해 항목 수·최근 기사·날짜 해석을 보여 줍니다 (저장 없음).
 "날짜 미확인" 이 있으면 "한국 시간으로 해석" 을 켜고 다시 확인하고, 날짜만 있는 Source 면 "날짜만 있는 Source" 를 켭니다.</li>
<li>확인이 끝나면 <b>저장</b>. 다음 실행부터 수집합니다.</li>
</ol>
<p class="muted">수집할 수 없는 주소: Atom 형식, 다른 주소로 이동 (Redirect) 하는 주소 (이동한 최종 주소를 넣으세요), 응답이 2MB 를 넘는 주소, http 주소.</p>
</details>"""


def sources_page(app: AdminApp, edit_id: str | None) -> str:
    """RSS Source 목록 (국내·해외·종류별 묶음, 검색)·추가·수정·사용/중지·삭제 (D-073, D-074)."""
    from saba.rss import KINDS, MAX_SOURCES, REGIONS
    entries = app.source_entries()
    enabled = sum(1 for e in entries if e.enabled)
    rows = ""
    for region in REGIONS:
        for kind in KINDS:
            group = sorted((e for e in entries if e.source.region == region and e.source.kind == kind),
                           key=lambda e: (not e.enabled, e.source.source_name))
            if not group:
                continue
            rows += f'<tr class="group"><td colspan="6">{escape(region)} · {escape(kind)} ({len(group)})</td></tr>'
            for e in group:
                s = e.source
                state = badge("사용", "b-ok") if e.enabled else badge("중지", "b-mute")
                rows += (f"<tr class='src' data-q='{escape((s.source_name + ' ' + s.source_id + ' ' + s.feed_url + ' ' + region + ' ' + kind).lower())}'>"
                         f"<td><b>{escape(s.source_name)}</b><div class=muted>{escape(s.source_id)}</div></td>"
                         f"<td class=url title='{escape(s.feed_url)}'>{escape(s.feed_url)}</td>"
                         f"<td>{'한국 시간' if s.local_offset else '표준'}{' · 날짜만' if s.date_only else ''}</td>"
                         f"<td>{state}</td><td style='white-space:nowrap'><a class=btn href='/sources?edit={quote(s.source_id)}'>수정</a> "
                         + button(app, "source_toggle", "중지" if e.enabled else "사용", "warn" if e.enabled else "success",
                                  back="/sources", fields={"id": s.source_id}) + " "
                         + button(app, "source_delete", "삭제", "danger", back="/sources", fields={"id": s.source_id}) + "</td></tr>")
    search = ('<input class="search" placeholder="검색: 이름·ID·주소·구분·종류" aria-label="검색: 이름·ID·주소·구분·종류" oninput="var q=this.value.toLowerCase();'
              'document.querySelectorAll(\'tr.src\').forEach(function(r){r.style.display=r.dataset.q.indexOf(q)<0?\'none\':\'\'})">')
    table = (f'<div class="card"><h2>RSS Source 목록<span class="muted">사용 {enabled}곳 / 전체 {len(entries)}곳 (최대 {MAX_SOURCES}곳) · '
             f'변경은 다음 실행부터 반영</span><span class="right">{search} <a class="btn primary" href="/sources?edit=new">추가</a></span></h2>'
             '<table><tr><th>이름</th><th>RSS 주소</th><th>날짜 해석</th><th>상태</th><th>관리</th></tr>'
             f'{rows}</table><p class="muted">중지·삭제해도 이미 수집한 기사와 AI 분석은 DB 에 남습니다. 삭제한 Source 의 기사는 메일에 나오지 않습니다.</p></div>')
    if not edit_id:
        return f'<div class="card">{SOURCE_GUIDE}</div>' + table
    current = next((e for e in entries if e.source.source_id == edit_id), None)
    if app.draft and (app.draft.get("id") == edit_id or (edit_id == "new" and app.draft.get("mode") != "edit")):
        values = app.draft
    elif current:
        values = {"id": current.source.source_id, "name": current.source.source_name, "url": current.source.feed_url,
                  "region": current.source.region, "kind": current.source.kind,
                  "kst": current.source.local_offset is not None, "date_only": current.source.date_only, "enabled": current.enabled}
    else:
        values = {"id": "", "name": "", "url": "https://", "region": "해외", "kind": "보안 전문 매체", "kst": False,
                  "date_only": False, "enabled": True}
    editing = current is not None
    checked = lambda key: " checked" if values.get(key) else ""
    kinds = "".join(f'<label><input type="radio" name="kind" value="{k}"{" checked" if values.get("kind") == k else ""}> {k}</label>' for k in KINDS)
    form = f"""
<div class="card"><h2>{"Source 수정: " + escape(current.source.source_name) if editing else "Source 추가"}</h2>
{SOURCE_GUIDE if not editing else ""}
<form method="post" action="/action/source_save" style="margin-top:12px">
<input type="hidden" name="token" value="{app.token}"><input type="hidden" name="back" value="/sources">
<input type="hidden" name="confirm" value="yes"><input type="hidden" name="mode" value="{"edit" if editing else "new"}">
<div class="grid" style="margin-bottom:0">
<div>
<div class="field"><label class="t">RSS 주소 (https)</label><input aria-label="RSS 주소 (https)" name="url" value="{escape(str(values.get("url", "")))}" required style="width:100%"></div>
<div class="field"><label class="t">ID (영문 소문자·숫자·하이픈 3~40자, 만든 뒤 바꿀 수 없음)</label>
 <input name="id" value="{escape(str(values.get("id", "")))}" {"readonly" if editing else "required"} pattern="[a-z0-9][a-z0-9-]{{2,39}}" style="width:100%"></div>
<div class="field"><label class="t">이름 (메일 출처 표시)</label><input aria-label="이름 (메일 출처 표시)" name="name" value="{escape(str(values.get("name", "")))}" required maxlength="60" style="width:100%"></div>
</div>
<div>
<div class="field"><label class="t">구분 (메일 섹션)</label><div class="chips">
 <label><input type="radio" name="region" value="국내"{" checked" if values.get("region") == "국내" else ""}> 국내</label>
 <label><input type="radio" name="region" value="해외"{" checked" if values.get("region") != "국내" else ""}> 해외</label></div></div>
<div class="field"><label class="t">종류</label><div class="chips">{kinds}</div></div>
<div class="field"><label class="t">날짜 해석과 사용</label><div class="chips">
 <label><input type="checkbox" name="kst" value="on"{checked("kst")}> 시간대 없는 날짜를 한국 시간으로 해석</label>
 <label><input type="checkbox" name="date_only" value="on"{checked("date_only")}> 날짜만 있는 Source (수집 기간 48시간)</label>
 <label><input type="checkbox" name="enabled" value="on"{checked("enabled")}> 사용</label></div></div>
</div></div>
<div class="row">
 <button class="btn warn" formaction="/action/source_check" onclick="return confirm('{escape(CONFIRM_TEXT["source_check"])}')">주소 확인</button>
 <button class="btn primary" onclick="return confirm('{escape(CONFIRM_TEXT["source_save"])}')">저장</button>
 <a class="btn" href="/sources">취소</a></div>
<p class="muted">새 Source 를 추가하거나 주소를 바꾸면 먼저 "주소 확인" 을 통과해야 저장할 수 있습니다 (30분 안, 1회 접속, 저장 없음).</p>
</form></div>"""
    return form + table


def recipients_page(app: AdminApp, group: str | None, edit: str | None) -> str:
    """수신자·그룹 관리 (D-074, D-075). 실제 발송은 TEST 1명 잠금."""
    from saba import recipients as rc
    path = app.recipients_path
    group_list, dept_list, domain_list = rc.groups(path), rc.departments(path), rc.domains(path)
    people = rc.recipients(path)
    shown = rc.recipients(path, group) if group else people
    enabled = sum(p.enabled for p in people)
    tiles = (f'<div class="tiles"><div class="tile"><div class="k">수신자</div><div class="v">{enabled}명 사용</div>'
             f'<div class="s">전체 {len(people)}명 · 중지 {len(people) - enabled}명</div></div>'
             f'<div class="tile"><div class="k">그룹</div><div class="v">{len(group_list) - 1}개</div><div class="s">"전체" 는 사용 중인 전원 자동</div></div>'
             f'<div class="tile"><div class="k">부서</div><div class="v">{len(dept_list)}개</div><div class="s">허용 도메인 {", ".join(domain_list)}</div></div>'
             f'<div class="tile"><div class="k">실제 발송 대상</div><div class="v">TEST 1명</div><div class="s">TEST 외 발송은 별도 승인 후</div></div></div>')
    target = ('<div class="card"><h2>발송 대상 그룹</h2><div class="row"><select disabled aria-label="발송 대상 그룹 (잠금)">'
              + "".join(f'<option{" selected" if g == "TEST" else ""}>{escape(g)} ({n}명)</option>' for g, n in group_list)
              + '</select>' + badge("TEST 로 잠금", "b-warn") + '</div>'
              '<p class="muted">지금은 예약·지금·테스트 발송 모두 고정 TEST 주소 1명에게만 보냅니다. 그룹 발송은 발송 전 승인 화면 없이 예약 시각에 수신자마다 1통씩 보내는 방식으로 만들어 두었지만 잠겨 있고, 잠금 해제는 회사 IT·보안 정책 확인 후 별도 승인이 필요합니다.</p></div>')

    filters = "".join(f'<a class="btn{" primary" if (group or "") == (g if g != "모두" else "") else ""}" href="/recipients{"?group=" + quote(g) if g != "모두" else ""}">{escape(g)} ({n})</a> '
                      for g, n in [("모두", len(people))] + group_list)
    rows = ""
    for p in shown:
        tags = " ".join(badge(g, "b-info") for g in p.groups) or '<span class="muted">-</span>'
        rows += (f"<tr class='src' data-q='{escape((p.name + ' ' + p.email + ' ' + p.department + ' ' + ' '.join(p.groups)).lower())}'>"
                 f"<td><b>{escape(p.name)}</b></td><td>{escape(p.email)}</td><td>{escape(p.department)}</td><td>{tags}</td>"
                 f"<td>{badge('사용', 'b-ok') if p.enabled else badge('중지', 'b-mute')}</td>"
                 f"<td style='white-space:nowrap'><a class=btn href='/recipients?edit={p.id}'>수정</a> "
                 + button(app, "recipient_toggle", "중지" if p.enabled else "사용", "warn" if p.enabled else "success", back="/recipients", fields={"id": str(p.id)}) + " "
                 + button(app, "recipient_delete", "삭제", "danger", back="/recipients", fields={"id": str(p.id)}) + "</td></tr>")
    search = ('<input class="search" placeholder="검색: 이름·메일·부서·그룹" aria-label="검색: 이름·메일·부서·그룹" oninput="var q=this.value.toLowerCase();'
              'document.querySelectorAll(\'tr.src\').forEach(function(r){r.style.display=r.dataset.q.indexOf(q)<0?\'none\':\'\'})">')
    listing = (f'<div class="card"><h2>수신자 목록<span class="right">{search} <a class="btn" href="/recipients/export.csv">명단 CSV 내려받기</a> '
               f'<a class="btn primary" href="/recipients?edit=new#form">추가</a></span></h2><div class="row">{filters}</div>'
               '<table><tr><th>이름</th><th>메일</th><th>부서</th><th>그룹</th><th>상태</th><th>관리</th></tr>'
               f'{rows or "<tr><td colspan=6>등록된 수신자가 없습니다. 오른쪽 위 \"추가\" 또는 아래 CSV 일괄 등록을 쓰세요.</td></tr>"}</table></div>')

    current = next((p for p in people if edit and str(p.id) == edit), None)
    values = current or rc.Recipient(0, "", "", dept_list[0][0] if dept_list else "", True, ["TEST"] if not current else [])
    dept_options = "".join(f'<option{" selected" if d == values.department else ""}>{escape(d)}</option>' for d, _ in dept_list)
    group_boxes = "".join(f'<label><input type="checkbox" name="groups" value="{escape(g)}"{" checked" if g in values.groups else ""}> {escape(g)}</label>'
                          for g, _ in group_list if g != rc.ALL_GROUP)
    form = (f'<div class="card" id="form"><h2>{"수신자 수정" if current else "수신자 추가"}</h2>'
            f'<form method="post" action="/action/recipient_save"><input type="hidden" name="token" value="{app.token}">'
            f'<input type="hidden" name="back" value="/recipients"><input type="hidden" name="id" value="{current.id if current else ""}">'
            f'<div class="field"><label class="t">이름</label><input aria-label="이름" name="name" value="{escape(values.name)}" required maxlength="40" style="width:100%"></div>'
            f'<div class="field"><label class="t">메일 ({escape(", ".join("@" + d for d in domain_list))} 만)</label>'
            f'<input name="email" type="email" aria-label="메일" value="{escape(values.email)}" required style="width:100%"></div>'
            f'<div class="field"><label class="t">부서</label><select aria-label="부서" name="department">{dept_options}</select></div>'
            f'<div class="field"><label class="t">그룹 (여러 개 가능, "전체" 는 자동)</label><div class="chips">{group_boxes}</div></div>'
            f'<div class="field"><label><input type="checkbox" name="enabled" value="on"{" checked" if values.enabled else ""}> 사용</label></div>'
            f'<div class="row"><button class="btn primary">저장</button><a class="btn" href="/recipients">취소</a></div></form></div>')

    csv_card = ('<div class="card"><h2>CSV 일괄 등록<span class="right"><a class="btn" href="/recipients/template.csv">빈 양식 내려받기</a></span></h2>'
                '<p class="muted">형식: <b>이름,메일,부서,그룹</b> (첫 줄은 제목). 그룹이 여러 개면 <b>;</b> 로 구분 (예: TEST;파일럿). '
                '엑셀에서 "CSV UTF-8" 로 저장한 파일을 고르거나, 엑셀 표를 복사해 아래 칸에 붙여 넣어도 됩니다. 이미 있는 메일은 정보가 갱신됩니다.</p>'
                f'<form method="post" action="/action/csv_preview"><input type="hidden" name="token" value="{app.token}"><input type="hidden" name="back" value="/recipients">'
                '<div class="row"><input type="file" aria-label="CSV 파일 고르기" accept=".csv,text/csv" onchange="var f=this.files[0];if(!f)return;var r=new FileReader();'
                'r.onload=function(){document.getElementById(\'csvtext\').value=r.result};r.readAsText(f,\'utf-8\')"></div>'
                '<textarea name="csv" id="csvtext" aria-label="CSV 내용" rows="7" style="width:100%" placeholder="이름,메일,부서,그룹"></textarea>'
                '<div class="row"><button class="btn primary">미리보기</button><span class="muted">미리보기는 저장하지 않습니다.</span></div></form></div>')
    preview = ""
    if app.csv_rows:
        status_badge = {"신규": "b-ok", "갱신": "b-info", "오류": "b-bad"}
        prow = "".join(f"<tr><td>{r['line']}</td><td>{badge(r['status'], status_badge[r['status']])}</td><td>{escape(r['name'])}</td>"
                       f"<td>{escape(r['email'])}</td><td>{escape(r['department'])}</td><td>{escape(';'.join(r['groups']))}</td>"
                       f"<td>{escape(r['error']) or '-'}</td></tr>" for r in app.csv_rows)
        preview = (f'<div class="card"><h2>CSV 미리보기 (아직 저장 안 됨)<span class="right">'
                   + button(app, "csv_apply", "신규·갱신 저장", "primary", back="/recipients") + " "
                   + button(app, "csv_cancel", "취소", "", back="/recipients") + '</span></h2>'
                   f'<table><tr><th>줄</th><th>결과</th><th>이름</th><th>메일</th><th>부서</th><th>그룹</th><th>오류</th></tr>{prow}</table></div>')

    def manage(title: str, items: list, action: str, placeholder: str, cls: str, locked: tuple = ()) -> str:
        rows = "".join(f"<tr><td>{escape(name)}</td><td>{'' if count is None else f'{count}명'}</td><td>"
                       + ("" if name in locked else button(app, f"{action}_delete", "삭제", "danger", back="/recipients", fields={"name": name}))
                       + "</td></tr>" for name, count in items)
        return (f'<div class="card {cls}"><h2>{title}</h2><table>{rows}</table>'
                f'<form method="post" action="/action/{action}_add" class="row"><input type="hidden" name="token" value="{app.token}">'
                f'<input type="hidden" name="back" value="/recipients"><input name="name" placeholder="{placeholder}" aria-label="{placeholder}" required>'
                f'<button class="btn primary">추가</button></form></div>')
    groups_card = manage("그룹", group_list, "group", "새 그룹 이름", "c-teal", locked=(rc.ALL_GROUP, "TEST"))
    dept_card = manage("부서 목록", dept_list, "department", "새 부서 이름", "c-purple")
    domain_card = manage("허용 도메인", [(d, None) for d in domain_list], "domain", "예: tbell.co.kr", "c-gray")
    return (tiles + f'<div class="grid">{target}{groups_card}</div>' + listing + preview
            + f'<div class="grid">{form}{csv_card}</div>' + f'<div class="grid">{dept_card}{domain_card}</div>')


def settings_page(app: AdminApp) -> str:
    from saba.send_mail import TEST_ADDRESS
    config, valid = app.config(), app._try(app.config)
    entries = app.source_entries()
    secret_rows = "".join(f"<tr><td>{escape(n)}</td><td>{badge('있음', 'b-ok') if v else badge('없음', 'b-bad')}</td></tr>"
                          for n, v in app.secrets_present().items())
    return (f'<div class="grid"><div class="card"><h2>예약 발송<a class="btn right" href="/schedule">변경</a></h2><table>'
            f'<tr><th style="width:160px">일정</th><td>{escape(schedule_summary(config))}</td></tr>'
            f'<tr><th>하루 AI 호출 상한</th><td>분석 {config.max_analysis_calls}건 · 시사점 {config.max_insight_calls}건</td></tr>'
            f'<tr><th>발송</th><td>{"발송" if config.send else "메일 생성까지만"}</td></tr>'
            f'<tr><th>보관 기간</th><td>로그 {config.log_days}일 · 메일 파일 {config.mail_days}일</td></tr>'
            f'<tr><th>설정 파일 점검</th><td>{escape(valid)}</td></tr></table></div>'
            f'<div class="card"><h2>RSS Source<a class="btn right" href="/sources">관리</a></h2><table>'
            f'<tr><th style="width:160px">사용 중</th><td>{sum(1 for e in entries if e.enabled)}곳</td></tr><tr><th>전체</th><td>{len(entries)}곳</td></tr></table></div></div>'
            f'<div class="grid"><div class="card"><h2>Secret (값은 표시하지 않음)<span class="muted">변경 기능은 로그인·권한 작업과 함께 예정</span></h2>'
            f'<table><tr><th>이름</th><th>상태</th></tr>{secret_rows}</table></div>'
            f'<div class="card"><h2>발송 대상<a class="btn right" href="/recipients">수신자·그룹</a></h2>'
            f'<table><tr><th style="width:160px">현재</th><td>TEST 1명 (고정, {escape(TEST_ADDRESS)}). TEST 외 발송은 별도 승인 후</td></tr></table></div></div>'
            + criteria_card(app))


def criteria_card(app: AdminApp) -> str:
    """부서별 분류 기준 편집 (D-075). AI 가 기사마다 '우리 업무와의 연결' 부서를 고르는 기준."""
    from saba.insights import DEPARTMENT_NAMES, load_departments
    scopes, examples = load_departments(app.departments_path)
    rows = "".join(
        f'<tr><th style="width:130px">{escape(name)}</th>'
        f'<td><textarea name="scope_{i}" aria-label="{escape(name)} 담당 업무" rows="2" style="width:100%" maxlength="200">{escape(scopes[name])}</textarea></td>'
        f'<td><textarea name="examples_{i}" aria-label="{escape(name)} 판단 예시" rows="3" style="width:100%" maxlength="300">{escape(examples[name])}</textarea></td></tr>'
        for i, name in enumerate(DEPARTMENT_NAMES))
    return (f'<div class="card"><h2>부서별 분류 기준<span class="muted">AI 가 기사마다 관련 부서를 고르는 기준입니다. '
            f'부서 이름 4개는 메일 부서 카드와 같아 고정입니다.</span></h2>'
            f'<form method="post" action="/action/criteria_save" onsubmit="return confirm(\'{escape(CONFIRM_TEXT["criteria_save"])}\')">'
            f'<input type="hidden" name="token" value="{app.token}"><input type="hidden" name="back" value="/settings">'
            f'<input type="hidden" name="confirm" value="yes">'
            f'<table><tr><th>부서</th><th>담당 업무 (200자 이내)</th><th>판단 예시 (300자 이내, 쉼표로 나열)</th></tr>{rows}</table>'
            f'<div class="row"><button class="btn primary">저장</button>'
            f'<span class="muted">저장하면 다음 실행부터 새 기준으로 시사점을 다시 만듭니다 (하루 AI 상한 안). 변경은 설정 변경 이력에 남습니다.</span></div>'
            f'</form></div>')


def make_handler(app: AdminApp, port: int):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # 요청 로그는 남기지 않는다
            pass

        def _send(self, code: int, body: str, content_type: str = "text/html; charset=utf-8", headers: dict | None = None):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
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
            if url.path == "/test":
                return self._send(200, page("테스트", test_page(app), message, refresh=app.running(), active="/test"))
            if url.path == "/sources":
                return self._send(200, page("RSS Source", sources_page(app, _first(query, "edit") or None), message, active="/sources"))
            if url.path == "/recipients":
                return self._send(200, page("수신자·그룹", recipients_page(app, _first(query, "group") or None, _first(query, "edit") or None),
                                            message, active="/recipients"))
            if url.path in ("/recipients/export.csv", "/recipients/template.csv"):
                from saba import recipients as rc
                text = rc.export_csv(app.recipients_path) if url.path.endswith("export.csv") else rc.template_csv()
                return self._send(200, text, "text/csv; charset=utf-8",
                                  {"Content-Disposition": f'attachment; filename="{url.path.rsplit("/", 1)[1]}"'})
            if url.path == "/schedule":
                return self._send(200, page("예약 발송 설정", schedule_page(app), message, active="/schedule"))
            if url.path == "/logs":
                tab = _first(query, "tab") or "runs"
                return self._send(200, page("실행 이력·뉴스레터", logs_page(app, tab, _first(query, "day") or None, _first(query, "name") or None, query),
                                            message, active="/logs"))
            if url.path == "/newsletter":  # 예전 주소: 실행 이력·뉴스레터의 뉴스레터 탭 (D-074)
                return self._send(200, page("실행 이력·뉴스레터", logs_page(app, "mail", None, _first(query, "name") or None, query), message, active="/logs"))
            if url.path == "/newsletter/view":
                html = app.newsletter_html(_first(query, "name") or None)
                return self._send(200, html or "<p>생성된 메일이 없습니다.</p>")
            if url.path == "/settings":
                return self._send(200, page("설정", settings_page(app), message, active="/settings"))
            return self._send(404, page("없는 페이지", "<p>없는 페이지입니다.</p>"))

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, "forbidden", "text/plain; charset=utf-8")
            length = min(int(self.headers.get("Content-Length") or 0), 262144)  # 수신자 CSV 붙여 넣기 (약 수천 명)
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
