"""국내 기관 공개 목록 페이지 수집 (D-078). 제목·링크·게시일·짧은 목록 정보만 읽는다 (본문·첨부 없음).

수집 규칙: robots.txt 준수, 같은 사이트 요청 간격 1초 이상, 실행당 목록 페이지 1개, 식별 가능한 User-Agent,
자동 재시도 없음, 응답 2MiB 상한, 리다이렉트는 같은 호스트 안에서만. 목록 형식이 바뀌어 0건이 되면 오류로 알린다.
"""

from datetime import datetime, timezone
import hashlib
import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

from saba.rss import KST, MAX_BYTES, TIMEOUT, RssError, Source
from saba.schema import Article, validate_articles

USER_AGENT = "SABA/0.1 company newsletter collector (public list pages only)"
MIN_INTERVAL = 1.0  # 같은 호스트 요청 간격 (초)
_last_request: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser] = {}


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            raise RssError("다른 사이트로의 리다이렉트는 따라가지 않습니다.")
        parts = urllib.parse.urlsplit(newurl)
        robots = _robots.get(f"{parts.scheme}://{parts.netloc}")
        if parts.scheme != "https" or (robots is not None and not robots.can_fetch(USER_AGENT, newurl)):
            raise RssError("리다이렉트 대상이 HTTPS 또는 robots.txt 규칙을 충족하지 않습니다.")
        host = urllib.parse.urlsplit(newurl).hostname or ""
        wait = MIN_INTERVAL - (time.monotonic() - _last_request.get(host, -MIN_INTERVAL))
        if wait > 0:
            time.sleep(wait)
        _last_request[host] = time.monotonic()
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url: str, *, sleep=time.sleep, clock=time.monotonic) -> tuple[int, str, bytes]:
    host = urllib.parse.urlsplit(url).hostname or ""
    wait = MIN_INTERVAL - (clock() - _last_request.get(host, -MIN_INTERVAL))
    if wait > 0:
        sleep(wait)
    _last_request[host] = clock()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    try:
        with urllib.request.build_opener(SameHostRedirect()).open(request, timeout=TIMEOUT) as response:
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise RssError("목록 페이지 응답이 2MiB 상한을 초과했습니다.")
            return response.status, response.headers.get_content_type(), body
    except urllib.error.HTTPError as exc:
        return exc.code, "", b""
    except (urllib.error.URLError, OSError) as exc:
        raise RssError(f"목록 페이지 요청 실패: {type(exc).__name__}. 자동 재시도는 하지 않습니다.") from None


def allowed(url: str, **options) -> bool:
    """robots.txt 를 사이트마다 한 번 읽는다. 없으면 (404) 허용, 받지 못하면 수집하지 않는다."""
    parts = urllib.parse.urlsplit(url)
    root = f"{parts.scheme}://{parts.netloc}"
    if root not in _robots:
        status, _, body = _get(root + "/robots.txt", **options)
        parser = urllib.robotparser.RobotFileParser()
        if status == 200:
            parser.parse(body.decode("utf-8", "replace").splitlines())
        elif status in (404, 410):
            parser.parse([])
        else:
            raise RssError(f"robots.txt 를 확인하지 못했습니다 (HTTP {status}). 수집하지 않습니다.")
        _robots[root] = parser
    return _robots[root].can_fetch(USER_AGENT, url)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _date(value: str) -> datetime:
    """YYYY-MM-DD·YYYY.MM.DD(.) 를 한국 날짜 0시로 (D-025 날짜만 Source 와 같은 해석)."""
    year, month, day = map(int, re.fullmatch(r"(\d{4})[-.](\d{2})[-.](\d{2})\.?", value.strip()).groups())
    return datetime(year, month, day, tzinfo=timezone(KST)).astimezone(timezone.utc)


def _cells(row: str) -> list[str]:
    return re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)


def parse_bizinfo(page: str, base: str) -> list[dict]:
    """기업마당 지원사업 공고: 지원분야·사업명·신청기간·소관부처·수행기관·등록일."""
    items = []
    for row in re.findall(r"<tr>(.*?)</tr>", page.split("<tbody", 1)[-1], re.S):
        cells = _cells(row)
        link = re.search(r'pblancId=(PBLN_\d+)', row)
        if len(cells) < 7 or not link:
            continue
        period, ministry, agency = _text(cells[3]), _text(cells[4]), _text(cells[5])
        items.append({"guid": link.group(1), "title": _text(cells[2]), "date": _text(cells[6]),
                      "url": f"https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId={link.group(1)}",
                      "excerpt": f"지원분야 {_text(cells[1])}. 신청기간 {period}. 소관 {ministry}. 수행기관 {agency}."})
    return items


def parse_moel(page: str, base: str) -> list[dict]:
    """고용노동부 보도자료."""
    items = []
    for row in re.findall(r"<tr>(.*?)</tr>", page.split("<tbody", 1)[-1], re.S):
        link = re.search(r'href="(enewsView\.do\?news_seq=(\d+))"[^>]*>(.*?)</a>', row, re.S)
        date = re.search(r'aria-label="등록일">\s*([\d.]+)\s*<', row)
        if link and date:
            items.append({"guid": link.group(2), "title": _text(link.group(3)), "date": date.group(1),
                          "url": urllib.parse.urljoin(base, link.group(1)), "excerpt": None})
    return items


def parse_nts(page: str, base: str) -> list[dict]:
    """국세청 보도자료 (상세는 nttSn 으로 연다)."""
    items = []
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(base).query))
    for row in re.findall(r"<tr>(.*?)</tr>", page.split("<tbody", 1)[-1], re.S):
        link = re.search(r'data-id="(\d+)"[^>]*class="nttInfoBtn"[^>]*>(.*?)</a>', row, re.S)
        date = re.search(r'data-table="date">\s*([\d.]+)\s*<', row)
        dept = re.findall(r'data-table="write">(.*?)</td>', row, re.S)
        if link and date:
            items.append({"guid": link.group(1), "title": _text(link.group(2)), "date": date.group(1),
                          "url": "https://www.nts.go.kr/nts/na/ntt/selectNttInfo.do?" + urllib.parse.urlencode(
                              {"mi": query.get("mi", ""), "bbsId": query.get("bbsId", ""), "nttSn": link.group(1)}),
                          "excerpt": f"담당 {_text(re.sub(r'<!--.*?-->', '', dept[0], flags=re.S))}." if dept else None})
    return items


def parse_iris(page: str, base: str) -> list[dict]:
    """IRIS 범부처 R&D 사업공고: 부처·전문기관·공고번호·공고일자·공고상태·공모유형."""
    items = []
    for block in re.findall(r"<li>\s*<span class=\"inst_title\">(.*?)</li>", page, re.S):
        link = re.search(r"f_bsnsAncmBtinSituListForm_view\('(\d+)','(\w+)'\)[^>]*>(.*?)</a>", block, re.S)
        date = re.search(r"공고일자 :</em>\s*([\d-]+)", block)
        if not link or not date:
            continue
        info = {k: _text(v) for k, v in re.findall(r"<em>(공고번호|공고상태|공모유형) :</em>(.*?)</span>", block, re.S)}
        institute = _text(block.split("</span>", 1)[0])
        items.append({"guid": link.group(1), "title": _text(link.group(3)), "date": date.group(1),
                      "url": "https://www.iris.go.kr/contents/retrieveBsnsAncmView.do?" + urllib.parse.urlencode(
                          {"ancmId": link.group(1), "ancmPrg": link.group(2)}),
                      "excerpt": f"{institute}. " + " ".join(f"{k} {v}." for k, v in info.items())})
    return items


def parse_nipa(page: str, base: str) -> list[dict]:
    """NIPA 사업공고: 마지막 날짜 칸의 등록일, 신청기간은 게시일로 쓰지 않는다."""
    items = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        cells = _cells(row)
        link = re.search(r'href="(/home/2-2/(\d+))"[^>]*>(.*?)</a>', row, re.S)
        date = _text(cells[-1]) if cells else ""
        if link and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            items.append({"guid": link.group(2), "title": _text(re.sub(r'<!--.*?-->', '', link.group(3), flags=re.S)),
                          "date": date, "url": urllib.parse.urljoin(base, link.group(1)), "excerpt": None})
    return items


def parse_smtech(page: str, base: str) -> list[dict]:
    """SMTECH R&D 관련 공지: 등록일·수정일 중 첫 날짜 칸을 사용, 세션 URL은 저장하지 않는다."""
    items = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        link = re.search(r'href="([^"]*notice01_detail\.do[^"]*)"[^>]*>(.*?)</a>', row, re.S)
        dates = [_text(c) for c in _cells(row) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", _text(c))]
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(html.unescape(link.group(1))).query)) if link else {}
        guid = query.get("bitmSeq", "")
        if link and guid.isdigit() and dates:
            items.append({"guid": guid, "title": _text(link.group(2)), "date": dates[0],
                          "url": urllib.parse.urljoin(base, "notice01_detail.do") + "?bitmSeq=" + guid, "excerpt": None})
    return items


def parse_kocca(page: str, base: str) -> list[dict]:
    """KOCCA 공지사항: 등록일 칸만 사용한다. 지원공고의 동적 목록과 구분한다."""
    items = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        link = re.search(r'href="(/kocca/bbs/view/B0000137/(\d+)\.do)[^"]*"[^>]*>(.*?)</a>', row, re.S)
        date = re.search(r'<td[^>]*data-label="등록일"[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</td>', row)
        if link and date:
            items.append({"guid": link.group(2), "title": _text(link.group(3)), "date": date.group(1),
                          "url": urllib.parse.urljoin(base, link.group(1)) + "?menuNo=204802", "excerpt": None})
    return items


def parse_searchadvisor(page: str, base: str) -> list[dict]:
    """공개 홈페이지에 게시된 웹마스터 공지 링크·날짜만 읽는다. 일반 검색 블로그는 제외."""
    items = []
    for link in re.finditer(r'href="(https://blog\.naver\.com/naver_webmaster/(\d+))"[^>]*>(.*?)</a>', page, re.S):
        text = _text(link.group(3))
        date = re.search(r'(\d{2})\.(\d{2})\.(\d{2})\s*$', text)
        if date:
            items.append({"guid": link.group(2), "title": text[:date.start()].removeprefix("웹마스터").strip(),
                          "date": "20" + '-'.join(date.groups()), "url": link.group(1), "excerpt": None})
    return items


PARSERS = {"crawl:bizinfo": parse_bizinfo, "crawl:moel": parse_moel, "crawl:nts": parse_nts, "crawl:iris": parse_iris,
           "crawl:nipa": parse_nipa, "crawl:smtech": parse_smtech, "crawl:kocca": parse_kocca,
           "crawl:searchadvisor": parse_searchadvisor}


def articles_from_items(items: list[dict], now: datetime, source: Source) -> list[Article]:
    data = []
    for item in items:
        identity = "guid:" + item["guid"]
        digest = hashlib.sha256((source.source_id + "\n" + identity).encode("utf-8")).hexdigest()
        data.append({"schema_version": 1, "article_id": source.source_id + ":" + digest, "source_id": source.source_id,
                     "source_name": source.source_name, "original_title": item["title"], "url": item["url"],
                     "collection_method": "crawl", "source_item_id": item["guid"], "collected_at": now.isoformat(),
                     "published_at": _date(item["date"]), "feed_excerpt": item["excerpt"]})
    try:
        return validate_articles(data) if data else []
    except ValueError:
        raise RssError("목록 항목 Schema 검증에 실패했습니다.") from None


def collect(source: Source, now: datetime, **options) -> list[Article]:
    parser = PARSERS.get(source.method)
    if parser is None:
        raise RssError(f"알 수 없는 수집 방식입니다 ({source.method}).")
    if not allowed(source.feed_url, **options):
        raise RssError("robots.txt 가 이 목록 페이지 수집을 허용하지 않습니다.")
    status, content_type, body = _get(source.feed_url, **options)
    if status != 200 or content_type != "text/html":
        raise RssError(f"목록 페이지 응답이 예상과 다릅니다 (HTTP {status}, {content_type or '형식 없음'}).")
    items = parser(body.decode("utf-8", "replace"), source.feed_url)
    if not items:
        raise RssError("목록에서 항목을 찾지 못했습니다. 사이트 화면 구조가 바뀌었을 수 있습니다.")
    try:
        return articles_from_items(items, now, source)
    except (AttributeError, ValueError):  # 날짜 형식이나 달력 날짜가 달라진 경우
        raise RssError("목록 항목의 날짜 형식이 예상과 다릅니다.") from None
