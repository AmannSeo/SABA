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
        return build_views(self.article_db, self.analysis_db, NOW, ledger_path=self.ledger, run=run, **options)

    def test_analysis_applied_out_of_scope_excluded_failures_fallback(self):
        run = FakeRun(self.plan)
        views, selection, stats = self.views(run)
        by_id = {v.article_id: v for v in views}
        self.assertNotIn("boan", by_id)  # 대상 밖 제외
        self.assertEqual(by_id["thn"].title, "가상 웹 서버 원격 코드 실행 취약점")
        self.assertTrue(by_id["thn"].has_full_analysis)
        self.assertIsNone(by_id["thn"].importance)  # D-022 중요도 미표시
        self.assertEqual(article_section(by_id["ai"]), "ai_tech")
        self.assertFalse(by_id["fail"].has_full_analysis)  # 실패 시 원문 발췌
        self.assertEqual(by_id["fail"].excerpt, EXCERPT)
        self.assertFalse(by_id["boho"].has_full_analysis)  # 발췌 없음은 호출 없이 제목만
        self.assertEqual((stats.valid, stats.out_of_scope, stats.insufficient, stats.reused), (2, 1, 1, 0))
        self.assertEqual(len(stats.failed), 1)
        html = build_newsletter_html(views)
        self.assertNotIn("높음", html)
        self.assertIn("가상 AI 보안 소식", html)

    def test_valid_results_saved_and_reused_without_new_calls(self):
        self.views(FakeRun(self.plan))
        self.assertEqual(len(list_analyses(self.analysis_db)), 3)  # 검토 필요 2 + 대상 밖 1
        second = FakeRun(self.plan)
        _, _, stats = self.views(second)
        self.assertEqual(stats.reused, 3)
        self.assertEqual([c[0] for c in second.calls], ["boho", "fail"])  # 저장 안 된 것만 다시 시도
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

    def test_no_ai_path_makes_no_calls(self):
        run = FakeRun(self.plan)
        views, _, stats = self.views(run, use_ai=False)
        self.assertEqual((run.calls, stats), ([], None))
        self.assertEqual(len(views), 5)
        self.assertFalse(self.analysis_db.exists())

    def test_display_result_hides_importance_only(self):
        article = self.articles[0]
        result = convert_response(article, prepare_request(article).request, response())
        shown = display_result(result)
        self.assertIsNone(shown.importance)
        self.assertEqual(result.importance, "높음")
        self.assertEqual(shown.summary, result.summary)
        self.assertEqual(shown.input_hash, analysis_input(article)[2])


if __name__ == "__main__":
    unittest.main()
