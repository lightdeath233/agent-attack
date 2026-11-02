from __future__ import annotations

from pathlib import Path

import pytest

import privacy_agent.config as config_mod
from privacy_agent.config import ConfigError, load_config, mask_key


@pytest.fixture(autouse=True)
def _isolate_dotenv(tmp_path, monkeypatch):
    """把 .env 指到一个不存在的文件。

    否则开发者本机真实的 .env 会渗进单元测试：既让断言随机器而变，
    也可能把真实 key 打进 pytest 的回溯输出里。
    """
    monkeypatch.setattr(config_mod, "ENV_FILE", tmp_path / "nonexistent.env")


def test_mask_key_short():
    assert mask_key(None) == "<未设置>"
    assert mask_key("") == "<未设置>"
    assert mask_key("abc") == "***"


def test_mask_key_long():
    masked = mask_key("sk-1234567890abcdef")
    assert masked.startswith("sk-")
    assert masked.endswith("cdef")
    assert "1234567890" not in masked


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "c.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_defaults_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    cfg = load_config(_write(tmp_path, "llm:\n  model: deepseek-flash\n  thinking: disabled\n"))
    assert cfg.llm.model == "deepseek-flash"
    assert cfg.llm.thinking_enabled is False
    assert cfg.llm.api_key is None
    assert cfg.llm.api_key_source == "未设置"


def test_env_overrides_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-abcdefghijkl")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    cfg = load_config(_write(tmp_path, "llm:\n  model: deepseek-flash\n"))
    assert cfg.llm.model == "deepseek-v4-pro"
    assert cfg.llm.api_key == "sk-test-abcdefghijkl"


def test_unknown_model_rejected(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    with pytest.raises(ConfigError, match="不支持的模型"):
        load_config(_write(tmp_path, "llm:\n  model: deepseek-chat\n"))


def test_invalid_thinking_rejected(tmp_path):
    with pytest.raises(ConfigError, match="thinking"):
        load_config(_write(tmp_path, "llm:\n  thinking: sometimes\n"))


def test_temperature_range(tmp_path):
    with pytest.raises(ConfigError, match="temperature"):
        load_config(_write(tmp_path, "llm:\n  temperature: 3\n"))


def test_agent_defaults(tmp_path):
    cfg = load_config(_write(tmp_path, "llm:\n  model: deepseek-flash\n"))
    assert cfg.agent.max_tool_rounds == 6


def test_missing_file():
    with pytest.raises(ConfigError, match="找不到配置文件"):
        load_config(Path("does-not-exist.yaml"))
