#!/usr/bin/env python3
"""
codex_corpus_profile.py

Evidence-oriented profiler for Codex JSONL session logs.

The profiler is event-first:
- files are discovery containers only; file mtime is never used as evidence
- every included row must have a parseable event timestamp
- filtering is performed on event timestamps using a half-open [since, until) window
- token usage is counted from recognized structured usage records only
- cumulative token snapshots are converted to deltas without summing snapshots
- rows that cannot be safely attributed are reported as coverage gaps

Default target:
  ~/.local/share/codex/sessions

Examples:
  # Last 48 hours, ending now (UTC boundaries are printed in the report)
  python codex_corpus_profile.py \
    --root ~/.local/share/codex \
    --hours 48 \
    --repo contract.cuemod \
    --out /tmp/codex-profile

  # Explicit Saturday-to-Saturday allowance cycle
  python codex_corpus_profile.py \
    --root ~/.local/share/codex \
    --since 2026-07-18T00:00:00-04:00 \
    --until 2026-07-25T00:00:00-04:00 \
    --repo "" \
    --out /tmp/codex-cycle

Outputs:
  <out>.md         human-readable report
  <out>.csv        per-session ledger
  <out>.daily.csv  per-day activity/token ledger
  <out>.json       machine-readable evidence manifest

Exit status:
  0  report generated
  1  no timestamped events in the requested window
  2  invalid arguments or missing root
  3  strict evidence mode rejected coverage gaps
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


TOKEN_USAGE_RE = re.compile(
    r"Token usage:\s*total=([0-9,]+)\s+input=([0-9,]+)"
    r"(?:\s+\(\+\s*([0-9,]+)\s+cached\))?"
    r"\s+output=([0-9,]+)\s+\(reasoning\s+([0-9,]+)\)"
)

UUID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)

RESUME_RE = re.compile(
    r"codex resume ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)

PATH_RE = re.compile(
    r"(?:(?:\.{1,2}|~)?/)?(?:[A-Za-z0-9_.@+-]+/)+[A-Za-z0-9_.@+-]+"
)

TOOL_KEYS = {
    "tool",
    "tool_name",
    "command",
    "cmd",
    "function",
    "recipient",
}

TIMESTAMP_KEYS = (
    "timestamp",
    "created_at",
    "createdat",
    "event_time",
    "eventtime",
    "time",
    "ts",
)

INCREMENTAL_USAGE_KEYS = (
    "last_token_usage",
    "token_usage_delta",
    "usage_delta",
    "incremental_token_usage",
)

CUMULATIVE_USAGE_KEYS = (
    "total_token_usage",
    "cumulative_token_usage",
)

DIRECT_INCREMENTAL_USAGE_KEYS = (
    "usage",
    "token_usage",
)

TOKEN_FIELD_NAMES = {
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "cached_tokens",
    "reasoning_tokens",
    "reasoning_output_tokens",
    "prompt_tokens",
    "completion_tokens",
}

MODEL_KEYS = {"model", "model_name", "model_slug"}
REPO_CONTEXT_KEYS = {
    "cwd",
    "workdir",
    "working_directory",
    "repository",
    "repo",
    "repo_root",
    "git_root",
}


@dataclass(frozen=True)
class TokenUsage:
    """Token dimensions for one attributable increment.

    cached_input and reasoning are descriptive dimensions. They are not added to
    total because they are normally subsets of input/output accounting.
    """

    total: int = 0
    input: int = 0
    cached_input: int = 0
    output: int = 0
    reasoning: int = 0

    @classmethod
    def zero(cls) -> "TokenUsage":
        return cls()

    def is_zero(self) -> bool:
        return not any((self.total, self.input, self.cached_input, self.output, self.reasoning))

    def normalized(self) -> "TokenUsage":
        total = self.total or max(0, self.input + self.output)
        return TokenUsage(
            total=max(0, total),
            input=max(0, self.input),
            cached_input=max(0, self.cached_input),
            output=max(0, self.output),
            reasoning=max(0, self.reasoning),
        )

    def plus(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            total=self.total + other.total,
            input=self.input + other.input,
            cached_input=self.cached_input + other.cached_input,
            output=self.output + other.output,
            reasoning=self.reasoning + other.reasoning,
        )

    def delta_from(self, previous: "TokenUsage") -> "TokenUsage | None":
        """Return a cumulative-snapshot delta, or None if a counter reset occurred."""

        current = self.normalized()
        prior = previous.normalized()
        dimensions = (
            (current.total, prior.total),
            (current.input, prior.input),
            (current.cached_input, prior.cached_input),
            (current.output, prior.output),
            (current.reasoning, prior.reasoning),
        )
        if any(now < before for now, before in dimensions):
            return None
        return TokenUsage(
            total=current.total - prior.total,
            input=current.input - prior.input,
            cached_input=current.cached_input - prior.cached_input,
            output=current.output - prior.output,
            reasoning=current.reasoning - prior.reasoning,
        )


@dataclass(frozen=True)
class TokenObservation:
    mode: str  # incremental | cumulative
    usage: TokenUsage
    source: str


@dataclass
class ParsedEvent:
    file: Path
    line_no: int
    raw_bytes: int
    obj: Any
    raw: str
    timestamp: datetime | None
    timestamp_source: str | None
    event_kind: str
    tools: list[str]
    paths: Counter
    models: list[str]
    repo_hints: list[str]
    token_observation: TokenObservation | None
    textual_token_report: bool


@dataclass
class SessionProfile:
    file: Path
    session_id: str | None = None

    scanned_lines: int = 0
    malformed_lines: int = 0
    timestamped_lines: int = 0
    untimestamped_lines: int = 0
    selected_lines: int = 0
    selected_bytes: int = 0

    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    selected_first_at: datetime | None = None
    selected_last_at: datetime | None = None

    event_counts: Counter = field(default_factory=Counter)
    tool_counts: Counter = field(default_factory=Counter)
    path_counts: Counter = field(default_factory=Counter)
    family_counts: Counter = field(default_factory=Counter)
    model_counts: Counter = field(default_factory=Counter)

    repo_hints: set[str] = field(default_factory=set)
    largest_rows: list[tuple[int, int, str, str]] = field(default_factory=list)

    tokens: TokenUsage = field(default_factory=TokenUsage.zero)
    token_observations: int = 0
    token_events_counted: int = 0
    token_methods: Counter = field(default_factory=Counter)
    token_missing_baseline: int = 0
    token_counter_resets: int = 0
    token_discrepancies: int = 0
    token_text_reports_ignored: int = 0

    classifications: list[str] = field(default_factory=list)

    @property
    def token_coverage_status(self) -> str:
        if self.token_observations == 0:
            return "no_structured_usage"
        if self.token_missing_baseline or self.token_counter_resets or self.token_discrepancies:
            return "partial"
        return "complete_for_recognized_usage"


@dataclass
class DailyProfile:
    day: str
    sessions: set[str] = field(default_factory=set)
    events: int = 0
    bytes_total: int = 0
    tool_calls: int = 0
    tokens: TokenUsage = field(default_factory=TokenUsage.zero)
    token_events: int = 0


@dataclass(frozen=True)
class Window:
    since: datetime
    until: datetime

    def contains(self, timestamp: datetime) -> bool:
        return self.since <= timestamp < self.until


@dataclass
class ScanDiagnostics:
    candidate_files: int = 0
    unreadable_files: int = 0
    scanned_lines: int = 0
    malformed_lines: int = 0
    timestamped_lines: int = 0
    untimestamped_lines: int = 0
    selected_lines: int = 0
    repo_filtered_sessions: int = 0


def walk(obj: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str, Any]]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_s = str(key)
            current = (*path, key_s)
            yield current, key_s, value
            yield from walk(value, current)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from walk(value, (*path, str(index)))


def parse_timezone(value: str) -> timezone | ZoneInfo:
    if value.upper() in {"UTC", "Z"}:
        return timezone.utc

    fixed = re.fullmatch(r"([+-])(\d{2}):(\d{2})", value)
    if fixed:
        sign = 1 if fixed.group(1) == "+" else -1
        delta = timedelta(hours=int(fixed.group(2)), minutes=int(fixed.group(3)))
        return timezone(sign * delta)

    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {value}") from exc


def parse_datetime_value(value: Any, naive_tz: timezone | ZoneInfo) -> datetime | None:
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        number = float(value)
        # Protect against accidentally treating small counters as Unix timestamps.
        if number < 100_000_000:
            return None
        if number > 10_000_000_000:
            number /= 1000.0
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    if re.fullmatch(r"\d{10}(?:\.\d+)?", text):
        return parse_datetime_value(float(text), naive_tz)
    if re.fullmatch(r"\d{13}", text):
        return parse_datetime_value(int(text), naive_tz)

    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        # A small set of common RFC3339-like fallbacks.
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                dt = datetime.strptime(candidate, fmt)
                break
            except ValueError:
                continue
        else:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=naive_tz)
    return dt.astimezone(timezone.utc)


def extract_timestamp(obj: Any, naive_tz: timezone | ZoneInfo) -> tuple[datetime | None, str | None]:
    if not isinstance(obj, dict):
        return None, None

    # Prefer top-level timestamp fields. Codex rollout JSONL normally uses this.
    lowered = {str(k).lower(): (str(k), v) for k, v in obj.items()}
    for key in TIMESTAMP_KEYS:
        if key in lowered:
            original, value = lowered[key]
            parsed = parse_datetime_value(value, naive_tz)
            if parsed is not None:
                return parsed, original

    # Then inspect only metadata wrappers, not arbitrary nested payload fields.
    for wrapper in ("metadata", "meta", "header"):
        value = obj.get(wrapper)
        if not isinstance(value, dict):
            continue
        nested = {str(k).lower(): (str(k), v) for k, v in value.items()}
        for key in TIMESTAMP_KEYS:
            if key in nested:
                original, raw = nested[key]
                parsed = parse_datetime_value(raw, naive_tz)
                if parsed is not None:
                    return parsed, f"{wrapper}.{original}"

    return None, None


def event_type(obj: Any) -> str:
    if not isinstance(obj, dict):
        return "unknown"

    outer = obj.get("type") or obj.get("event") or obj.get("kind")
    payload = obj.get("payload")
    inner = payload.get("type") if isinstance(payload, dict) else None

    if isinstance(inner, str) and inner:
        if isinstance(outer, str) and outer and outer != inner:
            return f"{outer}:{inner}"
        return inner
    if isinstance(outer, str) and outer:
        return outer

    for wrapper in ("msg", "message", "item"):
        nested = obj.get(wrapper)
        if isinstance(nested, dict):
            nested_type = event_type(nested)
            if nested_type != "unknown":
                return nested_type
    return "unknown"


def extract_strings(obj: Any) -> list[str]:
    strings: list[str] = []
    for _, _, value in walk(obj):
        if isinstance(value, str):
            strings.append(value)
    return strings


def extract_tools(obj: Any) -> list[str]:
    tools: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            kind = value.get("type") or value.get("kind")
            name = value.get("name")
            if (
                isinstance(kind, str)
                and any(marker in kind.lower() for marker in ("function_call", "tool_call"))
                and isinstance(name, str)
                and 1 <= len(name) <= 200
            ):
                tools.append(name)

            for key, child in value.items():
                lowered = str(key).lower()
                if lowered in TOOL_KEYS and isinstance(child, str) and 1 <= len(child) <= 200:
                    tools.append(child)
                elif lowered in {"cmd", "command"} and isinstance(child, list):
                    if child and all(isinstance(item, str) for item in child):
                        tools.append(" ".join(child[:8]))
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(obj)
    return list(dict.fromkeys(tools))


def extract_paths(strings: Iterable[str]) -> Counter:
    paths: Counter = Counter()
    for string in strings:
        for path in PATH_RE.findall(string):
            if len(path) >= 3:
                paths[path] += 1
    return paths


def extract_models(obj: Any) -> list[str]:
    models: list[str] = []
    for _, key, value in walk(obj):
        if key.lower() in MODEL_KEYS and isinstance(value, str) and 1 <= len(value) <= 120:
            models.append(value)
    return models


def extract_repo_hints(obj: Any) -> list[str]:
    hints: list[str] = []
    for _, key, value in walk(obj):
        if key.lower() in REPO_CONTEXT_KEYS and isinstance(value, str) and value:
            hints.append(value)
    return hints


def integer_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and re.fullmatch(r"[0-9,]+", value.strip()):
        return int(value.replace(",", ""))
    return None


def nested_int(mapping: Mapping[str, Any], path: Sequence[str]) -> int | None:
    current: Any = mapping
    for component in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(component)
    return integer_value(current)


def usage_from_mapping(mapping: Mapping[str, Any]) -> TokenUsage | None:
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    if not TOKEN_FIELD_NAMES.intersection(lowered):
        # Nested details alone are not sufficient to establish a usage object.
        return None

    def first(*names: str) -> int:
        for name in names:
            value = integer_value(lowered.get(name))
            if value is not None:
                return value
        return 0

    input_tokens = first("input_tokens", "prompt_tokens")
    output_tokens = first("output_tokens", "completion_tokens")
    total_tokens = first("total_tokens")
    cached = first("cached_input_tokens", "cached_tokens")
    reasoning = first("reasoning_tokens", "reasoning_output_tokens")

    input_details = lowered.get("input_tokens_details")
    if cached == 0 and isinstance(input_details, Mapping):
        cached = nested_int(input_details, ("cached_tokens",)) or 0

    output_details = lowered.get("output_tokens_details")
    if reasoning == 0 and isinstance(output_details, Mapping):
        reasoning = nested_int(output_details, ("reasoning_tokens",)) or 0

    usage = TokenUsage(
        total=total_tokens,
        input=input_tokens,
        cached_input=cached,
        output=output_tokens,
        reasoning=reasoning,
    ).normalized()
    return usage if not usage.is_zero() else None


def find_named_usage(obj: Any, keys: Sequence[str]) -> list[tuple[str, TokenUsage]]:
    matches: list[tuple[str, TokenUsage]] = []
    wanted = set(keys)
    for path, key, value in walk(obj):
        lowered = key.lower()
        if lowered not in wanted or not isinstance(value, Mapping):
            continue
        usage = usage_from_mapping(value)
        if usage is not None:
            matches.append((".".join(path), usage))
    return matches


def extract_token_observation(obj: Any, kind: str) -> TokenObservation | None:
    # One event can contain both last_token_usage and total_token_usage. Count the
    # incremental record and retain the cumulative record only as state elsewhere.
    incremental = find_named_usage(obj, INCREMENTAL_USAGE_KEYS)
    if incremental:
        source, usage = incremental[0]
        return TokenObservation("incremental", usage, source)

    cumulative = find_named_usage(obj, CUMULATIVE_USAGE_KEYS)
    if cumulative:
        source, usage = cumulative[0]
        return TokenObservation("cumulative", usage, source)

    # Some response-completion logs expose a direct usage object. Restrict this
    # fallback to event kinds that semantically indicate completion/usage.
    kind_lower = kind.lower()
    if any(marker in kind_lower for marker in ("completed", "token_count", "usage")):
        direct = find_named_usage(obj, DIRECT_INCREMENTAL_USAGE_KEYS)
        if direct:
            source, usage = direct[0]
            return TokenObservation("incremental", usage, source)

    return None


def extract_session_id(path: Path, events: Sequence[ParsedEvent]) -> str | None:
    match = UUID_RE.search(path.name)
    if match:
        return match.group(1)

    for event in events:
        match = RESUME_RE.search(event.raw)
        if match:
            return match.group(1)

        if isinstance(event.obj, dict):
            payload = event.obj.get("payload")
            candidates: list[Any] = [event.obj.get("session_id"), event.obj.get("id")]
            if isinstance(payload, dict):
                candidates.extend((payload.get("session_id"), payload.get("id")))
            for candidate in candidates:
                if isinstance(candidate, str):
                    uuid = UUID_RE.fullmatch(candidate.strip())
                    if uuid:
                        return uuid.group(1)
    return None


def family_for_path(path: str) -> str | None:
    p = path.strip()
    families = [
        ("fixtures.agent_runtime", "fixtures/agent-runtime"),
        ("fixtures.resolver", "fixtures/resolver"),
        ("contracts.agent_runtime", "contracts/agent-runtime"),
        ("contracts.agent_context_resolver", "contracts/agent-context-resolver"),
        ("contracts.repo", "contracts/repo"),
        ("contracts.vcs", "contracts/vcs"),
        ("contracts.agent_skill", "contracts/agent-skill"),
        ("generated.agent_context_resolver", "generated/agent-context-resolver"),
        ("projection.agent_skill", "projections/agent-skill"),
        ("codex.skill_hook", ".codex/skills/resolve-agent-context"),
        ("test", "test/"),
        ("github.issue", "github.com/fatb4f/contract.cuemod/issues"),
    ]
    for family, needle in families:
        if needle in p:
            return family
    return None


def classify(profile: SessionProfile) -> list[str]:
    c = profile.tool_counts
    f = profile.family_counts
    output: list[str] = []

    if c["apply_patch"] >= 20:
        output.append("patch_churn")
    if c["exec_command"] >= 50:
        output.append("exec_churn")
    if f["fixtures.agent_runtime"] >= 80:
        output.append("fixture_loop")
    if f["contracts.repo"] >= 40:
        output.append("repo_bleed")
    if f["generated.agent_context_resolver"] or f["projection.agent_skill"] or f["codex.skill_hook"]:
        output.append("generated_projection_hook_fanout")
    if c["_add_issue_comment"] or c["_update_issue"] or c["_issue_write"] or c["github_mcp.add_issue_comment"]:
        output.append("issue_workflow_overhead")
    if c["git_diff_staged"] + c["git_diff_unstaged"] + c["git_status"] >= 20:
        output.append("git_hygiene_loop")
    if f["test"] >= 30:
        output.append("validation_loop")
    if c["multi_agent_v1"]:
        output.append("multi_agent_overhead")

    return output or ["unclassified"]


def parse_event(path: Path, line_no: int, raw: str, naive_tz: timezone | ZoneInfo) -> ParsedEvent:
    malformed = False
    try:
        obj: Any = json.loads(raw)
    except json.JSONDecodeError:
        obj = {"_raw": raw}
        malformed = True

    timestamp, timestamp_source = extract_timestamp(obj, naive_tz)
    kind = event_type(obj)
    strings = extract_strings(obj)
    paths = extract_paths(strings)
    observation = extract_token_observation(obj, kind)

    event = ParsedEvent(
        file=path,
        line_no=line_no,
        raw_bytes=len(raw.encode("utf-8", errors="replace")),
        obj=obj,
        raw=raw,
        timestamp=timestamp,
        timestamp_source=timestamp_source,
        event_kind=kind,
        tools=extract_tools(obj),
        paths=paths,
        models=extract_models(obj),
        repo_hints=extract_repo_hints(obj),
        token_observation=observation,
        textual_token_report=bool(TOKEN_USAGE_RE.search(raw)),
    )
    # Attach a private marker without changing the report schema.
    setattr(event, "_malformed", malformed)
    return event


def read_events(path: Path, naive_tz: timezone | ZoneInfo) -> tuple[list[ParsedEvent], bool]:
    events: list[ParsedEvent] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, line in enumerate(handle, 1):
                raw = line.rstrip("\n")
                if raw:
                    events.append(parse_event(path, line_no, raw, naive_tz))
    except OSError:
        return [], False
    return events, True


def candidate_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix == ".jsonl" else []

    sessions_root = root / "sessions"
    base = sessions_root if sessions_root.exists() else root
    return sorted(path for path in base.rglob("*.jsonl") if path.is_file())


def session_matches_repo(path: Path, events: Sequence[ParsedEvent], repo: str) -> bool:
    if not repo:
        return True
    needle = repo.casefold()
    if needle in str(path).casefold():
        return True

    for event in events:
        if any(needle in hint.casefold() for hint in event.repo_hints):
            return True
        if any(needle in path_value.casefold() for path_value in event.paths):
            return True
        # Session metadata can store repository names in otherwise untyped strings.
        if "session_meta" in event.event_kind.lower() and needle in event.raw.casefold():
            return True
    return False


def choose_cumulative_observation(event: ParsedEvent) -> TokenObservation | None:
    """Return a cumulative snapshot even when an incremental snapshot was selected."""

    cumulative = find_named_usage(event.obj, CUMULATIVE_USAGE_KEYS)
    if not cumulative:
        return None
    source, usage = cumulative[0]
    return TokenObservation("cumulative", usage, source)


def profile_session(
    path: Path,
    events: Sequence[ParsedEvent],
    window: Window,
    report_tz: timezone | ZoneInfo,
) -> tuple[SessionProfile, list[tuple[datetime, TokenUsage, int, int]]]:
    """Profile one session and return daily contribution tuples.

    Daily tuple: (timestamp, token increment, selected event count, tool-call count).
    """

    profile = SessionProfile(file=path)
    profile.session_id = extract_session_id(path, events)
    profile.scanned_lines = len(events)
    profile.malformed_lines = sum(bool(getattr(event, "_malformed", False)) for event in events)
    profile.timestamped_lines = sum(event.timestamp is not None for event in events)
    profile.untimestamped_lines = profile.scanned_lines - profile.timestamped_lines

    timestamped = [event for event in events if event.timestamp is not None]
    timestamped.sort(key=lambda event: (event.timestamp, event.line_no))  # type: ignore[arg-type]

    if timestamped:
        profile.first_event_at = timestamped[0].timestamp
        profile.last_event_at = timestamped[-1].timestamp

    for event in events:
        profile.repo_hints.update(event.repo_hints)

    selected = [event for event in timestamped if window.contains(event.timestamp)]  # type: ignore[arg-type]
    profile.selected_lines = len(selected)
    profile.selected_bytes = sum(event.raw_bytes for event in selected)
    if selected:
        profile.selected_first_at = selected[0].timestamp
        profile.selected_last_at = selected[-1].timestamp

    # Build the descriptive selected-window profile first.
    for event in selected:
        profile.event_counts[event.event_kind] += 1
        profile.tool_counts.update(event.tools)
        profile.path_counts.update(event.paths)
        profile.model_counts.update(event.models)
        for path_value, count in event.paths.items():
            family = family_for_path(path_value)
            if family:
                profile.family_counts[family] += count
        if event.raw_bytes >= 20_000:
            timestamp = event.timestamp.astimezone(report_tz).isoformat()  # type: ignore[union-attr]
            profile.largest_rows.append((event.line_no, event.raw_bytes, event.event_kind, timestamp))
        if event.textual_token_report and event.token_observation is None:
            profile.token_text_reports_ignored += 1

    profile.largest_rows.sort(key=lambda row: row[1], reverse=True)

    # Token state is evaluated across the complete file so a pre-window cumulative
    # snapshot can establish the baseline for the first in-window delta.
    previous_cumulative: TokenUsage | None = None
    session_start_at = next(
        (
            event.timestamp
            for event in timestamped
            if any(marker in event.event_kind.lower() for marker in ("session_meta", "session_start"))
        ),
        None,
    )
    token_increment_by_line: dict[int, TokenUsage] = {}

    for event in timestamped:
        timestamp = event.timestamp
        assert timestamp is not None
        selected_event = window.contains(timestamp)
        observation = event.token_observation
        cumulative = choose_cumulative_observation(event)

        if observation is not None:
            profile.token_observations += int(selected_event)

        increment: TokenUsage | None = None
        method: str | None = None
        cumulative_delta: TokenUsage | None = None
        cumulative_reset = False

        if cumulative is not None and previous_cumulative is not None:
            cumulative_delta = cumulative.usage.delta_from(previous_cumulative)
            cumulative_reset = cumulative_delta is None

        if observation is not None and observation.mode == "incremental":
            observed_increment = observation.usage.normalized()
            # When the same event also exposes a cumulative snapshot, validate the
            # increment against the cumulative delta. This catches repeated
            # last_token_usage records and prevents silent double counting.
            if cumulative_reset:
                if selected_event:
                    profile.token_counter_resets += 1
                increment = observed_increment
                method = f"incremental_with_cumulative_reset:{observation.source}"
            elif cumulative_delta is not None and cumulative_delta.normalized() != observed_increment:
                if selected_event:
                    profile.token_discrepancies += 1
            elif (
                cumulative is not None
                and previous_cumulative is None
                and session_start_at is not None
                and session_start_at >= window.since
                and session_start_at <= timestamp
                and cumulative.usage.normalized() != observed_increment
            ):
                if selected_event:
                    profile.token_discrepancies += 1
            else:
                increment = observed_increment
                validation = "validated" if cumulative is not None else "direct"
                method = f"incremental_{validation}:{observation.source}"
        elif observation is not None and observation.mode == "cumulative":
            if previous_cumulative is not None:
                increment = observation.usage.delta_from(previous_cumulative)
                if increment is None:
                    if selected_event:
                        profile.token_counter_resets += 1
                    method = None
                else:
                    method = f"cumulative_delta:{observation.source}"
            elif (
                session_start_at is not None
                and session_start_at >= window.since
                and session_start_at <= timestamp
            ):
                # A recognized session-start marker is inside the window, so zero
                # is a defensible baseline for the first cumulative snapshot.
                increment = observation.usage
                method = f"cumulative_from_session_start:{observation.source}"
            elif selected_event:
                profile.token_missing_baseline += 1

        # Keep cumulative state synchronized even when incremental usage was used.
        if cumulative is not None:
            previous_cumulative = cumulative.usage
        elif observation is not None and observation.mode == "cumulative":
            previous_cumulative = observation.usage

        if selected_event:
            if increment is not None and method is not None:
                normalized = increment.normalized()
                profile.tokens = profile.tokens.plus(normalized)
                profile.token_events_counted += 1
                profile.token_methods[method] += 1
                token_increment_by_line[event.line_no] = normalized

    # Every selected event contributes to event/tool counts. Token increments are
    # attached by line number so equal timestamps cannot misattribute usage.
    normalized_daily: list[tuple[datetime, TokenUsage, int, int]] = []
    for event in selected:
        assert event.timestamp is not None
        usage = token_increment_by_line.get(event.line_no, TokenUsage.zero())
        normalized_daily.append((event.timestamp, usage, 1, len(event.tools)))

    profile.classifications = classify(profile)
    return profile, normalized_daily


def format_dt(value: datetime | None, tz: timezone | ZoneInfo) -> str:
    if value is None:
        return ""
    return value.astimezone(tz).isoformat()


def issue_ops(profile: SessionProfile) -> int:
    return (
        profile.tool_counts["_add_issue_comment"]
        + profile.tool_counts["_update_issue"]
        + profile.tool_counts["_issue_write"]
        + profile.tool_counts["github_mcp.add_issue_comment"]
    )


def git_diff_ops(profile: SessionProfile) -> int:
    return (
        profile.tool_counts["git_diff_staged"]
        + profile.tool_counts["git_diff_unstaged"]
        + profile.tool_counts["git_diff"]
    )


def build_daily_profiles(
    contributions: Sequence[tuple[str, datetime, TokenUsage, int, int]],
    report_tz: timezone | ZoneInfo,
) -> list[DailyProfile]:
    by_day: dict[str, DailyProfile] = {}
    for session_id, timestamp, usage, event_count, tool_calls in contributions:
        day = timestamp.astimezone(report_tz).date().isoformat()
        daily = by_day.setdefault(day, DailyProfile(day=day))
        daily.sessions.add(session_id)
        daily.events += event_count
        daily.tool_calls += tool_calls
        daily.tokens = daily.tokens.plus(usage)
        daily.token_events += int(not usage.is_zero())
    return [by_day[day] for day in sorted(by_day)]


def write_csv(path: Path, profiles: Sequence[SessionProfile], report_tz: timezone | ZoneInfo) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "file",
            "session_id",
            "selected_first_at",
            "selected_last_at",
            "tokens_total",
            "tokens_input",
            "tokens_cached_input",
            "tokens_output",
            "tokens_reasoning",
            "token_coverage",
            "token_observations",
            "token_events_counted",
            "token_missing_baseline",
            "token_counter_resets",
            "token_discrepancies",
            "selected_events",
            "selected_bytes",
            "untimestamped_lines",
            "malformed_lines",
            "exec_command",
            "apply_patch",
            "git_status",
            "git_diff",
            "issue_ops",
            "fixtures_agent_runtime",
            "contracts_agent_runtime",
            "contracts_repo",
            "test",
            "models",
            "classifications",
        ])

        for profile in profiles:
            writer.writerow([
                str(profile.file),
                profile.session_id or "",
                format_dt(profile.selected_first_at, report_tz),
                format_dt(profile.selected_last_at, report_tz),
                profile.tokens.total,
                profile.tokens.input,
                profile.tokens.cached_input,
                profile.tokens.output,
                profile.tokens.reasoning,
                profile.token_coverage_status,
                profile.token_observations,
                profile.token_events_counted,
                profile.token_missing_baseline,
                profile.token_counter_resets,
                profile.token_discrepancies,
                profile.selected_lines,
                profile.selected_bytes,
                profile.untimestamped_lines,
                profile.malformed_lines,
                profile.tool_counts["exec_command"],
                profile.tool_counts["apply_patch"],
                profile.tool_counts["git_status"],
                git_diff_ops(profile),
                issue_ops(profile),
                profile.family_counts["fixtures.agent_runtime"],
                profile.family_counts["contracts.agent_runtime"],
                profile.family_counts["contracts.repo"],
                profile.family_counts["test"],
                ",".join(f"{name}:{count}" for name, count in profile.model_counts.most_common()),
                ",".join(profile.classifications),
            ])


def write_daily_csv(path: Path, daily: Sequence[DailyProfile]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "day",
            "sessions",
            "events",
            "tool_calls",
            "token_events",
            "tokens_total",
            "tokens_input",
            "tokens_cached_input",
            "tokens_output",
            "tokens_reasoning",
        ])
        for item in daily:
            writer.writerow([
                item.day,
                len(item.sessions),
                item.events,
                item.tool_calls,
                item.token_events,
                item.tokens.total,
                item.tokens.input,
                item.tokens.cached_input,
                item.tokens.output,
                item.tokens.reasoning,
            ])


def combined_counter(profiles: Sequence[SessionProfile], attribute: str) -> Counter:
    result: Counter = Counter()
    for profile in profiles:
        result.update(getattr(profile, attribute))
    return result


def write_markdown(
    path: Path,
    profiles: Sequence[SessionProfile],
    daily: Sequence[DailyProfile],
    window: Window,
    report_tz: timezone | ZoneInfo,
    diagnostics: ScanDiagnostics,
    top: int,
    repo: str,
) -> None:
    profiles_by_tokens = sorted(profiles, key=lambda profile: profile.tokens.total, reverse=True)
    combined_tools = combined_counter(profiles, "tool_counts")
    combined_families = combined_counter(profiles, "family_counts")
    combined_paths = combined_counter(profiles, "path_counts")
    combined_classes = Counter(
        classification for profile in profiles for classification in profile.classifications
    )
    combined_methods = combined_counter(profiles, "token_methods")
    total_tokens = TokenUsage.zero()
    for profile in profiles:
        total_tokens = total_tokens.plus(profile.tokens)

    with path.open("w", encoding="utf-8") as handle:
        handle.write("# Codex session corpus profile\n\n")
        handle.write("## Evidence contract\n\n")
        handle.write("- Window semantics: event timestamps in `[since, until)`.\n")
        handle.write("- File modification times are not used for attribution.\n")
        handle.write("- Untimestamped rows are excluded from time-bounded evidence.\n")
        handle.write("- Structured incremental usage is counted directly.\n")
        handle.write("- Structured cumulative usage is counted only as a validated delta.\n")
        handle.write("- Textual token reports are diagnostics only and are not counted.\n\n")

        handle.write("## Window\n\n")
        handle.write(f"- since: `{format_dt(window.since, report_tz)}`\n")
        handle.write(f"- until: `{format_dt(window.until, report_tz)}`\n")
        handle.write(f"- timezone: `{getattr(report_tz, 'key', str(report_tz))}`\n")
        handle.write(f"- repository filter: `{repo or '(none)'}`\n\n")

        handle.write("## Coverage\n\n")
        handle.write(f"- candidate files: `{diagnostics.candidate_files}`\n")
        handle.write(f"- unreadable files: `{diagnostics.unreadable_files}`\n")
        handle.write(f"- scanned rows: `{diagnostics.scanned_lines}`\n")
        handle.write(f"- timestamped rows: `{diagnostics.timestamped_lines}`\n")
        handle.write(f"- untimestamped rows excluded: `{diagnostics.untimestamped_lines}`\n")
        handle.write(f"- malformed rows: `{diagnostics.malformed_lines}`\n")
        handle.write(f"- selected rows: `{diagnostics.selected_lines}`\n")
        handle.write(f"- profiled sessions: `{len(profiles)}`\n\n")

        handle.write("## Attributed token usage\n\n")
        handle.write(f"- total: `{total_tokens.total:,}`\n")
        handle.write(f"- input: `{total_tokens.input:,}`\n")
        handle.write(f"- cached input: `{total_tokens.cached_input:,}`\n")
        handle.write(f"- output: `{total_tokens.output:,}`\n")
        handle.write(f"- reasoning: `{total_tokens.reasoning:,}`\n\n")

        handle.write("### Token accounting methods\n\n")
        if combined_methods:
            for method, count in combined_methods.most_common():
                handle.write(f"- `{method}`: {count}\n")
        else:
            handle.write("- No recognized structured token-usage records were found.\n")

        handle.write("\n## Daily ledger\n\n")
        handle.write("| Day | Sessions | Events | Tool calls | Token events | Tokens | Input | Cached | Output | Reasoning |\n")
        handle.write("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
        for item in daily:
            handle.write(
                f"| {item.day} | {len(item.sessions)} | {item.events:,} | {item.tool_calls:,} "
                f"| {item.token_events:,} | {item.tokens.total:,} | {item.tokens.input:,} "
                f"| {item.tokens.cached_input:,} | {item.tokens.output:,} | {item.tokens.reasoning:,} |\n"
            )

        handle.write("\n## Highest attributed-token sessions\n\n")
        handle.write("| Tokens | Output | Reasoning | Events | apply_patch | exec | Coverage | Class | Session |\n")
        handle.write("|---:|---:|---:|---:|---:|---:|---|---|---|\n")
        for profile in profiles_by_tokens[:top]:
            handle.write(
                f"| {profile.tokens.total:,} | {profile.tokens.output:,} | {profile.tokens.reasoning:,} "
                f"| {profile.selected_lines:,} | {profile.tool_counts['apply_patch']} "
                f"| {profile.tool_counts['exec_command']} | {profile.token_coverage_status} "
                f"| {', '.join(profile.classifications)} "
                f"| `{profile.session_id or profile.file.name}` |\n"
            )

        handle.write("\n## Recurring classifications\n\n")
        for name, count in combined_classes.most_common():
            handle.write(f"- `{name}`: {count}\n")

        handle.write("\n## Combined tool counts\n\n")
        for name, count in combined_tools.most_common(top):
            handle.write(f"- `{name}`: {count}\n")

        handle.write("\n## Combined path families\n\n")
        for name, count in combined_families.most_common(top):
            handle.write(f"- `{name}`: {count}\n")

        handle.write("\n## Combined hot paths\n\n")
        for name, count in combined_paths.most_common(top):
            handle.write(f"- `{name}`: {count}\n")

        handle.write("\n## Coverage gaps by session\n\n")
        gaps = [
            profile for profile in profiles
            if profile.untimestamped_lines
            or profile.malformed_lines
            or profile.token_missing_baseline
            or profile.token_counter_resets
            or profile.token_discrepancies
            or profile.token_text_reports_ignored
        ]
        if not gaps:
            handle.write("No detected coverage gaps.\n")
        for profile in gaps:
            handle.write(f"\n### `{profile.session_id or profile.file.name}`\n\n")
            handle.write(f"- untimestamped rows: `{profile.untimestamped_lines}`\n")
            handle.write(f"- malformed rows: `{profile.malformed_lines}`\n")
            handle.write(f"- cumulative snapshots missing baseline: `{profile.token_missing_baseline}`\n")
            handle.write(f"- cumulative counter resets: `{profile.token_counter_resets}`\n")
            handle.write(f"- incremental/cumulative discrepancies: `{profile.token_discrepancies}`\n")
            handle.write(f"- textual token reports ignored: `{profile.token_text_reports_ignored}`\n")

        handle.write("\n## Per-session largest selected rows\n\n")
        for profile in profiles_by_tokens[:top]:
            if not profile.largest_rows:
                continue
            handle.write(f"\n### `{profile.session_id or profile.file.name}`\n\n")
            for line_no, size, kind, timestamp in profile.largest_rows[:5]:
                handle.write(
                    f"- `{size:,}` bytes at line `{line_no}`, event `{kind}`, timestamp `{timestamp}`\n"
                )


def profile_to_json(profile: SessionProfile, report_tz: timezone | ZoneInfo) -> dict[str, Any]:
    return {
        "file": str(profile.file),
        "session_id": profile.session_id,
        "coverage": {
            "scanned_lines": profile.scanned_lines,
            "malformed_lines": profile.malformed_lines,
            "timestamped_lines": profile.timestamped_lines,
            "untimestamped_lines": profile.untimestamped_lines,
            "selected_lines": profile.selected_lines,
            "token_status": profile.token_coverage_status,
            "token_observations": profile.token_observations,
            "token_events_counted": profile.token_events_counted,
            "token_missing_baseline": profile.token_missing_baseline,
            "token_counter_resets": profile.token_counter_resets,
            "token_discrepancies": profile.token_discrepancies,
            "token_text_reports_ignored": profile.token_text_reports_ignored,
        },
        "time": {
            "first_event_at": format_dt(profile.first_event_at, report_tz),
            "last_event_at": format_dt(profile.last_event_at, report_tz),
            "selected_first_at": format_dt(profile.selected_first_at, report_tz),
            "selected_last_at": format_dt(profile.selected_last_at, report_tz),
        },
        "tokens": asdict(profile.tokens),
        "token_methods": dict(profile.token_methods),
        "event_counts": dict(profile.event_counts),
        "tool_counts": dict(profile.tool_counts),
        "model_counts": dict(profile.model_counts),
        "family_counts": dict(profile.family_counts),
        "classifications": profile.classifications,
    }


def write_json_manifest(
    path: Path,
    profiles: Sequence[SessionProfile],
    daily: Sequence[DailyProfile],
    window: Window,
    report_tz: timezone | ZoneInfo,
    diagnostics: ScanDiagnostics,
    repo: str,
) -> None:
    manifest = {
        "schema_version": 1,
        "evidence_contract": {
            "window": "event_timestamp_half_open",
            "file_mtime_used": False,
            "untimestamped_rows_included": False,
            "text_token_reports_counted": False,
            "cumulative_usage": "positive_delta_with_baseline",
        },
        "window": {
            "since": format_dt(window.since, report_tz),
            "until": format_dt(window.until, report_tz),
            "timezone": getattr(report_tz, "key", str(report_tz)),
        },
        "repository_filter": repo or None,
        "diagnostics": asdict(diagnostics),
        "sessions": [profile_to_json(profile, report_tz) for profile in profiles],
        "daily": [
            {
                "day": item.day,
                "sessions": sorted(item.sessions),
                "events": item.events,
                "tool_calls": item.tool_calls,
                "token_events": item.token_events,
                "tokens": asdict(item.tokens),
            }
            for item in daily
        ],
    }
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_cli_datetime(value: str, naive_tz: timezone | ZoneInfo, label: str) -> datetime:
    parsed = parse_datetime_value(value, naive_tz)
    if parsed is None:
        raise ValueError(f"invalid {label} datetime: {value!r}")
    return parsed


def resolve_window(args: argparse.Namespace, naive_tz: timezone | ZoneInfo) -> Window:
    now = datetime.now(timezone.utc)

    if args.since or args.until:
        if not (args.since and args.until):
            raise ValueError("--since and --until must be supplied together")
        if args.hours is not None:
            raise ValueError("use either --hours or --since/--until, not both")
        since = parse_cli_datetime(args.since, naive_tz, "--since")
        until = parse_cli_datetime(args.until, naive_tz, "--until")
    else:
        hours = 48.0 if args.hours is None else args.hours
        if hours <= 0:
            raise ValueError("--hours must be greater than zero")
        until = now
        since = now - timedelta(hours=hours)

    if since >= until:
        raise ValueError("window requires --since earlier than --until")
    return Window(since=since, until=until)


def strict_failures(profiles: Sequence[SessionProfile], diagnostics: ScanDiagnostics) -> list[str]:
    del diagnostics  # Global scan diagnostics include repository-filtered sessions.
    failures: list[str] = []
    untimestamped = sum(profile.untimestamped_lines for profile in profiles)
    malformed = sum(profile.malformed_lines for profile in profiles)
    if untimestamped:
        failures.append(f"{untimestamped} untimestamped rows in profiled sessions")
    if malformed:
        failures.append(f"{malformed} malformed rows in profiled sessions")
    missing = sum(profile.token_missing_baseline for profile in profiles)
    resets = sum(profile.token_counter_resets for profile in profiles)
    discrepancies = sum(profile.token_discrepancies for profile in profiles)
    if missing:
        failures.append(f"{missing} cumulative token snapshots without baseline")
    if resets:
        failures.append(f"{resets} cumulative token counter resets")
    if discrepancies:
        failures.append(f"{discrepancies} incremental/cumulative token discrepancies")
    return failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Profile Codex JSONL logs by event timestamp with conservative token accounting."
    )
    parser.add_argument(
        "--root",
        default=os.environ.get("CODEX_HOME", str(Path.home() / ".local/share/codex")),
        help="Codex root, sessions directory, or one JSONL file",
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=None,
        help="rolling window ending now; default 48 when --since/--until are absent",
    )
    parser.add_argument("--since", help="inclusive ISO-8601 window start")
    parser.add_argument("--until", help="exclusive ISO-8601 window end")
    parser.add_argument(
        "--timezone",
        default="UTC",
        help="IANA timezone or ±HH:MM; used for naive input timestamps and report grouping",
    )
    parser.add_argument("--repo", default="contract.cuemod", help="session repository substring; empty disables")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--out", default="/tmp/codex-profile")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 3 when evidence coverage gaps are detected",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        report_tz = parse_timezone(args.timezone)
        window = resolve_window(args, report_tz)
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    root = Path(args.root).expanduser()
    if not root.exists():
        print(f"missing root: {root}", file=sys.stderr)
        return 2

    files = candidate_files(root)
    diagnostics = ScanDiagnostics(candidate_files=len(files))
    profiles: list[SessionProfile] = []
    all_daily_contributions: list[tuple[str, datetime, TokenUsage, int, int]] = []

    for path in files:
        events, readable = read_events(path, report_tz)
        if not readable:
            diagnostics.unreadable_files += 1
            continue

        diagnostics.scanned_lines += len(events)
        diagnostics.malformed_lines += sum(bool(getattr(event, "_malformed", False)) for event in events)
        diagnostics.timestamped_lines += sum(event.timestamp is not None for event in events)
        diagnostics.untimestamped_lines += sum(event.timestamp is None for event in events)

        if not session_matches_repo(path, events, args.repo):
            diagnostics.repo_filtered_sessions += 1
            continue

        profile, contributions = profile_session(path, events, window, report_tz)
        if profile.selected_lines == 0:
            continue

        profiles.append(profile)
        session_key = profile.session_id or str(profile.file)
        all_daily_contributions.extend(
            (session_key, timestamp, usage, event_count, tool_calls)
            for timestamp, usage, event_count, tool_calls in contributions
        )
        diagnostics.selected_lines += profile.selected_lines

    daily = build_daily_profiles(all_daily_contributions, report_tz)
    profiles.sort(key=lambda profile: (profile.selected_first_at or window.until, str(profile.file)))

    out_base = Path(args.out).expanduser()
    out_base.parent.mkdir(parents=True, exist_ok=True)
    md_path = out_base.with_suffix(".md")
    csv_path = out_base.with_suffix(".csv")
    daily_path = out_base.parent / f"{out_base.name}.daily.csv"
    json_path = out_base.with_suffix(".json")

    write_markdown(
        md_path,
        profiles,
        daily,
        window,
        report_tz,
        diagnostics,
        args.top,
        args.repo,
    )
    write_csv(csv_path, profiles, report_tz)
    write_daily_csv(daily_path, daily)
    write_json_manifest(json_path, profiles, daily, window, report_tz, diagnostics, args.repo)

    print(f"root: {root}")
    print(f"window: [{format_dt(window.since, report_tz)}, {format_dt(window.until, report_tz)})")
    print(f"candidate jsonl: {diagnostics.candidate_files}")
    print(f"scanned rows: {diagnostics.scanned_lines}")
    print(f"timestamped rows: {diagnostics.timestamped_lines}")
    print(f"untimestamped rows excluded: {diagnostics.untimestamped_lines}")
    print(f"selected rows: {diagnostics.selected_lines}")
    print(f"profiled sessions: {len(profiles)}")
    print(f"markdown: {md_path}")
    print(f"session csv: {csv_path}")
    print(f"daily csv: {daily_path}")
    print(f"manifest: {json_path}")

    failures = strict_failures(profiles, diagnostics)
    if failures:
        print("\ncoverage gaps:")
        for failure in failures:
            print(f"  - {failure}")
        if args.strict:
            return 3

    if diagnostics.selected_lines == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
