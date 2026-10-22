"""向量服务测试：hash 兜底向量的确定性与余弦合理性（无网络、无重型依赖）。"""
from __future__ import annotations

import math

from app.services.embedding import FALLBACK_DIM, EmbeddingService


def test_fallback_is_deterministic_across_instances() -> None:
    text = "开源项目工厂：GitHub 仓库智能推荐系统"
    first = EmbeddingService(force_fallback=True).encode([text])[0]
    second = EmbeddingService(force_fallback=True).encode([text])[0]
    assert first == second  # 跨实例（跨运行）完全一致
    assert len(first) == FALLBACK_DIM
    assert abs(math.sqrt(sum(x * x for x in first)) - 1.0) < 1e-9  # L2 归一化


def test_cosine_sanity() -> None:
    service = EmbeddingService(force_fallback=True)
    a, b, c = service.encode(
        ["python fastapi 后端服务", "python fastapi 后端服务", "电影 音乐 摄影"]
    )
    assert abs(service.cosine(a, b) - 1.0) < 1e-9  # 相同文本相似度为 1
    assert service.cosine(a, c) < service.cosine(a, b)  # 不同文本更不相似
    assert service.cosine(a, c) < 0.9


def test_encode_edge_cases() -> None:
    service = EmbeddingService(force_fallback=True)
    assert service.encode([]) == []
    zero = service.encode([""])[0]
    assert len(zero) == FALLBACK_DIM
    assert service.cosine(zero, zero) == 0.0  # 零向量不参与相似度
    assert service.cosine([1.0, 2.0], [1.0]) == 0.0  # 维度不一致返回 0


def test_encode_batch_consistent_with_single() -> None:
    service = EmbeddingService(force_fallback=True)
    texts = ["alpha beta gamma", "第二条测试文本"]
    batch = service.encode(texts)
    assert len(batch) == 2
    assert batch[0] == service.encode_one(texts[0])
