# 多轮交互 LLM Agent 隐私泄露评估平台

硕士论文《面向多轮交互的 LLM 智能体隐私泄露评估与动态防护方法研究》的实验代码。

**当前状态：第一阶段（P1.1–P1.4）** —— 环境、配置、DeepSeek 客户端、`doctor` 自检。
尚未包含：长期记忆、多轮循环、攻击者、评估指标、防御策略。

## 环境要求

- Windows 10/11 + PowerShell 5.1（实测：Windows 11 26200 / PowerShell 5.1）
- Python 3.11+（实测 3.13.7，仓库只用标准库 + 少量纯 Python 依赖）
- DeepSeek API key

## 安装

```powershell
cd D:\code\agent-attack
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> 本机直连 PyPI 实测会长时间卡在解析/下载阶段，因此默认走清华镜像。
> 如果镜像也不稳，换 `-i https://mirrors.aliyun.com/pypi/simple`。

不需要激活虚拟环境，直接调 `.\.venv\Scripts\python.exe` 即可，这样可以绕开
PowerShell 执行策略对 `Activate.ps1` 的限制。

## 配置 API key

```powershell
notepad D:\code\agent-attack\.env
```

把这一行补全后保存：

```
DEEPSEEK_API_KEY=sk-你的key
```

安全约定：

- `.env` 已在 `.gitignore` 中，不会被提交；
- `doctor` 只显示 `sk-****abcd` 形式的脱敏值；
- 不要把 key 写进 `configs/*.yaml`、代码、日志或对话。

## 自检

```powershell
.\.venv\Scripts\python.exe -m privacy_agent.cli doctor            # 只查配置
.\.venv\Scripts\python.exe -m privacy_agent.cli doctor --online   # 额外做一次真实调用
.\.venv\Scripts\python.exe -m privacy_agent.cli doctor --llm mock # 不联网，验证代码路径
```

`doctor` 退出码：`0` 正常，`2` 配置/密钥问题，`3` 网络或 API 问题。

期望输出（`--online`）：

```
[OK]   调用成功
model              deepseek-flash
system_fingerprint fp_...
latency            812 ms
tokens             prompt 24（cache hit 0 / miss 24） | completion 3 | total 27
cost               $0.0000340（低谷价，估算）
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

全部测试走 `MockLLM`，不联网、不产生费用。

## 目录结构

```
src/privacy_agent/
  config.py      # YAML + .env 加载、校验、密钥脱敏
  pricing.py     # DeepSeek 价格表与费用估算（高峰/低谷）
  cli.py         # doctor 子命令
  llm/
    base.py      # LLMResult / LLMError / 协议
    deepseek.py  # openai SDK + DeepSeek 兼容端点
    mock.py      # 离线确定性后端
configs/default.yaml  # 模型、thinking、temperature、重试
tests/                # 单元测试（离线）
runs/                 # 实验产物，gitignore
docs/00-phase1-plan.md  # 第一阶段实施方案
```

## 几个刻意的设计决定

1. **显式关闭 thinking**。DeepSeek 默认开启思考模式，且思考模式下 `temperature` 无效、
   输出 token 大增。第一阶段要的是可比与便宜，所以配置里写死 `thinking: disabled`。
2. **不用 `deepseek-chat`**。2026-11 的官方文档只有 `deepseek-flash` / `deepseek-v4-pro`。
3. **没有 seed 可用**。Chat Completions 无 `seed` 参数，`temperature=0` 也不保证可复现，
   后续实验必须靠重复采样（N 次）来估计方差，并记录响应里的 `system_fingerprint`。
4. **密钥与配置分离**。YAML 进版本库，密钥只走 `.env`/环境变量。

## 下一步（P1.5）

单轮 Agent + 一个工具（`calendar_query`）的完整 tool calling 闭环，并落地 JSONL 事件日志。
