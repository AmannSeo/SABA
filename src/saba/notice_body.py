"""승인된 보호나라·고용노동부 공지의 본문 앞부분만 발췌한다 (D-038·D-083)."""

import http.client
import json
import re
import urllib.error
import urllib.request
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from saba import crawl
from saba.rss import RssError
from saba.schema import Article

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = ROOT / "data" / "boho_bodies.json"
URL_PREFIX = "https://www.boho.or.kr/kr/bbs/view.do?"
SOURCE_PREFIX = "boho-"
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 15
EXCERPT_CHARS = 1200  # ponytail: 본문 앞부분 고정 길이, 요약 품질 확인 후 조정


def body_site(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or parts.netloc not in ("www.boho.or.kr", "www.moel.go.kr"):
        return None
    if parts.hostname == "www.boho.or.kr" and parts.path == "/kr/bbs/view.do":
        return "boho"
    if (parts.hostname == "www.moel.go.kr" and parts.path == "/news/enews/report/enewsView.do"
            and len(parse_qs(parts.query).get("news_seq", [])) == 1
            and parse_qs(parts.query)["news_seq"][0].isdigit()):
        return "moel"
    return None


def needs_body(article: Article) -> bool:
    site = body_site(str(article.url))
    return (not (article.feed_excerpt or "").strip()
            and ((site == "boho" and article.source_id.startswith(SOURCE_PREFIX))
                 or (site == "moel" and article.source_id == "moel-press")))


def fetch_page(url: str) -> bytes | None:
    """허용 URL만 robots·호스트 간격 검사 후 GET. Redirect·재시도·첨부 요청 없음."""
    if body_site(url) is None:
        return None
    try:
        if not crawl.allowed(url):
            return None
        status, kind, payload = crawl._get(url, redirects=False)
        return payload if status == 200 and kind == "text/html" and len(payload) <= MAX_BYTES else None
    except (RssError, urllib.error.URLError, OSError, http.client.HTTPException):
        return None


class MoelBody(HTMLParser):
    """보도자료 영역만 읽고 같은 이름의 중첩 div 종료를 추적한다."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.hidden, self.parts = 0, 0, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            if self.depth:
                self.depth += 1
            elif {"b_content", "news_content"} <= set(attrs.get("class", "").split()):
                self.depth = 1
        if self.depth:
            if tag in ("script", "style"):
                self.hidden += 1
            if tag in ("br", "p", "div", "li"):
                self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.depth:
            if tag in ("script", "style") and self.hidden:
                self.hidden -= 1
            if tag in ("p", "div", "li"):
                self.parts.append("\n")
            if tag == "div":
                self.depth -= 1

    def handle_data(self, data):
        if self.depth and not self.hidden:
            self.parts.append(data)


def body_excerpt(page: bytes, site: str = "boho") -> str | None:
    """content_html 블록의 줄을 문장으로 만들어 앞부분만 남긴다. HTML로 escape 해 기존 발췌 형식과 같게 둔다."""
    text = page.decode("utf-8", errors="replace")
    if site == "moel":
        parser = MoelBody()
        parser.feed(text)
        parser.close()
        lines = [" ".join(line.split()) for line in "".join(parser.parts).split("\n")]
    else:
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
        excerpt = f"{excerpt} {sentence}".strip()[:EXCERPT_CHARS]
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
            excerpt = body_excerpt(page, body_site(url)) if page else None
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
