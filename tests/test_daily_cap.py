"""하루 AI 호출 상한 (D-077): 한국 날짜별로 모든 실행이 분석·시사점 상한을 함께 쓴다. 실제 호출 없음."""

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from saba import openai_adapter as oa
from saba.briefing import add_insights, analyze_issues, AnalysisStats
from saba.ai_adapter import convert_response, prepare_request
from saba.issues import select_issues
from saba.openai_adapter import LiveOutcome, ProviderError, daily_used, send_once
from saba.schema import validate_articles
from saba.storage import save_articles

from test_briefing import NOW, response, row

KST_DAY = NOW.astimezone(oa.KST).date()


def entry(at: str, purpose: str | None = None, cost: float = 0.0001) -> dict:
    e = {"at": at, "month": at[:7], "model": oa.MODEL, "article_id": "x", "status": "valid",
         "input_tokens": 1, "output_tokens": 1, "cost_usd": cost, "estimated": False}
    if purpose:
        e["purpose"] = purpose
    return e


class DailyUsedTests(unittest.TestCase):
    def test_kst_boundary_purpose_and_bad_records(self):
        entries = [entry("2026-10-12T14:59:00+00:00"),  # KST 10-12 23:59
                   entry("2026-10-12T15:30:00+00:00"),  # KST 10-13 00:30 (UTC 날짜는 10-12)
                   entry("2026-10-13T01:00:00+00:00", "insight"),
                   entry("2026-10-13T02:00:00+00:00", "analysis"),
                   {"month": "2026-10", "cost_usd": 0.1},  # 시각 없음
                   entry("2026-10-13T03:00:00"),  # 시간대 없음: 추정하지 않음
                   entry("잘못된 시각")]
        self.assertEqual(daily_used(entries, None, date(2026, 10, 12)), 1)
        self.assertEqual(daily_used(entries, None, date(2026, 10, 13)), 2)  # purpose 없음 + analysis
        self.assertEqual(daily_used(entries, "insight", date(2026, 10, 13)), 1)
        self.assertEqual(daily_used(entries, None, date(2026, 10, 14)), 0)  # 다음 날은 새로


class SendOnceDailyLimitTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.ledger = Path(temp.name) / "usage.json"
        self.now = datetime(2026, 10, 13, 0, 30, tzinfo=timezone.utc)  # KST 09:30
        self.ledger.write_text(json.dumps([entry("2026-10-12T23:00:00+00:00"), entry("2026-10-12T23:10:00+00:00")]),
                               encoding="utf-8")

    def send(self, limit, purpose=None, transport=None):
        def fail(body):
            raise ProviderError("timeout")
        return send_once({"input": "가상"}, "fictional", ledger_path=self.ledger, max_calls=None,
                         transport=transport or fail, now=self.now, purpose=purpose, daily_limit=limit)

    def test_refuse_at_limit_without_record(self):
        before = self.ledger.read_bytes()
        for limit in (0, 2, 1):  # 상한 0, 도달, 이미 초과
            self.assertEqual(self.send(limit).status, "daily_limit_reached")
        self.assertEqual(self.ledger.read_bytes(), before)  # 전송 전 거부는 소비하지 않음

    def test_attempt_counts_even_when_it_fails(self):
        self.assertEqual(self.send(3).status, "timeout")  # 상한 직전: 1회 시도
        self.assertEqual(self.send(3).status, "daily_limit_reached")  # 실패한 시도도 소비로 셈
        self.assertEqual(len(json.loads(self.ledger.read_text(encoding="utf-8"))), 3)

    def test_analysis_and_insight_separate(self):
        self.assertEqual(self.send(2).status, "daily_limit_reached")
        self.assertEqual(self.send(2, purpose="insight").status, "timeout")

    def test_monthly_budget_still_applies(self):
        self.ledger.write_text(json.dumps([entry("2026-10-01T00:00:00+00:00", cost=oa.MONTHLY_LIMIT_USD)]), encoding="utf-8")
        self.assertEqual(self.send(20).status, "budget_exceeded")

    def test_key_missing_does_not_consume(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            sent = send_once({"input": "가상"}, "x", ledger_path=self.ledger, max_calls=None, transport=None,
                             now=self.now, daily_limit=20)
        self.assertEqual(sent.status, "api_key_missing")
        self.assertEqual(len(json.loads(self.ledger.read_text(encoding="utf-8"))), 2)


class LedgerRun:
    """send_once 와 같은 순서로 하루 상한을 확인하고, 통과하면 사용량 기록을 남기는 가짜 실행."""

    def __init__(self, purpose=None, plan=None):
        self.purpose, self.plan, self.calls = purpose, plan or {}, []

    def _gate(self, ledger_path, daily_limit):
        entries = oa.read_ledger(ledger_path)
        if daily_limit is not None and daily_used(entries, self.purpose, KST_DAY) >= daily_limit:
            return False
        entries.append(entry(NOW.isoformat(), self.purpose))
        oa.write_ledger(ledger_path, entries)
        return True

    def __call__(self, article, *rest, ledger_path, max_calls, daily_limit=None):
        if not self._gate(ledger_path, daily_limit):
            return LiveOutcome("daily_limit_reached") if self.purpose is None else ("daily_limit_reached", None)
        self.calls.append(article.article_id)
        if self.purpose == "insight":
            return "unavailable", None
        prepared = prepare_request(article)
        planned = self.plan.get(article.article_id)
        if planned is None:
            return LiveOutcome("unavailable")
        return LiveOutcome("valid", convert_response(article, prepared.request, planned))


class AnalyzeDailyCapTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        d = Path(temp.name)
        self.article_db, self.analysis_db, self.ledger = d / "saba.db", d / "analysis.db", d / "usage.json"
        self.articles = validate_articles([row(f"a{i}", "the-hacker-news", f"[Fictional] item {i}", hours=i + 1)
                                           for i in range(5)])
        save_articles(self.article_db, self.articles)
        self.issues = select_issues(self.articles, NOW).issues

    def seed(self, n, purpose=None):
        oa.write_ledger(self.ledger, [entry(NOW.isoformat(), purpose) for _ in range(n)])

    def analyze(self, limit, max_new=20):
        run = LedgerRun()
        _, stats = analyze_issues(self.issues, self.article_db, self.analysis_db, ledger_path=self.ledger, run=run,
                                  max_new_calls=max_new, daily_limit=limit, today=KST_DAY)
        return run, stats

    def test_repeated_runs_share_one_day(self):
        run, _ = self.analyze(3)
        self.assertEqual(len(run.calls), 3)
        run, stats = self.analyze(3)  # 같은 날 두 번째 실행: 남은 0
        self.assertEqual(run.calls, [])
        self.assertEqual(stats.called, 0)

    def test_remaining_after_earlier_runs_and_setting_change(self):
        self.seed(18)
        run, _ = self.analyze(20)
        self.assertEqual(len(run.calls), 2)
        run, _ = self.analyze(25)  # 같은 날 상한을 올리면 오늘 쓴 20건을 뺀 5건만
        self.assertEqual(len(run.calls), 5)

    def test_already_over_and_zero(self):
        self.seed(21)
        self.assertEqual(self.analyze(20)[0].calls, [])
        self.ledger.unlink()
        self.assertEqual(self.analyze(0)[0].calls, [])

    def test_insight_calls_do_not_use_analysis_budget(self):
        self.seed(20, "insight")
        self.assertEqual(len(self.analyze(3)[0].calls), 3)

    def test_without_daily_limit_per_run_cap_unchanged(self):  # CLI 등 명시 호출은 실행별 상한 그대로
        self.seed(30)
        run = LedgerRun()
        analyze_issues(self.issues, self.article_db, self.analysis_db, ledger_path=self.ledger, run=run, max_new_calls=2)
        self.assertEqual(len(run.calls), 2)

    def test_insights_daily_limit(self):
        from saba.analysis import AnalysisResult
        plan = {a.article_id: response() for a in self.articles}
        results, stats = analyze_issues(self.issues, self.article_db, self.analysis_db, ledger_path=self.ledger,
                                        run=LedgerRun(plan=plan), max_new_calls=5)
        self.seed(4, "insight")
        run = LedgerRun("insight")
        add_insights(self.issues, results, {}, stats, insight_db=self.ledger.parent / "insights.db", ledger_path=self.ledger,
                     max_new_calls=5, run=run, daily_limit=5, today=KST_DAY)
        self.assertEqual(len(run.calls), 1)
        self.assertEqual(stats.insights_called, 1)  # 전송 전 거부는 호출로 세지 않음


class DailyMailUsesDailyCapsTests(unittest.TestCase):
    def test_build_mail_shares_daily_caps(self):
        from unittest.mock import patch
        from saba import daily
        config = daily.DailyConfig(time="08:00", random_delay_minutes=5, weekdays=("MON",), max_analysis_calls=7,
                                   max_insight_calls=4, send=True)
        with patch("saba.briefing.build_views", return_value=([], None, None)) as build, self.assertRaises(daily.DailyError):
            daily.build_mail(NOW, config)
        kwargs = build.call_args.kwargs
        self.assertEqual((kwargs["max_new_calls"], kwargs["insight_calls"], kwargs["daily_caps"]), (7, 4, True))


class KstGateTests(unittest.TestCase):
    def test_build_views_counts_by_korean_date(self):
        from unittest.mock import patch
        from saba import briefing
        now = datetime(2026, 10, 12, 15, 30, tzinfo=timezone.utc)  # 한국 10월 13일 00:30
        with patch.object(briefing, "list_articles", return_value=[]), \
                patch.object(briefing, "notice_excerpts", return_value={}), \
                patch.object(briefing, "analyze_issues", return_value=({}, AnalysisStats())) as analyze, \
                patch.object(briefing, "add_insights", return_value={}) as insights:
            briefing.build_views(Path("a.db"), Path("b.db"), now, max_new_calls=7, insight_calls=4, daily_caps=True)
        self.assertEqual((analyze.call_args.kwargs["today"], analyze.call_args.kwargs["daily_limit"]), (date(2026, 10, 13), 7))
        self.assertEqual((insights.call_args.kwargs["today"], insights.call_args.kwargs["daily_limit"]), (date(2026, 10, 13), 4))

    def test_without_daily_caps_no_day_limit(self):
        from unittest.mock import patch
        from saba import briefing
        with patch.object(briefing, "list_articles", return_value=[]), \
                patch.object(briefing, "notice_excerpts", return_value={}), \
                patch.object(briefing, "analyze_issues", return_value=({}, AnalysisStats())) as analyze, \
                patch.object(briefing, "add_insights", return_value={}) as insights:
            briefing.build_views(Path("a.db"), Path("b.db"), NOW, max_new_calls=7)
        self.assertNotIn("daily_limit", analyze.call_args.kwargs)
        self.assertNotIn("daily_limit", insights.call_args.kwargs)


class AllPathsShareCapTests(unittest.TestCase):
    """예약·지금 발송·테스트 발송 (즉시·예약) 이 모두 같은 build_mail (하루 공유 상한) 을 쓴다."""

    def test_every_origin_uses_build_mail(self):
        import sys
        import tempfile as tf
        from unittest.mock import patch
        from saba import daily
        config = daily.DailyConfig(time="08:00", random_delay_minutes=5, weekdays=("MON",), max_analysis_calls=7,
                                   max_insight_calls=4, send=True)
        self.assertIs(daily.run_daily.__kwdefaults__["build"], daily.build_mail)
        for flags, origin in (([], "자동 실행"), (["--manual"], "관리 페이지 수동 실행"),
                              (["--test"], "테스트 발송 (예약)"), (["--test", "--manual"], "테스트 발송 (즉시)")):
            with self.subTest(origin=origin), tf.TemporaryDirectory() as temp, \
                    patch.object(sys, "argv", ["daily", "--run", *flags]), \
                    patch.multiple(daily, ROOT=Path(temp), LOG_DIR=Path(temp) / "logs", LOCK_PATH=Path(temp) / "lock",
                                   load_config=lambda: config, scheduled_on=lambda c, d: True), \
                    patch("logging.basicConfig"), patch.object(daily, "run_daily", return_value=0) as run:
                self.assertEqual(daily.main(), 0)
                self.assertNotIn("build", run.call_args.kwargs)  # 기본값 build_mail (daily_caps=True)
                self.assertEqual(run.call_args.kwargs["deliver"].keywords["origin"], origin)


if __name__ == "__main__":
    unittest.main()
