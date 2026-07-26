from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from codex_profile.reporting import (
    CUMULATIVE_USAGE_KEYS,
    DIRECT_INCREMENTAL_USAGE_KEYS,
    INCREMENTAL_USAGE_KEYS,
    TOKEN_FIELD_NAMES,
    TokenObservation,
    TokenUsage,
    choose_cumulative_observation,
    integer_value,
    parse_event,
    walk,
)
from codex_profile.sources.rollout import RolloutRecord


ADAPTER_ID = "rollout-usage-adapter"
LEGACY_ADAPTER_VERSION = "0.1.0"
LEGACY_ADAPTER_DIGEST = "sha256:" + hashlib.sha256(
    f"{ADAPTER_ID}:{LEGACY_ADAPTER_VERSION}".encode("utf-8")
).hexdigest()
ADAPTER_VERSION = "0.2.0"
ADAPTER_DIGEST = "sha256:" + hashlib.sha256(f"{ADAPTER_ID}:{ADAPTER_VERSION}".encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class UsageFields:
    reported_input_tokens: int
    cached_input_tokens: int
    fresh_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int

    @classmethod
    def from_usage(cls, usage: TokenUsage) -> "UsageFields":
        normalized = usage.normalized()
        fresh = normalized.input - normalized.cached_input
        return cls(
            reported_input_tokens=normalized.input,
            cached_input_tokens=normalized.cached_input,
            fresh_input_tokens=fresh,
            output_tokens=normalized.output,
            reasoning_output_tokens=normalized.reasoning,
            total_tokens=normalized.total,
        )


@dataclass(frozen=True)
class RawRolloutAdmission:
    record: RolloutRecord
    event_timestamp: datetime | None
    event_kind: str
    schema_name: str | None
    schema_version: str | None
    token_observation_mode: str | None
    token_fields: UsageFields | None
    cumulative_fields: UsageFields | None


@dataclass(frozen=True)
class NormalizedUsageAdmission:
    record: RolloutRecord
    event_timestamp: datetime
    event_kind: str
    method: str
    fields: UsageFields


@dataclass(frozen=True)
class UsageDiagnostic:
    record: RolloutRecord
    code: str
    message: str
    strict: bool = True
    scope: str = "record"


@dataclass
class UsageState:
    previous_cumulative: TokenUsage | None = None
    session_started: bool = False


@dataclass(frozen=True)
class AdaptedRolloutRecord:
    raw: RawRolloutAdmission
    normalized: NormalizedUsageAdmission | None
    diagnostics: tuple[UsageDiagnostic, ...]
    state: UsageState


def _schema_metadata(obj: object) -> tuple[str | None, str | None]:
    if not isinstance(obj, dict):
        return None, None
    schema = obj.get("schema")
    if isinstance(schema, str) and "." in schema:
        name, version = schema.rsplit(".", 1)
        return name, version
    if isinstance(schema, str):
        return schema, None
    version = obj.get("version") or obj.get("schema_version")
    return None, str(version) if version is not None else None


def _invalid_arithmetic(fields: UsageFields) -> str | None:
    if fields.cached_input_tokens > fields.reported_input_tokens:
        return "cached input exceeds reported input"
    if fields.fresh_input_tokens != fields.reported_input_tokens - fields.cached_input_tokens:
        return "fresh input does not equal reported input minus cached input"
    if fields.total_tokens != fields.reported_input_tokens + fields.output_tokens:
        return "total tokens do not equal reported input plus output"
    return None


def _fields(observation: TokenObservation | None) -> UsageFields | None:
    if observation is None:
        return None
    return UsageFields.from_usage(observation.usage)


def _invalid_raw_token_value(value: Any) -> bool:
    return integer_value(value) is None


def _usage_surface(key: str, event_kind: str) -> str | None:
    lowered = key.lower()
    if lowered in INCREMENTAL_USAGE_KEYS:
        return "incremental"
    if lowered in CUMULATIVE_USAGE_KEYS:
        return "cumulative"
    if lowered in DIRECT_INCREMENTAL_USAGE_KEYS:
        kind_lower = event_kind.lower()
        if any(marker in kind_lower for marker in ("completed", "token_count", "usage")):
            return "incremental"
    return None


def _invalid_usage_value_diagnostics(
    record: RolloutRecord,
    event_kind: str,
) -> tuple[list[UsageDiagnostic], set[str]]:
    diagnostics: list[UsageDiagnostic] = []
    invalid_surfaces: set[str] = set()
    if record.obj is None:
        return diagnostics, invalid_surfaces

    for path, key, value in walk(record.obj):
        if not isinstance(value, Mapping):
            continue
        surface = _usage_surface(key, event_kind)
        if surface is None:
            continue
        lowered = {str(field).lower(): raw for field, raw in value.items()}
        if not TOKEN_FIELD_NAMES.intersection(lowered):
            continue
        usage_path = ".".join(path)
        for field, raw_value in lowered.items():
            if field in TOKEN_FIELD_NAMES and _invalid_raw_token_value(raw_value):
                invalid_surfaces.add(surface)
                diagnostics.append(
                    UsageDiagnostic(
                        record,
                        "usage.invalid-accounting",
                        f"invalid token value for {field}",
                        scope=f"{surface}:{usage_path}:{field}",
                    )
                )

        input_details = lowered.get("input_tokens_details")
        if isinstance(input_details, Mapping) and "cached_tokens" in {str(k).lower() for k in input_details}:
            raw_cached = {str(k).lower(): v for k, v in input_details.items()}["cached_tokens"]
            if _invalid_raw_token_value(raw_cached):
                invalid_surfaces.add(surface)
                diagnostics.append(
                    UsageDiagnostic(
                        record,
                        "usage.invalid-accounting",
                        "invalid token value for input_tokens_details.cached_tokens",
                        scope=f"{surface}:{usage_path}:input_tokens_details.cached_tokens",
                    )
                )

        output_details = lowered.get("output_tokens_details")
        if isinstance(output_details, Mapping) and "reasoning_tokens" in {str(k).lower() for k in output_details}:
            raw_reasoning = {str(k).lower(): v for k, v in output_details.items()}["reasoning_tokens"]
            if _invalid_raw_token_value(raw_reasoning):
                invalid_surfaces.add(surface)
                diagnostics.append(
                    UsageDiagnostic(
                        record,
                        "usage.invalid-accounting",
                        "invalid token value for output_tokens_details.reasoning_tokens",
                        scope=f"{surface}:{usage_path}:output_tokens_details.reasoning_tokens",
                    )
                )

    return diagnostics, invalid_surfaces


def adapt_rollout_record(record: RolloutRecord, state: UsageState | None = None) -> AdaptedRolloutRecord:
    current_state = UsageState(
        previous_cumulative=None if state is None else state.previous_cumulative,
        session_started=False if state is None else state.session_started,
    )
    diagnostics: list[UsageDiagnostic] = []

    if record.json_error is not None or record.obj is None:
        diagnostics.append(UsageDiagnostic(record, "rollout.invalid-json", record.json_error or "invalid json"))
        raw = RawRolloutAdmission(
            record=record,
            event_timestamp=None,
            event_kind="unknown",
            schema_name=None,
            schema_version=None,
            token_observation_mode=None,
            token_fields=None,
            cumulative_fields=None,
        )
        return AdaptedRolloutRecord(raw, None, tuple(diagnostics), current_state)

    if not isinstance(record.obj, dict):
        diagnostics.append(UsageDiagnostic(record, "rollout.unknown-shape", "top-level JSONL value is not an object"))

    raw_text = record.raw.decode("utf-8", errors="replace")
    event = parse_event(Path(record.path), 0, raw_text, timezone.utc)
    schema_name, schema_version = _schema_metadata(record.obj)
    observation = event.token_observation
    cumulative = choose_cumulative_observation(event)
    value_diagnostics, invalid_surfaces = _invalid_usage_value_diagnostics(record, event.event_kind)
    diagnostics.extend(value_diagnostics)
    token_fields = _fields(observation)
    cumulative_fields = _fields(cumulative)
    if observation is not None and observation.mode in invalid_surfaces:
        token_fields = None
    if "cumulative" in invalid_surfaces:
        cumulative_fields = None

    if event.timestamp is None:
        diagnostics.append(UsageDiagnostic(record, "rollout.missing-event-timestamp", "record has no parseable event timestamp"))

    kind_lower = event.event_kind.lower()
    if event.timestamp is not None and any(marker in kind_lower for marker in ("session_meta", "session_start")):
        current_state.session_started = True

    raw = RawRolloutAdmission(
        record=record,
        event_timestamp=event.timestamp,
        event_kind=event.event_kind,
        schema_name=schema_name,
        schema_version=schema_version,
        token_observation_mode=None if observation is None else observation.mode,
        token_fields=token_fields,
        cumulative_fields=cumulative_fields,
    )

    normalized: NormalizedUsageAdmission | None = None
    cumulative_delta: TokenUsage | None = None
    cumulative_reset = False
    if cumulative is not None and current_state.previous_cumulative is not None:
        cumulative_delta = cumulative.usage.delta_from(current_state.previous_cumulative)
        cumulative_reset = cumulative_delta is None

    if observation is not None and token_fields is not None:
        reason = _invalid_arithmetic(token_fields)
        if reason is not None:
            scope = f"{observation.mode}:{observation.source}"
            diagnostics.append(UsageDiagnostic(record, "usage.invalid-accounting", reason, scope=scope))
    if cumulative_fields is not None:
        reason = _invalid_arithmetic(cumulative_fields)
        if reason is not None:
            diagnostics.append(UsageDiagnostic(record, "usage.invalid-accounting", reason, scope=f"cumulative:{cumulative.source if cumulative else 'unknown'}"))

    has_invalid_arithmetic = any(item.code == "usage.invalid-accounting" for item in diagnostics)
    if event.timestamp is not None and observation is not None and not has_invalid_arithmetic:
        increment: TokenUsage | None = None
        method: str | None = None

        if observation.mode == "incremental":
            observed_increment = observation.usage.normalized()
            if cumulative_reset:
                diagnostics.append(UsageDiagnostic(record, "usage.counter-reset", "cumulative token counters decreased"))
                increment = observed_increment
                method = f"incremental_with_cumulative_reset:{observation.source}"
            elif cumulative_delta is not None and cumulative_delta.normalized() != observed_increment:
                diagnostics.append(
                    UsageDiagnostic(
                        record,
                        "usage.incremental-cumulative-discrepancy",
                        "last_token_usage does not match cumulative delta",
                    )
                )
            elif (
                cumulative is not None
                and current_state.previous_cumulative is None
                and current_state.session_started
                and cumulative.usage.normalized() != observed_increment
            ):
                diagnostics.append(
                    UsageDiagnostic(
                        record,
                        "usage.incremental-cumulative-discrepancy",
                        "first cumulative snapshot does not match incremental usage",
                    )
                )
            else:
                increment = observed_increment
                validation = "validated" if cumulative is not None else "direct"
                method = f"incremental_{validation}:{observation.source}"
        elif observation.mode == "cumulative":
            if current_state.previous_cumulative is not None:
                increment = observation.usage.delta_from(current_state.previous_cumulative)
                if increment is None:
                    diagnostics.append(UsageDiagnostic(record, "usage.counter-reset", "cumulative token counters decreased"))
                    method = None
                else:
                    method = f"cumulative_delta:{observation.source}"
            elif current_state.session_started:
                increment = observation.usage
                method = f"cumulative_from_session_start:{observation.source}"
            else:
                diagnostics.append(
                    UsageDiagnostic(
                        record,
                        "usage.missing-baseline",
                        "cumulative token snapshot has no prior baseline",
                    )
                )

        if increment is not None and method is not None:
            fields = UsageFields.from_usage(increment)
            reason = _invalid_arithmetic(fields)
            if reason is None:
                normalized = NormalizedUsageAdmission(record, event.timestamp, event.event_kind, method, fields)
            else:
                diagnostics.append(UsageDiagnostic(record, "usage.invalid-accounting", reason, scope=f"normalized:{method}"))

    if cumulative is not None and "cumulative" not in invalid_surfaces:
        current_state.previous_cumulative = cumulative.usage
    elif observation is not None and observation.mode == "cumulative" and "cumulative" not in invalid_surfaces:
        current_state.previous_cumulative = observation.usage

    return AdaptedRolloutRecord(raw, normalized, tuple(diagnostics), current_state)


def adapt_rollout_records(
    records: Iterator[RolloutRecord],
    state: UsageState | None = None,
) -> Iterator[AdaptedRolloutRecord]:
    current = UsageState() if state is None else state
    for record in records:
        adapted = adapt_rollout_record(record, current)
        current = adapted.state
        yield adapted
