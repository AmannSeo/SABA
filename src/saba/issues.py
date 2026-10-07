"""같은 사건 기사 묶기 (D-027). 저장하지 않고 호출 시점에 계산하며 입력 기사를 바꾸지 않는다."""

from dataclasses import dataclass
from datetime import timedelta
from itertools import combinations
import re

from saba.analysis import FeedTextParser, normalize_text
from saba.rss import SOURCE_BY_ID
from saba.schema import Article, SourceReference

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


# Preview 선별 (D-029). 중요도 판단이 아닌 기계적 상한이다. 값은 실제 Preview를 보고 조정한다.
MAX_PER_SOURCE = 5
MAX_PER_SECTION = 10


@dataclass(frozen=True)
class Selection:
    issues: list[Issue]
    candidates: list[Candidate]
    in_window: int
    excluded_by_source_cap: int
    excluded_by_section_cap: int


def in_window(article: Article, now) -> bool:
    source = SOURCE_BY_ID.get(article.source_id)
    hours = 48 if source is not None and source.date_only else 24
    return article.published_at is not None and now - timedelta(hours=hours) <= article.published_at <= now


def select_issues(articles: list[Article], now) -> Selection:
    """기간 안 기사를 묶고, 공식 출처 우선 → 최신 순으로 Source별·섹션(출처 국가)별 상한을 적용한다."""
    window = [article for article in articles if in_window(article, now)]
    issues, candidates = group_issues(window)
    ordered = sorted(issues, key=lambda issue: (not is_official(issue.representative),
                                                -issue.representative.published_at.timestamp(),
                                                issue.representative.article_id))
    per_source: dict[str, int] = {}
    per_section: dict[str, int] = {}
    selected, source_cut, section_cut = [], 0, 0
    for issue in ordered:
        source = SOURCE_BY_ID[issue.representative.source_id]
        if per_source.get(source.source_id, 0) >= MAX_PER_SOURCE:
            source_cut += 1
            continue
        if per_section.get(source.region, 0) >= MAX_PER_SECTION:
            section_cut += 1
            continue
        per_source[source.source_id] = per_source.get(source.source_id, 0) + 1
        per_section[source.region] = per_section.get(source.region, 0) + 1
        selected.append(issue)
    return Selection(selected, candidates, len(window), source_cut, section_cut)


def preview_article(issue: Issue) -> Article:
    """대표 기사 사본에 출처 국가와 같은 사건 관련 보도를 붙인다. 원본과 DB는 바꾸지 않는다."""
    representative = issue.representative
    related = [SourceReference(source_name=a.source_name, title=a.original_title, url=a.url,
                               published_at=a.published_at) for a in issue.related]
    return representative.model_copy(update={
        "region": SOURCE_BY_ID[representative.source_id].region,
        "related_articles": [*representative.related_articles, *related],
    })
