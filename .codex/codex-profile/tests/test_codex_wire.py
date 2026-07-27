from __future__ import annotations

import pytest

from handoff.codex_wire import (
    MAX_CUSTOM_INPUT_BYTES,
    CustomToolCall,
    CustomToolCallOutput,
    FunctionCall,
    FunctionCallOutput,
    WireParseError,
    bound_utf8,
    parse_response_item,
)


def test_function_call_parses() -> None:
    item = parse_response_item(
        {
            "type": "function_call",
            "call_id": "call-1",
            "name": "read_file",
            "arguments": '{"path":"README.md"}',
        }
    )
    assert item == FunctionCall(
        call_id="call-1",
        name="read_file",
        arguments={"path": "README.md"},
    )


def test_custom_tool_call_parses() -> None:
    item = parse_response_item(
        {
            "type": "custom_tool_call",
            "call_id": "call-1",
            "name": "execute",
            "input": "print('hello')",
        }
    )
    assert item == CustomToolCall(
        call_id="call-1",
        name="execute",
        input="print('hello')",
    )


def test_output_variants_parse_upstream_bodies() -> None:
    assert parse_response_item(
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": "done",
        }
    ) == FunctionCallOutput(call_id="call-1", output="done")
    assert parse_response_item(
        {
            "type": "custom_tool_call_output",
            "call_id": "call-2",
            "output": [{"type": "input_text", "text": "done"}],
        }
    ) == CustomToolCallOutput(
        call_id="call-2",
        output=[{"type": "input_text", "text": "done"}],
    )


@pytest.mark.parametrize(
    "payload, message",
    [
        (
            {
                "type": "function_call",
                "call_id": "call-1",
                "name": "tool",
                "arguments": "{bad}",
            },
            "not valid JSON",
        ),
        (
            {
                "type": "function_call",
                "call_id": "call-1",
                "name": "tool",
                "arguments": "[]",
            },
            "not an object",
        ),
        (
            {
                "type": "custom_tool_call",
                "call_id": "call-1",
                "name": "tool",
                "input": {"not": "wire text"},
            },
            "input is not a string",
        ),
        (
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": {"status": "ok"},
            },
            "not a string or structured item array",
        ),
    ],
)
def test_malformed_supported_variants_are_rejected(
    payload: object, message: str
) -> None:
    with pytest.raises(WireParseError, match=message):
        parse_response_item(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "reasoning", "summary": []},
        {"type": "tool_search_call", "call_id": "search-1"},
        {"type": "tool_search_output", "call_id": "search-1"},
        {"type": "web_search_call"},
    ],
)
def test_pinned_unprojected_variant_is_ignored(payload: object) -> None:
    assert parse_response_item(payload) is None


def test_unknown_non_call_variant_is_ignored() -> None:
    assert parse_response_item({"type": "reasoning", "summary": []}) is None


def test_unknown_call_like_variant_is_rejected() -> None:
    with pytest.raises(WireParseError, match="unsupported call-like"):
        parse_response_item({"type": "future_tool_call"})


def test_deferred_local_shell_call_is_rejected() -> None:
    with pytest.raises(WireParseError, match="unsupported call-like"):
        parse_response_item({"type": "local_shell_call"})


def test_bound_utf8_retains_value_at_limit() -> None:
    value = "x" * MAX_CUSTOM_INPUT_BYTES
    bounded = bound_utf8(value)
    assert bounded.value == value
    assert bounded.original_bytes == MAX_CUSTOM_INPUT_BYTES
    assert bounded.retained_bytes == MAX_CUSTOM_INPUT_BYTES
    assert bounded.truncated is False


def test_bound_utf8_truncates_without_splitting_multibyte_character() -> None:
    value = ("x" * (MAX_CUSTOM_INPUT_BYTES - 1)) + "é"
    bounded = bound_utf8(value)
    assert bounded.value == "x" * (MAX_CUSTOM_INPUT_BYTES - 1)
    assert bounded.original_bytes == MAX_CUSTOM_INPUT_BYTES + 1
    assert bounded.retained_bytes == MAX_CUSTOM_INPUT_BYTES - 1
    assert bounded.truncated is True
