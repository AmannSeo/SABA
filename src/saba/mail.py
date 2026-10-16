"""Newsletter를 메일 앱 호환 HTML과 .eml 메시지로 만든다 (D-031, D-032, D-054). 발송 기능은 없다."""

from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path
import re

from css_inline import CSSInliner

from saba.newsletter import ArticleView, build_mail_html

ROOT = Path(__file__).resolve().parents[2]
LOGO_PATH = ROOT / "templates/logo_mail.png"  # 원본 SAMPLE/Codex/v09/LOGO.png 의 메일용 축소본 (124px, D-067)
SIGNATURE_PATH = ROOT / "templates/email_signature.html"
SIGNATURE_IMAGE_PATH = ROOT / "sign/sign_img.jpg"
LOGO_CID = "saba-logo"
SIGNATURE_CID = "saba-signature"


INLINER = CSSInliner(keep_at_rules=True, load_remote_stylesheets=False)


class MailFormatError(ValueError):
    """메일 서명 Template 구조가 변환 전제와 다르다."""


# 관리 화면에서 넣은 서명 (2026-10-16 사용자 요청). 없으면 templates/email_signature.html 을 쓴다.
CUSTOM_SIGNATURE_PATH = ROOT / "config" / "signature.html"
MAX_SIGNATURE = 100_000
_UNSAFE_SIGNATURE = re.compile(r"<\s*/?\s*(script|iframe|frame|object|embed|form|svg|math|base|meta|link|applet)\b"
                               r"|[\s/\"'`]on[a-z]+\s*=|(java|vb)script:|data:text/html|expression\s*\(|\\[0-9a-f]", re.I)  # 끝: CSS·HTML 16진 이스케이프 (u\72l(\6a avascript:) 등, Codex 2차 재검증)


def check_signature(html: str) -> str:
    """관리 화면에서 넣은 서명 HTML 검사. 스크립트·이벤트 속성·폼은 받지 않는다 (메일 앱이 지우거나 위험)."""
    html = html.strip()
    if not html:
        raise MailFormatError("서명 HTML 이 비어 있습니다.")
    if len(html) > MAX_SIGNATURE:
        raise MailFormatError(f"서명 HTML 은 {MAX_SIGNATURE:,}자 이하여야 합니다.")
    # 메일에 실제로 들어가는 부분 (<style>·<body> 안쪽) 을 검사한다. <head> 의 <meta charset> 등은 버려지므로 막지 않는다.
    # 엔터티 (&#106;avascript: 등) 를 풀고 공백·제어 문자를 지운 모양도 함께 검사한다 (Codex 교차 검증 2026-10-16)
    from html import unescape
    used = _signature_parts(html)
    decoded = unescape(used)
    squeezed = re.sub(r"[\x00-\x20]+", "", decoded)
    if any(_UNSAFE_SIGNATURE.search(text) for text in (used, decoded, squeezed)):
        raise MailFormatError("서명에 script·iframe·form·svg·javascript:·on 이벤트 속성 등은 쓸 수 없습니다.")
    return html


def _signature_parts(html: str) -> str:
    """전체 HTML 문서면 <style> 과 <body> 안쪽만, 조각이면 그대로 쓴다."""
    body = re.search(r"<body[^>]*>(.*)</body>", html, re.S | re.I)
    if body is None:
        return html
    styles = "".join(re.findall(r"<style[^>]*>.*?</style>", html, re.S | re.I))
    return styles + body.group(1)


def signature_source(custom_path: Path = CUSTOM_SIGNATURE_PATH) -> tuple[str, bool]:
    """(서명 HTML, 직접 넣은 서명인지). 직접 넣은 서명이 깨졌으면 기본 서명으로 보내고 경고를 남긴다."""
    if custom_path.exists():
        try:
            return check_signature(custom_path.read_text(encoding="utf-8-sig")), True
        except (MailFormatError, OSError, UnicodeDecodeError) as error:
            import logging
            logging.warning("직접 넣은 메일 서명을 쓰지 못해 기본 서명으로 보냅니다: %s", error)
    return SIGNATURE_PATH.read_text(encoding="utf-8"), False


def signature_body(custom_path: Path = CUSTOM_SIGNATURE_PATH) -> str:
    html, custom = signature_source(custom_path)
    if not custom:
        style = re.search(r"<style>.*?</style>", html, re.S)
        body = re.search(r"<body>(.*)</body>", html, re.S)
        if style is None or body is None:
            raise MailFormatError("메일 서명 Template 구조가 예상과 다릅니다.")
        return style.group(0) + _fill_author(body.group(1))
    return _fill_author(_signature_parts(html))


def _fill_author(html: str) -> str:
    """서명의 작성자 자리 (%%AUTHOR_...%%) 를 config/author.json 값으로 채운다. 값은 HTML 이스케이프.
    채운 결과를 다시 검사한다 (href="%%AUTHOR_NAME%%" 에 이름 javascript: 등, Codex 재검증 2026-10-16).
    통과하지 못하면 기본 작성자로 채우고 경고를 남긴다."""
    from saba.author import DEFAULT, current_author
    try:
        return check_signature(_fill(html, current_author()))
    except MailFormatError:
        import logging
        logging.warning("작성자 값을 넣은 서명이 안전 검사를 통과하지 못해 기본 작성자로 채웁니다.")
        return check_signature(_fill(html, DEFAULT))


def _fill(html: str, author: dict) -> str:
    from html import escape
    values = {**author, "title": " ".join(filter(None, (author["name"], author["position"])))}
    for key, value in values.items():
        html = html.replace(f"%%AUTHOR_{key.upper()}%%", escape(value, quote=True))
    return html


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
