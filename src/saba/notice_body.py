"""발췌가 없는 보호나라 공지의 본문 앞부분을 가져와 발췌로 쓴다 (D-038). 기사 DB는 쓰지 않는다."""

import http.client
import json
import re
import urllib.error
import urllib.request
from html import escape, unescape
from pathlib import Path

from saba.rss import NoRedirect
from saba.schema import Article

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = ROOT / "data" / "boho_bodies.json"
URL_PREFIX = "https://www.boho.or.kr/kr/bbs/view.do?"
SOURCE_PREFIX = "boho-"
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 15
EXCERPT_CHARS = 1200  # ponytail: 본문 앞부분 고정 길이, 요약 품질 확인 후 조정


def needs_body(article: Article) -> bool:
    return (article.source_id.startswith(SOURCE_PREFIX) and not (article.feed_excerpt or "").strip()
            and str(article.url).startswith(URL_PREFIX))


def fetch_page(url: str) -> bytes | None:
    """공지 페이지 GET 1회. Redirect·재시도 없음. 실패하면 None (제목만 표시로 남는다)."""
    request = urllib.request.Request(url, headers={"User-Agent": "SABA/0.1 notice body collector",
                                                   "Accept": "text/html", "Accept-Encoding": "identity"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=TIMEOUT) as response:
            if response.status != 200 or response.headers.get_content_type() != "text/html":
                return None
            payload = response.read(MAX_BYTES + 1)
            return None if len(payload) > MAX_BYTES else payload
    except (urllib.error.URLError, OSError, http.client.HTTPException):
        return None


def body_excerpt(page: bytes) -> str | None:
    """content_html 블록의 줄을 문장으로 만들어 앞부분만 남긴다. HTML로 escape 해 기존 발췌 형식과 같게 둔다."""
    text = page.decode("utf-8", errors="replace")
    match = re.search(r'<div class="content_html">(.*?)<div class="content">', text, re.S)
    if match is None:
        return None
    block = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", match.group(1), flags=re.S | re.I)
    block = re.sub(r"<br\s*/?>|</(p|li|tr|div|h\d)>", "\n", block, flags=re.I)
    lines = [" ".join(unescape(re.sub(r"<[^>]+>", " ", line)).split()) for line in block.split("\n")]
    excerpt = ""
    for line in filter(None, lines):
        # 문장부호 없는 줄("o 업데이트 권고")은 문장 단위 근거 번호를 위해 마침표를 붙인다.
        sentence = line if line[-1] in ".!?" else line + "."
        if excerpt and len(excerpt) + len(sentence) > EXCERPT_CHARS:
            break
        excerpt = f"{excerpt} {sentence}".strip()
    return escape(excerpt) if excerpt else None


def notice_excerpts(articles: list[Article], *, cache_path: Path = DEFAULT_CACHE, fetch: bool = True,
                    fetcher=fetch_page) -> dict[str, str]:
    """article_id → 본문 발췌. 같은 URL은 캐시를 재사용하고, fetch=False면 캐시만 쓴다."""
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        cache = {}
    excerpts, changed = {}, False
    for article in filter(needs_body, articles):
        url = str(article.url)
        if url not in cache and fetch:
            page = fetcher(url)
            excerpt = body_excerpt(page) if page else None
            if excerpt:
                cache[url], changed = excerpt, True
        if url in cache:
            excerpts[article.article_id] = cache[url]
    if changed:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return excerpts


def with_excerpt(article: Article, excerpts: dict[str, str]) -> Article:
    excerpt = excerpts.get(article.article_id)
    return article.model_copy(update={"feed_excerpt": excerpt}) if excerpt else article
