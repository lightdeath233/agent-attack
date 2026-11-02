"""工具注册与调用。

设计约束：工具只返回结构化数据，不负责措辞；是否把结果说给用户，
由模型（以及将来的防御层）决定。这样“工具能拿到什么”与“最终说了什么”
在日志里是两件可分开观察的事。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

ToolHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolOutcome:
    ok: bool
    result: Any = None
    error: str | None = None
    arguments: dict[str, Any] | None = None
    raw_arguments: str = ""


@dataclass
class ToolRegistry:
    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> "ToolRegistry":
        if tool.name in self._tools:
            raise ValueError(f"工具重名：{tool.name}")
        self._tools[tool.name] = tool
        return self

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[dict[str, Any]]:
        return [tool.spec() for tool in self._tools.values()]

    def call(self, name: str, raw_arguments: str) -> ToolOutcome:
        tool = self._tools.get(name)
        if tool is None:
            return ToolOutcome(ok=False, error=f"未知工具：{name}", raw_arguments=raw_arguments)

        try:
            args = json.loads(raw_arguments) if raw_arguments.strip() else {}
        except json.JSONDecodeError as exc:
            return ToolOutcome(ok=False, error=f"参数不是合法 JSON：{exc}", raw_arguments=raw_arguments)

        if not isinstance(args, dict):
            return ToolOutcome(ok=False, error="参数必须是 JSON 对象", raw_arguments=raw_arguments)

        try:
            result = tool.handler(args)
        except Exception as exc:  # noqa: BLE001 - 工具失败要记进日志，不能炸掉整轮
            return ToolOutcome(ok=False, error=f"{type(exc).__name__}: {exc}", arguments=args, raw_arguments=raw_arguments)

        return ToolOutcome(ok=True, result=result, arguments=args, raw_arguments=raw_arguments)


def build_registry(tools: Iterable[Tool]) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry
