"""공공데이터 API 수집 (D-078): 나라장터 입찰공고 (용역), K-Startup 사업공고.

- 인증키: 환경 변수 SABA_DATA_GO_KR_KEY (없으면 Windows 사용자 환경 변수에서 읽는다). 키는 화면·로그·오류에 남기지 않는다.
- 양이 많아 (나라장터 하루 약 700건, K-Startup 주 약 270건) 제목 키워드로 거른다. 키워드는 config/public_api.json (관리 화면 설정에서 수정).
- 실행당 페이지 수 상한, 자동 재시도 없음, 응답 크기 상한. 키워드에 맞는 공고가 0건이어도 정상이다.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from saba.rss import KST, TIMEOUT, NoRedirect, RssError, Source, check_api_url
from saba.schema import Article, validate_articles

KEY_NAME = "SABA_DATA_GO_KR_KEY"
LAW_KEY_NAME = "SABA_LAW_OC"  # 국가법령정보 공동활용 OC
KEYWORDS_PATH = Path(__file__).resolve().parents[2] / "config" / "public_api.json"
DEFAULT_KEYWORDS = {
    "g2b": ["정보보호", "정보보안", "사이버보안", "보안관제", "보안 관제", "모의해킹", "취약점", "개인정보 영향평가",
            "개인정보보호", "ISMS", "보안컨설팅", "보안 컨설팅", "소프트웨어 시험", "소프트웨어 테스트", "SW 테스트",
            "테스트 자동화", "인공지능", "AI", "데이터 플랫폼"],
    "kstartup": ["AI", "인공지능", "데이터", "보안", "정보보호", "소프트웨어", "SW", "디지털 전환", "DX", "기술사업화",
                 "R&D", "실증", "PoC", "바우처"],
    # 법령명·소관부처에 하나라도 있으면 (경영전략팀 · 사업지원팀: 노동·세무·4대보험·개인정보)
    "law": ["고용노동부", "근로", "노동", "임금", "퇴직", "산업안전", "산업재해", "고용보험", "소득세", "법인세", "부가가치세",
            "조세", "국세", "세법", "국민연금", "건강보험", "개인정보"],
}
MAX_BYTES = 8 * 1024 * 1024
PAGES = 4  # 실행당 최대 페이지 (나라장터 300건 x 4, K-Startup 100건 x 4)


def load_keywords(path: Path = KEYWORDS_PATH) -> dict[str, list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {k: list(v) for k, v in DEFAULT_KEYWORDS.items()}
    except json.JSONDecodeError:
        raise RssError("공공 API 키워드 설정이 JSON 형식이 아닙니다 (config/public_api.json).") from None
    if not isinstance(data, dict):
        raise RssError("공공 API 키워드 설정 형식이 올바르지 않습니다 (config/public_api.json).")
    data = {k: data.get(k, DEFAULT_KEYWORDS[k]) for k in DEFAULT_KEYWORDS}  # 나중에 생긴 항목은 기본값으로
    if not all(isinstance(data[k], list) and all(isinstance(w, str) and w.strip() for w in data[k]) for k in DEFAULT_KEYWORDS):
        raise RssError("공공 API 키워드 설정 형식이 올바르지 않습니다 (config/public_api.json).")
    return {k: [w.strip() for w in data[k]] for k in DEFAULT_KEYWORDS}


def save_keywords(keywords: dict[str, list[str]], path: Path = KEYWORDS_PATH) -> None:
    for k in DEFAULT_KEYWORDS:
        words = keywords.get(k, [])
        if not words or len(words) > 60 or any(not w or len(w) > 30 for w in words):
            raise RssError("키워드는 1~60개, 각 1~30자여야 합니다.")
    path.write_text(json.dumps({k: keywords[k] for k in DEFAULT_KEYWORDS}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def service_key(name: str = KEY_NAME) -> str | None:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    try:  # 키를 넣기 전에 켜진 프로그램 (관리 페이지 등) 도 새 값을 읽게 한다
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return str(winreg.QueryValueEx(key, name)[0]).strip() or None
    except (ImportError, OSError):
        return None


def _get_json(base: str, params: dict, key: str) -> dict:
    check_api_url(base)
    key_param = "OC" if urllib.parse.urlsplit(base).hostname == "www.law.go.kr" else "serviceKey"  # 법령 API 는 OC
    url = base + "?" + urllib.parse.urlencode({key_param: key, **params})
    request = urllib.request.Request(url, headers={"User-Agent": "SABA/0.1 company newsletter collector"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=TIMEOUT * 2) as response:
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise RssError(f"공공 API HTTP 오류: {exc.code}. 자동 재시도는 하지 않습니다.") from None
    except (urllib.error.URLError, OSError):
        raise RssError("공공 API 요청 실패 (연결·시간 초과). 자동 재시도는 하지 않습니다.") from None
    if len(body) > MAX_BYTES:
        raise RssError("공공 API 응답이 크기 상한을 넘었습니다.")
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        raise RssError("공공 API 응답이 JSON 이 아닙니다 (인증키 승인 전이거나 서비스 오류일 수 있습니다).") from None


def _matches(text: str, words: list[str]) -> bool:
    return any(w.lower() in text.lower() for w in words)


def _kst(value: str, layout: str) -> datetime:
    return datetime.strptime(value, layout).replace(tzinfo=timezone(KST)).astimezone(timezone.utc)


def parse_g2b(items: list[dict], words: list[str]) -> list[dict]:
    out = []
    for item in items:
        title = html.unescape(str(item.get("bidNtceNm", ""))).strip()
        if not title or not _matches(title, words):
            continue
        price = item.get("presmptPrce") or item.get("asignBdgtAmt")
        details = [f"공고기관 {item.get('ntceInsttNm', '')}", f"수요기관 {item.get('dminsttNm', '')}",
                   f"입찰 마감 {item.get('bidClseDt', '')}", f"계약 방법 {item.get('cntrctCnclsMthdNm', '')}"]
        if price:
            details.append(f"추정가격 {int(float(price)):,}원")
        out.append({"guid": f"{item['bidNtceNo']}-{item.get('bidNtceOrd', '000')}", "title": title,
                    "url": item.get("bidNtceDtlUrl") or item.get("bidNtceUrl"),
                    "published": _kst(str(item["bidNtceDt"])[:19], "%Y-%m-%d %H:%M:%S"),
                    "excerpt": ". ".join(details) + "."})
    return out


def parse_kstartup(items: list[dict], words: list[str], now: datetime | None = None) -> list[dict]:
    """게시일 필드가 없어 접수 시작일을 쓴다. 시작일이 미래인 예고 공고는 수집 시각으로 둔다 (미래 날짜면 표시 기간에서 빠져
    시작일이 와도 '처음 수집' 이 아니어서 끝내 안 나온다)."""
    now = now or datetime.now(timezone.utc)
    out = []
    for item in items:
        title = html.unescape(str(item.get("biz_pbanc_nm") or item.get("intg_pbanc_biz_nm") or "")).strip()
        if not title or not _matches(title + " " + html.unescape(str(item.get("intg_pbanc_biz_nm") or "")), words):
            continue
        start, end = str(item.get("pbanc_rcpt_bgng_dt", "")), str(item.get("pbanc_rcpt_end_dt", ""))
        out.append({"guid": str(item["pbanc_sn"]), "title": title, "url": item.get("detl_pg_url"),
                    "published": min(_kst(start[:8], "%Y%m%d"), now),
                    "excerpt": f"접수 {start[:4]}-{start[4:6]}-{start[6:8]} ~ {end[:4]}-{end[4:6]}-{end[6:8]}. "
                               f"대상 {item.get('aply_trgt') or '-'}. 주관 {html.unescape(str(item.get('pbanc_ntrp_nm') or '-'))}."})
    return out


def parse_law(laws: list[dict], words: list[str], since: datetime) -> list[dict]:
    """최근 공포 법령. 응답의 상세 링크에는 OC 가 들어 있어 쓰지 않고, OC 없는 공개 법령 화면 주소를 만든다."""
    out = []
    for law in laws:
        name, ministry = str(law.get("법령명한글", "")).strip(), str(law.get("소관부처명", ""))
        published = _kst(str(law.get("공포일자", "")), "%Y%m%d")
        if not name or published < since or not _matches(name + " " + ministry, words):
            continue
        effective = str(law.get("시행일자", ""))
        out.append({"guid": str(law["법령일련번호"]), "title": f"[{law.get('제개정구분명', '개정')}] {name}",
                    "url": "https://www.law.go.kr/LSW/lsInfoP.do?" + urllib.parse.urlencode({"lsiSeq": law["법령일련번호"]}),
                    "published": published,
                    "excerpt": f"{law.get('제개정구분명', '')}. 공포 {published.astimezone(timezone(KST)):%Y-%m-%d}, "
                               f"시행 {effective[:4]}-{effective[4:6]}-{effective[6:8]}. 소관 {ministry}. 법령 구분 {law.get('법령구분명', '')}."})
    return out


def _articles(items: list[dict], now: datetime, source: Source) -> list[Article]:
    data = []
    for item in items:
        if not item["url"]:
            continue
        digest = hashlib.sha256((source.source_id + "\nguid:" + item["guid"]).encode("utf-8")).hexdigest()
        data.append({"schema_version": 1, "article_id": source.source_id + ":" + digest, "source_id": source.source_id,
                     "source_name": source.source_name, "original_title": item["title"], "url": item["url"],
                     "collection_method": "api", "source_item_id": item["guid"], "collected_at": now.isoformat(),
                     "published_at": item["published"], "feed_excerpt": item["excerpt"]})
    try:
        return validate_articles(data) if data else []
    except ValueError:
        raise RssError("공공 API 항목 Schema 검증에 실패했습니다.") from None


def collect(source: Source, now: datetime, *, fetch=_get_json, keywords: dict | None = None) -> list[Article]:
    name = LAW_KEY_NAME if source.method == "api:law" else KEY_NAME
    key = service_key(name)
    if not key:
        raise RssError(f"인증키가 없습니다 ({name}). 관리 화면 설정 또는 Windows 환경 변수에 넣어 주세요.")
    words = (keywords or load_keywords())[source.method.removeprefix("api:")]
    local = now.astimezone(timezone(KST))
    items: list[dict] = []
    try:
        if source.method == "api:g2b":
            begin = (local - timedelta(days=1)).strftime("%Y%m%d%H%M")
            for page in range(1, PAGES + 1):
                body = fetch(source.feed_url, {"numOfRows": "300", "pageNo": str(page), "inqryDiv": "1", "type": "json",
                                               "inqryBgnDt": begin, "inqryEndDt": local.strftime("%Y%m%d%H%M")}, key)
                part = body["response"]["body"]
                if body["response"]["header"].get("resultCode") != "00":
                    raise RssError("나라장터 API 가 오류 코드를 돌려줬습니다.")
                items += parse_g2b(part.get("items") or [], words)
                if page * 300 >= int(part.get("totalCount") or 0):
                    break
        elif source.method == "api:kstartup":
            begin = (local - timedelta(days=7)).strftime("%Y%m%d")
            for page in range(1, PAGES + 1):
                body = fetch(source.feed_url, {"page": str(page), "perPage": "100", "returnType": "json",
                                               "cond[pbanc_rcpt_bgng_dt::GTE]": begin}, key)
                items += parse_kstartup(body.get("data") or [], words, now)
                if page * 100 >= int(body.get("matchCount") or 0):
                    break
        elif source.method == "api:law":  # 공포일 내림차순 최근 100건 중 7일 안 (주제 Source 기간과 같다)
            body = fetch(source.feed_url, {"target": "law", "type": "JSON", "display": "100", "sort": "ddes"}, key)
            root = body["LawSearch"]
            laws = root.get("law") or []
            items += parse_law(laws if isinstance(laws, list) else [laws], words, now - timedelta(days=7))
        else:
            raise RssError(f"알 수 없는 수집 방식입니다 ({source.method}).")
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        if isinstance(exc, RssError):
            raise
        raise RssError("공공 API 응답 형식이 예상과 다릅니다.") from None
    return _articles(items, now, source)
