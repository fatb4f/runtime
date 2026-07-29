from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, TypeAlias

CallFamily = Literal["function", "custom"]
OutputBody: TypeAlias = str | list[dict[str, object]]
MAX_CUSTOM_INPUT_BYTES = 32 * 1024
_IGNORED_PINNED_TYPES = frozenset(
    {
        "additional_tools",
        "agent_message",
        "compaction",
        "compaction_trigger",
        "context_compaction",
        "image_generation_call",
        "message",
        "other",
        "reasoning",
        "tool_search_call",
        "tool_search_output",
        "web_search_call",
    }
)


class WireParseError(ValueError):
    pass


@dataclass(frozen=True)
class FunctionCall:
    call_id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class CustomToolCall:
    call_id: str
    name: str
    input: str


@dataclass(frozen=True)
class FunctionCallOutput:
    call_id: str
    output: OutputBody


@dataclass(frozen=True)
class CustomToolCallOutput:
    call_id: str
    output: OutputBody


WireItem: TypeAlias = (
    FunctionCall | CustomToolCall | FunctionCallOutput | CustomToolCallOutput
)


@dataclass(frozen=True)
class BoundedText:
    value: str
    original_bytes: int
    truncated: bool

    @property
    def retained_bytes(self) -> int:
        return len(self.value.encode("utf-8"))


def bound_utf8(value: str, limit: int = MAX_CUSTOM_INPUT_BYTES) -> BoundedText:
    if limit < 0:
        raise ValueError("UTF-8 byte limit cannot be negative")
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return BoundedText(value=value, original_bytes=len(encoded), truncated=False)
    retained = encoded[:limit].decode("utf-8", errors="ignore")
    return BoundedText(value=retained, original_bytes=len(encoded), truncated=True)


def parse_response_item(payload: object) -> WireItem | None:
    if not isinstance(payload, dict):
        raise WireParseError("response item payload is not an object")
    item_type = payload.get("type")
    if not isinstance(item_type, str) or not item_type:
        raise WireParseError("response item has no type")

    if item_type == "function_call":
        return FunctionCall(
            call_id=_nonempty_string(payload, "call_id", item_type),
            name=_nonempty_string(payload, "name", item_type),
            arguments=_arguments(payload, item_type),
        )
    if item_type == "custom_tool_call":
        return CustomToolCall(
            call_id=_nonempty_string(payload, "call_id", item_type),
            name=_nonempty_string(payload, "name", item_type),
            input=_string(payload, "input", item_type),
        )
    if item_type == "function_call_output":
        return FunctionCallOutput(
            call_id=_nonempty_string(payload, "call_id", item_type),
            output=_output(payload, item_type),
        )
    if item_type == "custom_tool_call_output":
        return CustomToolCallOutput(
            call_id=_nonempty_string(payload, "call_id", item_type),
            output=_output(payload, item_type),
        )
    if item_type in _IGNORED_PINNED_TYPES:
        return None
    if item_type.endswith(("_call", "_call_output")):
        raise WireParseError(f"unsupported call-like response item: {item_type}")
    return None


def _nonempty_string(payload: dict[object, object], field: str, item_type: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise WireParseError(f"{item_type} has no {field}")
    return value


def _string(payload: dict[object, object], field: str, item_type: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise WireParseError(f"{item_type}.{field} is not a string")
    return value


def _arguments(payload: dict[object, object], item_type: str) -> dict[str, object]:
    raw = _string(payload, "arguments", item_type)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise WireParseError(f"{item_type}.arguments is not valid JSON") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise WireParseError(f"{item_type}.arguments is not an object")
    return value


def _output(payload: dict[object, object], item_type: str) -> OutputBody:
    if "output" not in payload:
        raise WireParseError(f"{item_type} has no output")
    value = payload["output"]
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_content_item(item, index) for index, item in enumerate(value)]
    raise WireParseError(f"{item_type}.output is not a string or structured item array")


def _content_item(value: object, index: int) -> dict[str, object]:
    if not isinstance(value, dict):
        raise WireParseError(f"output[{index}] is not an object")
    item_type = value.get("type")
    if item_type == "input_text":
        _required_content_string(value, "text", index)
    elif item_type == "input_image":
        _required_content_string(value, "image_url", index)
        _optional_image_detail(value, index)
    elif item_type == "input_audio":
        _required_content_string(value, "audio_url", index)
    elif item_type == "encrypted_content":
        _required_content_string(value, "encrypted_content", index)
    else:
        raise WireParseError(
            f"output[{index}] has unsupported content type: {item_type!r}"
        )
    return dict(value)


def _required_content_string(
    value: dict[object, object], field: str, index: int
) -> None:
    if not isinstance(value.get(field), str):
        raise WireParseError(f"output[{index}].{field} is not a string")


def _optional_image_detail(value: dict[object, object], index: int) -> None:
    if "detail" not in value or value["detail"] is None:
        return
    if value["detail"] not in {"auto", "low", "high", "original"}:
        raise WireParseError(f"output[{index}].detail is invalid")
