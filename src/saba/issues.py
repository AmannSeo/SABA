"""같은 사건 기사 묶기 (D-027). 저장하지 않고 호출 시점에 계산하며 입력 기사를 바꾸지 않는다."""

from dataclasses import dataclass
from datetime import timedelta
from itertools import combinations
import re

from saba.analysis import FeedTextParser, normalize_text
from saba.rss import SOURCE_BY_ID
from saba.schema import Article

CVE_PATTERN = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
# 여러 사건을 함께 다루는 요약 기사 표지. 제목에 있으면 묶지 않는다.
DIGEST_MARKERS = ("weekly recap", "week in review", "주간")
# ponytail: 고정 제품 키워드 목록, 실제 수집 사례 기반. 누락·오탐이 늘면 목록을 보완한다.
# 너무 넓은 이름(Microsoft, Google 등)은 다른 사건이 섞이므로 넣지 않는다.
PRODUCT_KEYWORDS = (
    ("citrix", "netscaler", "시트릭스", "넷스케일러"),
    ("atlassian", "jira", "confluence", "아틀라시안", "지라", "컨플루언스"),
    ("fortinet", "fortigate", "fortios", "fortimail", "포티넷"),
    ("cisco", "시스코"),
    ("check point", "체크포인트"),
    ("f5 big-ip", "big-ip"),
    ("sap netweaver", "sap kernel"),
    ("ivanti", "이반티"),
    ("palo alto", "pan-os"),
    ("vmware", "vcenter", "esxi"),
    ("exchange server", "microsoft exchange"),
    ("sharepoint", "셰어포인트"),
    ("wordpress", "워드프레스"),
    ("apache", "아파치"),
    ("gitlab", "깃랩"),
    ("mikrotik", "routeros"),
)
CANDIDATE_WINDOW = timedelta(days=3)


@dataclass(frozen=True)
class Issue:
    representative: Article
    related: tuple[Article, ...]
    cves: frozenset[str]

    @property
    def articles(self) -> tuple[Article, ...]:
        return (self.representative, *self.related)


@dataclass(frozen=True)
class Candidate:
    """같은 사건일 수 있는 이슈 쌍. 자동 병합하지 않고 사람이 확정한다."""

    first: Issue
    second: Issue
    keyword: str


def article_text(article: Article) -> str:
    parser = FeedTextParser()
    parser.feed(article.feed_excerpt or "")
    parser.close()
    return normalize_text(article.original_title + " " + "".join(parser.parts))


def article_cves(article: Article) -> frozenset[str]:
    return frozenset(match.upper() for match in CVE_PATTERN.findall(article_text(article)))


def is_digest(article: Article) -> bool:
    title = article.original_title.lower()
    return any(marker in title for marker in DIGEST_MARKERS)


def is_official(article: Article) -> bool:
    source = SOURCE_BY_ID.get(article.source_id)
    return source is not None and source.official


def title_keywords(article: Article) -> set[str]:
    title = normalize_text(article.original_title).lower()
    return {group[0] for group in PRODUCT_KEYWORDS if any(name in title for name in group)}


def group_issues(articles: list[Article]) -> tuple[list[Issue], list[Candidate]]:
    """CVE를 공유하는 기사는 자동으로 묶고, 제품 키워드와 3일 이내 발행이 겹치는 이슈는 후보로만 표시한다."""
    cves = {article.article_id: article_cves(article) for article in articles}
    parent = list(range(len(articles)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    owner: dict[str, int] = {}
    for index, article in enumerate(articles):
        if is_digest(article):
            continue
        for cve in cves[article.article_id]:
            if cve in owner:
                parent[root(index)] = root(owner[cve])
            else:
                owner[cve] = index
    groups: dict[int, list[Article]] = {}
    for index, article in enumerate(articles):
        groups.setdefault(root(index), []).append(article)

    issues = []
    for members in groups.values():
        # 공식 출처 우선, 같은 등급이면 먼저 발행된 기사. 발행일 미확인은 뒤로 둔다.
        ordered = sorted(members, key=lambda a: (not is_official(a), a.published_at is None,
                                                 a.published_at or a.collected_at, a.article_id))
        issues.append(Issue(ordered[0], tuple(ordered[1:]),
                            frozenset().union(*(cves[a.article_id] for a in members))))
    issues.sort(key=lambda issue: issue.representative.article_id)

    candidates = []
    for first, second in combinations(issues, 2):
        if any(is_digest(a) for a in (*first.articles, *second.articles)):
            continue
        shared = set().union(*map(title_keywords, first.articles)) & set().union(*map(title_keywords, second.articles))
        if not shared:
            continue
        dates = [(a.published_at, b.published_at) for a in first.articles for b in second.articles
                 if a.published_at is not None and b.published_at is not None]
        if any(abs(x - y) <= CANDIDATE_WINDOW for x, y in dates):
            candidates.append(Candidate(first, second, sorted(shared)[0]))
    return issues, candidates
