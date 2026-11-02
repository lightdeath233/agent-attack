"""命令行入口：python -m privacy_agent.cli <command>"""

from __future__ import annotations

import argparse
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from . import __version__
from .config import ENV_FILE, ConfigError, load_config, mask_key, require_api_key
from .llm import LLMError, build_client
from .pricing import estimate_cost, period_label

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


def _row(label: str, value: Any) -> str:
    return f"{label:<{LABEL_WIDTH}}{value}"


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="privacy_agent", description="多轮 Agent 隐私泄露实验平台")
    parser.add_argument("--version", action="version", version=f"privacy-agent {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="检查环境、配置与 API 连通性")
    doctor.add_argument("--config", type=Path, default=None, help="配置文件路径，默认 configs/default.yaml")
    doctor.add_argument("--online", action="store_true", help="额外做一次真实 API 调用")
    doctor.add_argument("--llm", choices=["deepseek", "mock"], default="deepseek", help="后端，mock 为离线")
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    _use_utf8_when_redirected()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
