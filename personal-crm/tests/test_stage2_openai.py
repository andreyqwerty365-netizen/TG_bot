"""Official SDK over synthetic HTTP; no model quality or live calls are claimed."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
import json
from threading import Event

import httpx2
from openai import OpenAI
import pytest
from sqlalchemy import func, select

from personal_crm.budget import AIError, BudgetLedger, price
from personal_crm.context import build_context
from personal_crm.integration_config import AIConfig
from personal_crm.models import AIReservation, SourceVersion, Task
from personal_crm.openai_adapter import ContextInterpreter, ProviderOutput, ResponsesAdapter
from personal_crm.schema import Incoming
from personal_crm.service import CRMService


OWNER = "synthetic-ai-owner"


def config(**changes):
    prices = {"synthetic-model": {"currency": "USD", "source": "https://example.invalid/synthetic-pricing",
        "valid_until": "2030-01-01T00:00:00Z", "input_per_million": "1", "output_per_million": "2",
        "input_token_ceiling": 20000}}
    return replace(AIConfig(enabled=True, key="synthetic-openai-key", model="synthetic-model",
        allowed_models=frozenset({"synthetic-model"}), consent_categories=frozenset({"owner", "forward", "mail", "tasks", "dialog"}),
        monthly_budget_usd=".1", prices_json=json.dumps(prices)), **changes)


def output(source, **changes):
    return {"source_version_id": source, "operation": "create", "kind": "task", "title": "Синтетическое дело",
        "obvious": True, "question": None, "deadline": None, "reminder_at": None, "target_id": None,
        "target_version": None, "change": None, "planned_on": None, "return_on": None, "focused": None,
        "draft_steps": ["Черновик шага"], **changes}


def frame(data, status="completed", refusal=False, raw=None):
    content = {"type": "refusal", "refusal": "Synthetic refusal"} if refusal else {
        "type": "output_text", "text": raw if raw is not None else json.dumps(data, ensure_ascii=False), "annotations": []}
    return {"id": "resp_synthetic", "object": "response", "created_at": 1, "model": "synthetic-model",
        "status": status, "error": None, "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "output": [{"id": "msg_synthetic", "type": "message", "role": "assistant", "status": "completed", "content": [content]}],
        "parallel_tool_calls": False, "tool_choice": "none", "tools": [], "store": False,
        "usage": {"input_tokens": 150, "output_tokens": 20, "total_tokens": 170,
                  "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}


def client_factory(handler):
    return lambda cfg: OpenAI(api_key=cfg.key, max_retries=0, timeout=cfg.timeout_seconds,
                             http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))


def setup(factory, clock, handler, cfg=None):
    adapter = ResponsesAdapter(factory, cfg or config(), clock, client_factory(handler))
    service = CRMService(factory, ContextInterpreter(adapter), clock)
    service.register(OWNER, "Europe/Moscow")
    return service, adapter


def save(service, number="1", text="Проекту нужен отдельный синтетический черновик", channel="owner"):
    return service.ingest(OWNER, channel, Incoming(external_id=number, account="synthetic-ai", text=text))


def context(factory, clock, source):
    with factory.begin() as s:
        from personal_crm.models import Profile, Source
        version = s.get(SourceVersion, source)
        return build_context(s, OWNER, s.get(Source, version.source_id), version, s.get(Profile, OWNER), clock())


def test_sdk_strict_payload_source_cache_and_drafts(factory, clock):
    requests = []
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        data = json.loads(body["input"][0]["content"])
        assert "owner_id" not in data and "account" not in data
        assert "synthetic-openai-key" not in json.dumps(body)
        assert body["store"] is False and body["truncation"] == "disabled"
        assert body["text"]["format"]["strict"] is True
        assert body["text"]["format"]["schema"]["additionalProperties"] is False
        return httpx2.Response(200, json=frame(output(data["source_version_id"])))
    service, adapter = setup(factory, clock, handler)
    source = save(service)
    result = service.process(OWNER, source)
    assert result["status"] == "created"
    assert result["task"]["draft_steps"] == ["Черновик шага"]
    assert service.process(OWNER, source) == result
    assert adapter.interpret_context(context(factory, clock, source)).title == "Синтетическое дело"
    assert len(requests) == 1
    with factory() as s:
        assert s.scalar(select(func.count(Task.id))) == 1
        reservation = s.scalar(select(AIReservation))
        assert (reservation.status, reservation.actual_micro_usd) == ("settled", 190)
    assert adapter.ledger.status(OWNER)["reserved_micro_usd"] == 0


@pytest.mark.parametrize("change,code", [
    ({"enabled": False}, "ai_disabled"), ({"key": ""}, "ai_configuration_invalid"),
    ({"allowed_models": frozenset()}, "ai_configuration_invalid"),
    ({"consent_categories": frozenset()}, "ai_consent_required"),
    ({"monthly_budget_usd": "0"}, "ai_configuration_invalid"),
    ({"prices_json": "{}"}, "ai_configuration_invalid"),
    ({"prices_json": "{bad"}, "ai_configuration_invalid"),
    ({"timeout_seconds": 30}, "ai_configuration_invalid"),
    ({"max_input_chars": 2}, "ai_configuration_invalid"),
    ({"monthly_budget_usd": ".0001"}, "ai_budget_limit"),
])
def test_missing_gate_never_constructs_sdk(factory, clock, change, code):
    def forbidden(_):
        pytest.fail("A configuration gate constructed a client")
    service, adapter = setup(factory, clock, forbidden, config(**change))
    adapter.client_factory = forbidden
    source = save(service)
    assert service.process(OWNER, source) == {"status": "error", "code": code, "source_version_id": source}
    with factory() as s:
        assert s.get(SourceVersion, source).text
        assert s.scalar(select(func.count(Task.id))) == 0


@pytest.mark.parametrize("mode,code", [("refusal", "ai_refusal"), ("incomplete", "ai_incomplete"),
    ("invalid_json", "ai_invalid_output"), ("wrong_source", "ai_invalid_output"),
    ("command", "ai_invalid_output"), ("invented_deadline", "ai_invalid_output"),
    ("wrong_date", "ai_invalid_output"), ("invented_time", "ai_invalid_output"),
    ("timeout", "ai_timeout"), ("unauthorized", "ai_auth_error")])
def test_provider_failures_preserve_source_and_do_not_retry(factory, clock, mode, code):
    calls = []
    def handler(request):
        calls.append(request)
        source = json.loads(json.loads(request.content)["input"][0]["content"])["source_version_id"]
        if mode == "timeout":
            raise httpx2.ReadTimeout("synthetic timeout", request=request)
        if mode == "unauthorized":
            return httpx2.Response(401, json={"error": {"message": "synthetic secret must never be echoed", "type": "invalid_api_key"}})
        data = output(source)
        if mode == "wrong_source": data["source_version_id"] = "foreign-source"
        if mode == "command": data.update(operation="command", target_id="foreign-task", target_version=1, change="close")
        if mode == "invented_deadline": data["deadline"] = {"precision": "date", "value": "2026-10-23", "original": "несуществующий срок", "timezone": "Europe/Moscow"}
        if mode == "wrong_date": data["deadline"] = {"precision": "date", "value": "2026-10-24", "original": "2026-10-23", "timezone": "Europe/Moscow"}
        if mode == "invented_time": data["reminder_at"] = "2026-10-23T16:00:00Z"
        return httpx2.Response(200, json=frame(data, status="incomplete" if mode == "incomplete" else "completed",
            refusal=mode == "refusal", raw="{invalid" if mode == "invalid_json" else None))
    service, adapter = setup(factory, clock, handler)
    source = save(service, text="Синтетический проект требует проверки 2026-10-23")
    assert service.process(OWNER, source)["code"] == code
    assert service.process(OWNER, source)["code"] == "ai_previous_attempt"
    assert len(calls) == 1
    with factory() as s:
        assert s.get(SourceVersion, source).text
        assert s.scalar(select(func.count(Task.id))) == 0
        reservation = s.scalar(select(AIReservation))
        if mode == "unauthorized":
            assert reservation.actual_micro_usd == 0
        elif mode in ("timeout", "invalid_json"):
            assert reservation.actual_micro_usd == 21024
    assert adapter.ledger.status(OWNER)["reserved_micro_usd"] == 0


def test_concurrent_requests_cannot_overspend(factory, clock):
    entered, release = Event(), Event()
    calls = []
    def handler(request):
        calls.append(request)
        entered.set()
        assert release.wait(5)
        source = json.loads(json.loads(request.content)["input"][0]["content"])["source_version_id"]
        return httpx2.Response(200, json=frame(output(source)))
    service, adapter = setup(factory, clock, handler, config(monthly_budget_usd=".021024"))
    first, second = save(service, "1"), save(service, "2")
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(service.process, OWNER, first)
        assert entered.wait(5)
        try:
            assert service.process(OWNER, second)["code"] == "ai_budget_limit"
            status = adapter.ledger.status(OWNER)
            assert status["reserved_micro_usd"] == 21024 and status["blocked"] and status["warning_80"]
        finally:
            release.set()
        assert future.result()["status"] == "created"
    assert len(calls) == 1


def test_80_100_thresholds_and_utc_month(factory, clock):
    service, _ = setup(factory, clock, lambda _: pytest.fail("No HTTP here"))
    ledger = BudgetLedger(factory, clock)
    sources = [save(service, str(i)) for i in range(4)]
    first, _ = ledger.reserve(OWNER, sources[0], "synthetic-model", 1000, 799)
    assert not ledger.status(OWNER)["warning_80"]
    ledger.settle(first, 799)
    second, _ = ledger.reserve(OWNER, sources[1], "synthetic-model", 1000, 1)
    assert ledger.status(OWNER)["warning_80"]
    ledger.settle(second, 1)
    third, _ = ledger.reserve(OWNER, sources[2], "synthetic-model", 1000, 200)
    assert ledger.status(OWNER)["blocked"]
    with pytest.raises(AIError, match="ai_budget_limit"):
        ledger.reserve(OWNER, sources[3], "synthetic-model", 1000, 1)
    ledger.settle(third)  # unknown usage retains the full ceiling
    clock.now = datetime(2026, 11, 1, tzinfo=UTC)
    assert ledger.status(OWNER)["spent_micro_usd"] == 0
    ledger.reserve(OWNER, sources[3], "synthetic-model", 1000, 1)


def test_prices_expired_unknown_and_nonfinite_fail_closed(clock):
    for changes in ({"valid_until": "2020-01-01T00:00:00Z"}, {"input_per_million": "NaN"},
                    {"source": "unknown"}, {"input_token_ceiling": True}, {"currency": "EUR"}):
        cfg = config()
        prices = json.loads(cfg.prices_json)
        prices[cfg.model].update(changes)
        with pytest.raises(AIError, match="ai_configuration_invalid"):
            price(replace(cfg, prices_json=json.dumps(prices)), clock())


def test_provider_schema_has_no_authority_or_arbitrary_actions():
    schema = ProviderOutput.model_json_schema()
    assert "command" not in schema["properties"]["operation"]["enum"]
    assert "owner_id" not in schema["properties"] and "authority" not in schema["properties"]
    assert set(schema["required"]) == set(schema["properties"])


def test_default_sdk_transport_bounds_body(monkeypatch):
    from personal_crm.openai_adapter import bounded_http_client
    def handler(request):
        return httpx2.Response(200, content=b"x" * 262145)
    monkeypatch.setattr(httpx2, "HTTPTransport", lambda **kwargs: httpx2.MockTransport(handler))
    with bounded_http_client(1) as client:
        with pytest.raises(httpx2.ReadTimeout):
            client.post("https://example.invalid/synthetic")


def test_sdk_error_leaves_preexisting_queue_functional(factory, clock):
    from personal_crm.adapters import FakeTransport
    from personal_crm.models import Job
    from personal_crm.worker import Worker
    def handler(request):
        raise httpx2.ReadTimeout("synthetic", request=request)
    service, _ = setup(factory, clock, handler)
    reminder = save(service, "reminder", "Завтра в 19:00 напомни обновить резюме")
    task = service.process(OWNER, reminder)["task"]
    failed = save(service, "ai")
    assert service.process(OWNER, failed)["code"] == "ai_timeout"
    clock.now = datetime(2026, 10, 14, 16, tzinfo=UTC)
    assert Worker(factory, FakeTransport(), clock, owner_id=OWNER).tick() == "sent"
    with factory() as s:
        assert s.get(Task, task["id"]).state == "active"
        assert s.scalar(select(Job).where(Job.kind == "repeat")).status == "pending"


def test_calendar_values_verified_independently_of_valid_json(clock):
    from personal_crm.context import SourceContext
    from personal_crm.openai_adapter import validate_dates
    from personal_crm.schema import Interpretation
    ctx = SourceContext(OWNER, "synthetic-source", "owner", "synthetic", "Завтра в 19:00 проверь учебный проект", clock(), None, "Europe/Moscow")
    valid = Interpretation.model_validate(output(ctx.source_version_id, reminder_at="2026-10-14T16:00:00Z"))
    validate_dates(valid, ctx)
    with pytest.raises(AIError):
        validate_dates(valid.model_copy(update={"reminder_at": datetime(2026, 10, 15, 16, tzinfo=UTC)}), ctx)
    ctx.timezone = None
    with pytest.raises(AIError):
        validate_dates(valid, ctx)


def test_new_model_plan_requires_bound_confirmation_and_preserves_drafts(factory, clock):
    def handler(request):
        source = json.loads(json.loads(request.content)["input"][0]["content"])["source_version_id"]
        return httpx2.Response(200, json=frame(output(source, planned_on="2026-10-23")))
    service, _ = setup(factory, clock, handler)
    source = save(service, text="Синтетический проект требует проверки 2026-10-23")
    assert service.process(OWNER, source)["status"] == "proposal"
    with factory() as s:
        assert s.scalar(select(func.count(Task.id))) == 0
    answer = save(service, "answer", "Да")
    accepted = service.process(OWNER, answer)
    assert accepted["status"] == "accepted" and accepted["task"]["planned_on"] == "2026-10-23"
    assert accepted["task"]["deadline"] is None
    assert accepted["task"]["draft_steps"] == ["Черновик шага"]
