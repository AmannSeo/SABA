"""매일 자동 생성·TEST 발송 (D-061). RSS 수집 → AI 분석·시사점 → 메일 생성 → 고정 TEST 수신자 발송.

한 단계라도 실패하면 그날은 발송하지 않고 로그에 단계·건수만 남긴다. 재시도하지 않는다.
실행: python -m saba.daily --run
작업 스케줄러 등록: python -m saba.daily --register (명령만 출력), --register --apply (실제 등록, 승인 후)
"""

import argparse
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
import hashlib
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


# 하루 AI 호출 상한 최대값: 섹션 6개 × 섹션당 10건 = 하루 1회 실행 최대 필요량 (2026-10-14 사용자 결정, D-080)
MAX_DAILY_CALLS = 60


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
    target_group: str = "TEST"  # 발송 대상 그룹 (D-076). 그룹 발송 잠금이 풀리기 전에는 TEST 주소 1명만


def parse_config(data: dict) -> DailyConfig:
    """설정 값 검증. 관리 페이지 저장도 같은 규칙을 쓴다 (D-072)."""
    try:
        config = DailyConfig(
            time=str(data["time"]), random_delay_minutes=int(data["random_delay_minutes"]),
            weekdays=tuple(data.get("weekdays", ())), max_analysis_calls=int(data["max_analysis_calls"]),
            max_insight_calls=int(data["max_insight_calls"]), send=bool(data["send"]),
            mode=str(data.get("mode", "weekly")), month_days=tuple(int(d) for d in data.get("month_days", ())),
            dates=tuple(str(d) for d in data.get("dates", ())), log_days=int(data.get("log_days", 90)),
            mail_days=int(data.get("mail_days", 30)), target_group=str(data.get("target_group", "TEST")).strip())
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
    if not (0 <= config.random_delay_minutes <= 30 and 0 <= config.max_analysis_calls <= MAX_DAILY_CALLS
            and 0 <= config.max_insight_calls <= MAX_DAILY_CALLS):
        raise DailyError(f"설정 오류: 무작위 지연은 0~30분, 하루 호출 상한은 0~{MAX_DAILY_CALLS}건이어야 합니다.")
    if not 1 <= len(config.target_group) <= 20:
        raise DailyError("설정 오류: 발송 대상 그룹 이름이 필요합니다.")
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
    """기존 수집 명령을 그대로 쓴다. 절반 이상 실패하면 단계 실패, 일부 실패는 로그에 남기고 계속 (D-078)."""
    result = subprocess.run([sys.executable, "-m", "saba", "--collect-rss"], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    partial = re.search(r"RSS 일부 수집 실패 (\d+)개 \(([^)]*)\)", result.stdout + result.stderr)
    if result.returncode == 0 and partial:
        logging.warning("RSS 일부 수집 실패 %s개 (%s) · 나머지로 계속", partial.group(1), partial.group(2))
    if result.returncode != 0:
        # 실패한 Source 이름만 남긴다 (수집 요약 줄 "실패 n개 (id, ...)", 원문·응답 내용은 남기지 않음).
        failed = re.search(r"실패 \d+개 \(([^)]*)\)", result.stdout + result.stderr)
        detail = f": {failed.group(1)}" if failed else ""
        raise DailyError(f"RSS 수집 실패 (종료 코드 {result.returncode}{detail})")


def build_mail(now: datetime, config: DailyConfig) -> tuple[bytes, str]:
    """분석·시사점 (하루 상한 안에서) 과 메일 .eml 생성. (.eml 바이트, 요약 문구)."""
    from saba.analysis_storage import DEFAULT_ANALYSIS_DB
    from saba.briefing import build_views
    from saba.mail import build_message, to_mail_html
    from saba.storage import DEFAULT_DB

    views, _selection, stats = build_views(DEFAULT_DB, DEFAULT_ANALYSIS_DB, now,
                                           max_new_calls=config.max_analysis_calls,
                                           insight_calls=config.max_insight_calls, daily_caps=True, analyzed_only=True)
    if stats is not None and stats.auth_failed:
        logging.warning("AI 분석 인증 실패: OPENAI_API_KEY 확인 필요 · 이후 분석 호출 중단, 분석 없는 기사는 원문 발췌로 표시")
    if not views:
        raise DailyError("메일 생성 실패 (표시할 기사 0건)")
    local = now.astimezone()
    today = f"{local.year}년 {local.month}월 {local.day}일 {'월화수목금토일'[local.weekday()]}요일"
    message = build_message(to_mail_html(views, today=today), f"[TEST] Security & AI Briefing · {today}")
    summary = (f"표시 {len(views)}건 · 분석 재사용 {stats.reused} · 신규 {stats.called} · 실패 {len(stats.failed)}"
               f" · 분석 없음 제외 {stats.dropped_unanalyzed}"
               f" · 시사점 재사용 {stats.insights_reused} · 신규 {stats.insights_called} · 실패 {stats.insights_failed}")
    return message.as_bytes(), summary


def send(eml: bytes, mail_file: str = "") -> str:
    from email import message_from_bytes
    from email.message import EmailMessage
    from email.policy import SMTP

    from saba.send_mail import send_test
    return send_test(message_from_bytes(eml, _class=EmailMessage, policy=SMTP), send=True)


class PartialSendError(DailyError):
    """그룹 발송에 실패·불명확·미시도가 있다 (D-077): 성공 인원은 이력에 남기고 실행은 실패 (종료 코드 1)."""


def _counts_text(counts: dict) -> str:
    return " · ".join(f"{name} {counts.get(name, 0)}" for name in ("성공", "실패", "불명확", "미시도"))


def open_round(origin: str, target: str, emails: list[str], *, mail_file: str, mail_sha256: str, history: Path,
               parent_id: int | None = None) -> int:
    """발송 회차를 먼저 만든다. 만들지 못하면 (DB 잠김·예전 형식 등) 아무에게도 보내지 않았으므로 DailyError."""
    from saba import sendlog
    try:
        return sendlog.start(origin, target, emails, mail_file=mail_file, mail_sha256=mail_sha256, parent_id=parent_id,
                             path=history)
    except sendlog.SendLogError as error:
        raise DailyError(f"{error} (보내기 전이라 아무에게도 보내지 않음)") from None


def deliver_group(message, emails: list[str], *, origin: str, target: str, mail_file: str, mail_sha256: str,
                  history: Path, parent_id: int | None = None) -> str:
    """회차를 먼저 만들고 (기록 실패면 보내지 않음) 한 명씩 결과를 저장하며 보낸다. 로그용 문구에는 인원만."""
    from saba import send_mail, sendlog
    send_id = open_round(origin, target, emails, mail_file=mail_file, mail_sha256=mail_sha256, history=history,
                         parent_id=parent_id)
    try:
        send_mail.send_group(message, emails, log=lambda email, status, detail: sendlog.mark(send_id, email, status, detail, history))
    finally:
        sendlog.finish(send_id, history)
    counts = next(item for item in sendlog.sends(history) if item.id == send_id).counts
    text = f"{target} {len(emails)}명 중 {_counts_text(counts)}"
    if counts.get("성공", 0) != len(emails):
        raise PartialSendError(f"그룹 발송 부분 실패: {text} (실패·미시도는 발송 이력에서 다시 보낼 수 있음, 불명확은 받은 편지함 확인)")
    return f"그룹 발송 완료: {text}"


def send_newsletter(eml: bytes, mail_file: str, *, config: DailyConfig, origin: str,
                    history: Path | None = None, recipients_path: Path | None = None) -> str:
    """발송 대상에 맞춰 보내고 발송 이력을 남긴다 (D-076, D-077).

    그룹 발송 잠금 (send_mail.GROUP_SEND_APPROVED) 이 꺼져 있으면 대상 설정과 관계없이 고정 TEST 주소 1명만.
    로그에는 인원·건수만 쓰고 주소는 발송 이력 DB (관리 화면) 에만 둔다.
    """
    import hashlib
    from email import message_from_bytes
    from email.message import EmailMessage
    from email.policy import SMTP

    from saba import recipients, send_mail, sendlog
    history = history or sendlog.DEFAULT_PATH
    message = message_from_bytes(eml, _class=EmailMessage, policy=SMTP)
    if config.target_group != "TEST" and send_mail.GROUP_SEND_APPROVED:
        emails = [r.email for r in recipients.recipients(recipients_path or recipients.DEFAULT_PATH, config.target_group)
                  if r.enabled]
        if not emails:
            raise DailyError(f"발송 대상 그룹 '{config.target_group}' 에 사용 중인 수신자가 없습니다")
        return deliver_group(message, emails, origin=origin, target=f"{config.target_group} 그룹", mail_file=mail_file,
                             mail_sha256=hashlib.sha256(eml).hexdigest(), history=history)
    # TEST 주소도 그룹과 같은 순서: 회차 → "전송 중" → 보내기 → 결과 → 마침 (D-077). 앞의 두 기록이 실패하면 보내지 않고,
    # 보낸 뒤 기록이 실패하거나 중단되면 "전송 중" 이 불명확으로 남는다.
    address = send_mail.TEST_ADDRESS
    send_id = open_round(origin, "TEST 주소", [address], mail_file=mail_file, mail_sha256=hashlib.sha256(eml).hexdigest(),
                         history=history)
    try:
        try:
            sendlog.mark(send_id, address, sendlog.SENDING, "", history)
        except sendlog.SendLogError as error:
            raise DailyError(f"{error} (보내기 전이라 보내지 않음)") from None
        try:
            text = send_mail.send_test(message, send=True)
        except send_mail.SendError as error:
            # 발송 단계 (메일 전송 중) 오류는 받았는지 알 수 없다. 연결·로그인 단계 오류는 보내지 않은 것이 확실하다.
            status = sendlog.UNCLEAR if "발송 단계" in str(error) else sendlog.FAILED
            with suppress(sendlog.SendLogError):  # 기록 실패면 "전송 중" → 불명확. 원래 오류를 그대로 알린다
                sendlog.mark(send_id, address, status, str(error)[:120], history)
            raise
        sendlog.mark(send_id, address, sendlog.OK, "성공", history)
    finally:
        sendlog.finish(send_id, history)
    locked = " (그룹 발송 잠금: TEST 주소만)" if config.target_group != "TEST" else ""
    return text + locked


def resend_check(send_id: int, *, history: Path | None = None, recipients_path: Path | None = None,
                 output_dir: Path | None = None, allowed: bool | None = None) -> tuple:
    """실패 수신자 재발송 전 검사 (D-077). (원회차, 보낼 주소, 원본 메일 바이트, 건너뛴 인원). 문제가 있으면 DailyError."""
    from saba import recipients, send_mail, sendlog
    history = history or sendlog.DEFAULT_PATH
    original = next((item for item in sendlog.sends(history) if item.id == send_id), None)
    if original is None:
        raise DailyError("발송 이력에 없는 회차입니다")
    if not (send_mail.GROUP_SEND_APPROVED if allowed is None else allowed):
        raise DailyError("그룹 발송 잠금 중에는 재발송할 수 없습니다 (TEST 주소로 대신 보내지 않음)")
    if original.target == "TEST 주소":
        raise DailyError("TEST 주소 회차는 재발송 대상이 아닙니다 (테스트 화면의 즉시 테스트 발송을 쓰세요)")
    targets = sendlog.resend_targets(send_id, history)
    rpath = recipients_path or recipients.DEFAULT_PATH
    current = {r.email: r for r in recipients.recipients(rpath)}
    domains = set(recipients.domains(rpath))
    emails = [e for e in targets if e in current and current[e].enabled and e.rsplit("@", 1)[-1] in domains]
    if not emails:
        raise DailyError("다시 보낼 수신자가 없습니다 (성공·불명확·이미 재발송 성공·중지·삭제된 수신자는 제외)")
    from saba.history import mail_path
    try:
        mail = mail_path(output_dir or ROOT / "output", original.mail_file)
    except ValueError as error:
        raise DailyError(str(error)) from None
    if not mail.is_file():
        raise DailyError("원본 메일 파일이 없습니다 (보관 기간 만료 등). 재발송하지 않습니다")
    data = mail.read_bytes()
    if original.mail_sha256 and hashlib.sha256(data).hexdigest() != original.mail_sha256:
        raise DailyError("원본 메일 파일이 처음 발송 때와 다릅니다. 재발송하지 않습니다")
    return original, emails, data, len(targets) - len(emails)


def resend_failed(send_id: int, **options) -> str:
    """원본 .eml 을 그대로 다시 쓴다 (새 AI 호출·메일 생성 없음). 원회차에 연결된 새 회차로 기록한다."""
    from email import message_from_bytes
    from email.message import EmailMessage
    from email.policy import SMTP

    from saba import sendlog
    original, emails, data, skipped = resend_check(send_id, **options)
    message = message_from_bytes(data, _class=EmailMessage, policy=SMTP)
    text = deliver_group(message, emails, origin=f"실패 재발송 (회차 {send_id})", target=original.target,
                         mail_file=original.mail_file, mail_sha256=original.mail_sha256,
                         history=options.get("history") or sendlog.DEFAULT_PATH, parent_id=send_id)
    return text + (f" · 제외 {skipped}명 (중지·삭제·도메인)" if skipped else "")


def save_mail_file(folder: Path, base: str, data: bytes) -> Path:
    """같은 분에 다시 실행해도 덮어쓰지 않는다 (D-077). 이름이 있으면 -2, -3 을 붙이고, 새 파일로만 연다 ("x")."""
    from saba.history import mail_path
    for number in range(1, 1000):
        path = mail_path(folder, base + ("" if number == 1 else f"-{number}") + ".eml")
        try:
            handle = path.open("xb")
        except FileExistsError:
            continue
        try:
            with handle:
                handle.write(data)
        except OSError:
            path.unlink(missing_ok=True)  # 쓰다 실패한 파일은 남기지 않는다 (발송도 하지 않음)
            raise
        return path
    raise DailyError("메일 파일 이름을 정하지 못했습니다 (같은 분에 1000번 넘게 실행)")


def run_daily(now: datetime, config: DailyConfig, *, output_dir: Path = ROOT / "output",
              collect: Callable[[], None] = collect_rss,
              build: Callable[[datetime, DailyConfig], tuple[bytes, str]] = build_mail,
              deliver: Callable[[bytes, str], str] = send) -> int:
    """단계별 실행. 실패하면 이후 단계(발송 포함) 를 하지 않는다. 종료 코드 0 = 성공."""
    stage = "RSS 수집"
    try:
        collect()
        logging.info("RSS 수집 완료")
        stage = "분석·메일 생성"
        eml, summary = build(now, config)
        from saba.history import mail_path
        local = now.astimezone()
        planned = mail_path(output_dir, f"{local:%y/%m}/daily_{local:%Y%m%d_%H%M}.eml")
        planned.parent.mkdir(parents=True, exist_ok=True)
        mail_path(output_dir, planned.relative_to(output_dir).as_posix())
        path = save_mail_file(planned.parent, planned.stem, eml)
        relative = path.relative_to(output_dir).as_posix()
        logging.info("메일 생성 완료: %s · %s · %s bytes", relative, summary, f"{len(eml):,}")
        if not config.send:
            logging.info("발송하지 않음 (send=false)")
            return 0
        stage = "발송"
        logging.info(deliver(eml, relative))
        return 0
    except PartialSendError as error:  # 일부는 보냈다: "발송하지 않음" 으로 쓰지 않는다 (D-077)
        logging.error("발송 단계 부분 실패: %s", str(error).removeprefix("그룹 발송 부분 실패: "))
        return 1
    except Exception as error:  # 단계 실패는 종류만 남긴다 (재시도 없음).
        logging.error("%s 단계 실패: %s", stage, failure_text(stage, error, "오늘은 발송하지 않음"))
        return 1


def failure_text(stage: str, error: Exception, not_sent: str) -> str:
    """실패 문구. 보낸 뒤일 수 있는 오류 (발송 이력 기록 실패, SMTP 전송 중 오류) 에는 "발송하지 않음" 을 쓰지 않는다 (D-077)."""
    name = type(error).__name__
    detail = str(error) if isinstance(error, DailyError) or name in ("SendError", "SendLogError") else name
    unclear = stage == "발송" and not isinstance(error, DailyError) and (name == "SendLogError" or "발송 단계," in str(error))
    return f"{detail} · " + ("발송 여부 불명확 (발송 이력·받은 편지함 확인)" if unclear else not_sent)


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
    # 절전 중이면 깨워서 실행, 배터리 사용 중에도 실행 (2026-10-15 사용자 결정, D-081). 완전히 꺼져 있던 날은 건너뜀 (D-080).
    wake = "-WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries"
    if not unattended:
        return command + (f"$s = New-ScheduledTaskSettingsSet {wake}; "
                          f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Trigger $t -Action $a -Settings $s -Force | Out-Null")
    return command + (f"$s = New-ScheduledTaskSettingsSet -StartWhenAvailable {wake}; "
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


def resend_main(send_id: int, now: datetime) -> int:
    """실패 수신자 재발송 (관리 화면에서 띄움). 매일 실행과 같은 잠금 안에서 한 번에 하나만."""
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(filename=LOG_DIR / f"daily_{now:%Y%m%d}.log", level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")
    origin = f"실패 재발송 (회차 {send_id})"
    try:
        with run_lock(LOCK_PATH):
            logging.info("실행 시작: %s (발송 포함)", origin)
            try:
                logging.info(resend_failed(send_id))
                return 0
            except PartialSendError as error:
                logging.error("발송 단계 부분 실패: %s", str(error).removeprefix("그룹 발송 부분 실패: "))
            except Exception as error:  # 잠금·검사 실패는 문구, 그 밖은 종류만
                logging.error("발송 단계 실패: %s", failure_text("발송", error, "재발송하지 않음"))
            return 1
    except DailyError as error:
        logging.warning("%s: %s · 이번 실행은 건너뜀", origin, error)
        return 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", action="store_true", help="오늘 분량 실행 (수집 → 분석 → 메일 → 발송)")
    group.add_argument("--register", action="store_true", help="작업 스케줄러 등록 명령 출력 (--apply 로 실제 등록)")
    group.add_argument("--resend", type=int, metavar="회차", help="발송 이력 회차의 실패·미시도 수신자만 다시 보내기 (D-077, 그룹 발송 잠금 중에는 거부)")
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
    if args.resend is not None:
        return resend_main(args.resend, now)
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
            from functools import partial
            return run_daily(now, config, deliver=partial(send_newsletter, config=config, origin=origin))
    except DailyError as error:  # 잠금 실패만 여기로 온다 (run_daily 는 자체 처리)
        logging.warning("%s: %s · 이번 실행은 건너뜀", origin, error)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
