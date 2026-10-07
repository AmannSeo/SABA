"""실제 수집 기사 Newsletter를 메일 호환 HTML과 .eml로 만든다 (D-032). 발송·네트워크 없음."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from saba.analysis_storage import DEFAULT_ANALYSIS_DB
from saba.briefing import build_views
from saba.mail import browser_preview, build_message, to_mail_html
from saba.newsletter import build_newsletter_html
from saba.storage import DEFAULT_DB

ROOT = Path(__file__).resolve().parents[1]
HTML_OUTPUT = ROOT / "output" / "newsletter_mail_preview.html"
EML_OUTPUT = ROOT / "output" / "newsletter_mail_preview.eml"
WEEKDAYS = "월화수목금토일"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", help="기준 시각 (시간대 있는 ISO 8601, 기본: 현재 시각)")
    parser.add_argument("--no-ai", action="store_true", help="AI 분석 없이 원문 발췌로 생성")
    parser.add_argument("--reuse-only", action="store_true", help="저장된 AI 분석 결과만 쓰고 새 호출은 하지 않음")
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        parser.error("--now 에는 시간대가 필요합니다.")
    if not DEFAULT_DB.exists():
        parser.error(f"기사 DB가 없습니다: {DEFAULT_DB}")
    views, selection, stats = build_views(DEFAULT_DB, DEFAULT_ANALYSIS_DB, now, use_ai=not args.no_ai,
                                          **({"max_new_calls": 0} if args.reuse_only else {}))
    local = now.astimezone()
    today = f"{local.year}년 {local.month}월 {local.day}일 {WEEKDAYS[local.weekday()]}요일"
    html = to_mail_html(build_newsletter_html(views, today=today))
    HTML_OUTPUT.write_text(browser_preview(html), encoding="utf-8")
    message = build_message(html, f"[TEST] Security & AI Briefing · {today}")
    EML_OUTPUT.write_bytes(message.as_bytes())
    print(f"표시 이슈 {len(views)}건 · 메일 HTML {len(html.encode('utf-8')):,} bytes · .eml {EML_OUTPUT.stat().st_size:,} bytes")
    print(f"생성: {HTML_OUTPUT.relative_to(ROOT)} (브라우저 확인용, 이미지는 원본 파일 경로)")
    print(f"생성: {EML_OUTPUT.relative_to(ROOT)} (메일 앱에서 열어 확인, 발송하지 않음)")
    if stats is not None:
        print(f"AI 분석: 재사용 {stats.reused} · 신규 호출 {stats.called} · 검토 필요 {stats.valid} · 대상 밖 제외 {stats.out_of_scope}"
              f" · 발췌 없음 {stats.insufficient} · 실패 {len(stats.failed)} · 호출 상한 초과 {stats.skipped_by_cap}")
        for failure in stats.failed:
            print(f"  분석 실패 (원문 발췌로 표시): {failure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
