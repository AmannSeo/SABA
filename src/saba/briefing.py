"""실제 수집 기사 Newsletter 화면 구성 (D-029, D-033). 기사 DB는 읽기만 한다."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from saba.analysis import AnalysisResult, analysis_input
from saba.analysis_storage import list_analyses, save_analysis
from saba.issues import Issue, Selection, preview_article, select_issues
from saba.newsletter import ArticleView, build_article_view
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


def stored_results(analysis_db: Path) -> dict[tuple[str, str], AnalysisResult]:
    if not analysis_db.exists():
        return {}
    # 같은 입력의 결과가 여러 개면 나중에 저장된 것을 쓴다 (list_analyses 는 저장 시각 순).
    return {(r["result"]["article_id"], r["result"]["input_hash"]): AnalysisResult.model_validate(r["result"])
            for r in list_analyses(analysis_db)}


def analyze_issues(issues: list[Issue], article_db: Path, analysis_db: Path, *,
                   ledger_path: Path = DEFAULT_LEDGER, max_new_calls: int = MAX_NEW_CALLS,
                   run: Callable[..., LiveOutcome] = run_openai) -> tuple[dict[str, AnalysisResult], AnalysisStats]:
    """대표 기사만 분석한다. 저장된 결과는 재사용하고, 새 유효 결과만 분석 DB에 저장한다."""
    stored = stored_results(analysis_db)
    max_calls = len(read_ledger(ledger_path)) + max_new_calls
    results: dict[str, AnalysisResult] = {}
    stats = AnalysisStats()
    for issue in issues:
        article = issue.representative
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
            save_analysis(article_db, analysis_db, [result.model_dump(mode="json")])
        results[article.article_id] = result
        if result.status == OUT_OF_SCOPE:
            stats.out_of_scope += 1
        elif result.status == "검토 필요":
            stats.valid += 1
    return results, stats


def display_result(result: AnalysisResult) -> AnalysisResult:
    # 중요도는 사람이 확정하기 전까지 표시하지 않는다 (D-022). 화면용 사본만 바꾼다.
    return result.model_copy(update={"importance": None, "importance_reason": None})


def build_views(article_db: Path, analysis_db: Path, now: datetime, *, use_ai: bool = True,
                **analyze_options) -> tuple[list[ArticleView], Selection, AnalysisStats | None]:
    selection = select_issues(list_articles(article_db), now)
    results: dict[str, AnalysisResult] = {}
    stats = None
    if use_ai:
        results, stats = analyze_issues(selection.issues, article_db, analysis_db, **analyze_options)
    views = []
    for issue in selection.issues:
        result = results.get(issue.representative.article_id)
        if result is not None and result.status == OUT_OF_SCOPE:
            continue
        views.append(build_article_view(preview_article(issue), display_result(result) if result else None))
    return views, selection, stats
