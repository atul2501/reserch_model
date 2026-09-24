"""Ollama response boundary: safe parse -> deterministic normalisation -> STRICT Pydantic -> council.

Regression for the production error `AnalystResponse.invalidators: List should have at most 10 items (got 11)`:
an over-limit, otherwise valid response used to cost the council an analyst (and, at scale, the quorum). Now the
bounded list is normalised under a documented policy and the repair is audited; anything not safely repairable is an
invalid analyst response that is excluded from quorum and can never authorise a trade."""
from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core import metrics
from app.models.council import CouncilAnalysis, CouncilDecision
from app.models.enums import Bias
from app.schemas.council import ANALYST_NAMES, AnalystResponse, JudgeResponse
from app.schemas.normalization import (
    BoundedResponse, ResponseNormalizationError, normalize_payload, parse_model_json,
)
from app.services.ollama_client import OllamaClient, OllamaKeyHealth, OllamaResponseError
from tests.test_council_failclosed import _run, council_on  # noqa: F401  (fixture)


def payload(**over):
    base = {"analyst": "trend", "bias": "LONG", "confidence": 0.7, "reasoning": "ok", "key_factors": ["a"], "invalidators": ["x"]}
    base.update(over)
    return base


def items(n):
    return [f"inv-{i}" for i in range(n)]


def norm(p, model=AnalystResponse):
    return normalize_payload(model, p)


# --- the schema itself stays strict ---------------------------------------------------------------------------


def test_pydantic_constraint_is_untouched_and_still_rejects_eleven():
    with pytest.raises(ValidationError):
        AnalystResponse(**payload(invalidators=items(11)))
    with pytest.raises(ValidationError):
        JudgeResponse(decision="LONG", confidence=0.5, reasoning="r", key_risks=items(11))
    assert AnalystResponse.model_fields["invalidators"].metadata[0].max_length == 10


def test_every_bounded_list_of_the_council_schemas_declares_its_ordering():
    for model in (AnalystResponse, JudgeResponse):
        bounded = {n for n, f in model.model_fields.items()
                   if any(getattr(m, "max_length", None) for m in f.metadata) and "list" in str(f.annotation)}
        assert bounded and bounded <= model.ordered_lists, (model.__name__, bounded - model.ordered_lists)


# --- cardinality -----------------------------------------------------------------------------------------------


def test_ten_invalidators_is_valid_and_untouched():
    out, rep = norm(payload(invalidators=items(10)))
    assert out["invalidators"] == items(10) and not rep.changed
    assert AnalystResponse.model_validate(out).invalidators == items(10)


def test_eleven_invalidators_keep_the_first_ten_and_record_the_truncation():
    out, rep = norm(payload(invalidators=items(11)))
    assert out["invalidators"] == items(10)                       # deterministic: the FIRST ten (ordered most-important-first)
    assert rep.truncations == [{"field": "invalidators", "original_count": 11, "accepted_count": 10,
                                "policy": "keep_first_n_ordered_most_important_first"}]
    assert rep.as_dict()["schema_truncated"] is True
    assert len(AnalystResponse.model_validate(out).invalidators) == 10


def test_one_hundred_invalidators_are_deterministic():
    a, _ = norm(payload(invalidators=items(100)))
    b, rep = norm(payload(invalidators=items(100)))
    assert a == b and a["invalidators"] == items(10) and rep.truncations[0]["original_count"] == 100


def test_blank_null_and_duplicate_items_are_removed_before_counting_so_they_never_displace_real_ones():
    raw = ["  a ", "A", "", "   ", None, "b"] + items(8)         # 4 noise/dup entries -> exactly 10 real
    out, rep = norm(payload(invalidators=raw))
    assert out["invalidators"] == ["a", "b"] + items(8) and rep.truncations == []
    assert rep.dropped_items["invalidators"] == 4 and rep.changed


def test_key_factors_and_judge_lists_are_bounded_consistently():
    out, rep = norm(payload(key_factors=items(25), invalidators=items(12)))
    assert len(out["key_factors"]) == len(out["invalidators"]) == 10
    assert {t["field"] for t in rep.truncations} == {"key_factors", "invalidators"}
    j, jr = norm({"decision": "long", "confidence": 0.5, "reasoning": "r", "key_risks": items(11), "invalidators": items(40)}, JudgeResponse)
    assert JudgeResponse.model_validate(j).decision == Bias.LONG and {t["field"] for t in jr.truncations} == {"key_risks", "invalidators"}


def test_over_long_reasoning_is_truncated_and_recorded():
    out, rep = norm(payload(reasoning="x" * 5000))
    assert len(out["reasoning"]) == 2048 and rep.truncations[0]["field"] == "reasoning"


def test_a_bounded_list_with_no_defined_ordering_is_rejected_not_guessed():
    from typing import Annotated

    from pydantic import Field

    class Unordered(BoundedResponse):
        tags: Annotated[list[str], Field(max_length=3)] = []

    assert normalize_payload(Unordered, {"tags": ["a", "b", "c"]})[0] == {"tags": ["a", "b", "c"]}
    with pytest.raises(ResponseNormalizationError) as e:
        normalize_payload(Unordered, {"tags": ["a", "b", "c", "d"]})
    assert e.value.reason == "over_limit_unordered:tags"


# --- missing / null / wrong types ------------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["invalidators", "key_factors"])
def test_missing_or_null_optional_list_becomes_empty_and_is_recorded(field):
    p = payload()
    del p[field]
    out, rep = norm(p)
    assert out[field] == [] and field in rep.defaulted_fields
    out, rep = norm(payload(**{field: None}))
    assert out[field] == [] and field in rep.defaulted_fields
    AnalystResponse.model_validate(out)


def test_empty_list_is_valid():
    out, rep = norm(payload(invalidators=[]))
    assert out["invalidators"] == [] and not rep.changed


@pytest.mark.parametrize("bad", ["one invalidator", {"a": 1}, 7, True])
def test_invalidators_of_the_wrong_type_are_rejected(bad):
    with pytest.raises(ResponseNormalizationError) as e:
        norm(payload(invalidators=bad))
    assert e.value.reason == "wrong_type:invalidators"


@pytest.mark.parametrize("item", [1, {"k": "v"}, ["nested"], 1.5])
def test_non_string_list_items_are_rejected(item):
    with pytest.raises(ResponseNormalizationError, match="wrong_item_type"):
        norm(payload(invalidators=["ok", item]))


@pytest.mark.parametrize("field", ["analyst", "bias", "confidence", "reasoning"])
def test_missing_or_null_required_fields_are_rejected(field):
    p = payload()
    del p[field]
    with pytest.raises(ResponseNormalizationError, match=f"missing_required:{field}"):
        norm(p)
    with pytest.raises(ResponseNormalizationError, match=f"missing_required:{field}"):
        norm(payload(**{field: None}))


def test_invalid_enum_wrong_scalar_types_and_out_of_range_are_never_guessed():
    for p in (payload(bias="BUY"), payload(bias="MOON"), payload(bias=1), payload(confidence=1.5), payload(confidence="high"),
              payload(reasoning=""), payload(analyst="oracle")):
        out, _ = norm(p)
        with pytest.raises(ValidationError):
            AnalystResponse.model_validate(out)
    for p in (payload(confidence=True), payload(confidence=float("nan")), payload(reasoning=5), payload(reasoning=["x"])):
        with pytest.raises(ResponseNormalizationError):
            norm(p)


def test_enum_case_and_whitespace_are_folded_only_to_a_real_member():
    out, _ = norm(payload(bias=" short "))
    assert AnalystResponse.model_validate(out).bias == Bias.SHORT


def test_unexpected_extra_fields_are_dropped_recorded_and_never_read():
    out, rep = norm(payload(trade_allowed=True, final_bias="LONG", size_modifier=9))
    assert set(out) == set(AnalystResponse.model_fields)
    assert rep.dropped_fields == ["final_bias", "size_modifier", "trade_allowed"]
    assert not hasattr(AnalystResponse.model_validate(out), "trade_allowed")


@pytest.mark.parametrize("top", [[payload()], "text", 3, None, True])
def test_non_object_top_level_is_rejected(top):
    with pytest.raises(ResponseNormalizationError, match="not_an_object"):
        norm(top)


# --- safe parsing ----------------------------------------------------------------------------------------------


def test_markdown_wrapped_and_prose_wrapped_json_is_extracted():
    body = json.dumps(payload())
    for text, method in ((body, "json"), (f"```json\n{body}\n```", "markdown_fence"), (f"```\n{body}\n```", "markdown_fence"),
                         (f"Sure! Here is my analysis:\n{body}\nHope it helps", "embedded_object")):
        value, how = parse_model_json(text)
        assert value == payload() and how == method


@pytest.mark.parametrize("text", ["", "   ", "not json", "{'a': 1}", '{"a": ', "```json\n{oops}\n```", '{"confidence": NaN}',
                                  '{"confidence": Infinity}'])
def test_malformed_json_is_rejected(text):
    with pytest.raises(ResponseNormalizationError) as e:
        parse_model_json(text)
    assert e.value.reason == "malformed_json"


# --- through the real OllamaClient ------------------------------------------------------------------------------


def client_for(handler):
    c = OllamaClient()
    c._api_keys = ["k"]
    c._key_health = [OllamaKeyHealth()]
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://fake")
    c._backoff_min, c._backoff_max = 0.0, 0.01
    return c


def respond(content):
    return lambda req: httpx.Response(200, json={"message": {"content": content if isinstance(content, str) else json.dumps(content)}})


async def gen(c, model=AnalystResponse):
    return await c.generate_structured(system_prompt="You are the trend analyst", user_prompt="u", response_model=model)


async def test_client_normalises_eleven_invalidators_and_audits_it():
    metrics.reset()
    resp, stats = await gen(client_for(respond(payload(invalidators=items(11)))))
    assert resp.invalidators == items(10)
    assert stats.normalization["schema_truncated"] is True
    assert stats.normalization["truncations"][0] == {"field": "invalidators", "original_count": 11, "accepted_count": 10,
                                                     "policy": "keep_first_n_ordered_most_important_first"}
    assert metrics.counter_value("ollama_schema_normalized", field="invalidators") == 1


async def test_client_logs_the_truncation_audit_fields(monkeypatch):
    from app.services import ollama_client as mod

    events: list[tuple[str, dict]] = []

    class Rec:
        def __getattr__(self, level):
            return lambda event, **kw: events.append((event, kw))

    monkeypatch.setattr(mod, "logger", Rec())     # the real logger is cached on first use, so capture_logs is order-dependent
    await gen(client_for(respond(payload(invalidators=items(11)))))
    kw = next(kw for e, kw in events if e == "ollama.schema_normalized")
    assert (kw["schema_truncated"], kw["field"], kw["original_count"], kw["accepted_count"]) == (True, "invalidators", 11, 10)


async def test_client_clean_response_carries_no_normalization():
    _, stats = await gen(client_for(respond(payload())))
    assert stats.normalization is None


async def test_client_accepts_markdown_wrapped_response():
    resp, stats = await gen(client_for(respond("```json\n" + json.dumps(payload()) + "\n```")))
    assert resp.bias == Bias.LONG and stats.normalization["parse_method"] == "markdown_fence"


@pytest.mark.parametrize("content", ["{not json", "[]", json.dumps(payload(invalidators="nope")), json.dumps(payload(bias="BUY")),
                                     json.dumps(payload(confidence=3)), json.dumps({"analyst": "trend"})])
async def test_client_rejects_unsafe_responses_with_a_typed_error(content):
    with pytest.raises(OllamaResponseError):
        await gen(client_for(respond(content)))


# --- the real production cycle, council enabled ------------------------------------------------------------------


def analyst_server(build):
    """Mock Ollama: `build(analyst_name) -> content (dict|str)`; the judge gets a NEUTRAL verdict."""
    def handler(req):
        system = json.loads(req.content)["messages"][0]["content"]
        name = next((n for n in ANALYST_NAMES if f"the {n} analyst" in system), None)
        content = {"decision": "NEUTRAL", "confidence": 0.5, "reasoning": "judged"} if name is None else build(name)
        return httpx.Response(200, json={"message": {"content": content if isinstance(content, str) else json.dumps(content)}})
    return handler


def long_vote(name, **over):
    return payload(analyst=name, **over)


async def test_over_limit_responses_no_longer_cost_the_council_its_analysts_and_are_audited(db_session, council_on):
    outcomes, orders, _ = await _run(db_session, client_for(analyst_server(lambda n: long_vote(n, invalidators=items(11)))))
    assert outcomes[0].council_status == "COMPLETE" and len(orders) == 3       # all 8 valid => agents trade
    rows = (await db_session.execute(select(CouncilAnalysis))).scalars().all()
    assert len(rows) == 8 and all(r.was_valid and len(r.invalidators) == 10 for r in rows)
    assert all(r.raw_response["normalization"]["truncations"][0]["original_count"] == 11 for r in rows)


async def test_one_hundred_invalidators_through_the_cycle_is_deterministic(db_session, council_on):
    _, orders, _ = await _run(db_session, client_for(analyst_server(lambda n: long_vote(n, invalidators=items(100)))))
    rows = (await db_session.execute(select(CouncilAnalysis))).scalars().all()
    assert len(orders) == 3 and all(r.invalidators == items(10) for r in rows)


async def test_a_wrong_type_analyst_is_excluded_from_quorum_but_a_healthy_quorum_still_trades(db_session, council_on):
    bad = {"risk", "contrarian"}       # 6/8 = the configured minimum
    _, orders, _ = await _run(db_session, client_for(analyst_server(
        lambda n: long_vote(n, invalidators="a string, not a list") if n in bad else long_vote(n))))
    dec = (await db_session.execute(select(CouncilDecision))).scalars().one()
    assert dec.successful_analysts == 6 and set(dec.failed_analysts) == bad and dec.quorum_met and dec.trade_allowed
    assert all("schema validation" in dec.failure_reasons[n] for n in bad)
    rows = {r.analyst: r for r in (await db_session.execute(select(CouncilAnalysis))).scalars().all()}
    assert all(not rows[n].was_valid and "validation_failure" in rows[n].raw_response for n in bad)
    assert len(orders) == 3


async def test_too_many_invalid_analysts_breaks_quorum_and_blocks_every_entry(db_session, council_on):
    bad = {"risk", "contrarian", "trend"}
    outcomes, orders, _ = await _run(db_session, client_for(analyst_server(
        lambda n: long_vote(n, invalidators={"x": 1}) if n in bad else long_vote(n))))
    assert outcomes[0].status == "COMPLETED" and outcomes[0].council_status == "INCOMPLETE" and orders == []


@pytest.mark.parametrize("build", [
    lambda n: "this is not json at all",
    lambda n: json.dumps([long_vote(n)]),
    lambda n: long_vote(n, invalidators=None, bias="BUY"),
    lambda n: long_vote(n, confidence=42),
    lambda n: {k: v for k, v in long_vote(n).items() if k != "bias"},
])
async def test_validation_failure_never_produces_a_trade(db_session, council_on, build):
    outcomes, orders, _ = await _run(db_session, client_for(analyst_server(build)))
    assert outcomes[0].status == "COMPLETED" and outcomes[0].council_status == "INCOMPLETE"
    assert orders == []
    dec = (await db_session.execute(select(CouncilDecision))).scalars().one()
    assert dec.trade_allowed is False and dec.final_bias == "NEUTRAL" and dec.successful_analysts == 0


async def test_a_model_cannot_authorise_a_trade_by_smuggling_extra_fields(db_session, council_on):
    """A confident SHORT council vetoes the long-only agents. Analysts that also smuggle `trade_allowed: true` /
    `final_bias: LONG` / `size_modifier` must not change that: the keys are dropped and audited, never read."""
    _, orders, _ = await _run(db_session, client_for(analyst_server(
        lambda n: payload(analyst=n, bias="SHORT", confidence=0.95, trade_allowed=True, final_bias="LONG", size_modifier=5))))
    assert orders == []
    dec = (await db_session.execute(select(CouncilDecision))).scalars().one()
    assert dec.final_bias == "SHORT"
    rows = (await db_session.execute(select(CouncilAnalysis))).scalars().all()
    assert all(r.raw_response["normalization"]["dropped_fields"] == ["final_bias", "size_modifier", "trade_allowed"] for r in rows)


async def test_an_analyst_answering_as_someone_else_is_rejected(db_session, council_on):
    await _run(db_session, client_for(analyst_server(lambda n: payload(analyst="risk" if n == "trend" else n))))
    dec = (await db_session.execute(select(CouncilDecision))).scalars().one()
    assert "trend" in dec.failed_analysts and dec.successful_analysts == 7
