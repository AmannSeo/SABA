from datetime import datetime, timedelta, timezone
import unittest

from saba.issues import article_cves, group_issues, is_digest, preview_article, select_issues
from saba.newsletter import article_section, build_article_view
from saba.schema import validate_articles

NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)


def article(article_id, source_id, title, excerpt=None, days_ago=0):
    return {
        "schema_version": 1, "article_id": article_id, "source_id": source_id,
        "source_name": "가상 출처", "original_title": title,
        "url": f"https://example.com/fictional/{article_id}", "collection_method": "rss",
        "collected_at": NOW.isoformat(),
        "published_at": (NOW - timedelta(days=days_ago)).isoformat() if days_ago is not None else None,
        "feed_excerpt": excerpt,
    }


def build(*rows):
    return validate_articles([article(*row) if isinstance(row, tuple) else row for row in rows])


def issue_ids(issues):
    return sorted(sorted(a.article_id for a in issue.articles) for issue in issues)


class IssueTests(unittest.TestCase):
    def test_cve_extraction_case_and_html(self):
        a, = build(("a", "the-hacker-news", "[가상] 결함", "<p>cve-2026-0001 and CVE-2026-12345</p>"))
        self.assertEqual(article_cves(a), {"CVE-2026-0001", "CVE-2026-12345"})

    def test_shared_cve_links_across_sources_and_languages(self):
        articles = build(
            ("ko", "boannews", "[가상] 가상 제품서 치명적 결함", "<p>CVE-2026-0001 확인</p>", 1),
            ("en", "the-hacker-news", "[Fictional] Critical flaw", "Tracked as cve-2026-0001.", 2),
            ("other", "the-hacker-news", "[Fictional] Unrelated", "CVE-2026-0002", 1),
        )
        issues, _ = group_issues(articles)
        self.assertEqual(issue_ids(issues), [["en", "ko"], ["other"]])
        linked = next(i for i in issues if len(i.articles) == 2)
        self.assertEqual(linked.cves, {"CVE-2026-0001"})

    def test_transitive_cve_link(self):
        articles = build(("a", "cisa-cybersecurity-advisories", "[가상] A", "CVE-2026-0001", 1),
                         ("b", "the-hacker-news", "[가상] B", "CVE-2026-0001 CVE-2026-0002", 1),
                         ("c", "boannews", "[가상] C", "CVE-2026-0002", 1))
        self.assertEqual(issue_ids(group_issues(articles)[0]), [["a", "b", "c"]])

    def test_representative_official_first_then_earliest(self):
        articles = build(("media-early", "the-hacker-news", "[가상] 결함", "CVE-2026-0001", 5),
                         ("official-late", "cisa-cybersecurity-advisories", "[가상] 권고", "CVE-2026-0001", 1),
                         ("official-early", "cert-eu-security-advisories", "[가상] 권고", "CVE-2026-0001", 3))
        issue, = group_issues(articles)[0]
        self.assertEqual(issue.representative.article_id, "official-early")
        self.assertEqual([a.article_id for a in issue.related], ["official-late", "media-early"])

    def test_same_grade_earliest_and_unknown_date_last(self):
        articles = build(("late", "the-hacker-news", "[가상] A", "CVE-2026-0001", 1),
                         ("unknown", "boannews", "[가상] B", "CVE-2026-0001", None),
                         ("early", "boannews", "[가상] C", "CVE-2026-0001", 2))
        issue, = group_issues(articles)[0]
        self.assertEqual([a.article_id for a in issue.articles], ["early", "late", "unknown"])

    def test_digest_not_linked(self):
        articles = build(("recap", "the-hacker-news", "⚡ Weekly Recap: NetScaler 0-Day", "CVE-2026-0001", 1),
                         ("weekly", "boannews", "[가상] 주간 보안 동향", "CVE-2026-0001", 1),
                         ("news", "the-hacker-news", "[Fictional] NetScaler Zero-Day", "CVE-2026-0001", 1))
        self.assertTrue(is_digest(articles[0]) and is_digest(articles[1]))
        issues, candidates = group_issues(articles)
        self.assertEqual(issue_ids(issues), [["news"], ["recap"], ["weekly"]])
        self.assertEqual(candidates, [])

    def test_candidate_by_product_keyword_within_three_days(self):
        articles = build(("cert", "cert-eu-security-advisories", "2026-014: Critical Vulnerabilities in Citrix NetScaler", None, 3),
                         ("boho", "boho-security-notice", "[가상] 시트릭스 제품 보안 업데이트 권고", None, 0),
                         ("edge", "boannews", "[가상] 넷스케일러 결함 정리", None, 6),
                         ("far", "boannews", "[가상] 넷스케일러 후속 정리", None, 10))
        issues, candidates = group_issues(articles)
        self.assertEqual(len(issues), 4)  # 후보는 자동 병합하지 않는다
        pairs = sorted(sorted((c.first.representative.article_id, c.second.representative.article_id)) for c in candidates)
        # cert-edge는 정확히 3일 차이라 포함, far는 다른 기사와 모두 3일 초과라 제외
        self.assertEqual(pairs, [["boho", "cert"], ["cert", "edge"]])
        self.assertTrue(all(c.keyword == "citrix" for c in candidates))

    def test_candidate_needs_shared_keyword_and_dates(self):
        articles = build(("a", "the-hacker-news", "[Fictional] Microsoft phishing campaign", None, 0),
                         ("b", "the-hacker-news", "[Fictional] Microsoft Teams update", None, 0),
                         ("c", "boannews", "[가상] 아틀라시안 결함", None, None),
                         ("d", "the-hacker-news", "[Fictional] Atlassian flaw", None, 0))
        self.assertEqual(group_issues(articles)[1], [])  # 넓은 이름 제외, 발행일 미확인은 후보 판단 불가

    def test_linked_issue_not_reported_as_candidate_with_itself(self):
        articles = build(("a", "cisa-cybersecurity-advisories", "[가상] Citrix NetScaler 권고", "CVE-2026-0001", 0),
                         ("b", "the-hacker-news", "[Fictional] NetScaler Zero-Day", "CVE-2026-0001", 0))
        issues, candidates = group_issues(articles)
        self.assertEqual((len(issues), candidates), (1, []))

    def test_single_articles_and_input_unchanged(self):
        articles = build(("a", "boannews", "[가상] 단독 기사", None, 0), ("b", "the-hacker-news", "[Fictional] Solo", None, 0))
        before = [a.model_dump(mode="json") for a in articles]
        issues, candidates = group_issues(articles)
        self.assertEqual(issue_ids(issues), [["a"], ["b"]])
        self.assertTrue(all(issue.related == () and issue.cves == frozenset() for issue in issues))
        self.assertEqual(candidates, [])
        self.assertEqual([a.model_dump(mode="json") for a in articles], before)
        self.assertEqual(group_issues([]), ([], []))



class SelectionTests(unittest.TestCase):
    def hours(self, article_id, source_id, hours, excerpt=None, title=None):
        row = article(article_id, source_id, title or f"[가상] {article_id}", excerpt, 0)
        row["published_at"] = (NOW - timedelta(hours=hours)).isoformat()
        return row

    def test_window_24h_and_48h_for_date_only_source(self):
        articles = build(self.hours("thn-23", "the-hacker-news", 23), self.hours("thn-25", "the-hacker-news", 25),
                         self.hours("boho-47", "boho-security-notice", 47), self.hours("boho-49", "boho-security-notice", 49))
        selection = select_issues(articles, NOW)
        self.assertEqual(sorted(i.representative.article_id for i in selection.issues), ["boho-47", "thn-23"])
        self.assertEqual(selection.in_window, 2)

    def test_source_cap_section_cap_and_order(self):
        rows = [self.hours(f"thn-{h}", "the-hacker-news", h) for h in range(1, 8)]
        rows += [self.hours(f"cisa-{h}", "cisa-cybersecurity-advisories", h) for h in range(10, 16)]
        rows.append(self.hours("cert", "cert-eu-security-advisories", 20))
        selection = select_issues(build(*rows), NOW)
        ids = [i.representative.article_id for i in selection.issues]
        # 공식 출처 먼저(최신 순), 그다음 언론(최신 순). 해외 섹션 10건 상한.
        self.assertEqual(ids, ["cisa-10", "cisa-11", "cisa-12", "cisa-13", "cisa-14", "cert",
                               "thn-1", "thn-2", "thn-3", "thn-4"])
        # cisa-15는 Source 상한(5), thn-5~7은 섹션이 먼저 차서 섹션 상한으로 제외
        self.assertEqual((selection.excluded_by_source_cap, selection.excluded_by_section_cap), (1, 3))

    def test_sections_capped_independently(self):
        rows = [self.hours(f"boan-{h}", "boannews", h) for h in range(1, 4)]
        rows += [self.hours(f"thn-{h}", "the-hacker-news", h) for h in range(1, 4)]
        selection = select_issues(build(*rows), NOW)
        self.assertEqual(len(selection.issues), 6)

    def test_preview_article_region_and_related_without_mutation(self):
        rows = [self.hours("cisa", "cisa-cybersecurity-advisories", 2, "CVE-2026-0001"),
                self.hours("thn", "the-hacker-news", 1, "CVE-2026-0001", "[Fictional] Same flaw"),
                self.hours("boan", "boannews", 1, None, "[가상] 국내 기사")]
        articles = build(*rows)
        before = [a.model_dump(mode="json") for a in articles]
        selection = select_issues(articles, NOW)
        linked = next(i for i in selection.issues if i.related)
        copy = preview_article(linked)
        self.assertEqual(copy.article_id, "cisa")
        self.assertEqual(copy.region, "해외")
        self.assertEqual([(r.title, str(r.url)) for r in copy.related_articles],
                         [("[Fictional] Same flaw", "https://example.com/fictional/thn")])
        domestic = preview_article(next(i for i in selection.issues if i.representative.article_id == "boan"))
        self.assertEqual(domestic.region, "국내")
        self.assertEqual([a.model_dump(mode="json") for a in articles], before)
        view = build_article_view(copy)
        self.assertEqual(len(view.sources), 2)  # 대표 기사 + 관련 보도
        self.assertEqual(article_section(view), "overseas")

    def test_candidates_reported_not_merged(self):
        rows = [self.hours("cert", "cert-eu-security-advisories", 2, None, "2026-014: Citrix NetScaler"),
                self.hours("boho", "boho-security-notice", 3, None, "[가상] Citrix 제품 보안 업데이트 권고")]
        selection = select_issues(build(*rows), NOW)
        self.assertEqual(len(selection.issues), 2)
        self.assertEqual(len(selection.candidates), 1)


if __name__ == "__main__":
    unittest.main()
