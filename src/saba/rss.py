"""승인된 Source Feed의 메타데이터만 수집한다 (D-023, D-024)."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import http.client
from pathlib import Path
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from pydantic import HttpUrl, TypeAdapter, ValidationError

from saba.schema import Article, validate_articles
from saba.storage import StorageError, list_articles, normalized_json



@dataclass(frozen=True)
class Source:
    source_id: str
    source_name: str
    feed_url: str
    # 시간대 없는 pubDate(YYYY-MM-DD, YYYY-MM-DD HH:MM:SS)를 이 UTC 오프셋 기준으로 해석한다. None이면 미확인 처리.
    local_offset: timedelta | None = None
    # pubDate가 날짜만 있어 0시로 해석되는 Source. 기본 수집 기간을 48시간으로 늘린다 (D-025).
    date_only: bool = False
    # 공식 기관 출처. 같은 사건 묶음의 대표 기사 선택에 우선한다 (D-027).
    official: bool = False
    # 출처 국가 기준 국내·해외. Preview 섹션 배치에만 쓰며 사건 발생 지역이 아니다 (D-029).
    region: str = "해외"


KST = timedelta(hours=9)  # 한국 표준시, 일광 절약 시간 없음
SOURCES = (
    Source("cert-eu-security-advisories", "CERT-EU", "https://cert.europa.eu/publications/security-advisories-rss",
           official=True),
    Source("boho-security-notice", "KISA 보호나라", "https://www.boho.or.kr/kr/rss.do?bbsId=B0000133",
           local_offset=KST, date_only=True, official=True, region="국내"),
    Source("cisa-cybersecurity-advisories", "CISA", "https://www.cisa.gov/cybersecurity-advisories/all.xml",
           official=True),
    Source("the-hacker-news", "The Hacker News", "https://feeds.feedburner.com/TheHackersNews"),
    Source("boannews", "보안뉴스", "https://www.boannews.com/rss/allArticle.xml", local_offset=KST, region="국내"),
    Source("boho-report-guide", "KISA 보호나라 보고서·가이드", "https://www.boho.or.kr/kr/rss.do?bbsId=B0000127",
           local_offset=KST, date_only=True, official=True, region="국내"),
)
SOURCE_BY_ID = {source.source_id: source for source in SOURCES}
CERT_EU = SOURCES[0]
FEED_URL = CERT_EU.feed_url
SOURCE_ID = CERT_EU.source_id
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 15
SOURCE_FIELDS = (
    "schema_version", "article_id", "source_id", "source_name", "original_title",
    "url", "collection_method", "source_item_id", "published_at", "feed_excerpt",
)


class RssError(ValueError):
    """응답 원문 없이 보고할 수 있는 수집 오류."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_feed(source: Source = CERT_EU) -> bytes:
    # timeout은 각 소켓 작업의 제한이다. DNS 및 전체 실행의 15초 상한은 아니다.
    request = urllib.request.Request(source.feed_url, headers={
        "User-Agent": "SABA/0.1 RSS metadata collector",
        "Accept": "application/rss+xml, application/xml, text/xml",
        "Accept-Encoding": "identity",
    })
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=TIMEOUT) as response:
            if response.status != 200:
                raise RssError("RSS HTTP 응답 상태가 200이 아닙니다.")
            if response.headers.get_content_type() not in (
                "application/rss+xml", "application/xml", "text/xml",
            ) or response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise RssError("RSS Content-Type 또는 Content-Encoding이 예상과 다릅니다.")
            payload = response.read(MAX_BYTES + 1)
            if len(payload) > MAX_BYTES:
                raise RssError("RSS 응답이 2MiB 상한을 초과했습니다.")
            return payload
    except urllib.error.HTTPError as exc:
        raise RssError(f"RSS HTTP 오류: {exc.code}. Redirect와 자동 재시도는 허용하지 않습니다.") from None
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        raise RssError(f"RSS 네트워크 요청 실패: {type(exc).__name__}. 연결·권한·시간 초과를 확인하세요.") from None


def publication_time(value: str | None, local_offset: timedelta | None = None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    if local_offset is not None:
        for pattern, layout in ((r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
                                (r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", "%Y-%m-%d %H:%M:%S")):
            if re.fullmatch(pattern, value):
                try:
                    local = datetime.strptime(value, layout).replace(tzinfo=timezone(local_offset))
                except ValueError:
                    return None
                return local.astimezone(timezone.utc)
    value = re.sub(r"\bCEST$", "+0200", value)
    value = re.sub(r"\bCET$", "+0100", value)
    try:
        result = parsedate_to_datetime(value)
        if result.tzinfo is None or result.utcoffset() is None:
            return None
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def parse_feed(payload: bytes, now: datetime, source: Source = CERT_EU) -> list[Article]:
    if len(payload) > MAX_BYTES:
        raise RssError("RSS 응답이 2MiB 상한을 초과했습니다.")
    # 외부 DTD와 엔티티는 수집에 필요하지 않으며 확장하지 않는다.
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeError:
        raise RssError("RSS는 UTF-8 XML이어야 합니다.") from None
    if "\x00" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise RssError("RSS DTD·엔티티 선언은 허용하지 않습니다.")
    try:
        root = ET.fromstring(payload)
    except (ET.ParseError, LookupError, ValueError):
        raise RssError("RSS XML을 파싱할 수 없습니다.") from None
    channels = root.findall("channel")
    if root.tag != "rss" or root.get("version") != "2.0" or len(channels) != 1:
        raise RssError("예상한 RSS 2.0 channel 형식이 아닙니다.")
    data = []
    for index, item in enumerate(channels[0].findall("item")):
        title = item.findtext("title")
        link = item.findtext("link")
        if not title or not title.strip() or not link or not link.strip():
            raise RssError(f"RSS 항목 {index + 1}: 필수 제목 또는 URL이 없습니다.")
        guid = item.findtext("guid")
        guid = guid if guid and guid.strip() else None
        try:
            url = str(TypeAdapter(HttpUrl).validate_python(link.strip()))
        except ValidationError:
            raise RssError(f"RSS 항목 {index + 1}: HTTP(S) URL이 필요합니다.") from None
        identity = "guid:" + guid if guid else "url:" + url
        digest = hashlib.sha256((source.source_id + "\n" + identity).encode("utf-8")).hexdigest()
        excerpt = item.findtext("description")
        data.append({
            "schema_version": 1, "article_id": source.source_id + ":" + digest,
            "source_id": source.source_id, "source_name": source.source_name,
            "original_title": title, "url": url, "collection_method": "rss",
            "source_item_id": guid, "collected_at": now.isoformat(),
            "published_at": publication_time(item.findtext("pubDate"), source.local_offset),
            "feed_excerpt": excerpt if excerpt and excerpt.strip() else None,
        })
    try:
        return validate_articles(data) if data else []
    except (ValidationError, ValueError):
        raise RssError("RSS 기사 Schema 또는 Feed 내부 ID 중복 검증에 실패했습니다.") from None


def select_articles(articles: list[Article], now: datetime, *, bootstrap=False,
                    since: datetime | None = None, date_only=False) -> tuple[list[Article], dict[str, int]]:
    if bootstrap and since is not None:
        raise RssError("bootstrap과 since는 함께 사용할 수 없습니다.")
    if since is not None:
        if since.tzinfo is None or since.utcoffset() is None or since > now:
            raise RssError("복구 시작 시각은 시간대가 있고 미래가 아닌 값이어야 합니다.")
        start = max(since - timedelta(hours=6), now - timedelta(days=7))
    else:
        # 날짜만 있는 Source는 0시로 해석하므로 기본 기간을 하루 늘려 전날 게시분 누락을 막는다 (D-025).
        start = now - timedelta(days=30) if bootstrap else now - timedelta(hours=48 if date_only else 24)
    unknown = [article for article in articles if article.published_at is None]
    dated = [article for article in articles
             if article.published_at is not None and start <= article.published_at <= now]
    dated.sort(key=lambda article: (article.published_at, article.article_id), reverse=True)
    # 발행일 미확인은 보관하되 최신 날짜가 확인된 기사를 먼저 선택한다.
    eligible = dated + unknown
    selected = eligible[:30]
    return selected, {
        "total": len(articles), "excluded": len(articles) - len(eligible),
        "unknown": len(unknown), "limited": max(0, len(eligible) - 30),
        "candidates": len(selected),
    }


def reconcile_articles(path: Path, articles: list[Article]) -> tuple[list[Article], int]:
    # ponytail: 전체 기사 읽기, DB 규모가 커지면 ID별 일괄 조회로 교체한다.
    existing = {article.article_id: article for article in list_articles(path)} if path.exists() else {}
    result = []
    skipped = conflicts = 0
    for article in articles:
        old = existing.get(article.article_id)
        if old is None:
            result.append(article)
            continue
        compared = old.model_copy(update={field: getattr(article, field) for field in SOURCE_FIELDS})
        if normalized_json(old) != normalized_json(compared):
            conflicts += 1
        else:
            result.append(old)
            skipped += 1
    if conflicts:
        raise StorageError(f"RSS 원문 변경 충돌 {conflicts}건: 신규 저장 0건. 입력 전체 저장을 보류했습니다.")
    return result, skipped
