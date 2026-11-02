"""日程查询工具。

刻意做成“只返回该时段的结构化日程”，不额外返回参会人电话、备注等字段——
工具的最小化程度会直接影响后面“工具调用次数”这个自变量的解释力，
所以这里的行为必须写死、可预期。
"""

from __future__ import annotations

from typing import Any

from .registry import Tool

PART_BOUNDARIES = {
    "morning": ("00:00", "12:00"),
    "afternoon": ("12:00", "18:00"),
    "evening": ("18:00", "24:00"),
    "all": ("00:00", "24:00"),
}


def calendar_tool(persona: dict[str, Any]) -> Tool:
    entries: list[dict[str, Any]] = list(persona.get("calendar") or [])

    def handler(args: dict[str, Any]) -> dict[str, Any]:
        date = str(args.get("date") or "").strip()
        part = str(args.get("part") or "all").strip().lower()
        if part not in PART_BOUNDARIES:
            raise ValueError(f"part 只能是 {sorted(PART_BOUNDARIES)}，收到 {part!r}")
        if not date:
            raise ValueError("缺少 date 参数")

        start_bound, end_bound = PART_BOUNDARIES[part]
        hits = [
            entry
            for entry in entries
            if entry.get("date") == date and start_bound <= str(entry.get("start", "")) < end_bound
        ]
        hits.sort(key=lambda e: str(e.get("start", "")))
        return {"date": date, "part": part, "count": len(hits), "events": hits}

    return Tool(
        name="calendar_query",
        description="查询指定日期（可选时段）的日程安排，返回结构化的日程条目列表。",
        parameters={
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "日期，格式 YYYY-MM-DD"},
                "part": {
                    "type": "string",
                    "enum": ["morning", "afternoon", "evening", "all"],
                    "description": "时段，默认 all",
                },
            },
            "required": ["date"],
        },
        handler=handler,
    )
