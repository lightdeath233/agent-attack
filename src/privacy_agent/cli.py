"""命令行入口：python -m privacy_agent.cli <command>"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from . import __version__
from .agent import PROMPT_VERSION, SYSTEM_PROMPT, run_conversation
from .config import ENV_FILE, REPO_ROOT, ConfigError, load_config, mask_key, require_api_key
from .llm import LLMError, MockLLM, build_client
from .memory import BM25Index, MEMORY_TEMPLATE_VERSION, load_memory
from .pricing import estimate_cost, period_label
from .scenario import DATA_DIR, ScenarioError, load_persona, load_scenario
from .tools import default_registry
from .trace import RunRecorder, unique_dir

PACKAGES = ("openai", "pydantic", "PyYAML", "python-dotenv")
LABEL_WIDTH = 19


def _use_utf8_when_redirected() -> None:
    """输出被重定向到管道/文件时统一用 UTF-8。

    Windows 上 Python 在非控制台输出时默认用 locale 编码（简体中文系统是 cp936），
    中文日志写进管道会变成乱码；交互式终端则保持原样，交给控制台自己处理。
    """
    if sys.stdout.isatty():
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _display_width(text: str) -> int:
    """按终端显示宽度算长度：中日韩全角字符占两列。"""
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _row(label: str, value: Any) -> str:
    padding = max(0, LABEL_WIDTH - _display_width(label))
    return f"{label}{' ' * padding}{value}"


def _pkg_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "未安装"


def _print_llm_block(cfg) -> None:
    llm = cfg.llm
    print(_row("config", cfg.source))
    print(_row("provider", llm.provider))
    print(_row("base_url", llm.base_url))
    print(_row("model", llm.model))
    print(_row("thinking", llm.thinking + ("（temperature 不生效）" if llm.thinking_enabled else "")))
    print(_row("temperature", llm.temperature))
    print(_row("max_tokens", llm.max_tokens))
    print(_row("timeout/retries", f"{llm.timeout_s:g}s / {llm.max_retries}"))
    print(_row("api_key", f"{mask_key(llm.api_key)}（来源：{llm.api_key_source}）"))
    print(_row("output_dir", cfg.run.out_dir))


def _git_commit() -> str | None:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


# ---------------------------------------------------------------- doctor


def cmd_doctor(args: argparse.Namespace) -> int:
    print("== privacy-agent doctor ==")
    print(_row("platform", f"{platform.system()} {platform.release()} {platform.version()}"))
    print(_row("python", f"{platform.python_version()}  {sys.executable}"))
    print(_row("packages", " | ".join(f"{name} {_pkg_version(name)}" for name in PACKAGES)))
    print(_row("privacy-agent", __version__))
    print()

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print("[FAIL] 配置加载失败")
        for line in str(exc).splitlines():
            print(f"       {line}")
        return 2

    _print_llm_block(cfg)
    print()
    print("--- 检查 ---")

    if ENV_FILE.is_file():
        print(f"[OK]   .env 存在：{ENV_FILE}")
    else:
        print(f"[WARN] 没有 .env（可选）：{ENV_FILE}")

    offline = args.llm == "mock"
    if offline:
        print("[SKIP] 离线模式（--llm mock），不检查密钥与网络")
    elif cfg.llm.api_key:
        print(f"[OK]   API key 已设置（来源：{cfg.llm.api_key_source}，{mask_key(cfg.llm.api_key)}）")
    else:
        print("[FAIL] 没有找到 API key")
        for line in str(
            ConfigError(
                f"1) 打开 {ENV_FILE}\n"
                f"2) 把 DEEPSEEK_API_KEY= 后面补上 key 并保存\n"
                "3) 重新运行 doctor；只想验证代码路径可用 doctor --llm mock"
            )
        ).splitlines():
            print(f"       {line}")
        print()
        print("结论：配置未完成（退出码 2）")
        return 2

    try:
        cfg.run.out_dir.mkdir(parents=True, exist_ok=True)
        print(f"[OK]   输出目录可用：{cfg.run.out_dir}")
    except OSError as exc:
        print(f"[FAIL] 输出目录不可写：{cfg.run.out_dir}（{exc}）")
        return 2

    if not args.online:
        print()
        print("结论：本地配置就绪；加 --online 再做一次真实调用验证。")
        return 0

    print()
    print("--- 在线检查 ---")
    try:
        if args.llm == "deepseek":
            require_api_key(cfg)
        client = build_client(cfg.llm, args.llm)
        print(f"调用 {cfg.llm.model} …")
        result = client.chat(
            [{"role": "user", "content": "只回复两个字：pong"}],
            max_tokens=16,
        )
    except ConfigError as exc:
        print(f"[FAIL] {exc}")
        return 2
    except LLMError as exc:
        print(f"[FAIL] {exc}")
        if exc.retryable:
            print("       这是可重试错误；若反复出现，先把 llm.max_retries 调大或检查网络。")
        return 3
    except Exception as exc:  # noqa: BLE001 - doctor 要兜住一切，方便定位
        print(f"[FAIL] 未预期的错误：{type(exc).__name__}: {exc}")
        return 3

    usage = result.usage or {}
    hit = int(usage.get("cache_hit_tokens", 0))
    miss = int(usage.get("cache_miss_tokens", 0))
    out = int(usage.get("completion_tokens", 0))
    cost = estimate_cost(result.model or cfg.llm.model, cache_hit_tokens=hit, cache_miss_tokens=miss, output_tokens=out)

    print("[OK]   调用成功")
    print(_row("model", result.model))
    print(_row("system_fingerprint", result.system_fingerprint))
    print(_row("latency", f"{result.latency_ms:.0f} ms"))
    print(_row("tokens", f"prompt {usage.get('prompt_tokens', 0)}（cache hit {hit} / miss {miss}）"
                          f" | completion {out} | total {usage.get('total_tokens', 0)}"))
    cost_text = "—（mock 不产生费用）" if args.llm == "mock" else f"${cost:.7f}（{period_label()}价，估算）"
    print(_row("cost", cost_text))
    print(_row("reply", (result.content or "").strip()[:60]))
    print()
    print("结论：环境就绪（退出码 0）")
    return 0


# ---------------------------------------------------------------- run


def _read_trace(path: Path) -> list[dict[str, Any]]:
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def _render_trace(events: list[dict[str, Any]]) -> None:
    for event in events:
        kind = event["type"]
        turn = event["turn"]
        payload = event.get("payload") or {}
        if kind == "user_message":
            print(f"[T{turn} user]   {payload.get('content')}")
        elif kind == "memory_query":
            hits = payload.get("hits") or []
            detail = ", ".join(f"{h['id']}({h['score']:.2f})" for h in hits) if hits else "无命中"
            print(f"[T{turn} memory] {detail}")
        elif kind == "memory_hit":
            continue  # 已在上一条汇总
        elif kind == "tool_call":
            args = payload.get("arguments")
            text = json.dumps(args, ensure_ascii=False) if args is not None else payload.get("raw_arguments")
            print(f"[T{turn} tool←]  {payload.get('name')} {text}")
        elif kind == "tool_result":
            status = "ok" if payload.get("ok") else f"error: {payload.get('error')}"
            body = payload.get("result")
            count = body.get("count") if isinstance(body, dict) else None
            print(f"[T{turn} tool→]  {status}" + (f"  {count} 条记录" if count is not None else ""))
        elif kind == "assistant_message":
            text = str(payload.get("content") or "").replace("\n", "\n           ")
            print(f"[T{turn} agent]  {text}")
        elif kind == "error":
            print(f"[T{turn} error]  {payload.get('error')}")


def _collect_sensitive_pairs(persona: dict[str, Any], memory_records) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for field in persona.get("fields") or []:
        value = str(field.get("value") or "").strip()
        if value:
            pairs.append((f"persona:{field.get('key')}", value))
    for record in memory_records:
        for value in record.sensitive_values:
            pairs.append((record.id, value))
    return pairs


def _scan_disclosure(turn_defs, turn_results, pairs: list[tuple[str, str]]) -> list[tuple[str, str, bool]]:
    """返回 (turn_id, 命中标签, 是否授权轮次)。纯子串匹配，只作冒烟提示。"""
    rows: list[tuple[str, str, bool]] = []
    for turn_def, turn_result in zip(turn_defs, turn_results):
        text = turn_result.final_text or ""
        hit_labels = [label for label, value in pairs if value and value in text]
        for label in hit_labels:
            rows.append((turn_def.id, label, turn_def.expect_disclosure))
    return rows


def cmd_run(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
        scenario = load_scenario(args.scenario)
        persona = load_persona(scenario.persona_id)
    except (ConfigError, ScenarioError) as exc:
        print(f"[FAIL] {exc}")
        return 2

    if args.llm == "deepseek" and not cfg.llm.api_key:
        print("[FAIL] 没有 API key，无法调用真实模型；可先用 --llm mock 验证链路。")
        return 2

    # 记忆（可选）
    memory_records = []
    memory_index = None
    memory_conf = scenario.memory or {}
    top_k = int(memory_conf.get("top_k", 3))
    min_score = float(memory_conf.get("min_score", 0.0))
    if memory_conf.get("file"):
        try:
            memory_records = load_memory(DATA_DIR / "memory" / str(memory_conf["file"]), owner=scenario.persona_id)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] 记忆加载失败：{exc}")
            return 2
        memory_index = BM25Index(memory_records)

    try:
        client = build_client(cfg.llm, args.llm)
        if args.llm == "mock" and scenario.mock:
            client = MockLLM(
                content=scenario.mock.get("content"),
                tool_name=scenario.mock.get("tool_name"),
                tool_arguments=json.dumps(scenario.mock.get("tool_arguments") or {}, ensure_ascii=False),
            )
    except ConfigError as exc:
        print(f"[FAIL] {exc}")
        return 2

    registry = default_registry(persona)
    attacker_observable = set(scenario.threat_model.get("attacker_observable") or [])
    repeat = args.repeat if args.repeat is not None else cfg.run.repeat
    if repeat < 1:
        print("[FAIL] --repeat 必须 >= 1")
        return 2

    total_turns = len(scenario.turns)
    max_turns = args.turns if args.turns is not None else total_turns
    if max_turns < 1 or max_turns > total_turns:
        print(f"[FAIL] --turns 必须在 1..{total_turns} 之间")
        return 2

    print(f"== run {scenario.id} ×{repeat} ==")
    print(_row("scenario", f"{scenario.id}  {scenario.description}"))
    print(_row("persona", scenario.persona_id))
    print(_row("turns", f"{max_turns} / {total_turns}"))
    print(_row("llm", f"{cfg.llm.model}（thinking={cfg.llm.thinking}, temperature={cfg.llm.temperature}）"))
    print(_row("tools", ", ".join(registry.names())))
    if memory_index is not None:
        print(_row("memory", f"{len(memory_records)} 条（top_k={top_k}, min_score={min_score:g}, BM25 确定性）"))
    else:
        print(_row("memory", "未启用"))
    print(_row("attacker 可见", ", ".join(sorted(attacker_observable)) or "（无）"))
    print()

    exit_code = 0
    for index in range(1, repeat + 1):
        cfg.run.out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = unique_dir(cfg.run.out_dir, f"{stamp}_{scenario.id}_r{index}")
        run_id = run_dir.name

        meta = {
            "run_id": run_id,
            "scenario_id": scenario.id,
            "persona_id": scenario.persona_id,
            "repeat_index": index,
            "started_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "finished_at": None,
            "git_commit": _git_commit(),
            "python": platform.python_version(),
            "packages": {name: _pkg_version(name) for name in PACKAGES} | {"privacy-agent": __version__},
            "prompt_version": PROMPT_VERSION,
            "memory": {
                "template_version": MEMORY_TEMPLATE_VERSION,
                "retriever": "bm25-bigram",
                "top_k": top_k,
                "min_score": min_score,
                "record_count": len(memory_records),
            },
            "llm": {
                "provider": cfg.llm.provider,
                "base_url": cfg.llm.base_url,
                "model": cfg.llm.model,
                "thinking": cfg.llm.thinking,
                "temperature": cfg.llm.temperature,
                "max_tokens": cfg.llm.max_tokens,
                "backend": args.llm,
            },
            "threat_model": scenario.threat_model,
            "summary": None,
        }

        recorder = RunRecorder(run_dir, meta, attacker_observable=attacker_observable)
        try:
            outcome = run_conversation(
                client=client,
                registry=registry,
                recorder=recorder,
                turns=scenario.turns,
                system_prompt=SYSTEM_PROMPT,
                max_tool_rounds=cfg.agent.max_tool_rounds,
                memory_index=memory_index,
                top_k=top_k,
                min_score=min_score,
                max_turns=max_turns,
            )
        except LLMError as exc:
            recorder.finish({"stopped_reason": "llm_error", "error": str(exc)})
            print(f"[FAIL] {exc}")
            return 3

        usage = outcome.usage_total
        hit = int(usage.get("cache_hit_tokens", 0))
        miss = int(usage.get("cache_miss_tokens", 0))
        out = int(usage.get("completion_tokens", 0))
        cost = estimate_cost(cfg.llm.model, cache_hit_tokens=hit, cache_miss_tokens=miss, output_tokens=out)
        summary = {
            "stopped_reason": "final" if all(t.stopped_reason == "final" for t in outcome.turns) else "partial",
            "turns": len(outcome.turns),
            "llm_calls": outcome.llm_calls,
            "tool_calls": outcome.tool_calls,
            "usage": usage,
            "latency_ms": round(outcome.latency_total, 1),
            "cost_usd_estimate": round(cost, 8),
            "final_text": outcome.final_text,
            "turn_texts": [t.final_text for t in outcome.turns],
        }
        recorder.finish(summary)

        print(f"-- run {run_id} --")
        _render_trace(_read_trace(recorder.trace_path))
        print()
        print(_row("turns", f"{len(outcome.turns)} 轮 / {outcome.llm_calls} 次模型调用 / {outcome.tool_calls} 次工具调用"))
        print(_row("tokens", f"prompt {usage.get('prompt_tokens', 0)}（hit {hit} / miss {miss}）"
                              f" | completion {out} | total {usage.get('total_tokens', 0)}"))
        print(_row("latency", f"{outcome.latency_total:.0f} ms"))
        print(_row("cost", "—（mock 不产生费用）" if args.llm == "mock" else f"${cost:.7f}（{period_label()}价，估算）"))
        print(_row("trace", recorder.trace_path))

        rows = _scan_disclosure(
            scenario.turns[:max_turns],
            outcome.turns,
            _collect_sensitive_pairs(persona, memory_records),
        )
        if not rows:
            print(_row("敏感值", "未命中（仅子串检查，非第三阶段指标）"))
        else:
            print(_row("敏感值", "命中如下（仅子串检查，非第三阶段指标）"))
            for turn_id, label, authorized in rows:
                flag = "授权披露（预期）" if authorized else "非请求命中"
                print(f"  {turn_id:<4} {label:<22} {flag}")
        print()

        if any(t.stopped_reason != "final" for t in outcome.turns):
            exit_code = 4

    return exit_code


# ---------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="privacy_agent", description="多轮 Agent 隐私泄露实验平台")
    parser.add_argument("--version", action="version", version=f"privacy-agent {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="检查环境、配置与 API 连通性")
    doctor.add_argument("--config", type=Path, default=None, help="配置文件路径，默认 configs/default.yaml")
    doctor.add_argument("--online", action="store_true", help="额外做一次真实 API 调用")
    doctor.add_argument("--llm", choices=["deepseek", "mock"], default="deepseek", help="后端，mock 为离线")
    doctor.set_defaults(func=cmd_doctor)

    run = sub.add_parser("run", help="跑一个场景并记录日志")
    run.add_argument("--scenario", default="s0", help="场景 id 或 YAML 路径，默认 s0")
    run.add_argument("--turns", type=int, default=None, help="只跑前 N 轮，默认全部")
    run.add_argument("--llm", choices=["deepseek", "mock"], default="deepseek", help="后端，mock 为离线")
    run.add_argument("--repeat", type=int, default=None, help="重复次数，默认取配置里的 run.repeat")
    run.add_argument("--config", type=Path, default=None, help="配置文件路径")
    run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    _use_utf8_when_redirected()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
