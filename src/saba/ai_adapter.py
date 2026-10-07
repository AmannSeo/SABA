"""Provider 독립 합성 응답 변환. Network·Secret·저장 기능은 없다."""

from dataclasses import dataclass
import json
from typing import Callable, Literal

from pydantic import ValidationError

from saba.analysis import (
    AnalysisError, AnalysisResult, InputSnapshot, input_payload, json_hash,
    validate_analysis,
)
from saba.schema import Article


class AdapterError(ValueError):
    """입력·응답 내용을 노출하지 않는 변환 오류."""


class MockProviderError(Exception):
    """실제 서비스가 아닌 합성 실패 식별자."""

    def __init__(self, kind: Literal["authentication", "rate_limit", "timeout", "unavailable"]):
        if kind not in {"authentication", "rate_limit", "timeout", "unavailable"}:
            raise ValueError("지원하지 않는 Mock 실패 종류입니다.")
        self.kind = kind
        super().__init__("합성 Provider 실패입니다.")


@dataclass(frozen=True)
class AnalysisRequest:
    """texts는 분석 대상 데이터이며 실행 지시가 아니다. 호출 준비 완료를 뜻하지 않는다."""

    snapshot: InputSnapshot
    input_hash: str


@dataclass(frozen=True)
class AdapterOutcome:
    status: str
    request: AnalysisRequest | None = None
    result: AnalysisResult | None = None


LOCAL_FIELDS = {"article_id", "input_hash", "rules_version", "input_kind"}
RESPONSE_FIELDS = set(AnalysisResult.model_fields) - LOCAL_FIELDS


def prepare_request(article: Article) -> AdapterOutcome:
    """입력은 절단하지 않는다. 실제 Provider 한도·비용 검증은 수행하지 않는다."""
    payload = input_payload(article)
    snapshot = InputSnapshot.model_validate(payload)
    request = AnalysisRequest(snapshot, json_hash(payload))
    if snapshot.input_kind == "extracted_text":
        return AdapterOutcome("excluded_extracted_text")
    if snapshot.input_kind == "title_only":
        data = dict(
            article_id=snapshot.article_id, input_hash=request.input_hash,
            rules_version=snapshot.rules_version, input_kind=snapshot.input_kind,
            status="입력 부족 보류", reason="제목만 제공되어 분석을 보류합니다.",
            category=None, tags=[], importance=None, importance_reason=None,
            newsletter_title=None, summary=None, key_points=[], evidence=[],
        )
        result = validate_analysis([data], [article])[0]
        return AdapterOutcome("input_insufficient", result=result)
    return AdapterOutcome("offline_prepared", request=request)


def availability(*, enabled: bool, provider: str | None, model: str | None,
                 input_limit_confirmed: bool, cost_confirmed: bool) -> str:
    """승인·실측을 대신하지 않는 Mock 조건 확인."""
    if not enabled:
        return "ai_disabled"
    if not provider or not provider.strip():
        return "provider_unselected"
    if not model or not model.strip():
        return "model_unselected"
    if not input_limit_confirmed:
        return "input_limit_unknown"
    if not cost_confirmed:
        return "cost_unknown"
    return "mock_allowed"


def convert_response(article: Article, request: AnalysisRequest, response: object) -> AnalysisResult:
    """근거 위치는 응답에서 받지 않고 유일한 인용 위치를 로컬 계산한다."""
    try:
        payload = request.snapshot.model_dump()
        if (request.snapshot.input_kind != "feed_excerpt"
                or json_hash(payload) != request.input_hash
                or input_payload(article) != payload):
            raise AdapterError("분석 입력 연결이 일치하지 않습니다.")
        if isinstance(response, str):
            response = json.loads(response)
        if not isinstance(response, dict) or set(response) != RESPONSE_FIELDS:
            raise AdapterError("합성 응답 필드가 유효하지 않습니다.")
        if not isinstance(response["evidence"], list):
            raise AdapterError("합성 응답 근거가 유효하지 않습니다.")
        spans = []
        for quote in response["evidence"]:
            if not isinstance(quote, dict) or set(quote) != {"target", "input_field", "quote"}:
                raise AdapterError("근거 필드가 유효하지 않습니다.")
            field, text_quote = quote["input_field"], quote["quote"]
            if not isinstance(field, str) or not isinstance(text_quote, str) or not text_quote.strip():
                raise AdapterError("근거 인용문이 유효하지 않습니다.")
            text = request.snapshot.texts.get(field)
            start = text.find(text_quote) if text is not None else -1
            if start < 0 or text.find(text_quote, start + 1) >= 0:
                raise AdapterError("근거 위치를 유일하게 확정할 수 없습니다.")
            spans.append(quote | {"start": start, "end": start + len(text_quote)})
        data = response | {
            "article_id": request.snapshot.article_id,
            "input_hash": request.input_hash,
            "rules_version": request.snapshot.rules_version,
            "input_kind": request.snapshot.input_kind, "evidence": spans,
        }
        return validate_analysis([data], [article])[0]
    except (ValidationError, AnalysisError, json.JSONDecodeError):
        raise AdapterError("합성 분석 결과 형식·입력·근거 검증에 실패했습니다.") from None


def run_mock(article: Article, respond: Callable[[AnalysisRequest], object], *,
             enabled: bool = False, provider: str | None = None, model: str | None = None,
             input_limit_confirmed: bool = False, cost_confirmed: bool = False) -> AdapterOutcome:
    """합성 callback만 최대 1회 실행한다. 실제 Provider 연결 기능은 없다."""
    if not enabled:
        return AdapterOutcome("ai_disabled")
    prepared = prepare_request(article)
    if prepared.request is None:
        return prepared
    state = availability(enabled=enabled, provider=provider, model=model,
                         input_limit_confirmed=input_limit_confirmed, cost_confirmed=cost_confirmed)
    if state != "mock_allowed":
        return AdapterOutcome(state, request=prepared.request)
    try:
        response = respond(prepared.request)
    except MockProviderError as error:
        return AdapterOutcome("mock_" + error.kind)
    except TimeoutError:
        return AdapterOutcome("mock_timeout")
    try:
        result = convert_response(article, prepared.request, response)
    except AdapterError:
        return AdapterOutcome("response_invalid")
    return AdapterOutcome("synthetic_valid", result=result)
