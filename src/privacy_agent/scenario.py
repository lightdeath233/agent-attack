"""场景与人物数据加载。

场景是“实验条件”的声明式描述：谁在什么威胁模型下、说哪几句话。
把用户话语写成脚本而不是让 LLM 扮演用户，是第一阶段就能定下来的原则——
LLM 模拟用户会引入第二个随机源，第四阶段做控制变量时没法把差异归因到自变量上。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import REPO_ROOT

DATA_DIR = REPO_ROOT / "data"
SCENARIO_DIR = DATA_DIR / "scenarios"
PERSONA_DIR = DATA_DIR / "personas"


class ScenarioError(RuntimeError):
    """场景或人物数据不合法。"""


@dataclass(frozen=True)
class TurnDef:
    id: str
    user: str
    # 这一轮是否由用户明确索要敏感信息（授权披露）。标了 True 的轮次出现敏感值不算泄露。
    expect_disclosure: bool = False


@dataclass(frozen=True)
class Scenario:
    id: str
    persona_id: str
    description: str
    threat_model: dict[str, Any]
    turns: list[TurnDef]
    source: Path
    mock: dict[str, Any] | None = None
    memory: dict[str, Any] | None = None


def resolve_scenario_path(ref: str) -> Path:
    candidate = Path(ref)
    if candidate.suffix in (".yaml", ".yml") and candidate.is_file():
        return candidate
    if candidate.is_file():
        return candidate
    return SCENARIO_DIR / f"{ref}.yaml"


def load_scenario(ref: str) -> Scenario:
    path = resolve_scenario_path(ref)
    if not path.is_file():
        raise ScenarioError(f"找不到场景文件：{path}")

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ScenarioError(f"场景文件不是合法 YAML：{path}\n{exc}") from exc

    if not isinstance(data, dict):
        raise ScenarioError(f"场景文件顶层必须是映射：{path}")

    scenario_id = str(data.get("id") or path.stem)
    persona_id = str(data.get("persona") or "").strip()
    if not persona_id:
        raise ScenarioError(f"场景 {scenario_id} 缺少 persona 字段")

    raw_turns = data.get("turns") or []
    if not isinstance(raw_turns, list) or not raw_turns:
        raise ScenarioError(f"场景 {scenario_id} 至少需要一个 turn")

    turns: list[TurnDef] = []
    for index, item in enumerate(raw_turns, start=1):
        if not isinstance(item, dict):
            raise ScenarioError(f"场景 {scenario_id} 的第 {index} 个 turn 必须是映射")
        text = str(item.get("user") or "").strip()
        if not text:
            raise ScenarioError(f"场景 {scenario_id} 的第 {index} 个 turn 缺少 user 文本")
        turns.append(
            TurnDef(
                id=str(item.get("id") or f"t{index}"),
                user=text,
                expect_disclosure=bool(item.get("expect_disclosure") or False),
            )
        )

    threat_model = data.get("threat_model") or {}
    if not isinstance(threat_model, dict):
        raise ScenarioError(f"场景 {scenario_id} 的 threat_model 必须是映射")

    mock = data.get("mock")
    if mock is not None and not isinstance(mock, dict):
        raise ScenarioError(f"场景 {scenario_id} 的 mock 必须是映射")

    memory = data.get("memory")
    if memory is not None and not isinstance(memory, dict):
        raise ScenarioError(f"场景 {scenario_id} 的 memory 必须是映射")

    return Scenario(
        id=scenario_id,
        persona_id=persona_id,
        description=str(data.get("description") or ""),
        threat_model=threat_model,
        turns=turns,
        source=path,
        mock=mock,
        memory=memory,
    )


def load_persona(persona_id: str) -> dict[str, Any]:
    path = PERSONA_DIR / f"{persona_id}.json"
    if not path.is_file():
        raise ScenarioError(f"找不到人物文件：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScenarioError(f"人物文件不是合法 JSON：{path}\n{exc}") from exc
    if not isinstance(data, dict):
        raise ScenarioError(f"人物文件顶层必须是对象：{path}")
    if not data.get("fields"):
        raise ScenarioError(f"人物 {persona_id} 缺少 fields")
    return data
