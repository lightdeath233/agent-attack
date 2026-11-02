"""运行记录器：一次 run 一个目录，trace.jsonl 追加写，meta.json 收尾时重写。

为什么 trace.jsonl 每写一条就 flush：跑 15 轮、几十次 API 调用时，
中途崩掉是常态；宁可留下半份可分析的日志，也不要丢全部。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import EventType, TraceEvent

# 默认谁能看到这类事件；“attacker”由威胁模型配置额外叠加。
DEFAULT_AUDIENCE: dict[str, set[str]] = {
    "user_message": {"user"},
    "assistant_message": {"user"},
    "llm_request": set(),
    "llm_response": set(),
    "tool_call": set(),
    "tool_result": set(),
    "error": set(),
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def unique_dir(base: Path, name: str) -> Path:
    candidate = base / name
    index = 2
    while candidate.exists():
        candidate = base / f"{name}-{index}"
        index += 1
    return candidate


def git_commit_of(repo_root: Path) -> str | None:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


class RunRecorder:
    def __init__(self, run_dir: Path, meta: dict[str, Any], *, attacker_observable: set[str] | None = None):
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.meta = meta
        self._attacker_observable = attacker_observable or set()
        self._trace_path = self.run_dir / "trace.jsonl"
        self._handle = self._trace_path.open("a", encoding="utf-8", newline="\n")
        self._seq = 0
        self._write_meta()

    @property
    def trace_path(self) -> Path:
        return self._trace_path

    def visibility_for(self, event_type: str) -> list[str]:
        audience = {"experimenter"} | DEFAULT_AUDIENCE.get(event_type, set())
        if event_type in self._attacker_observable:
            audience.add("attacker")
        order = {"experimenter": 0, "user": 1, "attacker": 2}
        return sorted(audience, key=lambda name: order.get(name, 99))

    def emit(
        self,
        event_type: EventType,
        *,
        actor: str,
        turn: int,
        payload: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        latency_ms: float | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> int:
        self._seq += 1
        event = TraceEvent(
            seq=self._seq,
            ts=now_iso(),
            run_id=self.meta["run_id"],
            turn=turn,
            type=event_type,
            actor=actor,  # type: ignore[arg-type]
            visibility=self.visibility_for(event_type),  # type: ignore[arg-type]
            payload=payload or {},
            usage=usage,
            latency_ms=round(latency_ms, 1) if latency_ms is not None else None,
            provenance=provenance,
        )
        self._handle.write(event.model_dump_json() + "\n")
        self._handle.flush()
        return self._seq

    def finish(self, summary: dict[str, Any]) -> None:
        self.meta["summary"] = summary
        self.meta["finished_at"] = now_iso()
        self._write_meta()
        self._handle.close()

    def _write_meta(self) -> None:
        path = self.run_dir / "meta.json"
        path.write_text(json.dumps(self.meta, ensure_ascii=False, indent=2), encoding="utf-8")
