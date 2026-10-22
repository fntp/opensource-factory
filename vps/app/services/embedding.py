"""文本向量化服务。

优先加载真实模型（BGE-M3）：sentence-transformers → FlagEmbedding；
未安装重型依赖时使用**确定性 hash 兜底向量**（256 维、字符 trigram 稳定哈希、L2 归一化），
保证任何环境（含 CI / 测试）都能跑通，且跨运行结果完全一致。
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Optional, Sequence

from app.config import get_settings

logger = logging.getLogger(__name__)

FALLBACK_DIM = 256
_WHITESPACE_RE = re.compile(r"\s+")


class EmbeddingService:
    """向量化服务（懒加载模型；可用 `force_fallback=True` 强制走 hash 兜底）。"""

    def __init__(self, model_name: str | None = None, *, force_fallback: bool = False) -> None:
        settings = get_settings()
        self.model_name: str = model_name or settings.EMBEDDING_MODEL
        self.force_fallback: bool = force_fallback
        self._backend: Optional[str] = None  # 'sentence-transformers' | 'flagembedding' | 'hash'
        self._model: object | None = None

    # ------------------------------------------------------------------ 后端

    @property
    def backend(self) -> str:
        """当前使用的后端名称（首次访问时触发懒加载）。"""
        if self._backend is None:
            self._load_backend()
        return self._backend or "hash"

    def _load_backend(self) -> str:
        """按优先级尝试加载真实模型；全部失败则降级为 hash。"""
        if self._backend is not None:
            return self._backend
        if self.force_fallback:
            self._backend = "hash"
            return self._backend

        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

            self._model = SentenceTransformer(self.model_name)
            self._backend = "sentence-transformers"
            logger.info("嵌入后端: sentence-transformers (%s)", self.model_name)
            return self._backend
        except Exception as exc:  # noqa: BLE001 - 未安装或加载失败都走降级
            logger.info("sentence-transformers 不可用: %s", exc)

        try:
            from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-not-found]

            self._model = BGEM3FlagModel(self.model_name, use_fp16=True)
            self._backend = "flagembedding"
            logger.info("嵌入后端: FlagEmbedding (%s)", self.model_name)
            return self._backend
        except Exception as exc:  # noqa: BLE001 - 同上
            logger.info("FlagEmbedding 不可用: %s", exc)

        self._backend = "hash"
        logger.warning("未安装向量模型依赖，使用确定性 hash 兜底向量（dim=%d）", FALLBACK_DIM)
        return self._backend

    # ------------------------------------------------------------------ 编码

    def encode(self, texts: list[str]) -> list[list[float]]:
        """批量编码为 L2 归一化向量。"""
        if not texts:
            return []
        backend = self._load_backend()
        if backend == "sentence-transformers":
            vectors = self._model.encode(texts, normalize_embeddings=True)  # type: ignore[union-attr]
            return [[float(x) for x in vec] for vec in vectors]
        if backend == "flagembedding":
            out = self._model.encode(texts, batch_size=8, max_length=2048)  # type: ignore[union-attr]
            dense = out["dense_vecs"]
            return [self.normalize([float(x) for x in vec]) for vec in dense]
        return [self._hash_encode(text) for text in texts]

    def encode_one(self, text: str) -> list[float]:
        """单条编码。"""
        vectors = self.encode([text])
        return vectors[0] if vectors else []

    # ------------------------------------------------------------ hash 兜底

    @staticmethod
    def _trigrams(text: str) -> list[str]:
        """字符 trigram 切分（中文按字、英文按字符窗口；短文本回退整串）。"""
        normalized = _WHITESPACE_RE.sub(" ", (text or "").strip().lower())
        if not normalized:
            return []
        if len(normalized) < 3:
            return [normalized]
        return [normalized[i : i + 3] for i in range(len(normalized) - 2)]

    def _hash_encode(self, text: str) -> list[float]:
        """确定性 hash 向量：trigram → blake2b → 下标 + 符号累加 → L2 归一化。"""
        vector = [0.0] * FALLBACK_DIM
        for token in self._trigrams(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            index = value % FALLBACK_DIM
            sign = 1.0 if (value >> 16) & 1 else -1.0
            vector[index] += sign
        return self.normalize(vector)

    # ------------------------------------------------------------------ 工具

    @staticmethod
    def normalize(vector: Sequence[float]) -> list[float]:
        """L2 归一化（零向量原样返回）。"""
        norm = math.sqrt(sum(x * x for x in vector))
        if norm <= 0:
            return [0.0] * len(vector)
        return [x / norm for x in vector]

    @staticmethod
    def cosine(a: Sequence[float], b: Sequence[float]) -> float:
        """余弦相似度；维度不一致或存在零向量时返回 0.0。"""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a <= 0 or norm_b <= 0:
            return 0.0
        return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """获取全局向量化服务单例。"""
    global _service
    if _service is None:
        _service = EmbeddingService()
    return _service
