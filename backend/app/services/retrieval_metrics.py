"""
Information retrieval metrics for evaluating code retrieval quality:
Precision@K, Recall@K, and Mean Reciprocal Rank (MRR).
"""

from typing import Sequence, Set


def precision_at_k(retrieved_paths: Sequence[str], relevant_paths: Set[str], k: int) -> float:
    """Calculate Precision@K: fraction of the top-K retrieved items that are relevant.

    Precision@K = |{retrieved[:k]} ∩ {relevant}| / k

    Args:
        retrieved_paths: Ordered list of retrieved file paths.
        relevant_paths: Set of ground-truth relevant file paths.
        k: Cut-off rank.

    Returns:
        Precision in the range [0.0, 1.0].
    """
    if k <= 0 or not retrieved_paths:
        return 0.0

    top_k_paths = retrieved_paths[:k]
    # Check if any relevant path is contained in or equals retrieved path
    relevant_hits = sum(
        1 for p in top_k_paths
        if any(rel in p or p in rel for rel in relevant_paths)
    )
    return relevant_hits / k


def recall_at_k(retrieved_paths: Sequence[str], relevant_paths: Set[str], k: int) -> float:
    """Calculate Recall@K: fraction of all relevant items retrieved in the top-K.

    Recall@K = |{retrieved[:k]} ∩ {relevant}| / |relevant|

    Args:
        retrieved_paths: Ordered list of retrieved file paths.
        relevant_paths: Set of ground-truth relevant file paths.
        k: Cut-off rank.

    Returns:
        Recall in the range [0.0, 1.0].
    """
    if not relevant_paths or k <= 0 or not retrieved_paths:
        return 0.0

    top_k_paths = retrieved_paths[:k]
    matched_relevant = set()
    for rel in relevant_paths:
        if any(rel in p or p in rel for p in top_k_paths):
            matched_relevant.add(rel)

    return len(matched_relevant) / len(relevant_paths)


def reciprocal_rank(retrieved_paths: Sequence[str], relevant_paths: Set[str]) -> float:
    """Calculate Reciprocal Rank (RR): reciprocal of the 1-based rank of the first relevant hit.

    RR = 1 / rank_first_hit (or 0.0 if no relevant item is found).

    Args:
        retrieved_paths: Ordered list of retrieved file paths.
        relevant_paths: Set of ground-truth relevant file paths.

    Returns:
        Reciprocal rank in the range [0.0, 1.0].
    """
    for idx, path in enumerate(retrieved_paths, start=1):
        if any(rel in path or path in rel for rel in relevant_paths):
            return 1.0 / idx
    return 0.0


def mean_reciprocal_rank(
    query_evaluations: Sequence[tuple[Sequence[str], Set[str]]]
) -> float:
    """Calculate Mean Reciprocal Rank (MRR) across multiple queries.

    MRR = (1 / |Q|) * sum_{q in Q} RR(q)

    Args:
        query_evaluations: Sequence of (retrieved_paths, relevant_paths) tuples.

    Returns:
        Mean Reciprocal Rank in the range [0.0, 1.0].
    """
    if not query_evaluations:
        return 0.0

    total_rr = sum(
        reciprocal_rank(retrieved, relevant)
        for retrieved, relevant in query_evaluations
    )
    return total_rr / len(query_evaluations)
