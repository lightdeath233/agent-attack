"""确定性检索：BM25 + 中文字符二元组。

为什么不用向量检索（第一版）：
- 第四阶段要单独调"记忆规模"这个变量，检索器必须是固定的、可复现的，
  否则 10 条和 200 条的差异无法归因到规模本身；
- 向量检索会引入 embedding 模型（另一个版本、另一份成本、另一种漂移），
  在还没确认"记忆会不会导致泄露"之前，不值得引入。

分词：中文按字符二元组（bigram），字母数字按连续串。没有 jieba 这类词典依赖，
结果完全由输入决定，同一个查询在两次运行里一定返回同一个排序。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .store import MemoryRecord

_LATIN = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    lowered = (text or "").lower()
    tokens: list[str] = []
    tokens.extend(_LATIN.findall(lowered))
    for run in _CJK.findall(lowered):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


@dataclass(frozen=True)
class MemoryHit:
    record: MemoryRecord
    score: float


class BM25Index:
    """一个很小的 BM25，只做确定性排序，不做任何学习或近似。"""

    def __init__(self, records: list[MemoryRecord], *, k1: float = 1.5, b: float = 0.75):
        self.records = list(records)
        self.k1 = k1
        self.b = b
        self._docs = [tokenize(record.text) for record in self.records]
        self._tf = [Counter(doc) for doc in self._docs]
        self._df: Counter[str] = Counter()
        for doc in self._docs:
            self._df.update(set(doc))
        self._n = len(self.records)
        self._avgdl = (sum(len(doc) for doc in self._docs) / self._n) if self._n else 0.0

    def __len__(self) -> int:
        return self._n

    def search(self, query: str, top_k: int = 3, min_score: float = 0.0) -> list[MemoryHit]:
        if not self._n or top_k <= 0:
            return []
        terms = set(tokenize(query))
        scores: dict[int, float] = {}
        for term in terms:
            df = self._df.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1 + (self._n - df + 0.5) / (df + 0.5))
            for index, tf in enumerate(self._tf):
                freq = tf.get(term, 0)
                if not freq:
                    continue
                length = len(self._docs[index]) or 1
                denom = freq + self.k1 * (1 - self.b + self.b * length / (self._avgdl or 1))
                scores[index] = scores.get(index, 0.0) + idf * freq * (self.k1 + 1) / denom

        ranked = sorted(scores.items(), key=lambda item: (-item[1], self.records[item[0]].id))
        hits = [
            MemoryHit(record=self.records[index], score=round(score, 4))
            for index, score in ranked
            if score > min_score
        ]
        return hits[:top_k]
