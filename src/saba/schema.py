"""수집 기사와 선택적 분석 입력의 공통 형식. 외부 서비스는 호출하지 않는다."""

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    HttpUrl,
    StrictInt,
    StringConstraints,
    TypeAdapter,
    ValidationInfo,
    field_validator,
)


def nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("빈 문자열 또는 공백뿐인 값은 허용하지 않습니다")
    return value


Text = Annotated[str, StringConstraints(strict=True), AfterValidator(nonblank)]
Department = Literal["경영전략팀", "기술개발연구소", "보안사업팀", "STE본"]


def utc_datetime(value: object) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError("ISO 8601 날짜시간이 필요합니다") from None
    if not isinstance(value, datetime):
        raise ValueError("ISO 8601 날짜시간 문자열이 필요합니다")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("날짜시간에는 시간대가 필요합니다")
    return value.astimezone(timezone.utc)


Timestamp = Annotated[datetime, BeforeValidator(utc_datetime)]


class SourceReference(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    source_name: Text
    title: Text
    url: HttpUrl
    published_at: Timestamp | None = None


class EvidenceReference(BaseModel):
    """근거가 가리키는 주소와 선택적 설명. 실제 확인 여부는 추론하지 않는다."""

    model_config = ConfigDict(strict=True, extra="forbid")

    url: HttpUrl
    note: Text | None = None


class AnalysisMetadata(BaseModel):
    """입력된 분석 실행 정보만 보존한다. 분석을 실행하지 않는다."""

    model_config = ConfigDict(strict=True, extra="forbid")

    provider: Text | None = None
    model: Text | None = None
    prompt_version: Text | None = None
    analyzed_at: Timestamp | None = None


class Article(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    schema_version: Annotated[StrictInt, Field(ge=1, le=1)]
    article_id: Text
    original_title: Text
    source_id: Text
    source_name: Text
    url: HttpUrl
    collection_method: Literal["rss", "api", "crawl"]
    collected_at: Timestamp

    source_item_id: Text | None = None
    canonical_url: HttpUrl | None = None
    published_at: Timestamp | None = None
    updated_at: Timestamp | None = None
    language: Text | None = None
    region: Literal["국내", "해외", "국제", "미확인"] | None = None
    feed_excerpt: Text | None = None
    extracted_text: Text | None = None
    content_hash: Text | None = None
    newsletter_title: Text | None = None
    category: Text | None = None
    tags: list[Text] = Field(default_factory=list)
    importance: Text | None = None
    importance_reason: Text | None = None
    departments: list[Department] = Field(default_factory=list)
    department_reasons: dict[Department, Text] = Field(default_factory=dict)
    summary: Text | None = None
    key_points: list[Text] = Field(default_factory=list)
    hook: Text | None = None
    why_read: Text | None = None
    context: Text | None = None
    implications: list[Text] = Field(default_factory=list)
    official_sources: list[SourceReference] = Field(default_factory=list)
    related_articles: list[SourceReference] = Field(default_factory=list)
    evidence_status: Text | None = None
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    cluster_id: Text | None = None
    analysis_metadata: AnalysisMetadata | None = None

    @field_validator("departments")
    @classmethod
    def unique_departments(cls, value: list[Department]) -> list[Department]:
        if len(value) != len(set(value)):
            raise ValueError("부서 중복은 허용하지 않습니다")
        return value

    @field_validator("department_reasons")
    @classmethod
    def reasons_for_selected_departments(
        cls, value: dict[Department, str], info: ValidationInfo
    ) -> dict[Department, str]:
        if not set(value).issubset(info.data.get("departments", [])):
            raise ValueError("이유는 departments에 포함된 부서에만 지정할 수 있습니다")
        return value


def validate_articles(value: object) -> list[Article]:
    """배열 전체의 Schema 및 내부 식별자 중복을 검증한다."""
    articles = TypeAdapter(Annotated[list[Article], Field(strict=True, min_length=1)]).validate_python(value)
    seen: set[str] = set()
    for index, article in enumerate(articles):
        if article.article_id in seen:
            raise ValueError(f"$[{index}].article_id: 중복 article_id는 허용하지 않습니다")
        seen.add(article.article_id)
    return articles
