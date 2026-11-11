"""Series and anime similarity named by Google Gemini (pipeline/ai_similar.py), as a sparse catalog-row matrix.

Gemini was asked, offline, for 24 similar titles per seed series. Each name is matched to the catalog (same kind of
title, same title ignoring case, year within one); names that match nothing are dropped. The first name in a list
weighs 1.0 and the last 0.4. The matrix is made symmetric (A names B, so B is also close to A), which lets titles
that were never seeds still be reached. About 45,000 edges, under 1 MB in memory."""
import re

import numpy as np
import scipy.sparse as sp

NAME = re.compile(r"^(.+?)\s*\((\d{4})\)$")
FIRST, LAST = 1.0, 0.4


def build(tmdb_ids, titles, years, kinds, named: dict) -> sp.csr_matrix | None:
    """`named` maps a seed TMDB id (as text) to its ordered list of "Title (YYYY)" names. All other arguments run along
    the catalog rows. Returns an n x n float32 matrix, or None when nothing matches."""
    n = len(tmdb_ids)
    row_of = {int(t): i for i, t in enumerate(tmdb_ids)}
    index: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for i in range(n):
        if kinds[i] in ("series", "anime"):
            index.setdefault((kinds[i], str(titles[i]).lower()), []).append((i, years[i]))
    rows, cols, vals = [], [], []
    for seed, names in named.items():
        a = row_of.get(int(seed))
        if a is None or kinds[a] not in ("series", "anime"):
            continue
        seen: set[int] = set()
        step = (FIRST - LAST) / max(len(names) - 1, 1)
        for rank, name in enumerate(names):
            m = NAME.match(str(name).strip())
            if not m:
                continue
            year = int(m.group(2))
            hits = [r for r, y in index.get((kinds[a], m.group(1).lower()), []) if r != a and (y != y or abs(y - year) <= 1)]
            if hits and hits[0] not in seen:
                seen.add(hits[0])
                rows.append(a); cols.append(hits[0]); vals.append(FIRST - step * rank)
    if not vals:
        return None
    sim = sp.csr_matrix((vals, (rows, cols)), shape=(n, n), dtype=np.float32)
    return sim.maximum(sim.T).tocsr()
