"""Newsletter HTML rendering for SABA."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from html import escape
from html.parser import HTMLParser
from typing import Optional

from saba.analysis import AnalysisResult
from saba.schema import Article

_ANALYSIS_READY_STATUS = "검토 필요"
_AI_TECH_CATEGORIES = {"AI·기술", "AI 보안"}
_WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
_DEEP_SECTION_META = {
    "domestic": ("국내 보안", "🇰🇷"),
    "overseas": ("해외 보안", "🌎"),
    "ai_tech": ("AI·기술", "🤖"),
    "other": ("기타", "🗂️"),
}
_BRIEF_GROUP_META = {
    "security": ("보안 뉴스", "🛡️", "security"),
    "ai_tech": ("AI·기술", "⚙️", "tech"),
    "other": ("기타", "🗂️", "company"),
}
_DEPARTMENT_CARDS = (
    ("경영전략팀", "📊", "strategy"),
    ("기술개발연구소", "💻", "development"),
    ("보안사업팀", "🛡️", "security-team"),
    ("STE본", "⚙️", "ste"),
)
_SECTION_PREFIX = {
    "domestic": "domestic",
    "overseas": "overseas",
    "ai_tech": "ai",
    "other": "other",
}
_IMPORTANCE_BADGE_CLASS = {
    "높음": "urgent",
    "보통": "important",
    "낮음": "reference",
}


class _ExcerptHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in {"script", "style"}:
            self.hidden_stack.append(tag)
        self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self.hidden_stack and tag == self.hidden_stack[-1]:
            self.hidden_stack.pop()
        self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden_stack:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self.hidden_stack:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.hidden_stack:
            self.parts.append(f"&#{name};")


@dataclass(slots=True)
class ArticleView:
    article_id: str
    title: str
    source_name: str
    url: str
    date_display: str
    date_label: str
    excerpt: Optional[str]
    category: Optional[str]
    tags: list[str] = field(default_factory=list)
    importance: Optional[str] = None
    summary: Optional[str] = None
    key_points: list[str] = field(default_factory=list)
    has_full_analysis: bool = False
    region: Optional[str] = None


def _analysis_is_ready(analysis: Optional[AnalysisResult]) -> bool:
    return analysis is not None and analysis.status == _ANALYSIS_READY_STATUS


def _format_article_date(value: datetime) -> str:
    return f"{value.year:04d}.{value.month:02d}.{value.day:02d}"


def _format_today_display(today_value: Optional[str]) -> str:
    if today_value:
        return today_value
    current = date.today()
    weekday = _WEEKDAYS[current.weekday()]
    return f"{current.year}년 {current.month}월 {current.day}일 {weekday}"


def _clean_excerpt(feed_excerpt: Optional[str]) -> Optional[str]:
    if feed_excerpt is None:
        return None
    parser = _ExcerptHTMLParser()
    parser.feed(feed_excerpt)
    parser.close()
    text = " ".join("".join(parser.parts).split())
    return text or None


def _safe_escape(value: object) -> str:
    return escape(str(value), quote=True)


def build_article_view(article: Article, analysis: Optional[AnalysisResult] = None) -> ArticleView:
    has_full_analysis = _analysis_is_ready(analysis)
    date_value = article.published_at or article.collected_at
    date_label = "발행일" if article.published_at is not None else "수집일"
    title = article.original_title
    if has_full_analysis and analysis is not None and analysis.newsletter_title is not None:
        title = analysis.newsletter_title
    category = article.category
    tags = list(article.tags)
    importance = None
    summary = None
    key_points: list[str] = []
    if has_full_analysis and analysis is not None:
        category = analysis.category if analysis.category is not None else article.category
        tags = list(analysis.tags)
        importance = analysis.importance
        summary = analysis.summary
        key_points = list(analysis.key_points)
    return ArticleView(
        article_id=article.article_id,
        title=title,
        source_name=article.source_name,
        url=str(article.url),
        date_display=_format_article_date(date_value),
        date_label=date_label,
        excerpt=_clean_excerpt(article.feed_excerpt),
        category=category,
        tags=tags,
        importance=importance,
        summary=summary,
        key_points=key_points,
        has_full_analysis=has_full_analysis,
        region=article.region,
    )


def article_section(view: ArticleView) -> str:
    if view.category in _AI_TECH_CATEGORIES:
        return "ai_tech"
    if view.region == "국내":
        return "domestic"
    if view.region in {"해외", "국제"}:
        return "overseas"
    return "other"


def _build_anchor_map(views: list[ArticleView]) -> dict[str, str]:
    counters = {key: 0 for key in _SECTION_PREFIX}
    anchors: dict[str, str] = {}
    for view in views:
        section = article_section(view)
        counters[section] += 1
        anchors[view.article_id] = f"news-{_SECTION_PREFIX[section]}-{counters[section]}"
    return anchors


def _render_brief_summary(groups: dict[str, list[ArticleView]]) -> str:
    items: list[str] = []
    for group_key in ("security", "ai_tech", "other"):
        label, icon, _heading_class = _BRIEF_GROUP_META[group_key]
        views = groups[group_key]
        if views:
            titles = []
            for view in views[:3]:
                suffix = "" if view.has_full_analysis else " (분석 대기 중)"
                titles.append(f"{view.title}{suffix}")
            message = f"<strong>{len(views)}건</strong> " + ", ".join(_safe_escape(title) for title in titles)
        else:
            message = "<strong>0건</strong> 수집된 기사가 없습니다"
        items.append(
            f"""
<div class="brief-compact-group">
<span class="brief-compact-label">{icon} {label}</span>
<p>{message}</p>
</div>""".strip()
        )
    return "\n".join(items)


def _render_brief_detail(groups: dict[str, list[ArticleView]], anchors: dict[str, str]) -> str:
    blocks: list[str] = []
    for group_key in ("security", "ai_tech", "other"):
        label, icon, heading_class = _BRIEF_GROUP_META[group_key]
        views = groups[group_key]
        if views:
            items = []
            for view in views:
                anchor = anchors.get(view.article_id, "")
                title = _safe_escape(view.title)
                source = _safe_escape(view.source_name)
                date_display = _safe_escape(view.date_display)
                pending = " <em>(분석 대기 중)</em>" if not view.has_full_analysis else ""
                items.append(
                    f'<li><a href="#{_safe_escape(anchor)}">{title}</a> · {source} · {date_display}{pending}</li>'
                )
            list_html = "\n".join(items)
        else:
            list_html = "<li>수집된 기사가 없습니다</li>"
        blocks.append(
            f"""
<div class="brief-group">
<div class="brief-heading {heading_class}">
<span>{icon}</span>
<h3>{label}</h3>
</div>
<ul>
{list_html}
</ul>
</div>""".strip()
        )
    return "\n".join(blocks)


def _render_department_cards() -> str:
    cards: list[str] = []
    for name, icon, css_class in _DEPARTMENT_CARDS:
        cards.append(
            f"""
<article class="department-card {css_class}">
<div class="department-header">
<div class="department-title">
<span class="department-icon">{icon}</span>
<div>
<h3>{name}</h3>
</div>
</div>
<span class="department-count">관련 이슈 0건</span>
</div>
<div class="department-content">
<div class="department-news-item">
<p class="card-summary">이번 브리핑에서 분류된 기사가 없습니다.</p>
</div>
</div>
</article>""".strip()
        )
    return "\n".join(cards)


def _render_badges(view: ArticleView) -> str:
    badges: list[str] = []
    if view.has_full_analysis and view.importance is not None:
        badge_class = _IMPORTANCE_BADGE_CLASS.get(view.importance, "neutral")
        badges.append(f'<span class="badge {badge_class}">{_safe_escape(view.importance)}</span>')
    if view.category:
        badges.append(f'<span class="badge ai-badge">{_safe_escape(view.category)}</span>')
    for tag in view.tags:
        badges.append(f'<span class="badge neutral">{_safe_escape(tag)}</span>')
    if not badges:
        badges.append('<span class="badge neutral">일반 기사</span>')
    return "".join(badges)


def _render_article_body(view: ArticleView) -> str:
    blocks: list[str] = []
    if view.excerpt is not None:
        blocks.append(f'<p class="news-lead">{_safe_escape(view.excerpt)}</p>')
    if view.has_full_analysis and view.summary is not None:
        blocks.append(
            f"""
<div class="article-content">
<p>{_safe_escape(view.summary)}</p>
</div>""".strip()
        )
    return "\n".join(blocks)


def _render_key_points(view: ArticleView) -> str:
    if not (view.has_full_analysis and view.key_points):
        return ""
    items = "\n".join(f"<li>{_safe_escape(point)}</li>" for point in view.key_points)
    return f"""
<div class="insight-box">
<h4><span>💡</span> 시사점</h4>
<div class="content-block">
<ul>
{items}
</ul>
</div>
</div>""".strip()


def _render_deep_news(groups: dict[str, list[ArticleView]], anchors: dict[str, str]) -> str:
    sections: list[str] = []
    for group_key in ("domestic", "overseas", "ai_tech", "other"):
        views = groups[group_key]
        if not views:
            continue
        title, icon = _DEEP_SECTION_META[group_key]
        cards = []
        for view in views:
            anchor = anchors.get(view.article_id, "")
            body = _render_article_body(view)
            key_points = _render_key_points(view)
            cards.append(
                f"""
<article class="news-card" id="{_safe_escape(anchor)}">
<div class="news-top">
<div class="news-badges">
{_render_badges(view)}
</div>
<span class="article-datetime">{_safe_escape(view.date_label)} · {_safe_escape(view.date_display)}</span>
</div>
<h3 class="news-title"><a href="{_safe_escape(view.url)}" target="_blank" rel="noopener noreferrer">{_safe_escape(view.title)}</a></h3>
<div class="news-meta">
<span>{_safe_escape(view.source_name)}</span>
<span><a href="{_safe_escape(view.url)}" target="_blank" rel="noopener noreferrer">{_safe_escape(view.url)}</a></span>
</div>
{body}
{key_points}
</article>""".strip()
            )
        sections.append(
            f"""
<div class="news-category-heading">
<div>
<span class="category-icon">{icon}</span>
<h3>{title}</h3>
</div>
<span class="category-count">{len(views)}건</span>
</div>
{chr(10).join(cards)}""".strip()
        )
    if not sections:
        return '<p class="news-lead">수집된 기사가 없습니다.</p>'
    return "\n".join(sections)


def build_newsletter_html(
    views: list[ArticleView],
    css_path: str = "../SAMPLE/Codex/v09/style_review_v9.css",
    logo_path: str = "../SAMPLE/Codex/v09/LOGO.png",
    today: Optional[str] = None,
) -> str:
    safe_views = list(views or [])
    anchors = _build_anchor_map(safe_views)
    brief_groups = {"security": [], "ai_tech": [], "other": []}
    deep_groups = {"domestic": [], "overseas": [], "ai_tech": [], "other": []}
    for view in safe_views:
        deep_section = article_section(view)
        deep_groups[deep_section].append(view)
        brief_key = "security"
        if deep_section == "ai_tech":
            brief_key = "ai_tech"
        elif deep_section == "other":
            brief_key = "other"
        brief_groups[brief_key].append(view)

    if safe_views:
        brief_summary = _render_brief_summary(brief_groups)
        brief_detail = _render_brief_detail(brief_groups, anchors)
    else:
        brief_summary = """
<div class="brief-compact-group">
<span class="brief-compact-label">📰 안내</span>
<p>수집된 기사가 없습니다</p>
</div>""".strip()
        brief_detail = """
<div class="brief-group">
<div class="brief-heading security">
<span>📰</span>
<h3>안내</h3>
</div>
<ul>
<li>수집된 기사가 없습니다</li>
</ul>
</div>""".strip()

    deep_news = _render_deep_news(deep_groups, anchors)
    today_display = _safe_escape(_format_today_display(today))
    css_href = _safe_escape(css_path)
    logo_src = _safe_escape(logo_path)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>SABA Newsletter</title>
<link href="{css_href}" rel="stylesheet"/>
</head>
<body>
<main class="newsletter">
<header class="header">
<div class="header-top">
<div>
<p class="eyebrow">DAILY SECURITY · AI · TECHNOLOGY</p>
<h1>Security &amp; AI Briefing</h1>
</div>
<img class="header-logo" src="{logo_src}" alt="TBELL SECURITY"/>
</div>
<div class="meta">
<span>{today_display}</span>
<span>작성자 : SABA Newsletter</span>
</div>
</header>

<section class="greeting">
<p>안녕하세요. 오늘의 주요 보안·AI 이슈를 정리해드립니다.</p>
<p>업무 참고용 브리핑으로 활용하시고, 자세한 내용은 원문 링크를 확인해주세요.</p>
</section>

<section class="section briefing-section">
<div class="section-heading briefing-section-heading">
<span class="section-icon">📰</span>
<div>
<h2>오늘의 브리핑 <span class="heading-count">{len(safe_views)}건</span></h2>
<p>보안·AI 업계의 오늘을 분야별로 빠르게 훑어보세요.</p>
</div>
</div>

<div class="brief-view-switch" role="tablist" aria-label="오늘의 브리핑 보기 방식">
<button class="brief-view-button active" type="button" data-brief-view="summary" aria-selected="true">간략 보기</button>
<button class="brief-view-button" type="button" data-brief-view="detail" aria-selected="false">자세히 보기</button>
</div>

<div class="brief-summary-view" data-brief-panel="summary">
{brief_summary}
</div>

<div class="brief-detail-view" data-brief-panel="detail" hidden>
<div class="brief-list">
{brief_detail}
</div>
</div>
</section>

<section class="section department-section">
<div class="section-heading">
<span class="section-icon">🏢</span>
<div>
<h2>부서별 주요 이슈</h2>
<p>오늘 우리 부서에서 한 번쯤 확인해볼 만한 소식입니다.</p>
</div>
</div>
<div class="department-grid">
{_render_department_cards()}
</div>
</section>

<section class="section deep-section">
<div class="section-heading">
<span class="section-icon">🔎</span>
<div>
<h2>보안 심층 뉴스</h2>
<p>오늘 업무에 참고할 만한 이슈를 조금 더 자세히 살펴봅니다.</p>
</div>
</div>
{deep_news}
</section>

<section class="security-habit-section">
<div class="security-habit-box">
<div class="security-habit-icon">🔐</div>
<div class="security-habit-content">
<div class="security-habit-heading">
<span>오늘의 보안 습관</span>
<strong>클린 데스크 · 클린 디스크 생활화</strong>
</div>
<p>PC와 책상 위에 보안 관련 주요 정보를 불필요하게 보관하지 말고, 계정 ID·비밀번호를 적은 메모를 노출된 장소에 두지 마세요.</p>
</div>
</div>
</section>

<section class="source-policy">
<div class="policy-block">
<h3><span>📋</span> 선정 기준</h3>
<p>공식 기관 발표 또는 신뢰할 수 있는 전문 매체를 우선 확인합니다. 동일 사건은 가능한 범위에서 교차 확인하며, 최근 수집 기사 중 업무 관련도가 높은 내용을 우선 정리합니다.</p>
</div>
<div class="policy-block">
<h3><span>🔗</span> 주요 출처</h3>
<div class="source-grid">
<div>
<strong>국내</strong>
<p>공식 기관 · CERT · 보안 전문 언론 · 주요 IT/경제 언론</p>
</div>
<div>
<strong>해외</strong>
<p>CERT · 보안기관 · Vendor Advisory · Security 전문매체 · AI 공식 블로그</p>
</div>
</div>
</div>
<div class="feedback">
<strong>브리핑에 의견이 있으신가요?</strong>
<p>분류가 맞지 않거나 추가로 다루길 원하는 주제가 있다면 회신으로 알려주시면 감사하겠습니다.</p>
</div>
</section>

<footer class="footer">
<div>
<strong>Security &amp; AI Briefing</strong>
<p>Security · AI · Technology Daily Briefing</p>
</div>
<p class="footer-notice">본 브리핑은 공개 자료를 업무 참고 목적으로 요약·정리하여 제공합니다. 정확한 세부 내용은 연결된 공식 자료 및 기사 원문을 확인해주세요.</p>
</footer>
</main>

<script>
  document.querySelectorAll('.brief-view-button').forEach(function (button) {{
    button.addEventListener('click', function () {{
      var view = button.getAttribute('data-brief-view');

      document.querySelectorAll('.brief-view-button').forEach(function (item) {{
        var isActive = item === button;
        item.classList.toggle('active', isActive);
        item.setAttribute('aria-selected', isActive ? 'true' : 'false');
      }});

      document.querySelectorAll('[data-brief-panel]').forEach(function (panel) {{
        panel.hidden = panel.getAttribute('data-brief-panel') !== view;
      }});
    }});
  }});
</script>
</body>
</html>
"""
