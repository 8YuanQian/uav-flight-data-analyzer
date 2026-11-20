# 运行工具和评估共用检索配置，编码方式也参与评估记录。
from dataclasses import dataclass
from math import isfinite

from src.rag.embedding import EMBEDDING_ENCODINGS, LEGACY_ENCODING, EmbeddingEncoding


@dataclass(frozen=True)
class RetrievalConfig:
    candidate_k: int = 10
    max_cosine_distance: float = 0.5
    final_k: int = 3
    min_rerank_score: float = 0.77
    encoding: EmbeddingEncoding = LEGACY_ENCODING

    def __post_init__(self):
        if self.encoding not in EMBEDDING_ENCODINGS:
            raise ValueError("向量编码方式无效")
        for name in ("candidate_k", "final_k"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} 必须是正整数")
        if self.final_k > self.candidate_k:
            raise ValueError("final_k 不能大于 candidate_k")
        if not isfinite(self.max_cosine_distance) or not 0 <= self.max_cosine_distance <= 2:
            raise ValueError("余弦距离上限必须在 0 至 2 之间")
        if not isfinite(self.min_rerank_score):
            raise ValueError("重排分数下限必须为有限数值")


DEFAULT_RETRIEVAL_CONFIG = RetrievalConfig()
