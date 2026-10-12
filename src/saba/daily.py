"""매일 자동 생성·TEST 발송 (D-061). RSS 수집 → AI 분석·시사점 → 메일 생성 → 고정 TEST 수신자 발송.

한 단계라도 실패하면 그날은 발송하지 않고 로그에 단계·건수만 남긴다. 재시도하지 않는다.
실행: python -m saba.daily --run
작업 스케줄러 등록: python -m saba.daily --register (명령만 출력), --register --apply (실제 등록, 승인 후)
"""

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "daily.json"
LOG_DIR = ROOT / "logs"
LOCK_PATH = ROOT / "data" / "daily.lock"
# 실행 파일 묶음 (D-069) 에서는 SABA.exe 자신이 실행 대상이다.
PYTHON = Path(sys.executable) if getattr(sys, "frozen", False) else ROOT / ".venv" / "Scripts" / "python.exe"
TASK_NAME = "SABA_Daily_Briefing"
TEST_TASK_NAME = "SABA_Test_Send"  # 시각 지정 테스트 발송용 1회 작업 (D-073)
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


class DailyError(Exception):
    """단계 실패. 메시지에는 단계 이름과 종류만 담는다."""


MODES = ("daily", "weekly", "monthly", "dates")  # 매일·매주·매월·특정 날짜 (D-072)


@dataclass(frozen=True)
class DailyConfig:
    time: str
    random_delay_minutes: int
    weekdays: tuple[str, ...]
    max_analysis_calls: int
    max_insight_calls: int
    send: bool
    mode: str = "weekly"
    month_days: tuple[int, ...] = ()
    dates: tuple[str, ...] = ()
    log_days: int = 90  # 보관 기간 (D-072)
    mail_days: int = 30


def parse_config(data: dict) -> DailyConfig:
    """설정 값 검증. 관리 페이지 저장도 같은 규칙을 쓴다 (D-072)."""
    try:
        config = DailyConfig(
            time=str(data["time"]), random_delay_minutes=int(data["random_delay_minutes"]),
            weekdays=tuple(data.get("weekdays", ())), max_analysis_calls=int(data["max_analysis_calls"]),
            max_insight_calls=int(data["max_insight_calls"]), send=bool(data["send"]),
            mode=str(data.get("mode", "weekly")), month_days=tuple(int(d) for d in data.get("month_days", ())),
            dates=tuple(str(d) for d in data.get("dates", ())), log_days=int(data.get("log_days", 90)),
            mail_days=int(data.get("mail_days", 30)))
    except (KeyError, TypeError, ValueError):
        raise DailyError("설정 오류: 필수 항목이 없거나 숫자 형식이 아닙니다.") from None
    if config.mode not in MODES:
        raise DailyError("설정 오류: 반복은 매일·매주·매월·특정 날짜 중 하나여야 합니다.")
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", config.time):
        raise DailyError("설정 오류: 시각은 HH:MM 형식이어야 합니다.")
    if set(config.weekdays) - set(WEEKDAYS) or (config.mode == "weekly" and not config.weekdays):
        raise DailyError("설정 오류: 매주 반복은 요일을 하나 이상 골라야 합니다.")
    if any(not 1 <= day <= 31 for day in config.month_days) or (config.mode == "monthly" and not config.month_days):
        raise DailyError("설정 오류: 매월 반복은 1~31일 중 하나 이상 골라야 합니다.")
    for value in config.dates:
        try:
            date.fromisoformat(value)
        except ValueError:
            raise DailyError(f"설정 오류: 날짜 형식이 아닙니다 ({value[:20]}).") from None
    if config.mode == "dates" and not config.dates:
        raise DailyError("설정 오류: 특정 날짜 반복은 날짜를 하나 이상 넣어야 합니다.")
    if not (0 <= config.random_delay_minutes <= 30 and 0 <= config.max_analysis_calls <= 50
            and 0 <= config.max_insight_calls <= 50):
        raise DailyError("설정 오류: 무작위 지연은 0~30분, 하루 호출 상한은 0~50건이어야 합니다.")
    if not (7 <= config.log_days <= 3650 and 1 <= config.mail_days <= 3650):
        raise DailyError("설정 오류: 로그 보관은 7~3650일, 메일 보관은 1~3650일이어야 합니다.")
    return config


def load_config(path: Path = CONFIG_PATH) -> DailyConfig:
    return parse_config(json.loads(path.read_text(encoding="utf-8")))


def config_dict(config: DailyConfig) -> dict:
    data = asdict(config)
    for key in ("weekdays", "month_days", "dates"):
        data[key] = list(data[key])
    return data


def save_config(config: DailyConfig, path: Path = CONFIG_PATH) -> None:
    path.write_text(json.dumps(config_dict(config), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def scheduled_on(config: DailyConfig, day: date) -> bool:
    """예약 발송 날짜인지. 작업 스케줄러는 매일 깨우고 날짜는 여기서 판단한다 (D-072)."""
    if config.mode == "daily":
        return True
    if config.mode == "weekly":
        return WEEKDAYS[day.weekday()] in config.weekdays
    if config.mode == "monthly":
        return day.day in config.month_days
    return day.isoformat() in config.dates


def next_runs(config: DailyConfig, now: datetime, count: int = 5) -> list[datetime]:
    """다음 예약 시각 (무작위 지연 전). 400일 안에서 찾는다."""
    hour, minute = map(int, config.time.split(":"))
    runs = []
    for offset in range(400):
        day = now.date() + timedelta(days=offset)
        at = datetime.combine(day, datetime.min.time(), now.tzinfo).replace(hour=hour, minute=minute)
        if at > now and scheduled_on(config, day):
            runs.append(at)
            if len(runs) == count:
                break
    return runs


def collect_rss() -> None:
    """기존 수집 명령을 그대로 쓴다. Source 하나라도 실패하면 단계 실패로 본다."""
    result = subprocess.run([sys.executable, "-m", "saba", "--collect-rss"], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise DailyError(f"RSS 수집 실패 (종료 코드 {result.returncode})")


def build_mail(now: datetime, config: DailyConfig) -> tuple[bytes, str]:
    """분석·시사점 (하루 상한 안에서) 과 메일 .eml 생성. (.eml 바이트, 요약 문구)."""
    from saba.analysis_storage import DEFAULT_ANALYSIS_DB
    from saba.briefing import build_views
    from saba.mail import build_message, to_mail_html
    from saba.storage import DEFAULT_DB

    views, _selection, stats = build_views(DEFAULT_DB, DEFAULT_ANALYSIS_DB, now,
                                           max_new_calls=config.max_analysis_calls,
                                           insight_calls=config.max_insight_calls)
    if not views:
        raise DailyError("메일 생성 실패 (표시할 기사 0건)")
    local = now.astimezone()
    today = f"{local.year}년 {local.month}월 {local.day}일 {'월화수목금토일'[local.weekday()]}요일"
    message = build_message(to_mail_html(views, today=today), f"[TEST] Security & AI Briefing · {today}")
    summary = (f"표시 {len(views)}건 · 분석 재사용 {stats.reused} · 신규 {stats.called} · 실패 {len(stats.failed)}"
               f" · 시사점 재사용 {stats.insights_reused} · 신규 {stats.insights_called} · 실패 {stats.insights_failed}")
    return message.as_bytes(), summary


def send(eml: bytes) -> str:
    from email import message_from_bytes
    from email.message import EmailMessage
    from email.policy import SMTP

    from saba.send_mail import send_test
    return send_test(message_from_bytes(eml, _class=EmailMessage, policy=SMTP), send=True)


def run_daily(now: datetime, config: DailyConfig, *, output_dir: Path = ROOT / "output",
              collect: Callable[[], None] = collect_rss,
              build: Callable[[datetime, DailyConfig], tuple[bytes, str]] = build_mail,
              deliver: Callable[[bytes], str] = send) -> int:
    """단계별 실행. 실패하면 이후 단계(발송 포함) 를 하지 않는다. 종료 코드 0 = 성공."""
    stage = "RSS 수집"
    try:
        collect()
        logging.info("RSS 수집 완료")
        stage = "분석·메일 생성"
        eml, summary = build(now, config)
        path = output_dir / f"daily_{now.astimezone():%Y%m%d_%H%M}.eml"  # 실행마다 따로 보관 (D-072)
        output_dir.mkdir(exist_ok=True)  # 새 PC·실행 파일 묶음에는 output 폴더가 없다
        path.write_bytes(eml)
        logging.info("메일 생성 완료: %s · %s · %s bytes", path.name, summary, f"{len(eml):,}")
        if not config.send:
            logging.info("발송하지 않음 (send=false)")
            return 0
        stage = "발송"
        logging.info(deliver(eml))
        return 0
    except Exception as error:  # 단계 실패는 종류만 남기고 발송하지 않는다 (재시도 없음).
        detail = str(error) if isinstance(error, DailyError) or type(error).__name__ == "SendError" else type(error).__name__
        logging.error("%s 단계 실패: %s · 오늘은 발송하지 않음", stage, detail)
        return 1


def register_command(config: DailyConfig, python: Path = PYTHON, *,
                     unattended: bool = False) -> str:
    """작업 스케줄러 등록 PowerShell 명령. 시각·요일·무작위 지연은 설정 파일에서 읽는다.

    unattended=True (부서 PC, D-068): 로그인 없이 실행 + 놓친 실행 보완. Windows 계정 비밀번호는 실행 때
    입력 창으로만 받고 명령·파일·로그에 남기지 않는다.
    """
    # 매일 같은 시각에 깨우고 예약 날짜인지는 --run 이 설정으로 판단한다 (매월·특정 날짜 지원, D-072).
    command = (f"$t = New-ScheduledTaskTrigger -Daily -At {config.time}"
               f" -RandomDelay (New-TimeSpan -Minutes {config.random_delay_minutes}); "
               f"$a = New-ScheduledTaskAction -Execute '{python}' -Argument '-m saba.daily --run' -WorkingDirectory '{ROOT}'; ")
    if not unattended:
        return command + f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Trigger $t -Action $a -Force | Out-Null"
    return command + ("$s = New-ScheduledTaskSettingsSet -StartWhenAvailable; "
                      r'$c = Get-Credential -UserName "$env:USERDOMAIN\$env:USERNAME" '
                      "-Message 'SABA 자동 실행용 Windows 계정 비밀번호 (저장하지 않음)'; "
                      f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Trigger $t -Action $a -Settings $s "
                      "-User $c.UserName -Password $c.GetNetworkCredential().Password -Force | Out-Null")


def test_task_command(at: datetime, python: Path = PYTHON) -> str:
    """시각 지정 테스트 발송 (D-073): 평소 예약과 별개인 1회용 작업. 같은 이름으로 다시 등록하면 바뀐다."""
    return (f"$t = New-ScheduledTaskTrigger -Once -At '{at:%Y-%m-%dT%H:%M:00}'; "
            f"$a = New-ScheduledTaskAction -Execute '{python}' -Argument '-m saba.daily --run --test' -WorkingDirectory '{ROOT}'; "
            f"Register-ScheduledTask -TaskName '{TEST_TASK_NAME}' -Trigger $t -Action $a -Force | Out-Null")


@contextmanager
def run_lock(path: Path = LOCK_PATH):
    """동시 실행 막기 (D-071). 자동·수동 실행이 겹쳐도 하나만 돈다.

    파일 잠금이라 프로세스가 비정상 종료돼도 OS 가 풀어 준다 (남은 파일 때문에 막히지 않는다).
    """
    path.parent.mkdir(exist_ok=True)
    handle = open(path, "a+b")
    try:
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise DailyError("이미 실행 중입니다") from None
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        handle.close()


def is_running(path: Path = LOCK_PATH) -> bool:
    if not path.exists():
        return False
    try:
        with run_lock(path):
            return False
    except DailyError:
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", action="store_true", help="오늘 분량 실행 (수집 → 분석 → 메일 → 발송)")
    group.add_argument("--register", action="store_true", help="작업 스케줄러 등록 명령 출력 (--apply 로 실제 등록)")
    parser.add_argument("--apply", action="store_true", help="--register 와 함께: 실제로 작업 스케줄러에 등록 (승인 후)")
    parser.add_argument("--unattended", action="store_true",
                        help="--register 와 함께: 로그인 없이 실행 + 놓친 실행 보완 (부서 PC, D-068)")
    parser.add_argument("--no-send", action="store_true", help="--run 과 함께: 메일 생성까지만 (발송 없음)")
    parser.add_argument("--manual", action="store_true", help="--run 과 함께: 관리 페이지 수동 실행으로 기록")
    parser.add_argument("--test", action="store_true", help="--run 과 함께: 테스트 발송으로 기록 (예약일과 관계없이 실행, D-073)")
    args = parser.parse_args()
    config = load_config()
    if args.register:
        command = register_command(config, unattended=args.unattended)
        if not args.apply:
            print(command)
            return 0
        return subprocess.run(["powershell", "-NoProfile", "-Command", command]).returncode
    now = datetime.now().astimezone()
    if not (args.manual or args.test) and not scheduled_on(config, now.date()):
        return 0  # 예약일이 아니다 (작업 스케줄러는 매일 깨운다, D-072). 로그도 남기지 않는다.
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(filename=LOG_DIR / f"daily_{now:%Y%m%d}.log", level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")
    if args.manual or args.test:  # 지금 발송·테스트 발송은 설정의 발송 여부와 관계없이 보낸다 (--no-send 제외)
        config = replace(config, send=not args.no_send)
    elif args.no_send:
        config = replace(config, send=False)
    if args.test:
        origin = "테스트 발송 (즉시)" if args.manual else "테스트 발송 (예약)"
    else:
        origin = "관리 페이지 수동 실행" if args.manual else "자동 실행"
    try:
        with run_lock(LOCK_PATH):
            logging.info("실행 시작: %s (%s)", origin, "발송 포함" if config.send else "발송 없이")
            from saba.history import cleanup
            removed = cleanup(ROOT, config.log_days, config.mail_days, now.date())
            if any(removed):
                logging.info("보관 기간 정리: 로그 %s개, 메일 %s개 삭제", *removed)
            return run_daily(now, config)
    except DailyError as error:  # 잠금 실패만 여기로 온다 (run_daily 는 자체 처리)
        logging.warning("%s: %s · 이번 실행은 건너뜀", origin, error)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
