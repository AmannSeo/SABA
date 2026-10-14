"""D-078 공공데이터 API: 나라장터·K-Startup 파서, 키워드 필터, 인증키 없음, 키 미노출, 미래 접수 시작일. 실제 접속 없음."""
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from saba import public_api
from saba.rss import RssError, Source

NOW = datetime(2026, 10, 14, 3, tzinfo=timezone.utc)
G2B = Source("virtual-g2b", "가상 나라장터", "https://apis.example.go.kr/g2b", region="국내", kind="공식 기관", topic="사업", method="api:g2b")
KS = Source("virtual-ks", "가상 K-Startup", "https://apis.example.go.kr/ks", region="국내", kind="공식 기관", topic="사업", method="api:kstartup")
WORDS = {"g2b": ["정보보호", "AI"], "kstartup": ["AI", "바우처"]}


def g2b_body(names, total=None):
    items = [{"bidNtceNo": f"R26{i:05}", "bidNtceOrd": "000", "bidNtceNm": n, "bidNtceDt": "2026-10-13 09:30:00",
              "ntceInsttNm": "가상기관", "dminsttNm": "가상수요", "bidClseDt": "2026-10-26 11:00:00", "cntrctCnclsMthdNm": "제한경쟁",
              "presmptPrce": "76363636", "bidNtceDtlUrl": f"https://www.g2b.example/{i}"} for i, n in enumerate(names)]
    return {"response": {"header": {"resultCode": "00"}, "body": {"items": items, "totalCount": total or len(items)}}}


class PublicApiTests(unittest.TestCase):
    def collect(self, source, pages, key="VIRTUAL-KEY-123"):
        calls = []
        def fetch(url, params, k):
            calls.append((url, params, k))
            return pages[len(calls) - 1]
        with patch.object(public_api, "service_key", return_value=key):
            return public_api.collect(source, NOW, fetch=fetch, keywords=WORDS), calls

    def test_g2b_keyword_filter_and_fields(self):
        articles, calls = self.collect(G2B, [g2b_body(["[가상] 정보보호 컨설팅 용역", "[가상] 청사 청소 용역", "[가상] AI 플랫폼 구축"])])
        self.assertEqual([a.original_title for a in articles], ["[가상] 정보보호 컨설팅 용역", "[가상] AI 플랫폼 구축"])
        self.assertIn("추정가격 76,363,636원", articles[0].feed_excerpt)
        self.assertEqual(articles[0].collection_method, "api")
        self.assertEqual(articles[0].published_at, datetime(2026, 10, 13, 0, 30, tzinfo=timezone.utc))  # KST 09:30
        self.assertEqual(calls[0][1]["inqryEndDt"], "202610141200")

    def test_g2b_pages_until_total(self):
        _, calls = self.collect(G2B, [g2b_body(["x"] * 3, total=450), g2b_body(["y"], total=450)])
        self.assertEqual([c[1]["pageNo"] for c in calls], ["1", "2"])

    def test_kstartup_future_start_uses_collection_time(self):
        body = {"matchCount": 2, "data": [
            {"pbanc_sn": 1, "biz_pbanc_nm": "[가상] AI 창업 지원", "pbanc_rcpt_bgng_dt": "20261020", "pbanc_rcpt_end_dt": "20261031",
             "aply_trgt": "일반기업", "pbanc_ntrp_nm": "가상센터", "detl_pg_url": "https://k.example/1"},
            {"pbanc_sn": 2, "biz_pbanc_nm": "[가상] 지역 축제 참가자 모집", "pbanc_rcpt_bgng_dt": "20261010", "pbanc_rcpt_end_dt": "20261020",
             "detl_pg_url": "https://k.example/2"}]}
        [article], _ = self.collect(KS, [body])
        self.assertEqual(article.published_at, NOW)  # 미래 시작일 대신 수집 시각
        self.assertIn("접수 2026-10-20 ~ 2026-10-31", article.feed_excerpt)

    def test_missing_key_and_key_never_in_errors(self):
        with patch.object(public_api, "service_key", return_value=None), self.assertRaisesRegex(RssError, "인증키가 없습니다"):
            public_api.collect(G2B, NOW, fetch=lambda *a: {}, keywords=WORDS)
        for broken in ({"response": {"header": {"resultCode": "30"}, "body": {}}}, {"unexpected": True}):
            with self.subTest(broken=broken), self.assertRaises(RssError) as caught:
                self.collect(G2B, [broken], key="SECRET-VALUE-XYZ")
            self.assertNotIn("SECRET-VALUE-XYZ", str(caught.exception))

    def test_keyword_file_rules(self):
        with self.assertRaises(RssError):
            public_api.save_keywords({"g2b": [], "kstartup": ["AI"]}, path=None)


if __name__ == "__main__":
    unittest.main()
