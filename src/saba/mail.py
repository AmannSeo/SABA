"""Newsletter를 메일 앱 호환 HTML과 .eml 메시지로 변환한다 (D-031, D-032). 발송 기능은 없다."""

from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
CSS_PATH = ROOT / "SAMPLE/Codex/v09/style_review_v9.css"
LOGO_PATH = ROOT / "SAMPLE/Codex/v09/LOGO.png"
SIGNATURE_PATH = ROOT / "templates/email_signature.html"
SIGNATURE_IMAGE_PATH = ROOT / "sign/sign_img.jpg"
LOGO_CID = "saba-logo"
SIGNATURE_CID = "saba-signature"


class MailFormatError(ValueError):
    """Newsletter HTML 구조가 변환 전제와 다르다."""


def _replace_once(text: str, pattern: str, replacement: str, label: str) -> str:
    result, count = re.subn(pattern, lambda _: replacement, text, count=1, flags=re.S)
    if count != 1:
        raise MailFormatError(f"메일 변환 대상 {label}을 찾지 못했습니다.")
    return result


def signature_body() -> str:
    html = SIGNATURE_PATH.read_text(encoding="utf-8")
    style = re.search(r"<style>.*?</style>", html, re.S)
    body = re.search(r"<body>(.*)</body>", html, re.S)
    if style is None or body is None:
        raise MailFormatError("메일 서명 Template 구조가 예상과 다릅니다.")
    return style.group(0) + body.group(1)


def to_mail_html(newsletter_html: str) -> str:
    """외부 CSS를 style 블록으로 포함하고 로고·서명을 CID 이미지로 바꾼다. 보기 전환은 script 없는 CSS 방식이라 그대로 둔다 (D-036).

    ponytail: CSS는 style 블록 포함까지만 한다. Outlook 데스크톱 등 style 블록을 일부 무시하는
    메일 앱 대응(완전 inline style)은 실제 표시 확인 후 필요하면 별도 승인으로 추가한다.
    """
    css = CSS_PATH.read_text(encoding="utf-8")
    html = _replace_once(newsletter_html, r'<link href="[^"]*" rel="stylesheet"/>', f"<style>\n{css}\n</style>", "외부 CSS")
    html = _replace_once(html, r'<img class="header-logo" src="[^"]*"', f'<img class="header-logo" src="cid:{LOGO_CID}"', "로고")
    # 서명은 뉴스레터 폭(main) 안에 두고 가운데 정렬한다 (D-033).
    return _replace_once(html, r"</main>", f'<div class="mail-signature">{signature_body()}</div>\n</main>', "본문 끝")


def build_message(mail_html: str, subject: str) -> EmailMessage:
    """보낸 사람·받는 사람 없이 본문과 CID 이미지만 담는다. 발송은 별도 승인 단계에서 구현한다."""
    message = EmailMessage(policy=SMTP)
    message["Subject"] = subject
    message.set_content("이 메일은 HTML 형식입니다. HTML을 지원하는 메일 앱에서 확인해 주세요.")
    message.add_alternative(mail_html, subtype="html")
    html_part = message.get_payload()[1]
    for path, cid in ((LOGO_PATH, LOGO_CID), (SIGNATURE_IMAGE_PATH, SIGNATURE_CID)):
        data = path.read_bytes()
        # 확장자가 아니라 실제 내용으로 형식을 정한다 (sign_img.jpg 는 실제로 PNG).
        subtype = "png" if data.startswith(b"\x89PNG") else "jpeg"
        html_part.add_related(data, maintype="image", subtype=subtype, cid=f"<{cid}>",
                              filename=path.name, disposition="inline")
    return message


def browser_preview(mail_html: str) -> str:
    """브라우저 확인용: CID 이미지를 원본 파일 경로로 바꾼다 (output/ 기준 상대 경로). .eml 에는 쓰지 않는다."""
    for path, cid in ((LOGO_PATH, LOGO_CID), (SIGNATURE_IMAGE_PATH, SIGNATURE_CID)):
        mail_html = mail_html.replace(f"cid:{cid}", "../" + path.relative_to(ROOT).as_posix())
    return mail_html
