"""회사 메일 TEST 발송 (D-045). 기본은 드라이런이고, --send 일 때만 고정 TEST 주소로 1회 보낸다.

접속 정보는 환경 변수로만 받는다. 값(서버명·아이디·비밀번호)은 출력·로그·오류 메시지에 남기지 않는다.
"""

import argparse
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import SMTP
import os
from pathlib import Path
import smtplib
import ssl
import time
from typing import Callable, Mapping

ROOT = Path(__file__).resolve().parents[2]
EML_PATH = ROOT / "output" / "newsletter_mail_preview.eml"
TEST_ADDRESS = "ch.seo@tbell.co.kr"  # 서명 원본의 본인 주소. 보낸 사람·받는 사람 모두 이 주소만 허용한다.
PORT = 465  # SSL/TLS (연결 시작부터 암호화, STARTTLS 아님)
TIMEOUT = 30
ENV_HOST, ENV_USER, ENV_PASSWORD = "SABA_SMTP_HOST", "SABA_SMTP_USER", "SABA_SMTP_PASSWORD"
# D-076: 그룹 발송 잠금. 회사 IT·보안 정책 확인과 별도 승인 뒤에만 True 로 바꾼다 (관리 화면에서는 켤 수 없음).
# 꺼져 있으면 발송 대상 설정과 관계없이 고정 TEST 주소 1명에게만 보낸다.
GROUP_SEND_APPROVED = False
PAUSE_SECONDS = 1.0  # 개별 발송 사이 쉬는 시간 (회사 메일 서버 부담 줄이기)


class SendError(Exception):
    """Secret 없이 실패 종류만 담는다."""


def prepare(message: EmailMessage) -> EmailMessage:
    """보낸 사람·받는 사람을 TEST 주소로 고정한다. 다른 수신자 헤더가 있으면 거부한다."""
    for header in ("To", "Cc", "Bcc", "From"):
        value = message.get(header)
        if value is not None and value.strip().lower() != TEST_ADDRESS:
            raise SendError(f"허용되지 않은 {header} 주소가 있습니다. TEST 주소만 허용합니다.")
        del message[header]
    message["From"] = TEST_ADDRESS
    message["To"] = TEST_ADDRESS
    return message


def _code_text(error: Exception) -> str:
    code = getattr(error, "smtp_code", None)
    return f"응답 코드 {code}" if isinstance(code, int) else "응답 코드 없음"


SMTP_VERBS = {"EHLO", "HELO", "AUTH", "MAIL", "RCPT", "DATA", "RSET", "NOOP", "QUIT", "STARTTLS"}


def trace_codes(server) -> list[str]:
    """명령 이름과 응답 코드 순서만 기록한다 (D-049). 명령 인자·인증 데이터·응답 문장은 남기지 않는다."""
    trace: list[str] = []
    putcmd, getreply = server.putcmd, server.getreply

    def traced_putcmd(cmd, args=""):
        verb = str(cmd).split(" ", 1)[0].upper()
        trace.append(verb if verb in SMTP_VERBS else "(인증 데이터)")
        return putcmd(cmd, args)

    def traced_getreply():
        reply = getreply()
        trace.append(str(reply[0]))
        return reply

    server.putcmd, server.getreply = traced_putcmd, traced_getreply
    return trace


def _quit(server) -> str | None:
    """연결을 닫는다. QUIT 실패는 경고 문자열로만 돌려주고 원래 결과·오류를 바꾸지 않는다."""
    if server is None:
        return None
    try:
        server.quit()
        return None
    except (smtplib.SMTPException, OSError) as error:
        server.close()
        return _code_text(error)


def send_test(message: EmailMessage, *, send: bool = False, env: Mapping[str, str] = os.environ,
              smtp_factory: Callable[..., smtplib.SMTP_SSL] = smtplib.SMTP_SSL, login_only: bool = False) -> str:
    """드라이런이면 접속하지 않고 요약만 돌려준다. send=True 면 1회 발송, 재시도 없음.

    login_only=True 면 연결·인증까지만 확인하고 메시지는 보내지 않는다 (관리 페이지 SMTP 확인, D-067).
    """
    message = prepare(message)
    size = len(message.as_bytes())
    present = {name: bool(env.get(name, "").strip()) for name in (ENV_HOST, ENV_USER, ENV_PASSWORD)}
    summary = (f"받는 사람 {TEST_ADDRESS} 1명 · 메시지 {size:,} bytes · 포트 {PORT} SSL/TLS · 환경 변수 "
               + ", ".join(f"{name} {'있음' if ok else '없음'}" for name, ok in present.items()))
    if not send:
        return "드라이런 (접속·발송 안 함): " + summary
    if not all(present.values()):
        raise SendError("SMTP 환경 변수가 설정되지 않았습니다. " + summary)
    # with 문은 쓰지 않는다. 발송 오류 뒤 with 종료의 QUIT 오류가 원래 오류를 덮어 원인이 가려졌다 (D-047).
    stage, server, trace = "연결", None, []
    try:
        server = smtp_factory(env[ENV_HOST].strip(), PORT, context=ssl.create_default_context(), timeout=TIMEOUT)
        trace = trace_codes(server)
        stage = "로그인"
        ehlo_code = server.ehlo()[0]
        # login() 의 자동 선택(CRAM-MD5 → PLAIN → LOGIN) 은 쓰지 않는다. 실제 서버가 CRAM-MD5 에 비정상 응답을
        # 보내 이후 응답이 한 칸씩 밀렸다 (응답 순서 EHLO 250 AUTH 334 데이터 -1 AUTH 535 AUTH 235 MAIL 503, D-050).
        # PLAIN 한 가지만 쓴다. 연결이 처음부터 SSL/TLS 라 PLAIN 도 암호화된 채로 전달된다.
        server.user, server.password = env[ENV_USER].strip(), env[ENV_PASSWORD]
        auth_code = server.auth("PLAIN", server.auth_plain)[0]
        # smtplib 은 AUTH 응답 503("이미 인증됨")도 성공으로 본다. 235 만 인증 성공으로 인정한다 (D-048).
        if auth_code != 235:
            raise SendError(f"SMTP 인증 미완료: EHLO 응답 코드 {ehlo_code}, AUTH 응답 코드 {auth_code}"
                            f" (지원 인증 방식 {server.esmtp_features.get('auth', '없음').split()})")
        stage = "발송"
        refused = {} if login_only else server.send_message(message, from_addr=TEST_ADDRESS, to_addrs=[TEST_ADDRESS])
    except smtplib.SMTPAuthenticationError:
        raise SendError("SMTP 인증 실패 (아이디·비밀번호·SMTP 사용 설정 확인)") from None
    except smtplib.SMTPException as error:
        # 단계와 응답 코드 숫자만 남긴다. 서버 응답 문장은 계정 정보를 담을 수 있어 표시하지 않는다.
        raise SendError(f"SMTP 오류: {stage} 단계, {type(error).__name__}, {_code_text(error)}"
                        f" · 응답 순서: {' '.join(trace) or '없음'}") from None
    except (OSError, ssl.SSLError) as error:
        raise SendError(f"SMTP 연결 실패: {stage} 단계, {type(error).__name__} (서버명·포트·네트워크 확인)") from None
    finally:
        quit_warning = _quit(server)
    if quit_warning:
        summary += f" · 종료(QUIT) 응답 비정상 ({quit_warning}), 받은 편지함 확인 필요"
    if refused:
        raise SendError("수신 서버가 TEST 주소를 거부했습니다.")
    return ("SMTP 연결·인증 확인 완료 (발송 없음): " if login_only else "발송 완료 1회: ") + summary


def _login(env: Mapping[str, str], smtp_factory):
    server = smtp_factory(env[ENV_HOST].strip(), PORT, context=ssl.create_default_context(), timeout=TIMEOUT)
    server.ehlo()
    server.user, server.password = env[ENV_USER].strip(), env[ENV_PASSWORD]
    if server.auth("PLAIN", server.auth_plain)[0] != 235:  # D-048, D-050 과 같은 기준
        _quit(server)
        raise SendError("SMTP 인증 미완료")
    return server


def send_group(message: EmailMessage, emails: list[str], *, env: Mapping[str, str] = os.environ,
               smtp_factory: Callable[..., smtplib.SMTP_SSL] = smtplib.SMTP_SSL, allowed: bool | None = None,
               pause: float = PAUSE_SECONDS, sleep: Callable[[float], None] = time.sleep) -> list:
    """수신자마다 1통 개별 발송 (D-076). 받는 사람 칸에는 본인만. 한 번 로그인해 차례로 보내고, 실패는 사람별로 기록한다.

    잠금 (GROUP_SEND_APPROVED) 이 꺼져 있으면 접속하지 않고 거부한다. 재시도는 연결이 끊긴 경우 다시 로그인해 그 사람에게 1번만.
    """
    from saba.sendlog import Result
    if not (GROUP_SEND_APPROVED if allowed is None else allowed):
        raise SendError("그룹 발송은 잠겨 있습니다 (별도 승인 전에는 TEST 주소 1명에게만 발송).")
    if not all(env.get(name, "").strip() for name in (ENV_HOST, ENV_USER, ENV_PASSWORD)):
        raise SendError("SMTP 환경 변수가 설정되지 않았습니다.")
    for header in ("Cc", "Bcc", "From", "To"):
        del message[header]
    message["From"] = TEST_ADDRESS
    results, server = [], None
    try:
        try:
            server = _login(env, smtp_factory)
        except smtplib.SMTPAuthenticationError:
            raise SendError("SMTP 인증 실패 (아이디·비밀번호·SMTP 사용 설정 확인)") from None
        except (smtplib.SMTPException, OSError) as error:
            raise SendError(f"SMTP 연결 실패: {type(error).__name__}") from None
        for index, email in enumerate(emails):
            del message["To"]
            message["To"] = email
            for attempt in (1, 2):
                try:
                    refused = server.send_message(message, from_addr=TEST_ADDRESS, to_addrs=[email])
                    results.append(Result(email, not refused, "거부됨" if refused else "성공"))
                    break
                except smtplib.SMTPServerDisconnected:
                    if attempt == 2:
                        results.append(Result(email, False, "연결 끊김"))
                        break
                    try:
                        server = _login(env, smtp_factory)
                    except (SendError, smtplib.SMTPException, OSError):
                        server = None  # 다시 접속하지 못하면 남은 사람은 모두 실패로 남긴다 (나중에 실패한 사람만 다시 보내기)
                        results += [Result(rest, False, "재접속 실패") for rest in emails[index:]]
                        return results
                except smtplib.SMTPException as error:
                    results.append(Result(email, False, f"{type(error).__name__}, {_code_text(error)}"))
                    break
            if pause and index < len(emails) - 1:
                sleep(pause)
    finally:
        _quit(server)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true", help="실제로 TEST 주소에 1회 발송 (승인 후에만 사용)")
    parser.add_argument("--eml", type=Path, default=EML_PATH, help="보낼 .eml (기본: output/newsletter_mail_preview.eml)")
    args = parser.parse_args()
    message = message_from_bytes(args.eml.read_bytes(), _class=EmailMessage, policy=SMTP)
    try:
        print(send_test(message, send=args.send))
    except SendError as error:
        print(f"발송하지 않음: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
