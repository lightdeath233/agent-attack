"""记忆条目与加载。

每条记忆都显式声明两件事：
- `sensitive_keys`：这条记忆涉及哪些敏感字段（用于第三阶段归因"泄露来自哪一条记忆"）；
- `sensitive_values`：对应的字面值（用于当前阶段的粗筛，以及后面构造攻击者的目标集合）。

把标签写在数据里而不是代码里，是为了让"数据集"本身可审阅、可替换。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


class MemoryError(RuntimeError):
    """记忆文件不合法。"""


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    text: str
    owner: str
    kind: str = "note"
    sensitive_keys: tuple[str, ...] = ()
    sensitive_values: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    created_at: str | None = None

    @property
    def is_sensitive(self) -> bool:
        return bool(self.sensitive_keys or self.sensitive_values)


def _as_tuple(value: Any, name: str, record_id: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise MemoryError(f"记忆 {record_id} 的 {name} 必须是字符串或字符串数组")


def parse_record(raw: dict[str, Any]) -> MemoryRecord:
    record_id = str(raw.get("id") or "").strip()
    if not record_id:
        raise MemoryError("记忆条目缺少 id")
    text = str(raw.get("text") or "").strip()
    if not text:
        raise MemoryError(f"记忆 {record_id} 缺少 text")

    return MemoryRecord(
        id=record_id,
        text=text,
        owner=str(raw.get("owner") or ""),
        kind=str(raw.get("kind") or "note"),
        sensitive_keys=_as_tuple(raw.get("sensitive_keys"), "sensitive_keys", record_id),
        sensitive_values=_as_tuple(raw.get("sensitive_values"), "sensitive_values", record_id),
        tags=_as_tuple(raw.get("tags"), "tags", record_id),
        created_at=str(raw["created_at"]) if raw.get("created_at") else None,
    )


def load_memory(path: Path, *, owner: str | None = None) -> list[MemoryRecord]:
    if not path.is_file():
        raise MemoryError(f"找不到记忆文件：{path}")

    records: list[MemoryRecord] = []
    seen: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MemoryError(f"{path} 第 {lineno} 行不是合法 JSON：{exc}") from exc
        record = parse_record(raw)
        if record.id in seen:
            raise MemoryError(f"记忆 id 重复：{record.id}")
        seen.add(record.id)
        if owner is None or record.owner == owner:
            records.append(record)
    return records


def collect_sensitive_values(records: Iterable[MemoryRecord]) -> list[tuple[str, str]]:
    """返回 (record_id, value) 列表，供粗筛使用。"""
    pairs: list[tuple[str, str]] = []
    for record in records:
        for value in record.sensitive_values:
            pairs.append((record.id, value))
    return pairs
