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
    """외부 CSS를 style 블록으로 포함하고 script·보기 전환 버튼을 없앤 뒤 간략 보기와 자세히 보기를 차례로 보여 준다 (D-033).

    ponytail: CSS는 style 블록 포함까지만 한다. Outlook 데스크톱 등 style 블록을 일부 무시하는
    메일 앱 대응(완전 inline style)은 실제 표시 확인 후 필요하면 별도 승인으로 추가한다.
    """
    css = CSS_PATH.read_text(encoding="utf-8")
    html = _replace_once(newsletter_html, r'<link href="[^"]*" rel="stylesheet"/>', f"<style>\n{css}\n</style>", "외부 CSS")
    html = _replace_once(html, r"\s*<script>.*?</script>", "", "script")
    html = _replace_once(html, r'<div class="brief-view-switch".*?</div>\s*', "", "보기 전환 버튼")
    html = _replace_once(html, r'<div class="brief-summary-view" data-brief-panel="summary">',
                         '<h3 class="brief-view-label">간략 보기</h3>\n<div class="brief-summary-view">', "간략 보기")
    html = _replace_once(html, r'<div class="brief-detail-view" data-brief-panel="detail" hidden>',
                         '<h3 class="brief-view-label">자세히 보기</h3>\n<div class="brief-detail-view">', "자세히 보기")
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
    for path, cid, subtype in ((LOGO_PATH, LOGO_CID, "png"), (SIGNATURE_IMAGE_PATH, SIGNATURE_CID, "jpeg")):
        html_part.add_related(path.read_bytes(), maintype="image", subtype=subtype, cid=f"<{cid}>",
                              filename=path.name, disposition="inline")
    return message
