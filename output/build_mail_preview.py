"""실제 수집 기사 Newsletter를 메일 호환 HTML과 .eml로 만든다 (D-032). 발송·네트워크 없음."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from saba.issues import preview_article, select_issues
from saba.mail import build_message, to_mail_html
from saba.newsletter import build_article_view, build_newsletter_html
from saba.storage import DEFAULT_DB, list_articles

ROOT = Path(__file__).resolve().parents[1]
HTML_OUTPUT = ROOT / "output" / "newsletter_mail_preview.html"
EML_OUTPUT = ROOT / "output" / "newsletter_mail_preview.eml"
WEEKDAYS = "월화수목금토일"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", help="기준 시각 (시간대 있는 ISO 8601, 기본: 현재 시각)")
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        parser.error("--now 에는 시간대가 필요합니다.")
    if not DEFAULT_DB.exists():
        parser.error(f"기사 DB가 없습니다: {DEFAULT_DB}")
    selection = select_issues(list_articles(DEFAULT_DB), now)
    local = now.astimezone()
    today = f"{local.year}년 {local.month}월 {local.day}일 {WEEKDAYS[local.weekday()]}요일"
    views = [build_article_view(preview_article(issue)) for issue in selection.issues]
    html = to_mail_html(build_newsletter_html(views, today=today))
    HTML_OUTPUT.write_text(html, encoding="utf-8")
    message = build_message(html, f"[TEST] Security & AI Briefing · {today}")
    EML_OUTPUT.write_bytes(message.as_bytes())
    print(f"표시 이슈 {len(selection.issues)}건 · 메일 HTML {len(html.encode('utf-8')):,} bytes · .eml {EML_OUTPUT.stat().st_size:,} bytes")
    print(f"생성: {HTML_OUTPUT.relative_to(ROOT)} (브라우저에서는 CID 이미지가 보이지 않음)")
    print(f"생성: {EML_OUTPUT.relative_to(ROOT)} (메일 앱에서 열어 확인, 발송하지 않음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
