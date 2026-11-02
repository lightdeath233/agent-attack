"""配置加载。

优先级：环境变量 > .env > configs/default.yaml > 代码内默认值。

之所以把密钥单独走环境变量/.env，而不是写进 YAML：
YAML 是要提交进 git 的，密钥不是。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "default.yaml"
ENV_FILE = REPO_ROOT / ".env"

ALLOWED_MODELS = ("deepseek-flash", "deepseek-v4-pro")
ALLOWED_THINKING = ("disabled", "enabled")
API_KEY_VAR = "DEEPSEEK_API_KEY"


class ConfigError(RuntimeError):
    """配置缺失、字段非法或密钥未设置。"""


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    base_url: str
    model: str
    thinking: str
    temperature: float
    max_tokens: int
    timeout_s: float
    max_retries: int
    api_key: str | None
    api_key_source: str  # ".env" | "环境变量" | "未设置"

    @property
    def thinking_enabled(self) -> bool:
        return self.thinking == "enabled"


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path
    repeat: int


@dataclass(frozen=True)
class AppConfig:
    llm: LLMConfig
    run: RunConfig
    source: Path


def mask_key(key: str | None) -> str:
    """只保留前 3 位和后 4 位，日志与终端里都用它。"""
    if not key:
        return "<未设置>"
    k = key.strip()
    if len(k) <= 8:
        return "*" * len(k)
    return f"{k[:3]}****{k[-4:]}"


def _key_from_env_file() -> str | None:
    """直接读 .env 文件，用于区分“密钥来自 .env”还是“来自当前会话环境变量”。"""
    if not ENV_FILE.is_file():
        return None
    for raw in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == API_KEY_VAR:
            value = value.strip().strip('"').strip("'")
            return value or None
    return None


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"找不到配置文件：{path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件不是合法 YAML：{path}\n{exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件顶层必须是键值映射：{path}")
    return data


def _as_number(value: Any, name: str, *, integer: bool = False) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"配置项 {name} 必须是数字，当前为 {value!r}")
    return int(value) if integer else float(value)


def load_config(path: Path | str | None = None) -> AppConfig:
    """加载配置。任何一处不合法都抛 ConfigError，不静默兜底。"""
    load_dotenv(ENV_FILE, override=False)

    cfg_path = Path(path).expanduser() if path else DEFAULT_CONFIG_PATH
    data = _read_yaml(cfg_path)

    raw_llm = data.get("llm") or {}
    raw_run = data.get("run") or {}
    if not isinstance(raw_llm, dict):
        raise ConfigError("配置项 llm 必须是键值映射")
    if not isinstance(raw_run, dict):
        raise ConfigError("配置项 run 必须是键值映射")

    model = str(os.environ.get("DEEPSEEK_MODEL") or raw_llm.get("model") or "deepseek-flash")
    if model not in ALLOWED_MODELS:
        raise ConfigError(
            f"不支持的模型 {model!r}，可选：{', '.join(ALLOWED_MODELS)}\n"
            "注意 deepseek-chat / deepseek-reasoner 已不在 2026-11 的官方文档中。"
        )

    thinking = str(raw_llm.get("thinking") or "disabled").lower()
    if thinking not in ALLOWED_THINKING:
        raise ConfigError(f"配置项 llm.thinking 只能是 {'/'.join(ALLOWED_THINKING)}，当前为 {thinking!r}")

    temperature = _as_number(raw_llm.get("temperature", 0.0), "llm.temperature")
    if not 0.0 <= temperature <= 2.0:
        raise ConfigError(f"llm.temperature 必须在 [0, 2] 之间，当前为 {temperature}")

    max_tokens = _as_number(raw_llm.get("max_tokens", 1024), "llm.max_tokens", integer=True)
    if not 1 <= max_tokens <= 393216:
        raise ConfigError(f"llm.max_tokens 必须在 [1, 393216] 之间，当前为 {max_tokens}")

    timeout_s = _as_number(raw_llm.get("timeout_s", 60), "llm.timeout_s")
    if timeout_s <= 0:
        raise ConfigError(f"llm.timeout_s 必须为正数，当前为 {timeout_s}")

    max_retries = _as_number(raw_llm.get("max_retries", 3), "llm.max_retries", integer=True)
    if not 0 <= max_retries <= 10:
        raise ConfigError(f"llm.max_retries 必须在 [0, 10] 之间，当前为 {max_retries}")

    repeat = _as_number(raw_run.get("repeat", 1), "run.repeat", integer=True)
    if repeat < 1:
        raise ConfigError(f"run.repeat 必须 >= 1，当前为 {repeat}")

    out_dir = Path(str(raw_run.get("out_dir") or "runs"))
    if not out_dir.is_absolute():
        out_dir = (cfg_path.parent.parent / out_dir).resolve()

    env_key = os.environ.get(API_KEY_VAR)
    file_key = _key_from_env_file()
    if env_key:
        api_key = env_key.strip() or None
        source = ".env" if file_key and env_key.strip() == file_key else "环境变量"
    elif file_key:
        api_key, source = file_key, ".env"
    else:
        api_key, source = None, "未设置"

    return AppConfig(
        llm=LLMConfig(
            provider=str(raw_llm.get("provider") or "deepseek"),
            base_url=str(os.environ.get("DEEPSEEK_BASE_URL") or raw_llm.get("base_url") or "https://api.deepseek.com"),
            model=model,
            thinking=thinking,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            max_retries=max_retries,
            api_key=api_key,
            api_key_source=source,
        ),
        run=RunConfig(out_dir=out_dir, repeat=repeat),
        source=cfg_path,
    )


def require_api_key(cfg: AppConfig) -> str:
    key = cfg.llm.api_key
    if key:
        return key
    raise ConfigError(
        "没有找到 DeepSeek API key。\n"
        f"  1) 打开 {ENV_FILE}\n"
        f"  2) 把 {API_KEY_VAR}= 后面补上你的 key 并保存\n"
        f"  3) 重新运行 doctor 确认（终端只会显示 {mask_key('sk-0123456789ab')} 这种脱敏值）\n"
        "如果只想验证代码路径而不联网，用：doctor --llm mock"
    )
