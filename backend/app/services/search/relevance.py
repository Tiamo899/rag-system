"""相关性判定：主流程与调试台共用同一套判据，避免两套逻辑漂移。

判定顺序：
    1. 无候选 → 不相关
    2. RRF 分达标 或 余弦相似度达标 → 相关（双判据取或）
    3. 余弦不可用（Embedding 服务异常）但有关键词候选 → 相关，并标记降级
       —— 单路召回时 RRF 上限只有 1/(k+1)，双路阈值永远达不到；
       此时若仍判"不相关"，会把本可回答的问题一律推给兜底文案。
    4. 其余 → 不相关
"""
from dataclasses import dataclass


@dataclass
class RelevanceDecision:
    is_relevant: bool
    rrf_pass: bool
    cosine_pass: bool
    degraded: bool
    reason: str


def decide_relevance(
    top_rrf: float,
    top_cosine: float,
    rrf_threshold: float,
    cos_threshold: float,
    cos_available: bool,
    has_candidates: bool,
) -> RelevanceDecision:
    if not has_candidates:
        return RelevanceDecision(
            is_relevant=False,
            rrf_pass=False,
            cosine_pass=False,
            degraded=False,
            reason="两路均无候选 → 走兜底文案",
        )

    rrf_pass = top_rrf >= rrf_threshold
    cosine_pass = cos_available and top_cosine >= cos_threshold

    if rrf_pass or cosine_pass:
        hits = "、".join(
            [n for n, ok in (("RRF 分", rrf_pass), ("余弦", cosine_pass)) if ok]
        )
        return RelevanceDecision(
            is_relevant=True,
            rrf_pass=rrf_pass,
            cosine_pass=cosine_pass,
            degraded=False,
            reason=f"判为相关（{hits}达标，双判据取或）",
        )

    if not cos_available:
        return RelevanceDecision(
            is_relevant=True,
            rrf_pass=rrf_pass,
            cosine_pass=False,
            degraded=True,
            reason="向量服务不可用，降级为关键词检索结果作答（结果可能不完整）",
        )

    return RelevanceDecision(
        is_relevant=False,
        rrf_pass=False,
        cosine_pass=False,
        degraded=False,
        reason="双判据均未达标 → 判为不相关，走兜底文案",
    )
