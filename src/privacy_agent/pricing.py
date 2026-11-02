"""DeepSeek 价格表与费用估算（单位：美元）。

单价来源：https://api-docs.deepseek.com/quick_start/pricing
抓取时间：2026-11-02。

注意：
- 高峰时段为 UTC 周一至周五 01:00-04:00 与 06:00-10:00（不含中国法定节假日），
  其余为低谷价（半价）。本模块按 UTC 判断，不考虑节假日，因此估算值只作量级参考，
  论文里请以平台账单为准并记录账单口径。
- 缓存命中价（cache hit）远低于未命中价，所以同一份长 system prompt 反复使用时，
  实测费用会明显低于按“全量未命中”估算的费用。
"""

from __future__ import annotations

from datetime import datetime, timezone

# 每 1M tokens 单价，(低谷, 高峰)
PRICES: dict[str, dict[str, tuple[float, float]]] = {
    "deepseek-flash": {
        "cache_hit": (0.003, 0.006),
        "cache_miss": (0.15, 0.30),
        "output": (0.60, 1.20),
    },
    "deepseek-v4-pro": {
        "cache_hit": (0.022, 0.044),
        "cache_miss": (0.66, 1.32),
        "output": (1.98, 3.96),
    },
}

PEAK_HOURS_UTC = ((1, 4), (6, 10))  # [start, end) 左闭右开


def is_peak(when: datetime | None = None) -> bool:
    """是否为高峰计费时段（UTC 工作日）。"""
    now = when or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    if now.weekday() >= 5:  # 周六、周日
        return False
    return any(start <= now.hour < end for start, end in PEAK_HOURS_UTC)


def estimate_cost(
    model: str,
    *,
    cache_hit_tokens: int = 0,
    cache_miss_tokens: int = 0,
    output_tokens: int = 0,
    when: datetime | None = None,
) -> float:
    """按 token 数估算单次调用费用；模型不在价格表里时按 deepseek-flash 计。"""
    table = PRICES.get(model, PRICES["deepseek-flash"])
    idx = 1 if is_peak(when) else 0
    return (
        cache_hit_tokens / 1_000_000 * table["cache_hit"][idx]
        + cache_miss_tokens / 1_000_000 * table["cache_miss"][idx]
        + output_tokens / 1_000_000 * table["output"][idx]
    )


def period_label(when: datetime | None = None) -> str:
    return "高峰" if is_peak(when) else "低谷"
