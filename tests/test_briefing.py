from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from saba.analysis import analysis_input
from saba.analysis_storage import list_analyses
from saba.briefing import analyze_issues, build_views, display_result
from saba.ai_adapter import convert_response, prepare_request
from saba.issues import select_issues
from saba.newsletter import article_section, build_newsletter_html
from saba.openai_adapter import LiveOutcome
from saba.schema import validate_articles
from saba.storage import save_articles

NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
EXCERPT = "가상 웹 서버에서 원격 코드 실행 취약점이 확인됐습니다."


def row(article_id, source_id, title, excerpt=EXCERPT, hours=1):
    return {"schema_version": 1, "article_id": article_id, "source_id": source_id, "source_name": "가상 출처",
            "original_title": title, "url": f"https://example.com/fictional/{article_id}", "collection_method": "rss",
            "collected_at": NOW.isoformat(), "published_at": (NOW - timedelta(hours=hours)).isoformat(),
            "feed_excerpt": excerpt}


def response(status="검토 필요", category="취약점·권고", title="가상 웹 서버 원격 코드 실행 취약점"):
    if status != "검토 필요":
        return {"status": status, "reason": "가상 판단 이유입니다.", "category": None, "tags": [], "importance": None,
                "importance_reason": None, "newsletter_title": None, "summary": None, "key_points": [], "evidence": []}
    quote = {"input_field": "feed_excerpt", "quote": EXCERPT}
    return {"status": status, "reason": "가상 판단 이유입니다.", "category": category, "tags": ["취약점"],
            "importance": "높음", "importance_reason": "가상 중요도 이유입니다.", "newsletter_title": title,
            "summary": "가상 출처에 따르면 가상 웹 서버에서 원격 코드 실행 취약점이 확인됐습니다.",
            "key_points": ["원격 코드 실행 취약점 확인"],
            "evidence": [quote | {"target": t} for t in ("newsletter_title", "summary", "category",
                                                           "importance_reason", "tags[0]", "key_points[0]")]}


class FakeRun:
    def __init__(self, plan):
        self.plan, self.calls = plan, []

    def __call__(self, article, *, ledger_path, max_calls):
        self.calls.append((article.article_id, max_calls))
        prepared = prepare_request(article)
        if prepared.request is None:
            return LiveOutcome(prepared.status, prepared.result)
        planned = self.plan.get(article.article_id)
        if planned is None:
            return LiveOutcome("unavailable")
        return LiveOutcome("valid", convert_response(article, prepared.request, planned))


class BriefingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.article_db, self.analysis_db, self.ledger = self.dir / "saba.db", self.dir / "analysis.db", self.dir / "usage.json"
        self.articles = validate_articles([
            row("thn", "the-hacker-news", "[Fictional] Web server flaw", hours=1),
            row("boan", "boannews", "[가상] 자격시험 안내", hours=2),
            row("ai", "the-hacker-news", "[Fictional] AI model release", hours=3),
            row("boho", "boho-security-notice", "[가상] 보안 업데이트 권고", excerpt=None, hours=4),
            row("fail", "cisa-cybersecurity-advisories", "[Fictional] Advisory", hours=5),
        ])
        save_articles(self.article_db, self.articles)
        self.plan = {"thn": response(), "boan": response("대상 밖"), "ai": response(category="AI 보안", title="가상 AI 보안 소식")}

    def views(self, run, **options):
        # 운영 data/insights.db 를 읽지 않도록 임시 DB 를 쓴다
        options.setdefault("insight_db", self.dir / "insights.db")
        return build_views(self.article_db, self.analysis_db, NOW, ledger_path=self.ledger, run=run, **options)

    def test_analysis_applied_out_of_scope_excluded_failures_fallback(self):
        run = FakeRun(self.plan)
        views, selection, stats = self.views(run)
        by_id = {v.article_id: v for v in views}
        self.assertNotIn("boan", by_id)  # 대상 밖 제외
        self.assertEqual(by_id["thn"].title, "가상 웹 서버 원격 코드 실행 취약점")
        self.assertTrue(by_id["thn"].has_full_analysis)
        self.assertEqual(by_id["thn"].importance, "높음")  # D-059 AI 중요도 표시
        self.assertEqual(article_section(by_id["ai"]), "ai_tech")
        self.assertFalse(by_id["fail"].has_full_analysis)  # 실패 시 원문 발췌
        self.assertEqual(by_id["fail"].excerpt, EXCERPT)
        self.assertFalse(by_id["boho"].has_full_analysis)  # 발췌 없음은 호출 없이 제목만
        self.assertEqual((stats.valid, stats.out_of_scope, stats.insufficient, stats.reused), (2, 1, 1, 0))
        self.assertEqual(len(stats.failed), 1)
        html = build_newsletter_html(views)
        self.assertIn('<span class="badge urgent">긴급</span>', html)  # 높음 → 긴급 (D-059)
        self.assertIn("가상 AI 보안 소식", html)

    def test_valid_results_saved_and_reused_without_new_calls(self):
        self.views(FakeRun(self.plan))
        self.assertEqual(len(list_analyses(self.analysis_db)), 3)  # 검토 필요 2 + 대상 밖 1
        second = FakeRun(self.plan)
        _, _, stats = self.views(second)
        self.assertEqual(stats.reused, 3)
        self.assertEqual([c[0] for c in second.calls], ["fail"])  # 제목뿐인 입력은 호출 전에 제외
        self.assertEqual(len(list_analyses(self.analysis_db)), 3)

    def test_changed_input_not_reused(self):
        self.views(FakeRun(self.plan))
        changed = self.articles[0].model_copy(update={"feed_excerpt": EXCERPT + " 추가 문장입니다."})
        issues = select_issues([changed], NOW).issues
        run = FakeRun({})
        _, stats = analyze_issues(issues, self.article_db, self.analysis_db, ledger_path=self.ledger, run=run)
        self.assertEqual((stats.reused, len(run.calls)), (0, 1))

    def test_new_call_cap(self):
        run = FakeRun(self.plan)
        _, _, stats = self.views(run, max_new_calls=2)
        self.assertEqual(stats.called, 2)
        self.assertGreaterEqual(stats.skipped_by_cap, 1)
        self.assertTrue(all(max_calls == 2 for _, max_calls in run.calls))  # 빈 사용량 기록 + 2

    def test_analyzed_only_drops_every_result_without_valid_analysis(self):
        run = FakeRun(self.plan)
        views, _, stats = self.views(run, max_new_calls=2, analyzed_only=True)
        shown = {v.article_id for v in views}
        self.assertTrue(stats.capped_ids)
        self.assertFalse(shown & stats.capped_ids)  # 상한으로 분석 못 한 글은 메일에서 뺀다 (D-080)
        self.assertEqual(stats.dropped_unanalyzed, 5 - len(shown))
        self.assertNotIn("boho", shown)
        self.assertNotIn("fail", shown)
        self.assertNotIn("boan", shown)
        self.assertTrue(all(v.has_full_analysis for v in views))
        self.assertEqual(len(stats.excluded), stats.dropped_unanalyzed)
        _, _, plain = self.views(FakeRun(self.plan), max_new_calls=2)
        self.assertEqual(plain.dropped_unanalyzed, 0)  # 기본값은 이전 동작 그대로

    def test_strict_exclusion_reasons_and_response_failure(self):
        base = FakeRun(self.plan)
        def run(article, **options):
            return LiveOutcome("response_invalid") if article.article_id == "fail" else base(article, **options)
        views, selection, stats = self.views(run, max_new_calls=20, analyzed_only=True)
        self.assertEqual({v.article_id for v in views}, {"thn", "ai"})
        self.assertEqual(stats.excluded, {"boho": "입력 부족", "boan": "대상 밖", "fail": "응답 오류"})
        self.assertEqual(len(views) + len(stats.excluded), len(selection.issues))

    def test_strict_cached_results_reused_with_zero_calls_and_changed_input_excluded(self):
        self.views(FakeRun(self.plan))
        run = FakeRun({})
        views, _, stats = self.views(run, max_new_calls=0, analyzed_only=True)
        self.assertEqual({v.article_id for v in views}, {"thn", "ai"})
        self.assertEqual(run.calls, [])
        changed = self.articles[0].model_copy(update={"feed_excerpt": EXCERPT + " 추가 문장."})
        self.article_db = self.dir / "changed.db"
        save_articles(self.article_db, [changed])
        views, _, stats = self.views(run, max_new_calls=0, analyzed_only=True)
        self.assertNotIn("thn", {v.article_id for v in views})

    def test_strict_no_ai_path_has_no_unverified_articles(self):
        views, _, stats = self.views(FakeRun({}), use_ai=False, analyzed_only=True)
        self.assertEqual(views, [])

    def test_authentication_failure_stops_further_calls(self):
        calls = []
        def run(article, *, ledger_path, max_calls):
            calls.append(article.article_id)
            return LiveOutcome("authentication")
        views, _, stats = self.views(run, max_new_calls=10)
        self.assertEqual(len(calls), 1)  # 첫 인증 실패 뒤에는 호출하지 않는다
        self.assertTrue(stats.auth_failed)
        self.assertEqual(stats.called, 1)
        self.assertTrue(views)  # 메일 표시는 이전처럼 원문 발췌

    def test_no_ai_path_makes_no_calls(self):
        run = FakeRun(self.plan)
        views, _, stats = self.views(run, use_ai=False)
        self.assertEqual((run.calls, stats), ([], None))
        self.assertEqual(len(views), 5)
        self.assertFalse(self.analysis_db.exists())

    def test_display_result_keeps_importance(self):
        article = self.articles[0]
        result = convert_response(article, prepare_request(article).request, response())
        shown = display_result(result)
        self.assertEqual(shown.importance, "높음")
        self.assertEqual(result.importance, "높음")
        self.assertEqual(shown.summary, result.summary)
        self.assertEqual(shown.input_hash, analysis_input(article)[2])

    def test_display_result_replaces_company_hanja_only_in_copy(self):
        from saba.briefing import COMPANY_HANJA
        article = self.articles[0]
        result = convert_response(article, prepare_request(article).request, response())
        hanja = result.model_copy(update={"summary": result.summary.replace("가상 웹 서버", "가상" + COMPANY_HANJA + " 서버"),
                                          "tags": ["가상" + COMPANY_HANJA]})
        shown = display_result(hanja)
        self.assertNotIn(COMPANY_HANJA, shown.summary + "".join(shown.tags))
        self.assertIn("가상사 서버", shown.summary)
        self.assertIn(COMPANY_HANJA, hanja.summary)  # 원본 결과는 그대로
        self.assertEqual(shown.evidence, hanja.evidence)


if __name__ == "__main__":
    unittest.main()
