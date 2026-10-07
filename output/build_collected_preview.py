"""실제 수집 기사(data/saba.db, 읽기 전용)로 비AI Newsletter Preview를 생성한다 (D-029). 발송·네트워크 없음."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from saba.issues import MAX_PER_SECTION, MAX_PER_SOURCE, preview_article, select_issues
from saba.newsletter import build_article_view, build_newsletter_html
from saba.storage import DEFAULT_DB, list_articles

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "newsletter_preview_collected.html"
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
    views = [build_article_view(preview_article(issue)) for issue in selection.issues]
    local = now.astimezone(timezone.utc).astimezone()
    today = f"{local.year}년 {local.month}월 {local.day}일 {WEEKDAYS[local.weekday()]}요일"
    OUTPUT.write_text(build_newsletter_html(views, today=today), encoding="utf-8")

    print(f"기준 시각 {now.isoformat()} · 기간 안 기사 {selection.in_window}건")
    print(f"표시 이슈 {len(selection.issues)}건 · Source 상한({MAX_PER_SOURCE}) 제외 {selection.excluded_by_source_cap}건"
          f" · 섹션 상한({MAX_PER_SECTION}) 제외 {selection.excluded_by_section_cap}건 (중요도 선별 아님)")
    for issue in selection.issues:
        if issue.related:
            print(f"  같은 사건 묶음: {issue.representative.original_title.strip()} 외 {len(issue.related)}건")
    for candidate in selection.candidates:
        print(f"  같은 사건 후보 ({candidate.keyword}, 사람 확인 필요): "
              f"{candidate.first.representative.original_title.strip()} ↔ {candidate.second.representative.original_title.strip()}")
    print(f"Preview 생성: {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
