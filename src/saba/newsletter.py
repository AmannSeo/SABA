"""Newsletter HTML rendering for SABA."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from saba.analysis import AnalysisResult
from saba.schema import Article

if TYPE_CHECKING:
    from saba.insights import InsightResult

_ANALYSIS_READY_STATUS = "검토 필요"
_AI_TECH_CATEGORIES = {"AI·기술", "AI 보안"}
_WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
_DEEP_SECTION_META = {
    "domestic": ("국내 보안", "🇰🇷"),
    "overseas": ("해외 보안", "🌎"),
    "ai_tech": ("AI & Tech", "🤖"),
    "other": ("기타", "🗂️"),
}
_BRIEF_GROUP_META = {
    "schedule": ("일정", "🗓️", "schedule"),
    "hot": ("핫이슈", "🔥", "hot"),
    "market": ("보안시장 동향", "📈", "market"),
    "security": ("보안 뉴스", "🛡️", "security"),
    "company": ("기업 소식", "🏢", "company"),
    "ai_tech": ("테크(Tech)", "⚙️", "tech"),
    "economy": ("경제 지표", "📊", "economy"),
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
BRIEF_MAX_PER_GROUP = 5  # 오늘의 브리핑 분야당 최대 건수 (D-033). 입력 순서(공식 우선 → 최신)를 따른다.
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
    sources: list[tuple[str, str, str, str]] = field(default_factory=list)
    sample_implications: list[str] = field(default_factory=list)
    sample_connections: dict[str, str] = field(default_factory=dict)
    sample_only: bool = False
    sample_brief_group: Optional[str] = None
    ai_implication: Optional[str] = None
    ai_connections: dict[str, str] = field(default_factory=dict)


def _implications(view: ArticleView) -> list[str]:
    if view.sample_implications:
        return ["SAMPLE/MOCK: " + text for text in view.sample_implications]
    return [view.ai_implication] if view.ai_implication else []  # 표시 문구 없음 (D-044)


def _connections(view: ArticleView) -> dict[str, str]:
    if view.sample_connections:
        return {name: "SAMPLE/MOCK: " + text for name, text in view.sample_connections.items()}
    return dict(view.ai_connections)


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


def build_article_view(article: Article, analysis: Optional[AnalysisResult] = None, *,
                       preview_sample: Optional[dict] = None, insight: Optional[InsightResult] = None) -> ArticleView:
    if preview_sample is not None and preview_sample.get("brief_group") not in (None, *_BRIEF_GROUP_META):
        raise ValueError("지원하지 않는 SAMPLE 브리핑 그룹입니다.")
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
        sources=[(article.source_name, article.original_title, str(article.url),
                  _format_article_date(article.published_at) if article.published_at else "발행일 미확인")]
                + [(ref.source_name, ref.title, str(ref.url),
                    _format_article_date(ref.published_at) if ref.published_at else "발행일 미확인")
                   for ref in article.official_sources + article.related_articles],
        sample_implications=list((preview_sample or {}).get("implications", [])),
        sample_connections=dict((preview_sample or {}).get("connections", {})),
        sample_only=preview_sample is not None,
        sample_brief_group=(preview_sample or {}).get("brief_group"),
        ai_implication=insight.implication if insight else None,
        ai_connections={c.department: c.text for c in insight.connections} if insight else {},
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


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]


def _render_brief_summary(groups: dict[str, list[ArticleView]]) -> str:
    # SAMPLE 형식: 분야마다 한 줄. 기사가 없는 분야는 표시하지 않는다 (D-036).
    items: list[str] = []
    for group_key, (label, icon, css_class) in _BRIEF_GROUP_META.items():
        views = groups[group_key]
        if not views:
            continue
        message = _brief_message(views)
        items.append(f'<div class="brief-compact-group {css_class}">\n'
                     f'<span class="brief-compact-label">{icon} {label}</span>\n<p>{message}</p>\n</div>')
    return "\n".join(items)


def _render_brief_detail(groups: dict[str, list[ArticleView]], anchors: dict[str, str]) -> str:
    # SAMPLE 형식: 기사 제목 링크 + 설명 한 문장 (AI 요약 첫 문장). 요약이 없으면 출처만 붙인다.
    blocks: list[str] = []
    for group_key, (label, icon, heading_class) in _BRIEF_GROUP_META.items():
        views = groups[group_key]
        if not views:
            continue
        items = []
        for view in views:
            link = f'<a href="#{_safe_escape(anchors.get(view.article_id, ""))}">{_safe_escape(view.title)}</a>'
            detail = _first_sentence(view.summary) if view.has_full_analysis and view.summary else view.source_name
            items.append(f"<li>{link}<br/>{_safe_escape(detail)}</li>")
        list_html = "\n".join(items)
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


def _render_department_cards(views: list[ArticleView], anchors: dict[str, str]) -> str:
    cards: list[str] = []
    for name, icon, css_class in _DEPARTMENT_CARDS:
        assigned = [view for view in views if name in _connections(view)][:3]
        content = "\n".join(
            '<div class="department-news-item">'
            '<div class="card-meta-row"><div class="card-badges">'
            f'<span class="type-badge">{_safe_escape(view.category or "미분류")}</span>'
            f'</div><span class="card-date">{_safe_escape(view.date_display)}</span></div>'
            f'<h4>{_safe_escape(view.title)}</h4>'
            f'<p class="card-summary">{_safe_escape(_connections(view)[name])}</p>'
            f'<div class="card-actions"><span class="card-source-bottom">{_safe_escape(view.source_name)}</span>'
            f'<a class="card-button" href="#{_safe_escape(anchors[view.article_id])}">관련 뉴스 보기 →</a></div></div>'
            for view in assigned
        ) or ('<div class="department-news-item"><p class="card-summary">'
              # STE본은 업무 범위 미확정이라 AI 연결 대상이 아니다 (PROJECT_RULES 10절, D-041).
              + ("업무 범위 확인 중입니다." if name == "STE본" else "이번 브리핑에서 분류된 기사가 없습니다.")
              + '</p></div>')
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
<span class="department-count">관련 이슈 {len(assigned)}건</span>
</div>
<div class="department-content">
{content}
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
    # 본문은 AI 한국어 요약(3~5문장)만 표시한다. 원문 발췌·펼치기는 표시하지 않는다 (D-036).
    if view.has_full_analysis and view.summary is not None:
        return f'<div class="article-content">\n<p>{_safe_escape(view.summary)}</p>\n</div>'
    return ""


def _empty_section_text(group_key: str, analyzed: bool) -> str:
    # AI & Tech는 AI 분석 결과로만 채워지므로, 분석 전이면 기사가 없는 이유를 함께 밝힌다 (D-030).
    if group_key == "ai_tech" and not analyzed:
        return "AI 분석 전이라 분류된 기사가 없습니다."
    return "수집된 기사가 없습니다."


def _render_deep_news(groups: dict[str, list[ArticleView]], anchors: dict[str, str]) -> str:
    sections: list[str] = []
    analyzed = any(view.has_full_analysis for views in groups.values() for view in views)
    for group_key in ("domestic", "overseas", "ai_tech", "other"):
        views = groups[group_key]
        if not views and group_key == "other":
            continue
        title, icon = _DEEP_SECTION_META[group_key]
        cards = []
        for view in views:
            anchor = anchors.get(view.article_id, "")
            body = _render_article_body(view)
            implications = "".join(f'<p>{_safe_escape(text)}</p>' for text in _implications(view))
            implications = implications or '<p>분석 정보가 없습니다.</p>'
            connections = "".join(
                f'<div class="impact-row"><strong>{_safe_escape(name)}</strong><span>{_safe_escape(text)}</span></div>'
                for name, text in _connections(view).items()
            ) or '<p>검토된 업무 연결 정보가 없습니다.</p>'
            sources = "".join(
                f'<a class="source-row" href="{_safe_escape(url)}" target="_blank" rel="noopener noreferrer">'
                f'<span class="source-name">{_safe_escape(name)}</span>'
                f'<span class="source-title">{_safe_escape(title)}</span>'
                f'<span class="source-date">{_safe_escape(published)} →</span></a>'
                for name, title, url, published in view.sources
            )
            cards.append(
                f"""
<article class="news-card" id="{_safe_escape(anchor)}">
<div class="news-top">
<div class="news-badges">
{_render_badges(view)}
</div>
<span class="article-datetime">{_safe_escape(view.date_label)} · {_safe_escape(view.date_display)}</span>
</div>
<h3 class="news-title">{_safe_escape(view.title)}</h3>
{body}
<div class="insight-box"><h4><span>💡</span> 시사점</h4>{implications}</div>
<div class="department-impact"><h4><span>🏢</span> 우리 업무와의 연결</h4>{connections}</div>
<div class="source-related"><h4><span>🔗</span> 출처 · 관련 기사</h4>{sources}</div>
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
{chr(10).join(cards) if cards else f'<p class="news-lead">{_empty_section_text(group_key, analyzed)}</p>'}""".strip()
        )
    if not sections:
        return '<p class="news-lead">수집된 기사가 없습니다.</p>'
    return "\n".join(sections)


def _group_views(views: list[ArticleView]):
    """(앵커, 오늘의 브리핑 그룹, 심층 뉴스 그룹). 웹 Preview 와 메일이 같은 구성을 쓴다."""
    anchors = _build_anchor_map(views)
    brief_groups = {key: [] for key in _BRIEF_GROUP_META}
    deep_groups = {"domestic": [], "overseas": [], "ai_tech": [], "other": []}
    for view in views:
        deep_section = article_section(view)
        deep_groups[deep_section].append(view)
        brief_key = "security"
        if deep_section == "ai_tech":
            brief_key = "ai_tech"
        elif view.has_full_analysis and view.category == "산업·시장·기업":
            brief_key = "market"
        elif deep_section == "other":
            brief_key = "other"
        group = brief_groups[view.sample_brief_group or brief_key]
        if len(group) < BRIEF_MAX_PER_GROUP:
            group.append(view)
    return anchors, brief_groups, deep_groups


def _brief_message(views: list[ArticleView]) -> str:
    head, *rest = [_safe_escape(view.title) for view in views[:2]]
    message = f"<strong>{head}</strong>" + "".join(f" · {title}" for title in rest)
    return message + (f" 외 {len(views) - 2}건" if len(views) > 2 else "")


def build_newsletter_html(
    views: list[ArticleView],
    css_path: str = "../SAMPLE/Codex/v09/style_review_v9.css",
    logo_path: str = "../SAMPLE/Codex/v09/LOGO.png",
    today: Optional[str] = None,
    *, preview_mode: bool = False,
) -> str:
    safe_views = list(views or [])
    if any(view.sample_only for view in safe_views) and not preview_mode:
        raise ValueError("SAMPLE 데이터는 preview_mode에서만 표시할 수 있습니다.")
    anchors, brief_groups, deep_groups = _group_views(safe_views)
    brief_summary = _render_brief_summary(brief_groups)
    brief_detail = _render_brief_detail(brief_groups, anchors)

    deep_news = _render_deep_news(deep_groups, anchors)
    today_display = _safe_escape(_format_today_display(today))
    css_href = _safe_escape(css_path)
    logo_src = _safe_escape(logo_path)

    template = Path(__file__).resolve().parents[2] / "templates" / "newsletter.html"
    return template.read_text(encoding="utf-8").format(
        css_href=css_href, logo_src=logo_src, today_display=today_display,
        article_count=len(safe_views), brief_summary=brief_summary,
        brief_detail=brief_detail, deep_news=deep_news,
        department_cards=_render_department_cards(safe_views, anchors),
        preview_label=' · SAMPLE/MOCK 미리보기' if preview_mode else '',
    )


# ---- 메일 전용 table 레이아웃 (D-054). 색·여백은 SAMPLE/Codex/v09 CSS 값을 옮겼다. ----
_DEPARTMENT_COLORS = {"strategy": "#16a34a", "development": "#2563eb", "security-team": "#dc2626", "ste": "#7c3aed"}
_TABLE = 'role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'


def _mail_badge(text: str, color: str = "#6b7280", background: str = "#f3f4f6") -> str:
    return (f'<span style="display:inline-block;margin:0 4px 4px 0;padding:3px 7px;border-radius:4px;'
            f'background:{background};color:{color};font-size:11px;font-weight:700;">{_safe_escape(text)}</span>')


def _mail_brief_rows(groups: dict[str, list[ArticleView]]) -> str:
    rows = []
    for key, (label, icon, _css) in _BRIEF_GROUP_META.items():
        if groups[key]:
            rows.append(f'<tr><td valign="top" width="118" style="padding:11px 0;border-bottom:1px solid #eef0f2;'
                        f'color:#374151;font-size:13px;font-weight:700;white-space:nowrap;">{icon} {label}</td>'
                        f'<td valign="top" style="padding:11px 0 11px 10px;border-bottom:1px solid #eef0f2;'
                        f'color:#6b7280;font-size:13px;line-height:1.65;">{_brief_message(groups[key])}</td></tr>')
    return "\n".join(rows) or '<tr><td style="padding:11px 0;color:#9ca3af;font-size:13px;">수집된 기사가 없습니다.</td></tr>'


def _mail_department_card(name: str, icon: str, css_class: str, views: list[ArticleView],
                          anchors: dict[str, str]) -> str:
    assigned = [view for view in views if name in _connections(view)][:3]
    items = "".join(
        f'<tr><td style="padding:14px 16px;border-bottom:1px solid #eef0f2;">'
        f'{_mail_badge(view.category or "미분류")}'
        f'<span style="color:#9ca3af;font-size:11px;">{_safe_escape(view.date_display)}</span>'
        f'<p style="margin:6px 0 0;color:#111827;font-size:14px;font-weight:700;line-height:1.5;"><strong>{_safe_escape(view.title)}</strong></p>'
        f'<p style="margin:6px 0 0;color:#6b7280;font-size:12px;line-height:1.65;">{_safe_escape(_connections(view)[name])}</p>'
        f'<p style="margin:8px 0 0;font-size:11px;"><span style="color:#9ca3af;">{_safe_escape(view.source_name)}</span>'
        f' &nbsp;<a href="{_safe_escape(view.url)}" target="_blank" style="color:#374151;font-weight:700;text-decoration:none;">기사 원문 보기 →</a></p>'
        f'</td></tr>'
        for view in assigned
    ) or (f'<tr><td style="padding:14px 16px;color:#9ca3af;font-size:12px;">'
          f'{"업무 범위 확인 중입니다." if name == "STE본" else "이번 브리핑에서 분류된 기사가 없습니다."}</td></tr>')
    return (f'<table {_TABLE} bgcolor="#ffffff" style="background:#ffffff;border:1px solid #e5e7eb;'
            f'border-top:3px solid {_DEPARTMENT_COLORS[css_class]};border-radius:8px;">'
            f'<tr><td bgcolor="#fafafa" style="padding:12px 16px;background:#fafafa;border-bottom:1px solid #e5e7eb;">'
            f'<table {_TABLE}><tr><td style="color:#111827;font-size:14px;font-weight:700;">{icon} {name}</td>'
            f'<td align="right" style="color:#6b7280;font-size:11px;">관련 이슈 {len(assigned)}건</td></tr></table>'
            f'</td></tr>{items}</table>')


def _mail_departments(views: list[ArticleView], anchors: dict[str, str]) -> str:
    cards = [_mail_department_card(name, icon, css, views, anchors) for name, icon, css in _DEPARTMENT_CARDS]
    rows = []
    for left, right in zip(cards[0::2], cards[1::2]):
        rows.append(f'<tr><td valign="top" width="50%" style="padding:0 6px 12px 0;">{left}</td>'
                    f'<td valign="top" width="50%" style="padding:0 0 12px 6px;">{right}</td></tr>')
    return f'<table {_TABLE}>{"".join(rows)}</table>'


def _mail_news_card(view: ArticleView, anchor: str) -> str:
    badges = "".join([_mail_badge(view.category, "#4f46e5", "#eef2ff")] if view.category else [])
    badges += "".join(_mail_badge(tag) for tag in view.tags) or ("" if badges else _mail_badge("일반 기사"))
    body = (f'<p style="margin:12px 0 0;color:#374151;font-size:14px;line-height:1.8;">{_safe_escape(view.summary)}</p>'
            if view.has_full_analysis and view.summary else "")
    implications = "".join(f'<p style="margin:6px 0 0;color:#4b5563;font-size:13px;line-height:1.7;">{_safe_escape(text)}</p>'
                           for text in _implications(view)) or \
        '<p style="margin:6px 0 0;color:#9ca3af;font-size:13px;">분석 정보가 없습니다.</p>'
    connections = "".join(
        f'<tr><td valign="top" width="110" style="padding:7px 0;border-bottom:1px solid #f0f1f3;color:#111827;'
        f'font-size:12px;font-weight:700;">{_safe_escape(name)}</td><td style="padding:7px 0;border-bottom:1px solid #f0f1f3;'
        f'color:#4b5563;font-size:12px;line-height:1.6;">{_safe_escape(text)}</td></tr>'
        for name, text in _connections(view).items()
    ) or '<tr><td style="padding:7px 0;color:#9ca3af;font-size:12px;">검토된 업무 연결 정보가 없습니다.</td></tr>'
    sources = "".join(
        f'<tr><td valign="top" width="120" style="padding:8px 0;border-bottom:1px solid #eef0f2;color:#2563eb;'
        f'font-size:11px;font-weight:700;">{_safe_escape(name)}</td>'
        f'<td style="padding:8px 8px;border-bottom:1px solid #eef0f2;font-size:12px;line-height:1.5;">'
        f'<a href="{_safe_escape(url)}" style="color:#374151;text-decoration:none;">{_safe_escape(title)}</a></td>'
        f'<td valign="top" align="right" width="78" style="padding:8px 0;border-bottom:1px solid #eef0f2;color:#9ca3af;'
        f'font-size:11px;white-space:nowrap;">{_safe_escape(published)}</td></tr>'
        for name, title, url, published in view.sources)
    return (f'<a name="{_safe_escape(anchor)}" id="{_safe_escape(anchor)}"></a>'
            f'<table {_TABLE} bgcolor="#ffffff" style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;margin-bottom:16px;">'
            f'<tr><td style="padding:20px 22px;">'
            f'<table {_TABLE}><tr><td valign="top">{badges}</td><td valign="top" align="right" width="120" '
            f'style="color:#9ca3af;font-size:11px;white-space:nowrap;">{_safe_escape(view.date_label)} · {_safe_escape(view.date_display)}</td></tr></table>'
            f'<h3 style="margin:8px 0 0;color:#111827;font-size:19px;font-weight:700;line-height:1.5;"><strong>{_safe_escape(view.title)}</strong></h3>'
            f'{body}'
            f'<table {_TABLE} bgcolor="#fffdf5" style="margin-top:16px;background:#fffdf5;border-left:3px solid #f59e0b;">'
            f'<tr><td style="padding:14px 16px;"><p style="margin:0;color:#111827;font-size:13px;font-weight:700;">💡 시사점</p>'
            f'{implications}</td></tr></table>'
            f'<p style="margin:16px 0 4px;color:#111827;font-size:13px;font-weight:700;">🏢 우리 업무와의 연결</p>'
            f'<table {_TABLE}>{connections}</table>'
            f'<p style="margin:16px 0 4px;color:#111827;font-size:13px;font-weight:700;">🔗 출처 · 관련 기사</p>'
            f'<table {_TABLE} style="border-top:1px solid #e5e7eb;">{sources}</table>'
            f'</td></tr></table>')


def _mail_deep_news(groups: dict[str, list[ArticleView]], anchors: dict[str, str]) -> str:
    analyzed = any(view.has_full_analysis for views in groups.values() for view in views)
    parts = []
    for key in ("domestic", "overseas", "ai_tech", "other"):
        views = groups[key]
        if not views and key == "other":
            continue
        title, icon = _DEEP_SECTION_META[key]
        parts.append(f'<table {_TABLE} style="margin:28px 0 14px;border-bottom:2px solid #111827;"><tr>'
                     f'<td style="padding-bottom:9px;color:#111827;font-size:16px;font-weight:700;">{icon} {title}</td>'
                     f'<td align="right" style="padding-bottom:9px;color:#9ca3af;font-size:12px;">{len(views)}건</td></tr></table>')
        parts.extend(_mail_news_card(view, anchors.get(view.article_id, "")) for view in views)
        if not views:
            parts.append(f'<p style="margin:0 0 12px;color:#9ca3af;font-size:13px;">{_empty_section_text(key, analyzed)}</p>')
    return "\n".join(parts)


def build_mail_html(views: list[ArticleView], *, today: Optional[str] = None, logo_src: str, signature: str) -> str:
    """메일 전용 table 레이아웃 HTML (D-054). 웹 Preview 와 같은 기사 구성을 쓴다. SAMPLE 데이터는 받지 않는다."""
    safe_views = list(views or [])
    if any(view.sample_only for view in safe_views):
        raise ValueError("SAMPLE 데이터는 메일에 쓸 수 없습니다.")
    anchors, brief_groups, deep_groups = _group_views(safe_views)
    template = Path(__file__).resolve().parents[2] / "templates" / "newsletter_mail.html"
    return template.read_text(encoding="utf-8").format(
        logo_src=_safe_escape(logo_src), today_display=_safe_escape(_format_today_display(today)),
        article_count=len(safe_views), brief_rows=_mail_brief_rows(brief_groups),
        department_cards=_mail_departments(safe_views, anchors), deep_news=_mail_deep_news(deep_groups, anchors),
        signature=signature,
    )
