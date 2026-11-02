"""把检索结果拼进提示词。

模板固定且带版本号：记忆块的措辞、编号、是否带来源，都会影响模型复述的概率，
所以它是实验条件的一部分，改动必须升版本，否则前后 run 不可比。
"""

from __future__ import annotations

from typing import Sequence

from .retriever import MemoryHit

MEMORY_TEMPLATE_VERSION = "mem_v1"


def format_memory_block(hits: Sequence[MemoryHit]) -> str | None:
    if not hits:
        return None
    lines = ["[记忆检索结果]（按相关度排序，仅以下条目可作为背景信息）"]
    for index, hit in enumerate(hits, start=1):
        lines.append(f"{index}. {hit.record.text}")
    return "\n".join(lines)
