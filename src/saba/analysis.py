"""합성 분석 결과의 형식·입력 연결 검증. 분석 실행과 저장은 하지 않는다."""

import hashlib
from html.parser import HTMLParser
import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StrictInt, TypeAdapter, model_validator

from saba.schema import Article, Text, utc_datetime

RULES_VERSION = "saba-analysis-v1"
Category = Literal["보안 사고", "취약점·권고", "위협 동향", "AI 보안", "AI·기술", "산업·시장·기업"]
InputKind = Literal["title_only", "feed_excerpt", "extracted_text"]


class AnalysisError(ValueError):
    """기사·결과 원문 없이 보고하는 연결 오류."""


class FeedTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden.append(tag)
        self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def input_payload(article: Article) -> dict:
    texts = {"original_title": normalize_text(article.original_title)}
    kind: InputKind = "title_only"
    if article.extracted_text is not None:
        content = normalize_text(article.extracted_text)
        if content:
            kind = "extracted_text"
            texts[kind] = content
    if kind == "title_only" and article.feed_excerpt is not None:
        parser = FeedTextParser()
        parser.feed(article.feed_excerpt)
        parser.close()
        content = normalize_text("".join(parser.parts))
        if content:
            kind = "feed_excerpt"
            texts[kind] = content
    payload = {
        "rules_version": RULES_VERSION, "article_id": article.article_id,
        "schema_version": article.schema_version, "source_id": article.source_id,
        "source_name": article.source_name, "url": str(article.url),
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "input_kind": kind, "texts": texts,
    }
    return payload


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def analysis_input(article: Article) -> tuple[dict[str, str], InputKind, str]:
    payload = input_payload(article)
    return payload["texts"], payload["input_kind"], json_hash(payload)


class InputSnapshot(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    rules_version: Literal["saba-analysis-v1"]
    article_id: Text
    schema_version: Annotated[StrictInt, Field(ge=1, le=1)]
    source_id: Text
    source_name: Text
    url: Text
    published_at: Text | None
    input_kind: InputKind
    texts: dict[Literal["original_title", "feed_excerpt", "extracted_text"], Text]

    @model_validator(mode="after")
    def normalized_input(self):
        expected = {"original_title"}
        if self.input_kind != "title_only":
            expected.add(self.input_kind)
        if set(self.texts) != expected or any(normalize_text(text) != text for text in self.texts.values()):
            raise ValueError("스냅샷 입력 필드·공백 정규화가 일치하지 않습니다")
        if str(TypeAdapter(HttpUrl).validate_python(self.url)) != self.url:
            raise ValueError("스냅샷 URL은 정규화된 HTTP(S) URL이어야 합니다")
        if self.published_at is not None and utc_datetime(self.published_at).isoformat() != self.published_at:
            raise ValueError("스냅샷 발행일은 정규화된 UTC여야 합니다")
        return self


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    target: Annotated[str, Field(pattern=r"^(newsletter_title|summary|category|importance_reason|tags\[[0-9]+\]|key_points\[[0-9]+\])$")]
    input_field: Literal["original_title", "feed_excerpt", "extracted_text"]
    start: Annotated[StrictInt, Field(ge=0)]
    end: Annotated[StrictInt, Field(gt=0)]
    quote: Text


class AnalysisResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    article_id: Text
    input_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    rules_version: Literal["saba-analysis-v1"]
    input_kind: InputKind
    status: Literal["검토 필요", "입력 부족 보류", "대상 밖"]
    reason: Text
    category: Category | None
    tags: Annotated[list[Text], Field(max_length=5)]
    importance: Literal["높음", "보통", "낮음"] | None
    importance_reason: Text | None
    newsletter_title: Text | None
    summary: Annotated[Text, Field(max_length=300)] | None
    key_points: Annotated[list[Text], Field(max_length=3)]
    evidence: list[EvidenceSpan]

    @model_validator(mode="after")
    def consistent_output(self):
        if len(self.tags) != len(set(self.tags)) or len(self.key_points) != len(set(self.key_points)):
            raise ValueError("태그와 핵심 사실의 중복은 허용하지 않습니다")
        if (self.importance is None) != (self.importance_reason is None):
            raise ValueError("중요도와 중요도 이유는 함께 입력하거나 함께 NULL이어야 합니다")
        if self.status != "검토 필요":
            if any((self.category, self.tags, self.importance, self.importance_reason,
                    self.newsletter_title, self.summary, self.key_points, self.evidence)):
                raise ValueError("보류·대상 밖 결과에는 분석 내용을 채울 수 없습니다")
        elif self.newsletter_title is None or self.summary is None:
            raise ValueError("검토 필요 결과에는 제목 후보와 요약이 필요합니다")
        if self.summary is not None:
            # ponytail: 문장부호 기반 형식 검사, 실제 문장·번역 품질 평가는 별도 수행한다.
            pieces = re.split(r'[.!?。！？]+["\u201d\u2019)\]]*(?:\s+|$)', self.summary)
            if sum(bool(piece.strip()) for piece in pieces) > 2:
                raise ValueError("요약은 문장부호 기준 최대 2문장이어야 합니다")
        return self


def validate_analysis(value: object, articles: list[Article]) -> list[AnalysisResult]:
    results = TypeAdapter(Annotated[list[AnalysisResult], Field(strict=True, min_length=1)]).validate_python(value)
    by_id = {article.article_id: article for article in articles}
    seen = set()
    for index, result in enumerate(results):
        prefix = f"$[{index}]"
        if result.article_id in seen:
            raise AnalysisError(f"{prefix}: 중복 결과 article_id입니다.")
        seen.add(result.article_id)
        article = by_id.get(result.article_id)
        if article is None:
            raise AnalysisError(f"{prefix}: 입력 기사에 없는 article_id입니다.")
        validate_snapshot_result(result, InputSnapshot.model_validate(input_payload(article)), prefix)
    return results


def validate_snapshot_result(result: AnalysisResult, snapshot: InputSnapshot, prefix="결과") -> None:
    if (result.article_id != snapshot.article_id or result.rules_version != snapshot.rules_version
            or result.input_kind != snapshot.input_kind or result.input_hash != json_hash(snapshot.model_dump())):
        raise AnalysisError(f"{prefix}: 분석 입력 종류 또는 Hash가 일치하지 않습니다.")
    if result.summary is not None and not result.summary.startswith(snapshot.source_name + "에 따르면"):
        raise AnalysisError(f"{prefix}: 요약은 입력 출처 이름과 '에 따르면'으로 시작해야 합니다.")
    targets = {field for field in ("newsletter_title", "summary", "category", "importance_reason")
               if getattr(result, field) is not None}
    targets.update(f"tags[{i}]" for i in range(len(result.tags)))
    targets.update(f"key_points[{i}]" for i in range(len(result.key_points)))
    covered = set()
    for span in result.evidence:
        text = snapshot.texts.get(span.input_field)
        if span.target not in targets or text is None or not (0 <= span.start < span.end <= len(text)):
            raise AnalysisError(f"{prefix}: 근거 대상·입력 필드·위치가 유효하지 않습니다.")
        if text[span.start:span.end] != span.quote:
            raise AnalysisError(f"{prefix}: 근거 인용문이 입력 위치와 일치하지 않습니다.")
        covered.add(span.target)
    if covered != targets:
        raise AnalysisError(f"{prefix}: 채워진 분석 출력에 근거 연결이 필요합니다.")
