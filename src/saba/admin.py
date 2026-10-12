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
    "test_now": "즉시 테스트 발송: RSS 수집 → AI 분석 (하루 상한 안) → 메일 생성 → TEST 1명 발송을 지금 실행합니다. 진행할까요?",
    "test_schedule": "정한 시각에 테스트 발송을 1회 예약합니다 (평소 예약 발송 일정은 그대로). 진행할까요?",
    "test_cancel": "예약된 테스트 발송을 취소할까요?",
    "source_check": "RSS 주소 확인: 입력한 주소에 1회 접속합니다 (저장 없음). 진행할까요?",
    "source_save": "RSS Source 를 저장합니다. 다음 실행부터 수집에 반영됩니다. 진행할까요?",
    "source_toggle": "이 RSS Source 의 사용·중지를 바꿀까요? 이미 수집한 기사는 그대로 둡니다.",
    "source_delete": "이 RSS Source 를 목록에서 삭제할까요? 수집한 기사·분석은 DB 에 남지만 메일에는 더 이상 나오지 않습니다.",
    "rss_dryrun": "RSS 수집 점검: 사용 중인 RSS Source 에 접속합니다 (저장 없음). 진행할까요?",
    "smtp_check": "메일 서버 로그인 점검: 회사 메일 서버에 접속해 로그인만 확인합니다 (발송 없음). 진행할까요?",
    "save_schedule": "예약 발송 설정을 저장합니다. 일정이 바뀌면 작업 스케줄러에 다시 등록합니다. 진행할까요?",
}
MODE_LABEL = {"daily": "매일", "weekly": "매주", "monthly": "매월", "dates": "특정 날짜"}
DAY_LABEL = dict(zip(("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"), "월화수목금토일"))
FIELD_LABEL = {"mode": "주기", "time": "시각", "random_delay_minutes": "무작위 지연(분)", "weekdays": "요일",
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
:root{--bg:#f1f4f9;--card:#fff;--line:#e2e8f0;--text:#1e293b;--muted:#64748b;--brand:#2563eb;--ok:#15803d;--bad:#b91c1c;--warn:#b45309}
*{box-sizing:border-box}
body{margin:0;font-family:'Malgun Gothic','Apple SD Gothic Neo',Arial,sans-serif;background:var(--bg);color:var(--text);font-size:14px}
header{background:#0f172a;color:#fff;padding:0 32px;display:flex;align-items:center;gap:32px;min-height:58px;flex-wrap:wrap}
header .logo{font-weight:700;font-size:17px;letter-spacing:.3px}
header nav{display:flex;gap:22px;flex-wrap:wrap}
header nav a{color:#cbd5e1;text-decoration:none;padding:18px 2px;border-bottom:3px solid transparent}
header nav a.on{color:#fff;border-color:#60a5fa}
header nav span{color:#64748b;padding:18px 2px}
main{max-width:1440px;margin:24px auto;padding:0 24px}
h1{font-size:21px;margin:0 0 18px}
.tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin-bottom:16px}
.tile{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--accent,#94a3b8);border-radius:10px;padding:16px 18px}
.tile .k{color:var(--muted);font-size:12px;font-weight:600}.tile .v{font-size:19px;font-weight:700;margin-top:8px;color:var(--accent,#1e293b)}
.tile .s{color:var(--muted);font-size:12px;margin-top:6px}
.card{background:var(--card);border:1px solid var(--line);border-top:4px solid var(--accent,#cbd5e1);border-radius:10px;padding:18px 22px;margin-bottom:16px}
.card h2{font-size:15px;margin:0 0 14px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;color:#0f172a}
.card h2 .right{margin-left:auto}
.c-blue{--accent:#2563eb}.c-green{--accent:#16a34a}.c-purple{--accent:#7c3aed}.c-orange{--accent:#ea580c}.c-teal{--accent:#0d9488}.c-gray{--accent:#64748b}.c-red{--accent:#dc2626}
table{border-collapse:collapse;width:100%;border-top:1px solid var(--line)}
th,td{padding:9px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:#f8fafc;color:#475569;font-weight:600;font-size:13px;white-space:nowrap}
tr.group td{background:#eef2ff;color:#3730a3;font-weight:700;font-size:13px}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap}
.b-ok{background:#dcfce7;color:var(--ok)}.b-bad{background:#fee2e2;color:var(--bad)}.b-warn{background:#fef3c7;color:var(--warn)}.b-mute{background:#f1f5f9;color:#475569}.b-info{background:#dbeafe;color:#1d4ed8}
.btn{display:inline-block;padding:7px 14px;border-radius:6px;border:1px solid #cbd5e1;background:#fff;color:#334155;cursor:pointer;font-size:13px;text-decoration:none;font-family:inherit}
.btn:hover{filter:brightness(.96)}
.btn.primary{background:var(--brand);color:#fff;border-color:var(--brand)}
.btn.success{background:#16a34a;color:#fff;border-color:#16a34a}
.btn.warn{background:#fff7ed;color:#c2410c;border-color:#fdba74}
.btn.danger{background:#fef2f2;color:#b91c1c;border-color:#fca5a5}
.help{width:22px;height:22px;border-radius:50%;border:1px solid #94a3b8;background:#fff;color:#475569;font-weight:700;cursor:pointer;font-size:12px;padding:0;margin-left:6px}
.msg{background:#eff6ff;border:1px solid #bfdbfe;border-left:5px solid #2563eb;border-radius:10px;padding:12px 16px;margin-bottom:16px;white-space:pre-wrap}
.info{background:#f8fafc;border:1px dashed #cbd5e1;border-radius:8px;padding:14px 16px;color:#475569}
.muted{color:var(--muted);font-size:12px}
.tabs{display:flex;gap:4px;margin-bottom:-1px}
.tabs a{padding:9px 18px;border:1px solid var(--line);border-bottom:none;border-radius:8px 8px 0 0;background:#e2e8f0;color:#475569;text-decoration:none}
.tabs a.on{background:#fff;color:var(--brand);font-weight:700;border-top:3px solid var(--brand)}
.tabbody{border-top-left-radius:0}
form.inline{display:inline}
.row{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin:8px 0}
.field{margin-bottom:16px}.field>label.t{display:block;font-weight:600;margin-bottom:6px}
.chips label{display:inline-block;margin:0 6px 6px 0;padding:5px 11px;border:1px solid var(--line);border-radius:6px;background:#f8fafc;cursor:pointer}
input[type=number]{width:90px}input,textarea,select{font:inherit;padding:6px 8px;border:1px solid #cbd5e1;border-radius:6px}
dialog{border:none;border-radius:12px;max-width:560px;padding:22px 26px;box-shadow:0 12px 32px rgba(0,0,0,.25);line-height:1.6}
dialog h3{margin:0 0 10px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;align-items:stretch;margin-bottom:16px}
.grid>.card{margin-bottom:0}
.side{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:16px;align-items:start}
.sticky{position:sticky;top:16px}
@media (max-width:1000px){.grid,.side,.tiles{grid-template-columns:1fr}}
.switch{position:relative;display:inline-block;width:52px;height:28px;vertical-align:middle;margin-right:8px}
.switch input{opacity:0;width:0;height:0}
.slider{position:absolute;cursor:pointer;inset:0;background:#cbd5e1;border-radius:28px;transition:.2s}
.slider:before{content:"";position:absolute;height:22px;width:22px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.2s}
.switch input:checked+.slider{background:#16a34a}.switch input:checked+.slider:before{transform:translateX(24px)}
.steps{display:flex;gap:6px;align-items:stretch;margin-top:12px}
.step{flex:1;border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:#f8fafc;color:var(--muted)}
.step b{display:block;color:var(--text);margin-bottom:2px}
.step.done{border-color:#86efac;background:#f0fdf4}.step.fail{border-color:#fca5a5;background:#fef2f2}
.arrow{align-self:center;color:#94a3b8}
.summary{font-size:15px;line-height:1.6}
.need{background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;padding:12px 14px;margin-top:12px}
td.url{max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.search{width:320px}
details.guide summary{cursor:pointer;font-weight:700;color:#1d4ed8}
details.guide ol{margin:10px 0 0;padding-left:20px;line-height:1.8}
"""

MENU = [("/", "대시보드"), ("/test", "테스트"), ("/schedule", "예약 발송 설정"), ("/sources", "RSS Source"),
        ("/logs", "실행 이력·뉴스레터"), ("/settings", "설정")]
RESULT_BADGE = {"성공": "b-ok", "성공 (발송 안 함)": "b-info", "실패": "b-bad", "건너뜀": "b-warn", "진행 중": "b-mute"}


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
    if run.result == "실패":
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
    on = task.get("state") not in ("Disabled", "등록 안 됨", "확인 실패")
    upcoming = next_runs(config, now, 3)
    running = app.running()
    sent = next((r for r in real_today if r.sent), None)
    need = app.send_needed()
    recent = app.recent_articles()
    enabled_sources = sum(1 for e in app.source_entries() if e.enabled)

    tile_task = (badge("켜짐", "b-ok") if on else badge("꺼짐", "b-mute")) + (
        f'<div class="s">다음 예약 {escape(kst_label(upcoming[0]))}</div>' if on and upcoming else '<div class="s">예약 발송이 꺼져 있습니다</div>')
    if running:
        today_state, today_sub = badge("실행 중", "b-info"), "끝나면 결과가 표시됩니다"
    elif sent:
        today_state, today_sub = badge(f"{sent.start[11:16]} 발송 완료", "b-ok"), escape(sent.origin)
    elif need:
        today_state, today_sub = badge("발송 안 됨", "b-bad"), "아래 \"지금 발송\" 으로 보낼 수 있습니다"
    else:
        today_state, today_sub = badge("예약 대기", "b-mute"), escape(f"오늘 {config.time} 예정" if upcoming and upcoming[0].date() == now.date() else "오늘은 예약 없음")
    tiles = (f'<div class="tiles"><div class="tile c-blue"><div class="k">예약 발송</div><div class="v">{tile_task}</div></div>'
             f'<div class="tile c-green"><div class="k">오늘 뉴스레터</div><div class="v">{today_state}</div><div class="s">{today_sub}</div></div>'
             f'<div class="tile c-purple"><div class="k">이번 달 AI 비용</div><div class="v">${use["cost"]:.3f} / ${use["limit"]:.0f}</div>'
             f'<div class="s">호출 {use["calls"]}건 (성공 {use["ok"]} · 실패 {use["failed"]})</div></div>'
             f'<div class="tile c-orange"><div class="k">최근 24시간 수집 기사</div><div class="v">{"-" if recent is None else recent}건</div>'
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
    today_card = (f'<div class="card c-green"><h2>마지막 실행{" " + badge(last.result, RESULT_BADGE.get(last.result, "b-mute")) if last else ""}'
                  f'<a class="btn right" href="/logs">전체 이력</a></h2>{body}</div>')

    if on:
        upcoming_rows = "".join(f"<li>{escape(kst_label(at))}</li>" for at in upcoming) or "<li>예정 없음</li>"
        schedule_body = (f'<table><tr><th>일정</th><td>{escape(schedule_summary(config))}</td></tr>'
                         f'<tr><th>다음 예약</th><td><ul style="margin:0;padding-left:18px">{upcoming_rows}</ul></td></tr>'
                         f'<tr><th>발송</th><td>{"TEST 1명에게 발송" if config.send else "메일 생성까지만"}</td></tr></table>')
    else:
        schedule_body = (f'<div class="info"><b>예약 발송이 꺼져 있습니다.</b><br>정해진 시각에 뉴스레터를 보내지 않습니다. '
                         f'스위치를 켜면 저장된 일정 ({escape(schedule_summary(config))}) 으로 다시 발송합니다.</div>')
    schedule_card = (f'<div class="card c-blue"><h2>예약 발송<a class="btn right" href="/schedule">설정 변경</a></h2>'
                     f'{task_switch(app, on)}{schedule_body}</div>')

    status_rows = [
        ("이번 달 AI 호출", f'{use["calls"]}건 (성공 {use["ok"]} · 실패 {use["failed"]})'),
        ("이번 달 AI 비용", f'${use["cost"]:.4f} / 상한 ${use["limit"]:.2f}'),
        ("하루 AI 호출 상한", f"분석 {config.max_analysis_calls}건 · 시사점 {config.max_insight_calls}건"),
        ("발송 대상", "TEST 1명 (고정 주소)"),
        ("작업 스케줄러", f'{task.get("state", "-")} · 마지막 결과 코드 {task.get("result", "-") or "-"}'),
    ]
    status_card = ('<div class="card c-purple"><h2>운영 현황</h2><table>'
                   + "".join(f"<tr><th style='width:160px'>{escape(a)}</th><td>{escape(b)}</td></tr>" for a, b in status_rows)
                   + "</table></div>")
    recent_rows = "".join(f"<tr><td style='white-space:nowrap'>{escape(r.start[5:16])}</td><td>{escape(r.origin)}</td>"
                          f"<td>{badge(r.result, RESULT_BADGE.get(r.result, 'b-mute'))}</td></tr>" for r in runs[:5])
    recent_card = ('<div class="card c-orange"><h2>최근 실행<a class="btn right" href="/logs">더 보기</a></h2>'
                   f'<table><tr><th>시각</th><th>실행 주체</th><th>결과</th></tr>{recent_rows or "<tr><td colspan=3>기록 없음</td></tr>"}</table></div>')
    return (tiles + f'<div class="grid">{today_card}{schedule_card}</div>'
            + f'<div class="grid">{recent_card}{status_card}</div>')


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
        f"<td>{f'<a href=/logs?tab=mail&name={quote(r.mail_file)}>메일 보기</a>' if r.mail_file else ''}</td></tr>" for r in tests)
    history = ('<div class="card c-green"><h2>테스트 발송 기록</h2><table><tr><th>시각</th><th>종류</th><th>결과</th><th>기사</th>'
               f'<th>메일 크기 (bytes)</th><th>발송</th><th>실패 사유</th><th></th></tr>{rows or "<tr><td colspan=8>아직 테스트 발송 기록이 없습니다.</td></tr>"}</table></div>')
    tool_rows = "".join(
        f"<tr><td>{escape(name)}{help_button(key, name, body)}</td>"
        f"<td>{badge('외부 접속 있음', 'b-warn') if external == '있음' else badge('외부 접속 없음', 'b-mute')}</td>"
        f"<td>{button(app, key, '실행', 'warn' if external == '있음' else '', back='/test')}</td></tr>" for key, name, external, body in TOOLS)
    tools = ('<div class="card c-gray"><h2>점검 도구<span class="muted">문제가 생겼을 때 원인을 찾는 도구입니다. ? 를 누르면 설명이 나옵니다.</span></h2>'
             f'<table><tr><th>도구</th><th>외부 접속</th><th style="width:90px">실행</th></tr>{tool_rows}</table></div>')
    return (f'<div class="grid"><div class="card c-blue"><h2>즉시 테스트 발송</h2>{now_body}</div>'
            f'<div class="card c-purple"><h2>시각 지정 테스트 발송</h2>{schedule_body}</div></div>' + history + tools)


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
<div class="card c-blue"><h2>주기</h2>
 <div class="field"><div class="chips">{mode_radios}</div></div>
 <div id="m-weekly" class="field"><label class="t">요일</label><div class="chips">{weekday_boxes}</div></div>
 <div id="m-monthly" class="field"><label class="t">매월 날짜</label><div class="chips">{month_boxes}</div>
  <div class="muted">그 달에 없는 날짜 (예: 31일) 는 건너뜁니다.</div></div>
 <div id="m-dates" class="field"><label class="t">특정 날짜</label>
  <div class="row"><input type="date" id="pick"> <button type="button" class="btn" onclick="addDate()">날짜 추가</button></div>
  <textarea name="dates" id="dates" rows="4" cols="30" placeholder="한 줄에 하나 (예: 2026-10-20)">{escape(chr(10).join(config.dates))}</textarea>
  <div class="muted">지난 날짜는 무시됩니다. 줄을 지우면 날짜가 빠집니다.</div></div>
</div>
<div class="card c-purple"><h2>시각</h2>
 <div class="row"><label>발송 시각 <input type="time" name="time" value="{escape(config.time)}" required></label>
 <label>무작위 지연 최대 <input type="number" name="random_delay_minutes" min="0" max="30" value="{config.random_delay_minutes}"> 분</label></div>
 <div class="muted">무작위 지연: 정해진 시각부터 이 시간 안에서 아무 때나 실행합니다 (0 이면 정각).</div>
</div>
<div class="card c-orange"><h2>AI 호출과 발송</h2>
 <div class="row"><label>하루 AI 분석 상한 <input type="number" name="max_analysis_calls" min="0" max="50" value="{config.max_analysis_calls}"> 건</label>
 <label>하루 AI 시사점 상한 <input type="number" name="max_insight_calls" min="0" max="50" value="{config.max_insight_calls}"> 건</label></div>
 <div class="muted">현재 하루 최대 {per_day}건 · 매일 발송해도 한 달 최대 약 ${per_day * COST_PER_CALL * 31:.2f} (월 상한 $3, 변경 불가). 이미 분석한 기사는 다시 호출하지 않습니다.</div>
 <div class="row"><label><input type="radio" name="send" value="on"{" checked" if config.send else ""}> 예약 시각에 TEST 1명에게 발송</label>
 <label><input type="radio" name="send" value="off"{"" if config.send else " checked"}> 메일 생성까지만 (발송 안 함)</label></div>
</div>
<div class="card c-gray"><h2>보관 기간</h2>
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
    side = (f'<div class="card c-green sticky"><h2>현재 일정</h2><div class="summary">{escape(schedule_summary(config))}</div>'
            f'<h2 style="margin-top:16px">다음 예약 5회</h2><table><tr><th style="width:50px">순서</th><th>시각 (무작위 지연 전)</th></tr>'
            f'{upcoming or "<tr><td colspan=2>예정 없음</td></tr>"}</table>'
            '<p class="muted">시각을 정해 한 번만 확인하려면 테스트 화면의 "시각 지정 테스트 발송" 을 쓰세요 (이 일정은 바뀌지 않음).</p></div>')
    return f'<div class="side"><div>{form}</div><div>{side}</div></div>'


LOG_TABS = (("runs", "실행 이력"), ("mail", "뉴스레터"), ("detail", "상세 로그"), ("changes", "설정 변경 이력"))


def logs_page(app: AdminApp, tab: str, day: str | None, name: str | None = None) -> str:
    """실행 이력·뉴스레터 (D-074 합침): 탭 실행 이력 · 뉴스레터 · 상세 로그 · 설정 변경 이력."""
    from saba.history import log_files, read_changes, read_log, storage_status
    config = app.config()
    store = storage_status(app.root)
    tabs = "".join(f'<a href="/logs?tab={key}"{" class=on" if tab == key else ""}>{label}</a>' for key, label in LOG_TABS)
    keep = (f'<div class="muted" style="margin-bottom:12px">보관: 실행 로그 {config.log_days}일 (현재 {store["logs"]["count"]}개 파일 · '
            f'{store["logs"]["bytes"] / 1024:.1f} KB · 가장 오래된 날짜 {store["logs"]["oldest"]}) · 메일 파일 {config.mail_days}일 '
            f'(현재 {store["mails"]["count"]}개 · {store["mails"]["bytes"] / 1024 / 1024:.2f} MB). 기간이 지나면 매일 실행 때 자동 삭제.</div>')
    if tab == "mail":
        return f'<div class="tabs">{tabs}</div><div class="card tabbody c-blue">{keep}{newsletter_body(app, name)}</div>'
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
            mail = f"<a href='/logs?tab=mail&name={quote(run.mail_file)}'>메일</a> · " if run.mail_file else ""
            rows += (f"<tr><td style='white-space:nowrap'>{escape(run.start[:16])}</td><td>{escape(run.origin)}</td>"
                     f"<td>{badge(run.result, RESULT_BADGE.get(run.result, 'b-mute'))}</td>"
                     f"<td>{'-' if run.articles is None else run.articles}</td><td>{'-' if run.ai_calls is None else run.ai_calls}</td>"
                     f"<td>{escape(run.mail_bytes or '-')}</td><td>{'발송' if run.sent else '-'}</td>"
                     f"<td>{escape(run.error) or '-'}</td><td style='white-space:nowrap'>{mail}<a href='/logs?tab=detail&day={day_key}'>로그</a></td></tr>")
        body = ("<table><tr><th>시작</th><th>실행 주체</th><th>결과</th><th>기사</th><th>AI 신규 호출</th><th>메일 크기 (bytes)</th>"
                f"<th>발송</th><th>실패 사유</th><th>보기</th></tr>{rows or '<tr><td colspan=9>실행 기록 없음</td></tr>'}</table>")
    return f'<div class="tabs">{tabs}</div><div class="card tabbody c-blue">{keep}{body}</div>'


def _show(value) -> str:
    if isinstance(value, bool):
        return "발송" if value else "발송 안 함"
    if isinstance(value, list):
        return ", ".join(DAY_LABEL.get(str(v), str(v)) for v in value) or "(없음)"
    return MODE_LABEL.get(str(value), str(value))


def newsletter_body(app: AdminApp, name: str | None) -> str:
    files = app.mail_files()
    kind_badge = {"발송본": "b-ok", "생성만 (발송 안 함)": "b-info", "미리보기": "b-warn"}
    rows = "".join(f"<tr><td><a href='/logs?tab=mail&name={quote(f['name'])}'>{escape(f['name'])}</a></td>"
                   f"<td>{badge(f['kind'], kind_badge.get(f['kind'], 'b-mute'))}</td><td>{escape(f['made'])}</td>"
                   f"<td>{escape(f['origin'])}</td><td>{f['size'] / 1024:.0f} KB</td></tr>" for f in files)
    name = name or (files[0]["name"] if files else None)
    guide = ('<div class="muted" style="margin-bottom:10px">발송본: 실제로 TEST 수신자에게 보낸 메일 · 생성만: 만들었지만 보내지 않은 메일 · '
             '미리보기: 점검 도구 "미리보기 다시 만들기" 로 만든 확인용 (최신 1개만 보관). 메일은 만든 시각 기준 최근 24시간 (월요일 72시간) 기사로 '
             '구성되므로 만든 시각이 다르면 기사 구성이 다릅니다.</div>')
    frame = (f'<h2 style="margin-top:18px">{escape(name)}</h2><iframe src="/newsletter/view?name={quote(name)}" style="width:100%;height:900px;border:1px solid var(--line);border-radius:8px"></iframe>'
             if name else "<p>생성된 메일이 없습니다.</p>")
    return (f'{guide}<table><tr><th>파일</th><th>종류</th><th>만든 시각</th><th>실행 주체</th><th>크기</th></tr>'
            f'{rows or "<tr><td colspan=5>없음</td></tr>"}</table>{frame}')


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
    search = ('<input class="search" placeholder="검색: 이름·ID·주소·구분·종류" oninput="var q=this.value.toLowerCase();'
              'document.querySelectorAll(\'tr.src\').forEach(function(r){r.style.display=r.dataset.q.indexOf(q)<0?\'none\':\'\'})">')
    table = (f'<div class="card c-blue"><h2>RSS Source 목록<span class="muted">사용 {enabled}곳 / 전체 {len(entries)}곳 (최대 {MAX_SOURCES}곳) · '
             f'변경은 다음 실행부터 반영</span><span class="right">{search} <a class="btn primary" href="/sources?edit=new">추가</a></span></h2>'
             '<table><tr><th>이름</th><th>RSS 주소</th><th>날짜 해석</th><th>상태</th><th>관리</th></tr>'
             f'{rows}</table><p class="muted">중지·삭제해도 이미 수집한 기사와 AI 분석은 DB 에 남습니다. 삭제한 Source 의 기사는 메일에 나오지 않습니다.</p></div>')
    if not edit_id:
        return f'<div class="card c-gray">{SOURCE_GUIDE}</div>' + table
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
<div class="card c-orange"><h2>{"Source 수정: " + escape(current.source.source_name) if editing else "Source 추가"}</h2>
{SOURCE_GUIDE if not editing else ""}
<form method="post" action="/action/source_save" style="margin-top:12px">
<input type="hidden" name="token" value="{app.token}"><input type="hidden" name="back" value="/sources">
<input type="hidden" name="confirm" value="yes"><input type="hidden" name="mode" value="{"edit" if editing else "new"}">
<div class="grid" style="margin-bottom:0">
<div>
<div class="field"><label class="t">RSS 주소 (https)</label><input name="url" value="{escape(str(values.get("url", "")))}" required style="width:100%"></div>
<div class="field"><label class="t">ID (영문 소문자·숫자·하이픈 3~40자, 만든 뒤 바꿀 수 없음)</label>
 <input name="id" value="{escape(str(values.get("id", "")))}" {"readonly" if editing else "required"} pattern="[a-z0-9][a-z0-9-]{{2,39}}" style="width:100%"></div>
<div class="field"><label class="t">이름 (메일 출처 표시)</label><input name="name" value="{escape(str(values.get("name", "")))}" required maxlength="60" style="width:100%"></div>
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


def settings_page(app: AdminApp) -> str:
    from saba.send_mail import TEST_ADDRESS
    config, valid = app.config(), app._try(app.config)
    entries = app.source_entries()
    secret_rows = "".join(f"<tr><td>{escape(n)}</td><td>{badge('있음', 'b-ok') if v else badge('없음', 'b-bad')}</td></tr>"
                          for n, v in app.secrets_present().items())
    return (f'<div class="grid"><div class="card c-blue"><h2>예약 발송<a class="btn right" href="/schedule">변경</a></h2><table>'
            f'<tr><th style="width:160px">일정</th><td>{escape(schedule_summary(config))}</td></tr>'
            f'<tr><th>하루 AI 호출 상한</th><td>분석 {config.max_analysis_calls}건 · 시사점 {config.max_insight_calls}건</td></tr>'
            f'<tr><th>발송</th><td>{"발송" if config.send else "메일 생성까지만"}</td></tr>'
            f'<tr><th>보관 기간</th><td>로그 {config.log_days}일 · 메일 파일 {config.mail_days}일</td></tr>'
            f'<tr><th>설정 파일 점검</th><td>{escape(valid)}</td></tr></table></div>'
            f'<div class="card c-orange"><h2>RSS Source<a class="btn right" href="/sources">관리</a></h2><table>'
            f'<tr><th style="width:160px">사용 중</th><td>{sum(1 for e in entries if e.enabled)}곳</td></tr><tr><th>전체</th><td>{len(entries)}곳</td></tr></table></div></div>'
            f'<div class="grid"><div class="card c-red"><h2>Secret (값은 표시하지 않음)<span class="muted">변경 기능은 로그인·권한 작업과 함께 예정</span></h2>'
            f'<table><tr><th>이름</th><th>상태</th></tr>{secret_rows}</table></div>'
            f'<div class="card c-teal"><h2>발송 대상<span class="muted">수신자·그룹 (전체 인원) 관리는 다음 작업</span></h2>'
            f'<table><tr><th style="width:160px">현재</th><td>TEST 1명 (고정, {escape(TEST_ADDRESS)})</td></tr></table></div></div>')


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
            if url.path == "/test":
                return self._send(200, page("테스트", test_page(app), message, refresh=app.running(), active="/test"))
            if url.path == "/sources":
                return self._send(200, page("RSS Source", sources_page(app, _first(query, "edit") or None), message, active="/sources"))
            if url.path == "/schedule":
                return self._send(200, page("예약 발송 설정", schedule_page(app), message, active="/schedule"))
            if url.path == "/logs":
                tab = _first(query, "tab") or "runs"
                return self._send(200, page("실행 이력·뉴스레터", logs_page(app, tab, _first(query, "day") or None, _first(query, "name") or None),
                                            message, active="/logs"))
            if url.path == "/newsletter":  # 예전 주소: 실행 이력·뉴스레터의 뉴스레터 탭 (D-074)
                return self._send(200, page("실행 이력·뉴스레터", logs_page(app, "mail", None, _first(query, "name") or None), message, active="/logs"))
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
