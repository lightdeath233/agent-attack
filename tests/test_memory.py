from __future__ import annotations

import json

import pytest

from privacy_agent.memory import BM25Index, MemoryRecord, load_memory, tokenize
from privacy_agent.memory.context import format_memory_block


def _records():
    return [
        MemoryRecord(id="m1", text="客户张敏的手机号是 13900005678。", owner="p001", sensitive_values=("13900005678",)),
        MemoryRecord(id="m2", text="项目周会每周二 11:00 在线上举行。", owner="p001"),
        MemoryRecord(id="m3", text="差旅报销需要月底前提交发票。", owner="p001"),
        MemoryRecord(id="m4", text="张伟习惯把客户对接会安排在上午。", owner="p001"),
    ]


def test_tokenizer_splits_cjk_into_bigrams():
    assert tokenize("张敏") == ["张敏"]
    assert tokenize("手机号") == ["手机", "机号"]
    assert "abc" in tokenize("ABC 123")
    assert "123" in tokenize("ABC 123")


def test_search_is_deterministic():
    index = BM25Index(_records())
    first = [hit.record.id for hit in index.search("张敏的手机号", top_k=3)]
    second = [hit.record.id for hit in index.search("张敏的手机号", top_k=3)]
    assert first == second
    assert first[0] == "m1"


def test_top_k_respected():
    index = BM25Index(_records())
    assert len(index.search("会议 报销 手机号", top_k=2)) == 2


def test_no_overlap_returns_empty():
    index = BM25Index(_records())
    assert index.search("量子计算", top_k=3) == []


def test_min_score_filters():
    index = BM25Index(_records())
    hits = index.search("张敏的手机号", top_k=3)
    assert hits, "至少要有一条命中"
    strict = index.search("张敏的手机号", top_k=3, min_score=hits[0].score + 1)
    assert strict == []


def test_format_block_is_versioned_and_numbered():
    index = BM25Index(_records())
    block = format_memory_block(index.search("张敏的手机号", top_k=2))
    assert block is not None
    assert block.startswith("[记忆检索结果]")
    assert "1. " in block


def test_format_block_empty():
    assert format_memory_block([]) is None


def test_load_memory_roundtrip(tmp_path):
    path = tmp_path / "mem.jsonl"
    rows = [
        {"id": "a", "owner": "p001", "text": "x", "sensitive_values": ["1"]},
        {"id": "b", "owner": "p002", "text": "y"},
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")

    all_records = load_memory(path)
    assert [r.id for r in all_records] == ["a", "b"]

    only_p001 = load_memory(path, owner="p001")
    assert [r.id for r in only_p001] == ["a"]
    assert only_p001[0].sensitive_values == ("1",)


def test_load_memory_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "mem.jsonl"
    path.write_text(
        json.dumps({"id": "a", "owner": "p", "text": "x"}) + "\n"
        + json.dumps({"id": "a", "owner": "p", "text": "y"}),
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="重复"):
        load_memory(path)


def test_load_memory_rejects_bad_json(tmp_path):
    path = tmp_path / "mem.jsonl"
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(Exception, match="合法 JSON"):
        load_memory(path)
