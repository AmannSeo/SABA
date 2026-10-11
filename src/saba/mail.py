"""Newsletter를 메일 앱 호환 HTML과 .eml 메시지로 만든다 (D-031, D-032, D-054). 발송 기능은 없다."""

from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path
import re

from css_inline import CSSInliner

from saba.newsletter import ArticleView, build_mail_html

ROOT = Path(__file__).resolve().parents[2]
LOGO_PATH = ROOT / "SAMPLE/Codex/v09/LOGO.png"
SIGNATURE_PATH = ROOT / "templates/email_signature.html"
SIGNATURE_IMAGE_PATH = ROOT / "sign/sign_img.jpg"
LOGO_CID = "saba-logo"
SIGNATURE_CID = "saba-signature"


INLINER = CSSInliner(keep_at_rules=True, load_remote_stylesheets=False)


class MailFormatError(ValueError):
    """메일 서명 Template 구조가 변환 전제와 다르다."""


def signature_body() -> str:
    html = SIGNATURE_PATH.read_text(encoding="utf-8")
    style = re.search(r"<style>.*?</style>", html, re.S)
    body = re.search(r"<body>(.*)</body>", html, re.S)
    if style is None or body is None:
        raise MailFormatError("메일 서명 Template 구조가 예상과 다릅니다.")
    return style.group(0) + body.group(1)


def to_mail_html(views: list[ArticleView], *, today: str | None = None) -> str:
    """메일 전용 table 템플릿으로 만든다 (D-054). 로고·서명은 CID 이미지.

    한비로메일 웹메일은 style 블록을 지우므로 서명 CSS 도 각 요소 style 속성으로 옮기고 (D-052),
    남은 flex·grid 배치는 세로 배치로 바꾼다 (D-053). 템플릿 자체는 table 배치라 영향이 없다.
    """
    html = build_mail_html(views, today=today, logo_src=f"cid:{LOGO_CID}", signature=signature_body())
    return flatten_layout(INLINER.inline(html))


# 웹메일이 flex·grid 배치를 지원하지 않아 모든 영역이 깨졌다. 세로 1열로 바꾼다 (D-053).
# ponytail: 가로 배치(로고·제목, 2열 카드, 출처 행) 는 세로가 된다. 원래 모양이 필요하면 메일 전용 table 템플릿.
_LAYOUT_PROPS = re.compile(r"^(gap|row-gap|column-gap|grid(-.*)?|flex(-.*)?|align-(items|content|self)"
                           r"|justify-(content|items|self)|place-.*|order)$")


def _flat_style(match: re.Match) -> str:
    kept = []
    for declaration in match.group(1).split(";"):
        name, _, value = declaration.partition(":")
        name, value = name.strip().lower(), value.strip()
        if not name or _LAYOUT_PROPS.match(name):
            continue
        if name == "display":
            value = {"flex": "block", "grid": "block", "inline-flex": "inline-block",
                     "inline-grid": "inline-block"}.get(value, value)
        kept.append(f"{name}: {value}")
    return f'style="{";".join(kept)}"'


def flatten_layout(html: str) -> str:
    return re.sub(r'style="([^"]*)"', _flat_style, html)


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
