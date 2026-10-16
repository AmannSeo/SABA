"""2026-10-16 사용자 지적 회귀: 부서와 관련 없는 기사·억지 부서 연결 (09:42 메일 23건 점검)."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from saba import briefing, insights, newsletter, openai_adapter


class Connection:
    def __init__(self, department, text="가상 연결"):
        self.department, self.text = department, text

    def model_copy(self, update):
        return Connection(self.department, update.get("text", self.text))


class Insight:
    def __init__(self, departments):
        self.implication, self.connections = "가상 시사점", [Connection(d) for d in departments]

    def model_copy(self, update):
        copy = Insight([])
        copy.implication, copy.connections = update["implication"], update["connections"]
        return copy


class QualityRuleTests(unittest.TestCase):
    def test_labour_article_keeps_only_strategy_department(self):
        # 고용 통계의 "취약 부문" 을 보안 점검에 엮은 연결 등은 버린다
        shown = briefing.display_insight(Insight(list(insights.DEPARTMENTS)), "경영·노무·세무")
        self.assertEqual([c.department for c in shown.connections], ["경영전략팀 · 사업지원팀"])
        advisory = briefing.display_insight(Insight(list(insights.DEPARTMENTS)), "취약점·권고")
        self.assertEqual({c.department for c in advisory.connections}, {"보안사업팀", "기술개발연구소"})
        old = briefing.display_insight(Insight(["STE본부"]), None)  # 분류 없는 예전 결과는 그대로
        self.assertEqual(len(old.connections), 1)

    def test_department_box_prefers_own_category_then_importance(self):
        base = newsletter.ArticleView(article_id="x", title="t", source_name="s", url="https://example.com", date_display="",
                                      date_label="", excerpt=None, category=None)
        labour = replace(base, article_id="l", category="경영·노무·세무", importance="보통",
                         ai_connections={"보안사업팀": "억지"})
        low = replace(base, article_id="a", category="취약점·권고", importance="낮음", ai_connections={"보안사업팀": "점검"})
        high = replace(base, article_id="b", category="취약점·권고", importance="높음", ai_connections={"보안사업팀": "점검"})
        ids = [v.article_id for v in newsletter._department_views("보안사업팀", [labour, low, high])]
        self.assertEqual(ids, ["b", "a", "l"])

    def test_stale_business_judgements_are_rechecked(self):
        def record(category, stored_at, status="검토 필요"):
            return {"stored_at": stored_at, "result": {"status": status, "category": category}}
        self.assertTrue(briefing._stale(record("경영·노무·세무", "2026-10-16T00:43:55+00:00")))
        self.assertTrue(briefing._stale(record("SW 테스트·품질", "2026-10-15T12:00:00+00:00")))
        self.assertFalse(briefing._stale(record("경영·노무·세무", "2026-10-16T03:00:01+00:00")))  # 새 기준 결과
        self.assertFalse(briefing._stale(record("취약점·권고", "2026-10-15T12:00:00+00:00")))  # 보안은 재사용
        self.assertFalse(briefing._stale(record("경영·노무·세무", "2026-10-15T12:00:00+00:00", "대상 밖")))

    def test_identical_recheck_is_remembered(self):
        # 새 기준으로 다시 분석해도 같은 결과면 분석 DB 는 그대로라 (저장 시각 유지) 따로 남겨 매일 재호출하지 않는다
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "analysis.db"
            old = {"analysis_id": "a1", "stored_at": "2026-10-15T00:00:00+00:00",
                   "result": {"status": "검토 필요", "category": "경영·노무·세무"}}
            self.assertTrue(briefing._stale(old, briefing._load_rechecked(db)))
            briefing._mark_rechecked(db, "a1")
            self.assertFalse(briefing._stale(old, briefing._load_rechecked(db)))
            (Path(directory) / "analysis_rechecked.json").write_text("{broken", encoding="utf-8")
            with self.assertLogs(level="WARNING"):
                self.assertEqual(briefing._load_rechecked(db), frozenset())  # 깨진 파일은 다시 확인하면 된다
            with patch("os.replace", side_effect=PermissionError), self.assertLogs(level="WARNING"):
                briefing._mark_rechecked(db, "a2")  # 쓰지 못해도 실행은 계속한다

    def test_same_event_merge_is_conservative(self):
        from datetime import datetime, timedelta, timezone
        from types import SimpleNamespace
        base = newsletter.ArticleView(article_id="x", title="t", source_name="s", url="https://example.com", date_display="",
                                      date_label="", excerpt=None, category="취약점·권고")
        day = datetime(2026, 10, 14, tzinfo=timezone.utc)

        def pair(i, title, summary, source="cert-eu-security-advisories", category="취약점·권고", days=0):
            view = replace(base, article_id=f"{source}:{i}", title=title, summary=summary, category=category,
                           sources=[(source, title, f"https://example.com/{i}", "")])
            return view, SimpleNamespace(article_id=view.article_id, source_id=source, published_at=day + timedelta(days=days),
                                         original_title=title, feed_excerpt=None)
        kisa = pair(1, "Cisco 제품 보안 업데이트 권고", "Cisco Secure Email Gateway 에서 발생하는 취약점", "boho-security-notice")
        cert = pair(2, "Cisco Secure Email Gateway 의 심각한 취약점", "Cisco Secure Email Gateway 루트 권한 실행")
        merged = briefing.merge_same_event([kisa, cert])
        self.assertEqual(len(merged), 1)
        self.assertEqual([s[0] for s in merged[0].sources], ["boho-security-notice", "cert-eu-security-advisories"])
        xe, xr = pair(3, "Cisco IOS XE 취약점", "Cisco IOS XE 웹 UI"), pair(4, "Cisco IOS XR 취약점", "Cisco IOS XR 라우터")
        self.assertEqual(len(briefing.merge_same_event([xe, xr])), 2)  # 두 단어만 같으면 다른 제품
        late = pair(5, "Cisco Secure Email Gateway 패치", "Cisco Secure Email Gateway 패치", days=5)
        self.assertEqual(len(briefing.merge_same_event([cert, late])), 2)  # 3일 넘으면 따로
        ai = pair(6, "Cisco Secure Email Gateway AI 기능", "Cisco Secure Email Gateway AI", category="AI·기술")
        self.assertEqual(len(briefing.merge_same_event([cert, ai])), 2)  # 보안 분류끼리만
        a = pair(7, "Cisco Secure Email Gateway CVE-2026-1111", "Cisco Secure Email Gateway 취약점")
        b = pair(8, "Cisco Secure Email Gateway CVE-2026-2222", "Cisco Secure Email Gateway 취약점")
        self.assertEqual(len(briefing.merge_same_event([a, b])), 2)  # 서로 다른 CVE 는 다른 취약점 (Codex 교차 검증)
        same = pair(9, "Cisco Secure Email Gateway 권고 CVE-2026-1111", "Cisco Secure Email Gateway 패치")
        self.assertEqual(len(briefing.merge_same_event([a, same])), 1)
        self.assertEqual(len(briefing.merge_same_event([a, cert])), 1)  # 한쪽에만 CVE 가 있으면 제품으로 판단

    def test_auth_failure_day_is_not_sent(self):
        from datetime import datetime, timezone
        from saba import daily
        stats = briefing.AnalysisStats(auth_failed=True)
        config = daily.load_config()
        with patch("saba.briefing.build_views", return_value=([object()], None, stats)),                 self.assertRaisesRegex(daily.DailyError, "AI 인증 실패로 발송하지 않음"):
            daily.build_mail(datetime(2026, 10, 16, tzinfo=timezone.utc), config)

    def test_instructions_name_exclusions_and_no_assumption(self):
        for phrase in ("청중·참가자·평가단 모집", "고용·경제 통계 발표", "업무협약", "곧 게시"):
            self.assertIn(phrase, openai_adapter.INSTRUCTIONS)
        for phrase in ("지어내 연결하지 않는다", "쓴다고 가정하지 않는다"):
            self.assertIn(phrase, insights.INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
