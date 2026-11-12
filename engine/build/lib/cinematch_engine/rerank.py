"""Diversity reranking (MMR) and Discovery Mode (spec section 6.8).

From the top 100 films by blend score, pick one film at a time:
    next = argmax [ lambda * relevance(i) - (1 - lambda) * max_similarity(i, picked) + beta * novelty(i) ]
relevance = blend score scaled 0-1, similarity = content cosine, novelty = -log(popularity share)
scaled 0-1. Discover also gives a small boost to films outside the user's languages and to genres
that are rare in the user's history.
"""
import numpy as np

# tail_share: the share of a list reserved for less-known films (the long-tail channel, see tail_slots below).
# Chosen from pipeline/tail_eval.py (artifacts/metrics/long_tail.json): 10% costs about 5% of NDCG@10 in Balanced, 20%
# about 10% in Discover (an upper bound: a film nobody in MovieLens rated cannot score). Familiar stays at 0.
# 2026-11-11: more diverse on purpose (Aryav: lists felt samey). Lower lambda = more weight on being different from what is
# already picked; beta = reward for lesser-known films. These were hand-tuned from the earlier values (0.95/0.75/0.55, beta
# 0/0.05/0.20, tail 0/0.1/0.2); the offline cost in NDCG@10 has not been re-measured.
MODES = {"familiar": {"lambda": 0.9, "beta": 0.02, "explore_boost": 0.0, "tail_share": 0.05},
         "balanced": {"lambda": 0.65, "beta": 0.08, "explore_boost": 0.02, "tail_share": 0.15},
         "discover": {"lambda": 0.5, "beta": 0.25, "explore_boost": 0.06, "tail_share": 0.25}}
TOP_N = 100
TAIL_PCT = 80          # a film is "long tail" when it is outside the 20% most-voted films of the catalog


def tail_slots(k: int, share: float) -> int:
    """How many of k positions are reserved for long-tail films (never more than half the list)."""
    return min(int(round(k * share)), k // 2)


def spread(head: np.ndarray, tail: np.ndarray) -> np.ndarray:
    """Put the tail picks at evenly spaced positions of the final list instead of piling them at the end."""
    k = len(head) + len(tail)
    out = list(head)
    for j, x in enumerate(tail):
        out.insert(min(round((j + 1) * k / (len(tail) + 1)) - 1, len(out)), x)
    return np.array(out, dtype=head.dtype if len(head) else tail.dtype)


def mmr(items: np.ndarray, relevance: np.ndarray, sim: np.ndarray, novelty: np.ndarray, k: int,
        lam: float, beta: float, boost: np.ndarray | None = None, allowed: np.ndarray | None = None,
        already: np.ndarray | None = None) -> np.ndarray:
    """items: candidate indices (sorted by relevance, at most TOP_N); sim: item x item similarity.
    allowed: optional mask over items (only these may be picked). already: positions in `items` that are already
    on the list, so they count for similarity and cannot be picked again."""
    rel = relevance - relevance.min()
    rel = rel / rel.max() if rel.max() > 0 else rel
    extra = beta * novelty[items] + (boost if boost is not None else 0)
    picked: list[int] = []
    max_sim = np.zeros(len(items), dtype=np.float32)
    available = np.ones(len(items), dtype=bool) if allowed is None else allowed.copy()
    for j in (already if already is not None else []):
        available[j] = False
        max_sim = np.maximum(max_sim, sim[items, items[j]])
    for _ in range(min(k, int(available.sum()))):
        score = lam * rel - (1 - lam) * max_sim + extra
        score[~available] = -np.inf
        j = int(np.argmax(score))
        picked.append(j)
        available[j] = False
        max_sim = np.maximum(max_sim, sim[items, items[j]])
    return items[picked]


def scaled_novelty(item_counts: np.ndarray, n_users: int) -> np.ndarray:
    share = np.clip(item_counts / max(n_users, 1), 1e-9, None)
    nov = -np.log(share)
    return ((nov - nov.min()) / (nov.max() - nov.min())).astype(np.float32)

def refresh(items, k: int, rng: np.random.Generator, pool_mult: int = 3, keep: int = 3) -> list:
    """k items from the first k * pool_mult, best-first order kept. The first `keep` always stay (the very best); the
    rest are drawn at random with a lean towards the top (weight 1 / (1 + rank / k)). With a seed that changes daily,
    a row is still a strong list but not the same 20 titles every day."""
    items = list(items)
    head, rest = items[:keep], items[keep:keep + max(k * pool_mult - keep, 0)]
    need = k - len(head)
    if need <= 0 or len(rest) <= need:
        return (head + rest)[:k] if need > 0 else items[:k]
    w = 1.0 / (1.0 + np.arange(len(rest)) / max(k, 1))
    keys = rng.random(len(rest)) ** (1.0 / w)
    chosen = np.sort(np.argsort(-keys)[:need])
    return head + [rest[i] for i in chosen]


def spread_languages(items: list, languages: list[str], cap: float = 0.5, window: int = 12) -> list:
    """Within the first `window` places no single language takes more than `cap` of them; the extras move just after the
    window. Order is otherwise kept. (So a list is not a dozen Korean dramas in a row.)"""
    limit = max(int(window * cap), 1)
    seen: dict[str, int] = {}
    first, later = [], []
    for it, lang in zip(items, languages):
        if len(first) < window and seen.get(lang, 0) < limit:
            first.append(it)
            seen[lang] = seen.get(lang, 0) + 1
        else:
            later.append(it)
    return first + later
