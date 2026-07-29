from __future__ import annotations

from typing import Literal

from .codex_wire import CallFamily

ToolKind = Literal["shell", "tool"]

_SHELL_TOOLS = frozenset(
    {
        "exec_command",
        "write_stdin",
        "shell_command",
    }
)


def classify_tool(name: str, family: CallFamily) -> ToolKind:
    if family == "custom":
        return "tool"
    return "shell" if name in _SHELL_TOOLS else "tool"
