"""매일 자동 생성·TEST 발송 (D-061). RSS 수집 → AI 분석·시사점 → 메일 생성 → 고정 TEST 수신자 발송.

한 단계라도 실패하면 그날은 발송하지 않고 로그에 단계·건수만 남긴다. 재시도하지 않는다.
실행: python -m saba.daily --run
작업 스케줄러 등록: python -m saba.daily --register (명령만 출력), --register --apply (실제 등록, 승인 후)
"""

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import logging
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "daily.json"
LOG_DIR = ROOT / "logs"
# 실행 파일 묶음 (D-069) 에서는 SABA.exe 자신이 실행 대상이다.
PYTHON = Path(sys.executable) if getattr(sys, "frozen", False) else ROOT / ".venv" / "Scripts" / "python.exe"
TASK_NAME = "SABA_Daily_Briefing"
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
_DAY_NAMES = {"MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday", "THU": "Thursday", "FRI": "Friday",
              "SAT": "Saturday", "SUN": "Sunday"}


class DailyError(Exception):
    """단계 실패. 메시지에는 단계 이름과 종류만 담는다."""


@dataclass(frozen=True)
class DailyConfig:
    time: str
    random_delay_minutes: int
    weekdays: tuple[str, ...]
    max_analysis_calls: int
    max_insight_calls: int
    send: bool


def load_config(path: Path = CONFIG_PATH) -> DailyConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    config = DailyConfig(time=data["time"], random_delay_minutes=int(data["random_delay_minutes"]),
                         weekdays=tuple(data["weekdays"]), max_analysis_calls=int(data["max_analysis_calls"]),
                         max_insight_calls=int(data["max_insight_calls"]), send=bool(data["send"]))
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", config.time):
        raise DailyError("설정 오류: time 은 HH:MM 형식이어야 합니다.")
    if not config.weekdays or set(config.weekdays) - set(WEEKDAYS):
        raise DailyError("설정 오류: weekdays 는 MON~SUN 중에서 골라야 합니다.")
    if not (0 <= config.random_delay_minutes <= 60 and 0 <= config.max_analysis_calls <= 50
            and 0 <= config.max_insight_calls <= 50):
        raise DailyError("설정 오류: 지연은 0~60분, 하루 호출 상한은 0~50건이어야 합니다.")
    return config


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
        path = output_dir / f"daily_{now.astimezone():%Y%m%d}.eml"
        output_dir.mkdir(exist_ok=True)  # 새 PC·실행 파일 묶음에는 output 폴더가 없다
        path.write_bytes(eml)
        logging.info("메일 생성 완료: %s · %s · %s bytes", path.name, summary, f"{len(eml):,}")
        if not config.send:
            logging.info("설정 send=false: 발송하지 않음")
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
    days = ",".join(_DAY_NAMES[day] for day in config.weekdays)
    command = (f"$t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek {days} -At {config.time}"
               f" -RandomDelay (New-TimeSpan -Minutes {config.random_delay_minutes}); "
               f"$a = New-ScheduledTaskAction -Execute '{python}' -Argument '-m saba.daily --run' -WorkingDirectory '{ROOT}'; ")
    if not unattended:
        return command + f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Trigger $t -Action $a -Force | Out-Null"
    return command + ("$s = New-ScheduledTaskSettingsSet -StartWhenAvailable; "
                      r'$c = Get-Credential -UserName "$env:USERDOMAIN\$env:USERNAME" '
                      "-Message 'SABA 자동 실행용 Windows 계정 비밀번호 (저장하지 않음)'; "
                      f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Trigger $t -Action $a -Settings $s "
                      "-User $c.UserName -Password $c.GetNetworkCredential().Password -Force | Out-Null")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", action="store_true", help="오늘 분량 실행 (수집 → 분석 → 메일 → 발송)")
    group.add_argument("--register", action="store_true", help="작업 스케줄러 등록 명령 출력 (--apply 로 실제 등록)")
    parser.add_argument("--apply", action="store_true", help="--register 와 함께: 실제로 작업 스케줄러에 등록 (승인 후)")
    parser.add_argument("--unattended", action="store_true",
                        help="--register 와 함께: 로그인 없이 실행 + 놓친 실행 보완 (부서 PC, D-068)")
    args = parser.parse_args()
    config = load_config()
    if args.register:
        command = register_command(config, unattended=args.unattended)
        if not args.apply:
            print(command)
            return 0
        return subprocess.run(["powershell", "-NoProfile", "-Command", command]).returncode
    now = datetime.now().astimezone()
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(filename=LOG_DIR / f"daily_{now:%Y%m%d}.log", level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")
    return run_daily(now, config)


if __name__ == "__main__":
    raise SystemExit(main())
