"""승인된 Source Feed의 메타데이터만 수집한다 (D-023, D-024)."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
import http.client
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from pydantic import HttpUrl, TypeAdapter, ValidationError

from saba.schema import Article, validate_articles
from saba.storage import StorageError, list_articles, normalized_json



class RssError(ValueError):
    """응답 원문 없이 보고할 수 있는 수집 오류."""


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
    # 관리 화면 분류 (D-074). official 은 kind == "공식 기관" 이다.
    kind: str = "보안 전문 매체"
    # 메일 섹션·선별 상한 묶음 (F13). "보안" 은 기존처럼 region 으로 나누고, 나머지는 주제 섹션으로 간다.
    topic: str = "보안"
    # 수집 방식 (D-078): "rss" 는 RSS·Atom, "crawl:<사이트>" 는 saba.crawl 의 목록 페이지 수집기.
    method: str = "rss"


KST = timedelta(hours=9)  # 한국 표준시, 일광 절약 시간 없음
SOURCES_PATH = Path(__file__).resolve().parents[2] / "config" / "sources.json"
MAX_SOURCES = 60  # D-073 은 15곳, 부서별 신규 출처 추가로 늘림 (F13, 2026-10-13)
REGIONS = ("국내", "해외")
KINDS = ("공식 기관", "보안 전문 매체", "IT 언론", "기업·벤더")  # D-074
TOPICS = ("보안", "경영", "사업", "테스트", "AI", "개발")  # 개발: 개발 도구·인프라 (2026-10-16 사용자 결정, D-085)  # AI: AI 개발·도입 (기술개발연구소 관심사, 2026-10-14)  # F13: 보안·AI (기존) + 경영·노무·세무, 사업 지원·마케팅, SW 테스트·품질
METHODS = ("rss", "crawl:bizinfo", "crawl:moel", "crawl:nts", "crawl:iris", "crawl:nipa", "crawl:smtech",
           "crawl:kocca", "crawl:searchadvisor", "crawl:kiat", "crawl:selenium",  # saba.crawl.PARSERS 와 같아야 한다
           "api:g2b", "api:kstartup", "api:law")  # 공공데이터 API (saba.public_api, D-078)
SOURCE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{2,39}")


@dataclass(frozen=True)
class SourceEntry:
    """설정 파일의 Source 한 줄 (D-073). 관리 화면에서 추가·수정·중지·삭제한다."""
    source: Source
    enabled: bool = True
    note: str = ""  # 관리 메모 (중지 사유 등, 200자). 수집에는 쓰지 않는다 (2026-10-16 사용자 요청)


def check_api_url(url: str) -> None:
    """환경 변수 인증키를 붙일 주소는 승인된 공공 API 호스트로 제한한다."""
    try:
        parts = urllib.parse.urlsplit(url)
        valid = (parts.scheme == "https" and parts.hostname in {"apis.data.go.kr", "www.law.go.kr"}
                 and parts.port in (None, 443) and not (parts.username or parts.password or parts.query or parts.fragment))
    except ValueError:
        valid = False
    if not valid:
        raise RssError("공공 API 주소는 승인된 HTTPS 호스트이며 인증정보·쿼리·조각이 없어야 합니다.")


def parse_sources(rows: list) -> list[SourceEntry]:
    """설정 값 검증. 잘못된 줄이 있으면 전체를 거부한다 (수집 대상이 조용히 바뀌지 않게)."""
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_SOURCES:
        raise RssError(f"Source 설정 오류: 1~{MAX_SOURCES}개여야 합니다.")
    entries, seen = [], set()
    for row in rows:
        try:
            source_id, name, url = str(row["id"]), str(row["name"]).strip(), str(row["url"]).strip()
            region, kst, date_only, enabled = (row.get("region", "해외"), bool(row.get("kst", False)),
                                               bool(row.get("date_only", False)), bool(row.get("enabled", True)))
            kind = row.get("kind") or ("공식 기관" if row.get("official") else "보안 전문 매체")
            topic = row.get("topic") or "보안"
            method = row.get("method") or "rss"
            note = " ".join(str(row.get("note") or "").split())
        except (KeyError, TypeError, AttributeError):
            raise RssError("Source 설정 오류: id·name·url 이 필요합니다.") from None
        if not SOURCE_ID_PATTERN.fullmatch(source_id) or source_id in seen:
            raise RssError(f"Source 설정 오류: ID 는 영문 소문자·숫자·하이픈 3~40자이고 겹치지 않아야 합니다 ({source_id[:40]}).")
        if not name or len(name) > 60:
            raise RssError("Source 설정 오류: 이름은 1~60자여야 합니다.")
        if not re.fullmatch(r"https://[^\s<>\"']{4,290}", url):
            raise RssError("Source 설정 오류: RSS 주소는 https:// 로 시작해야 합니다.")
        if region not in REGIONS:
            raise RssError("Source 설정 오류: 구분은 국내·해외 중 하나여야 합니다.")
        if kind not in KINDS:
            raise RssError("Source 설정 오류: 종류는 공식 기관·보안 전문 매체·IT 언론·기업·벤더 중 하나여야 합니다.")
        if topic not in TOPICS:
            raise RssError("Source 설정 오류: 주제는 " + "·".join(TOPICS) + " 중 하나여야 합니다.")
        if method not in METHODS:
            raise RssError("Source 설정 오류: 수집 방식은 " + "·".join(METHODS) + " 중 하나여야 합니다.")
        if len(note) > 200:
            raise RssError("Source 설정 오류: 메모는 200자 이하여야 합니다.")
        if method.startswith("api:"):
            check_api_url(url)
        seen.add(source_id)
        entries.append(SourceEntry(Source(source_id, name, url, KST if kst else None, date_only, kind == "공식 기관",
                                          region, kind, topic, method), enabled, note))
    return entries


def source_row(entry: SourceEntry) -> dict:
    s = entry.source
    return {"id": s.source_id, "name": s.source_name, "url": s.feed_url, "region": s.region, "kind": s.kind,
            "topic": s.topic, "method": s.method, "kst": s.local_offset is not None, "date_only": s.date_only,
            "enabled": entry.enabled, **({"note": entry.note} if entry.note else {})}


def load_source_entries(path: Path = SOURCES_PATH) -> list[SourceEntry]:
    return parse_sources(json.loads(path.read_text(encoding="utf-8-sig")))


def save_source_entries(entries: list[SourceEntry], path: Path = SOURCES_PATH) -> None:
    rows = [source_row(entry) for entry in entries]
    parse_sources(rows)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def reload_sources(path: Path = SOURCES_PATH) -> None:
    """SOURCES 는 사용 중인 Source, SOURCE_BY_ID 는 중지 포함 전체 (이미 수집한 기사 표시용).

    SOURCE_BY_ID 는 같은 dict 를 고쳐 쓴다 (from saba.rss import SOURCE_BY_ID 로 가져간 모듈도 바로 반영).
    삭제된 Source 의 기사는 SOURCE_BY_ID 에 없어 표시에서 빠진다.
    """
    global SOURCES
    entries = load_source_entries(path)
    SOURCES = tuple(entry.source for entry in entries if entry.enabled)
    SOURCE_BY_ID.clear()
    SOURCE_BY_ID.update({entry.source.source_id: entry.source for entry in entries})


SOURCES: tuple[Source, ...] = ()
SOURCE_BY_ID: dict[str, Source] = {}
reload_sources()
# 함수 기본값·테스트용. 설정에서 삭제돼도 가져오기가 깨지지 않게 설정과 따로 둔다.
CERT_EU = Source("cert-eu-security-advisories", "CERT-EU", "https://cert.europa.eu/publications/security-advisories-rss",
                 official=True, kind="공식 기관")
FEED_URL = CERT_EU.feed_url
SOURCE_ID = CERT_EU.source_id
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 15
SOURCE_FIELDS = (
    "schema_version", "article_id", "source_id", "source_name", "original_title",
    "url", "collection_method", "source_item_id", "published_at", "feed_excerpt",
)


ATOM = "{http://www.w3.org/2005/Atom}"
PRERELEASE = re.compile(r"(?<![a-z])(alpha|beta|nightly|preview|canary)(?![a-z])|(?:[-.]|\d)rc[.-]?\d*\b|\brc\b|\d[ab]\d+\b", re.IGNORECASE)


def _atom_item(entry) -> dict:
    """Atom entry 를 RSS item 과 같은 모양으로 바꾼다 (F13: GitHub 릴리스·Blogger 피드)."""
    links = entry.findall(ATOM + "link")
    link = next((l.get("href") for l in links if l.get("rel", "alternate") == "alternate"), None)
    # content 는 릴리스 노트 전문일 수 있어 길이를 줄인다. summary 가 있으면 그것을 쓴다.
    excerpt = entry.findtext(ATOM + "summary") or (entry.findtext(ATOM + "content") or "")[:3000]
    return {"title": entry.findtext(ATOM + "title"), "link": link, "guid": entry.findtext(ATOM + "id"),
            "date": entry.findtext(ATOM + "published") or entry.findtext(ATOM + "updated"), "excerpt": excerpt}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_feed(source: Source = CERT_EU) -> bytes:
    # timeout은 각 소켓 작업의 제한이다. DNS 및 전체 실행의 15초 상한은 아니다.
    request = urllib.request.Request(source.feed_url, headers={
        "User-Agent": "SABA/0.1 RSS metadata collector",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
        "Accept-Encoding": "identity",
    })
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=TIMEOUT) as response:
            if response.status != 200:
                raise RssError("RSS HTTP 응답 상태가 200이 아닙니다.")
            if response.headers.get_content_type() not in (
                "application/rss+xml", "application/atom+xml", "application/xml", "text/xml",
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
        for pattern, layout in ((r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"), (r"\d{4}\.\d{2}\.\d{2}", "%Y.%m.%d"),
                                (r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", "%Y-%m-%d %H:%M:%S")):
            if re.fullmatch(pattern, value):
                try:
                    local = datetime.strptime(value, layout).replace(tzinfo=timezone(local_offset))
                except ValueError:
                    return None
                return local.astimezone(timezone.utc)
    value = re.sub(r"\bCEST$", "+0200", value)
    value = re.sub(r"\bCET$", "+0100", value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:\d{2})", value):  # Atom (RFC 3339)
        try:
            return datetime.fromisoformat(value).astimezone(timezone.utc)
        except ValueError:
            return None
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
    # DTD·엔티티 선언은 루트 요소 앞(prolog)에만 올 수 있다. 본문 기사 안의 "<!DOCTYPE" 글자는 선언이 아니다.
    root_start = re.search(r"<(?:rss|[\w.-]*:?feed)\b", text)
    prolog = text[:root_start.start()] if root_start else text
    if "\x00" in text or "<!DOCTYPE" in prolog.upper() or "<!ENTITY" in prolog.upper():
        raise RssError("RSS DTD·엔티티 선언은 허용하지 않습니다.")
    try:
        root = ET.fromstring(payload)
    except (ET.ParseError, LookupError, ValueError):
        raise RssError("RSS XML을 파싱할 수 없습니다.") from None
    if root.tag == ATOM + "feed":
        items = [_atom_item(entry) for entry in root.findall(ATOM + "entry")]
        if re.fullmatch(r"https://github\.com/[^/]+/[^/]+/releases\.atom", source.feed_url):
            # GitHub 릴리스는 정식판만 (alpha·beta·rc·nightly·preview 제외). 시험판이 매일 올라와 메일을 채우지 않게 한다.
            items = [i for i in items if not PRERELEASE.search(i["title"] or "")]
        offset = None
    else:
        channels = root.findall("channel")
        if root.tag != "rss" or root.get("version") != "2.0" or len(channels) != 1:
            raise RssError("예상한 RSS 2.0 channel 또는 Atom feed 형식이 아닙니다.")
        items = [{"title": i.findtext("title"), "link": i.findtext("link"), "guid": i.findtext("guid"),
                  "date": i.findtext("pubDate"), "excerpt": i.findtext("description")} for i in channels[0].findall("item")]
        offset = source.local_offset
    data = []
    for index, item in enumerate(items):
        title = item["title"]
        link = item["link"]
        if not title or not title.strip() or not link or not link.strip():
            raise RssError(f"RSS 항목 {index + 1}: 필수 제목 또는 URL이 없습니다.")
        guid = item["guid"]
        guid = guid if guid and guid.strip() else None
        try:
            url = str(TypeAdapter(HttpUrl).validate_python(link.strip()))
        except ValidationError:
            raise RssError(f"RSS 항목 {index + 1}: HTTP(S) URL이 필요합니다.") from None
        identity = "guid:" + guid if guid else "url:" + url
        digest = hashlib.sha256((source.source_id + "\n" + identity).encode("utf-8")).hexdigest()
        excerpt = item["excerpt"]
        data.append({
            "schema_version": 1, "article_id": source.source_id + ":" + digest,
            "source_id": source.source_id, "source_name": source.source_name,
            "original_title": " ".join(html.unescape(title).split()),  # 이중 이스케이프 (&amp;#034;) 와 제목 앞뒤 줄바꿈 (Jenkins) 정리
            "url": url, "collection_method": "rss",
            "source_item_id": guid, "collected_at": now.isoformat(),
            "published_at": publication_time(item["date"], offset),
            "feed_excerpt": excerpt if excerpt and excerpt.strip() else None,
        })
    try:
        return validate_articles(data) if data else []
    except (ValidationError, ValueError):
        raise RssError("RSS 기사 Schema 또는 Feed 내부 ID 중복 검증에 실패했습니다.") from None


TOPIC_DAYS = 7  # 보안 외 주제 Source 는 게시가 드물어 7일 안 게시물을 저장하고, 처음 수집된 날에만 메일에 낸다 (F13)


def select_articles(articles: list[Article], now: datetime, *, bootstrap=False,
                    since: datetime | None = None, date_only=False, wide=False) -> tuple[list[Article], dict[str, int]]:
    if bootstrap and since is not None:
        raise RssError("bootstrap과 since는 함께 사용할 수 없습니다.")
    if since is not None:
        if since.tzinfo is None or since.utcoffset() is None or since > now:
            raise RssError("복구 시작 시각은 시간대가 있고 미래가 아닌 값이어야 합니다.")
        start = max(since - timedelta(hours=6), now - timedelta(days=7))
    else:
        # 날짜만 있는 Source는 0시로 해석하므로 기본 기간을 하루 늘려 전날 게시분 누락을 막는다 (D-025).
        hours = 48 if date_only else 24
        if now.astimezone(timezone(KST)).weekday() == 0:  # 월요일은 주말 게시분도 저장 (+48시간, 표시 기간과 같음, D-063)
            hours += 48
        if wide:
            hours = max(hours, TOPIC_DAYS * 24)
        start = now - timedelta(days=30) if bootstrap else now - timedelta(hours=hours)
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


def reconcile_articles(path: Path, articles: list[Article]) -> tuple[list[Article], int, list[Article]]:
    """(새로 저장할 기사, 같은 원문 건수, 원문이 바뀐 기존 기사의 갱신본).

    원문이 바뀐 기사는 처음 수집 시각 등 다른 값은 두고 원문 항목만 새 값으로 바꾼다 (D-074, 이전에는 저장 보류).
    """
    # ponytail: 전체 기사 읽기, DB 규모가 커지면 ID별 일괄 조회로 교체한다.
    existing = {article.article_id: article for article in list_articles(path)} if path.exists() else {}
    result, changed = [], []
    skipped = 0
    for article in articles:
        old = existing.get(article.article_id)
        if old is None:
            result.append(article)
            continue
        compared = old.model_copy(update={field: getattr(article, field) for field in SOURCE_FIELDS})
        if normalized_json(old) != normalized_json(compared):
            changed.append(compared)
        else:
            result.append(old)
            skipped += 1
    return result, skipped, changed
