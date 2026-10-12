"""실행 이력·로그 해석, 설정 변경 기록, 보관 기간 정리 (D-072).

로그 파일 (logs/daily_YYYYMMDD.log) 이 원본이다. 별도 DB 없이 로그를 읽어 실행 단위 표로 만든다.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re

LINE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ (INFO|WARNING|ERROR) (.*)")
MAIL = re.compile(r"메일 생성 완료: (\S+) · 표시 (\d+)건 · 분석 재사용 \d+ · 신규 (\d+) · 실패 \d+"
                  r" · 시사점 재사용 \d+ · 신규 (\d+) · 실패 \d+ · ([\d,]+) bytes")
SENT_BYTES = re.compile(r"메시지 ([\d,]+) bytes")
LOG_NAME = re.compile(r"daily_(\d{8})\.log")
MAIL_NAME = re.compile(r"daily_(\d{8})(?:_[\w-]+)?\.eml")


@dataclass
class LogLine:
    time: str  # YYYY-MM-DD HH:MM:SS
    level: str
    message: str


@dataclass
class Run:
    start: str
    origin: str
    result: str = "진행 중"  # 성공 · 성공 (발송 안 함) · 실패 · 건너뜀 · 진행 중
    stages: list[tuple[str, str, str, str]] = field(default_factory=list)  # 단계, 시각, 결과, 내용
    articles: int | None = None
    ai_calls: int | None = None
    mail_file: str | None = None
    mail_bytes: str | None = None
    sent: bool = False
    error: str = ""

    @property
    def closed(self) -> bool:
        return self.result != "진행 중"


def read_log(path: Path) -> list[LogLine]:
    lines: list[LogLine] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = LINE.match(raw)
        if match:
            lines.append(LogLine(*match.groups()))
        elif lines and raw.strip():  # 여러 줄 메시지는 앞 줄에 붙인다
            lines[-1].message += " " + raw.strip()
    return lines


def parse_runs(lines: list[LogLine]) -> list[Run]:
    """로그 줄을 실행 단위로 묶는다. D-071 이전 기록은 "실행 시작" 줄이 없어 수집 완료부터 묶는다."""
    runs: list[Run] = []
    current: Run | None = None
    for line in lines:
        msg, clock = line.message, line.time[11:16]
        if msg.startswith("실행 시작:"):
            current = Run(line.time, msg.removeprefix("실행 시작:").strip())
            runs.append(current)
            current.stages.append(("시작", clock, "완료", current.origin))
            continue
        if line.level == "WARNING" and "이미 실행 중" in msg:
            runs.append(Run(line.time, msg.split(":")[0], "건너뜀", [("시작", clock, "건너뜀", "다른 실행이 진행 중")],
                            error="이미 실행 중이라 건너뜀"))
            continue
        if current is None or current.closed:
            if msg != "RSS 수집 완료" and line.level != "ERROR":
                continue
            current = Run(line.time, "주체 미기록 (이전 형식)")
            runs.append(current)
        if msg.startswith("보관 기간 정리"):
            current.stages.append(("보관 정리", clock, "완료", msg.split(":", 1)[-1].strip()))
        elif msg == "RSS 수집 완료":
            current.stages.append(("RSS 수집", clock, "완료", ""))
        elif match := MAIL.match(msg):
            name, shown, analysis, insight, size = match.groups()
            current.mail_file, current.mail_bytes = name, size
            current.articles, current.ai_calls = int(shown), int(analysis) + int(insight)
            current.stages.append(("메일 생성", clock, "완료",
                                   f"기사 {shown}건 · AI 신규 호출 {current.ai_calls}건 · {size} bytes"))
        elif msg.startswith("발송 완료"):
            size = SENT_BYTES.search(msg)
            current.stages.append(("발송", clock, "완료", f"TEST 1명 · {size.group(1) if size else '-'} bytes"))
            current.result, current.sent = "성공", True
        elif msg.startswith("발송하지 않음") or "send=false" in msg:
            current.stages.append(("발송", clock, "안 함", "설정: 발송 안 함"))
            current.result = "성공 (발송 안 함)"
        elif line.level == "ERROR":
            stage = msg.split(" 단계 실패")[0] if " 단계 실패" in msg else "실행"
            reason = msg.split(":", 1)[-1].replace("· 오늘은 발송하지 않음", "").strip()
            current.stages.append((stage, clock, "실패", reason))
            current.result, current.error = "실패", f"{stage} 단계: {reason}"
    return runs


def log_files(log_dir: Path) -> list[Path]:
    return sorted((p for p in log_dir.glob("daily_*.log") if LOG_NAME.fullmatch(p.name)), reverse=True)


def load_runs(log_dir: Path) -> list[Run]:
    """모든 로그의 실행, 최신 순."""
    runs = [run for path in log_files(log_dir) for run in parse_runs(read_log(path))]
    return sorted(runs, key=lambda run: run.start, reverse=True)


# ---- 설정 변경 기록 ----
def append_change(path: Path, changes: dict[str, tuple], reregistered: bool, now: datetime | None = None) -> None:
    path.parent.mkdir(exist_ok=True)
    record = {"at": (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
              "changes": {key: list(value) for key, value in changes.items()}, "reregistered": reregistered}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_changes(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return list(reversed(records))


# ---- 보관 기간 ----
def _file_date(name: str, pattern: re.Pattern) -> date | None:
    match = pattern.fullmatch(name)
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date() if match else None
    except ValueError:
        return None


def cleanup(root: Path, log_days: int, mail_days: int, today: date) -> tuple[int, int]:
    """보관 기간이 지난 logs/daily_*.log, output/daily_*.eml 만 지운다 (파일 이름의 날짜 기준). 다른 파일은 건드리지 않는다."""
    removed = [0, 0]
    for index, (folder, pattern, days) in enumerate((("logs", LOG_NAME, log_days), ("output", MAIL_NAME, mail_days))):
        limit = today - timedelta(days=days)
        for path in (root / folder).glob("daily_*"):
            day = _file_date(path.name, pattern)
            if day is not None and day < limit:
                path.unlink()
                removed[index] += 1
    return removed[0], removed[1]


def storage_status(root: Path) -> dict:
    status = {}
    for key, folder, pattern in (("logs", "logs", LOG_NAME), ("mails", "output", MAIL_NAME)):
        files = [p for p in (root / folder).glob("daily_*") if pattern.fullmatch(p.name)]
        days = [d for d in (_file_date(p.name, pattern) for p in files) if d]
        status[key] = {"count": len(files), "bytes": sum(p.stat().st_size for p in files),
                       "oldest": min(days).isoformat() if days else "-"}
    return status
