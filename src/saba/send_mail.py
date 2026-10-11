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
from typing import Callable, Mapping

ROOT = Path(__file__).resolve().parents[2]
EML_PATH = ROOT / "output" / "newsletter_mail_preview.eml"
TEST_ADDRESS = "ch.seo@tbell.co.kr"  # 서명 원본의 본인 주소. 보낸 사람·받는 사람 모두 이 주소만 허용한다.
PORT = 465  # SSL/TLS (연결 시작부터 암호화, STARTTLS 아님)
TIMEOUT = 30
ENV_HOST, ENV_USER, ENV_PASSWORD = "SABA_SMTP_HOST", "SABA_SMTP_USER", "SABA_SMTP_PASSWORD"


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


def send_test(message: EmailMessage, *, send: bool = False, env: Mapping[str, str] = os.environ,
              smtp_factory: Callable[..., smtplib.SMTP_SSL] = smtplib.SMTP_SSL) -> str:
    """드라이런이면 접속하지 않고 요약만 돌려준다. send=True 면 1회 발송, 재시도 없음."""
    message = prepare(message)
    size = len(message.as_bytes())
    present = {name: bool(env.get(name, "").strip()) for name in (ENV_HOST, ENV_USER, ENV_PASSWORD)}
    summary = (f"받는 사람 {TEST_ADDRESS} 1명 · 메시지 {size:,} bytes · 포트 {PORT} SSL/TLS · 환경 변수 "
               + ", ".join(f"{name} {'있음' if ok else '없음'}" for name, ok in present.items()))
    if not send:
        return "드라이런 (접속·발송 안 함): " + summary
    if not all(present.values()):
        raise SendError("SMTP 환경 변수가 설정되지 않았습니다. " + summary)
    stage = "연결"
    try:
        with smtp_factory(env[ENV_HOST].strip(), PORT, context=ssl.create_default_context(),
                          timeout=TIMEOUT) as server:
            stage = "로그인"
            server.login(env[ENV_USER].strip(), env[ENV_PASSWORD])
            stage = "발송"
            refused = server.send_message(message, from_addr=TEST_ADDRESS, to_addrs=[TEST_ADDRESS])
            stage = "종료"  # 여기부터의 오류는 with 종료 시 QUIT 응답이다. 메시지는 이미 서버가 받았다.
    except smtplib.SMTPAuthenticationError:
        raise SendError("SMTP 인증 실패 (아이디·비밀번호·SMTP 사용 설정 확인)") from None
    except smtplib.SMTPException as error:
        # 단계와 응답 코드 숫자만 남긴다. 서버 응답 문장은 계정 정보를 담을 수 있어 표시하지 않는다.
        code = getattr(error, "smtp_code", None)
        code_text = f"응답 코드 {code}" if isinstance(code, int) else "응답 코드 없음"
        if stage != "종료":
            raise SendError(f"SMTP 오류: {stage} 단계, {type(error).__name__}, {code_text}") from None
        refused = {}
        summary += f" · 종료(QUIT) 응답 비정상 ({code_text}), 받은 편지함 확인 필요"
    except (OSError, ssl.SSLError) as error:
        raise SendError(f"SMTP 연결 실패: {stage} 단계, {type(error).__name__} (서버명·포트·네트워크 확인)") from None
    if refused:
        raise SendError("수신 서버가 TEST 주소를 거부했습니다.")
    return "발송 완료 1회: " + summary


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
