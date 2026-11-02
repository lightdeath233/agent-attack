"""模拟工具集合。第一阶段只有日程查询。"""

from __future__ import annotations

from .calendar import calendar_tool
from .registry import Tool, ToolOutcome, ToolRegistry, build_registry

__all__ = ["Tool", "ToolOutcome", "ToolRegistry", "build_registry", "calendar_tool", "default_registry"]


def default_registry(persona: dict) -> ToolRegistry:
    return build_registry([calendar_tool(persona)])
