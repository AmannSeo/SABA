"""실제 수집 기사 Newsletter 화면 구성 (D-029, D-033). 기사 DB는 읽기만 한다."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from saba.analysis import AnalysisResult, analysis_input
from saba.analysis_storage import list_analyses, save_analysis
from saba.insights import DEFAULT_INSIGHT_DB, InsightResult, insight_hash, load_insights, run_insight, save_insight
from saba.issues import Issue, Selection, preview_article, select_issues
from saba.newsletter import ArticleView, build_article_view
from saba.notice_body import DEFAULT_CACHE, notice_excerpts, with_excerpt
from saba.openai_adapter import DEFAULT_LEDGER, LiveOutcome, read_ledger, run_openai
from saba.schema import Article
from saba.storage import list_articles

MAX_NEW_CALLS = 20  # 1회 생성당 신규 OpenAI 호출 상한 (D-033)
OUT_OF_SCOPE = "대상 밖"


@dataclass
class AnalysisStats:
    reused: int = 0
    called: int = 0
    valid: int = 0
    out_of_scope: int = 0
    insufficient: int = 0
    failed: list[str] = field(default_factory=list)
    skipped_by_cap: int = 0
    insights_reused: int = 0
    insights_called: int = 0
    insights_failed: int = 0


def stored_results(analysis_db: Path) -> dict[tuple[str, str], AnalysisResult]:
    if not analysis_db.exists():
        return {}
    # 같은 입력의 결과가 여러 개면 나중에 저장된 것을 쓴다 (list_analyses 는 저장 시각 순).
    return {(r["result"]["article_id"], r["result"]["input_hash"]): AnalysisResult.model_validate(r["result"])
            for r in list_analyses(analysis_db)}


def analyze_issues(issues: list[Issue], article_db: Path, analysis_db: Path, *,
                   ledger_path: Path = DEFAULT_LEDGER, max_new_calls: int = MAX_NEW_CALLS,
                   run: Callable[..., LiveOutcome] = run_openai,
                   excerpts: dict[str, str] | None = None) -> tuple[dict[str, AnalysisResult], AnalysisStats]:
    """대표 기사만 분석한다. 저장된 결과는 재사용하고, 새 유효 결과만 분석 DB에 저장한다.

    excerpts: 발췌 없는 공지의 본문 발췌 (D-038). 분석 입력과 저장 검증에 같이 쓴다.
    """
    excerpts = excerpts or {}
    stored = stored_results(analysis_db)
    max_calls = len(read_ledger(ledger_path)) + max_new_calls
    results: dict[str, AnalysisResult] = {}
    stats = AnalysisStats()
    for issue in issues:
        article = with_excerpt(issue.representative, excerpts)
        cached = stored.get((article.article_id, analysis_input(article)[2]))
        if cached is not None:
            stats.reused += 1
            result = cached
        elif stats.called >= max_new_calls:
            stats.skipped_by_cap += 1
            continue
        else:
            outcome = run(article, ledger_path=ledger_path, max_calls=max_calls)
            if outcome.status == "input_insufficient":
                stats.insufficient += 1
                continue
            stats.called += 1
            if outcome.result is None:
                stats.failed.append(f"{article.article_id}: {outcome.status}")
                continue
            result = outcome.result
            save_analysis(article_db, analysis_db, [result.model_dump(mode="json")], excerpts=excerpts)
        results[article.article_id] = result
        if result.status == OUT_OF_SCOPE:
            stats.out_of_scope += 1
        elif result.status == "검토 필요":
            stats.valid += 1
    return results, stats


COMPANY_HANJA = "\u793e"  # 원문의 회사 한자 표기. 모델이 지시문과 관계없이 그대로 써서 화면에서만 바꾼다 (D-040).


def _hangul(text: str | None) -> str | None:
    return None if text is None else text.replace(COMPANY_HANJA, "사")


def display_result(result: AnalysisResult) -> AnalysisResult:
    # 화면용 사본만 바꾼다. 저장 결과와 근거 인용(evidence)은 원문 그대로 둔다.
    # 중요도는 저장된 AI 결과를 그대로 표시한다 (D-059, D-022 의 사람 확정 전 미표시를 변경).
    return result.model_copy(update={
        "newsletter_title": _hangul(result.newsletter_title), "summary": _hangul(result.summary),
        "tags": [_hangul(t) for t in result.tags], "key_points": [_hangul(p) for p in result.key_points]})


def display_insight(insight: InsightResult) -> InsightResult:
    return insight.model_copy(update={"implication": _hangul(insight.implication), "connections": [
        c.model_copy(update={"text": _hangul(c.text)}) for c in insight.connections]})


def add_insights(issues: list[Issue], results: dict[str, AnalysisResult], excerpts: dict[str, str],
                 stats: AnalysisStats, *, insight_db: Path, ledger_path: Path, max_new_calls: int,
                 run: Callable[..., tuple[str, InsightResult | None]] = run_insight) -> dict[str, InsightResult]:
    """검토 필요 결과에만 시사점을 붙인다 (D-041). 저장된 것은 재사용하고 새 호출은 max_new_calls 까지."""
    stored = load_insights(insight_db)
    max_calls = len(read_ledger(ledger_path)) + max_new_calls
    insights: dict[str, InsightResult] = {}
    for issue in issues:
        result = results.get(issue.representative.article_id)
        if result is None or result.status != "검토 필요":
            continue
        article = with_excerpt(issue.representative, excerpts)
        insight = stored.get((article.article_id, insight_hash(article, result)))
        if insight is not None:
            stats.insights_reused += 1
        elif stats.insights_called < max_new_calls:
            stats.insights_called += 1
            status, insight = run(article, result, ledger_path=ledger_path, max_calls=max_calls)
            if insight is None:
                stats.insights_failed += 1
                continue
            save_insight(insight_db, insight)
        else:
            continue
        insights[article.article_id] = insight
    return insights


def build_views(article_db: Path, analysis_db: Path, now: datetime, *, use_ai: bool = True,
                body_cache: Path = DEFAULT_CACHE, insight_db: Path = DEFAULT_INSIGHT_DB, insight_calls: int = 0,
                insight_run: Callable[..., tuple[str, InsightResult | None]] = run_insight,
                **analyze_options) -> tuple[list[ArticleView], Selection, AnalysisStats | None]:
    """insight_calls: 시사점 신규 호출 상한. 기본 0 이면 저장된 시사점만 쓴다 (실제 호출은 별도 승인)."""
    selection = select_issues(list_articles(article_db), now)
    results: dict[str, AnalysisResult] = {}
    stats = None
    if use_ai:
        # 새 호출이 없는 실행(--reuse-only)은 네트워크 없이 본문 캐시만 쓴다.
        excerpts = notice_excerpts([issue.representative for issue in selection.issues], cache_path=body_cache,
                                   fetch=analyze_options.get("max_new_calls", MAX_NEW_CALLS) > 0)
        results, stats = analyze_issues(selection.issues, article_db, analysis_db, excerpts=excerpts, **analyze_options)
        insights = add_insights(selection.issues, results, excerpts, stats, insight_db=insight_db,
                                ledger_path=analyze_options.get("ledger_path", DEFAULT_LEDGER),
                                max_new_calls=insight_calls, run=insight_run)
    else:
        insights = {}
    views = []
    for issue in selection.issues:
        result = results.get(issue.representative.article_id)
        if result is not None and result.status == OUT_OF_SCOPE:
            continue
        insight = insights.get(issue.representative.article_id)
        views.append(build_article_view(preview_article(issue), display_result(result) if result else None,
                                        insight=display_insight(insight) if insight else None))
    return views, selection, stats
