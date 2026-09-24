"""Model-response boundary: safe JSON extraction + deterministic schema normalisation.

    model text -> parse_model_json -> normalize_payload -> Pydantic model_validate (UNCHANGED, strict) -> caller

The Pydantic schemas stay strict. This module only repairs *cardinality/shape noise that carries no trading
meaning* (an 11th "invalidator", a ```json fence, a stray extra key) under an explicit, documented policy, and
records every repair. Anything it cannot repair safely raises `ResponseNormalizationError`; the caller then marks
the response invalid (excluded from quorum) and the council's existing fail-closed logic decides. Nothing here can
ever produce or authorise a trade: the only fields a downstream consumer reads are the schema's own, and
unexpected keys are dropped, never interpreted.

Normalisation policy (deterministic, no randomness, no model-supplied priorities):
  * bounded list[str] fields (`max_length`) — items are stripped, `None`/blank items dropped, case-insensitive
    duplicates removed (first occurrence wins); then, if still over the limit, ONLY the first `max_length` are kept.
    That is legitimate only because the schema defines these lists as ORDERED MOST-IMPORTANT-FIRST (declared in
    `ordered_lists`, and stated in the prompts). A bounded list that is not declared ordered has no defined
    priority, so an over-limit one is REJECTED rather than truncated by a guess.
  * optional list field missing / null      -> [] (recorded)          required field missing / null -> reject
  * list field that is not a list           -> reject                  non-string list item          -> reject
  * bounded str field (`max_length`)        -> truncated (recorded); not a string -> reject
  * enum field                              -> whitespace/case folded to a member if unambiguous, else left for
                                               Pydantic to reject (no guessing: "BUY" is not "LONG")
  * bool for a numeric field                -> reject (Pydantic lax mode would read True as 1.0)
  * unexpected extra keys                   -> dropped and recorded (names only); never used
  * top-level value that is not an object   -> reject
"""
from __future__ import annotations

import enum
import json
import math
import re
import typing
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel

MAX_DROPPED_NAMES_LOGGED = 20
_FENCE = re.compile(r"```[ \t]*(?:json|JSON)?[ \t]*\r?\n?(.*?)```", re.DOTALL)


class ResponseNormalizationError(ValueError):
    """The response cannot be safely normalised. `reason` is a short machine-readable code (never model content)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class BoundedResponse(BaseModel):
    """Base for model-facing response schemas that opt in to boundary normalisation."""

    # Bounded list fields whose order is defined as meaningful (most important first) — the only lists that may be
    # truncated to their limit. Every bounded list field of a subclass must be listed here or over-limit input is rejected.
    ordered_lists: ClassVar[frozenset[str]] = frozenset()


@dataclass
class NormalizationReport:
    parse_method: str = "json"                                  # json | markdown_fence | embedded_object
    truncations: list[dict[str, Any]] = field(default_factory=list)   # {field, original_count, accepted_count, policy}
    dropped_fields: list[str] = field(default_factory=list)
    defaulted_fields: list[str] = field(default_factory=list)
    dropped_items: dict[str, int] = field(default_factory=dict)       # blanks / nulls / duplicates removed per field

    @property
    def changed(self) -> bool:
        return bool(self.truncations or self.dropped_fields or self.defaulted_fields or self.dropped_items
                    or self.parse_method != "json")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_truncated": bool(self.truncations),
            "parse_method": self.parse_method,
            "truncations": list(self.truncations),
            "dropped_fields": self.dropped_fields[:MAX_DROPPED_NAMES_LOGGED],
            "defaulted_fields": list(self.defaulted_fields),
            "dropped_items": dict(self.dropped_items),
        }


# --- safe parsing --------------------------------------------------------------------------------------------


def _reject_constant(name: str):
    raise ValueError(f"non-finite JSON constant {name}")


def _loads(text: str) -> Any:
    return json.loads(text, parse_constant=_reject_constant)


def parse_model_json(content: str) -> tuple[Any, str]:
    """Extract one JSON value from model text. Order: the text itself, then the first markdown code fence, then the
    first embedded JSON object after leading prose. Raises ResponseNormalizationError('malformed_json')."""
    text = content.strip().lstrip("﻿")
    try:
        return _loads(text), "json"
    except ValueError:
        pass
    m = _FENCE.search(text)
    if m:
        try:
            return _loads(m.group(1).strip()), "markdown_fence"
        except ValueError:
            pass
    start = text.find("{")
    if start != -1:
        try:
            value, _end = json.JSONDecoder(parse_constant=_reject_constant).raw_decode(text[start:])
            return value, "embedded_object"
        except ValueError:
            pass
    raise ResponseNormalizationError("malformed_json")


# --- normalisation -------------------------------------------------------------------------------------------


def _max_length(field_info) -> int | None:
    for meta in field_info.metadata:
        n = getattr(meta, "max_length", None)
        if n is not None:
            return int(n)
    return None


def _normalize_list(name: str, value: Any, limit: int | None, ordered: bool, report: NormalizationReport) -> list[str]:
    if not isinstance(value, list):
        raise ResponseNormalizationError(f"wrong_type:{name}")
    items: list[str] = []
    seen: set[str] = set()
    removed = 0
    for item in value:
        if item is None:
            removed += 1
            continue
        if not isinstance(item, str):
            raise ResponseNormalizationError(f"wrong_item_type:{name}")
        s = item.strip()
        key = s.casefold()
        if not s or key in seen:
            removed += 1
            continue
        seen.add(key)
        items.append(s)
    if removed:
        report.dropped_items[name] = removed
    if limit is not None and len(items) > limit:
        if not ordered:
            raise ResponseNormalizationError(f"over_limit_unordered:{name}")
        report.truncations.append({"field": name, "original_count": len(value), "accepted_count": limit,
                                   "policy": "keep_first_n_ordered_most_important_first"})
        items = items[:limit]
    return items


def normalize_payload(model: type[BaseModel], payload: Any) -> tuple[dict[str, Any], NormalizationReport]:
    """Return (payload safe to hand to `model.model_validate`, audit report). Raises ResponseNormalizationError."""
    report = NormalizationReport()
    if not isinstance(payload, dict):
        raise ResponseNormalizationError("not_an_object")
    ordered_lists: frozenset[str] = getattr(model, "ordered_lists", frozenset())
    out: dict[str, Any] = {}

    for name, info in model.model_fields.items():
        annotation = info.annotation
        is_list = typing.get_origin(annotation) is list
        present = name in payload and payload[name] is not None
        if not present:
            if info.is_required():
                raise ResponseNormalizationError(f"missing_required:{name}")
            if is_list:                       # optional annotation list: absent/null == empty, recorded
                report.defaulted_fields.append(name)
                out[name] = []
            continue
        value = payload[name]
        if is_list:
            out[name] = _normalize_list(name, value, _max_length(info), name in ordered_lists, report)
        elif annotation is str:
            if not isinstance(value, str):
                raise ResponseNormalizationError(f"wrong_type:{name}")
            value = value.strip()
            limit = _max_length(info)
            if limit is not None and len(value) > limit:
                report.truncations.append({"field": name, "original_count": len(value), "accepted_count": limit,
                                           "policy": "truncate_text"})
                value = value[:limit]
            out[name] = value
        elif annotation is float or annotation is int:
            if isinstance(value, bool):
                raise ResponseNormalizationError(f"wrong_type:{name}")
            if isinstance(value, float) and not math.isfinite(value):
                raise ResponseNormalizationError(f"non_finite:{name}")
            out[name] = value
        elif isinstance(annotation, type) and issubclass(annotation, enum.Enum):
            if isinstance(value, str):
                folded = value.strip().upper()
                members = {str(m.value).upper(): m.value for m in annotation}
                out[name] = members.get(folded, value)
            else:
                out[name] = value            # wrong type: Pydantic rejects it
        else:
            out[name] = value

    extras = [k for k in payload if k not in model.model_fields]
    if extras:
        report.dropped_fields = sorted(str(k) for k in extras)
    return out, report
