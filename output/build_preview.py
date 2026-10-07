"""합성 기사와 별도 SAMPLE 보강 정보로 Preview만 생성한다. DB·네트워크 미사용."""

import json
from pathlib import Path

from saba.analysis import AnalysisResult
from saba.newsletter import build_article_view, build_newsletter_html
from saba.schema import SourceReference, validate_articles

ROOT = Path(__file__).resolve().parents[1]


def main():
    articles = validate_articles(json.loads((ROOT / "tests/fixtures/analysis_articles.json").read_text(encoding="utf-8")))
    result = AnalysisResult.model_validate(json.loads((ROOT / "tests/fixtures/analysis_valid.json").read_text(encoding="utf-8"))[0])
    # 합성 원본과 별도 Preview 보강 데이터. 실제 분석 Schema나 DB에 쓰지 않는다.
    # Preview 카드 수만 줄인다. Production 기사 선택 상한이 아니다.
    groups = ("security", "security", "ai_tech")
    sample_articles = [articles[0].model_copy(update={"article_id": f"sample-{i}",
                       "original_title": f"[SAMPLE] {group} 표시 검증", "region": "국내" if i % 2 == 0 else "해외"})
                       for i, group in enumerate(groups)]
    views = []
    assignments = (
        {"경영전략팀": "가상 자료 검토 카드", "보안사업팀": "가상 안내 검토 카드"},
        {"기술개발연구소": "가상 기술 검토 카드", "보안사업팀": "가상 안내 검토 카드"},
        {"경영전략팀": "가상 자료 검토 카드", "기술개발연구소": "가상 기술 검토 카드",
         "보안사업팀": "가상 안내 검토 카드", "STE본": "업무 범위 추정 없이 배치만 검증"},
    )
    for i, article in enumerate(sample_articles):
        article = article.model_copy(update={"related_articles": [SourceReference(
            source_name="SAMPLE 참고 출처", title="[SAMPLE] 관련 자료 표시 검증",
            url="https://example.com/sample/reference", published_at=article.published_at,
        )]})
        sample_result = result.model_copy(update={"article_id": article.article_id,
            "newsletter_title": article.original_title,
            "category": "AI·기술" if groups[i] == "ai_tech" else "취약점·권고"})
        views.append(build_article_view(article, sample_result, preview_sample={
            "implications": ["가상 시사점 표시 검증입니다."],
            "connections": assignments[i],
            "brief_group": groups[i],
        }))
    for filename, selected in (
        ("newsletter_preview_with_ai.html", views),
        ("newsletter_preview_no_ai.html", [build_article_view(article) for article in articles]),
    ):
        html = build_newsletter_html(selected, today="2026년 10월 7일 수요일", preview_mode=True)
        (ROOT / "output" / filename).write_text(html, encoding="utf-8")
        print(f"SAMPLE Preview 생성: output/{filename}")


if __name__ == "__main__":
    main()
