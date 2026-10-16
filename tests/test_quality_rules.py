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

    def test_instructions_name_exclusions_and_no_assumption(self):
        for phrase in ("청중·참가자·평가단 모집", "고용·경제 통계 발표", "업무협약", "곧 게시"):
            self.assertIn(phrase, openai_adapter.INSTRUCTIONS)
        for phrase in ("지어내 연결하지 않는다", "쓴다고 가정하지 않는다"):
            self.assertIn(phrase, insights.INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
