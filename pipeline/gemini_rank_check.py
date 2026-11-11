"""Before/after lists for series and anime ranking with and without the Gemini graph (engine/ai_graph.py).

There are no held-out TV ratings, so this cannot measure accuracy. It prints, for a fixed set of made-up viewers who
each like one or two named titles, the top 10 without and with the graph, so a person can judge them, plus how many
of the top 10 changed and how many of the top 10 are neighbours Gemini named. Run: python pipeline/gemini_rank_check.py
(needs the staged data/processed and artifacts/models, including ai_similar.json)."""
import json
import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from cinematch_engine import ai_graph                      # noqa: E402
from cinematch_engine.online import UserState               # noqa: E402
from pipeline.availability_calibration import MODELS, build_engine   # noqa: E402

VIEWERS = [("series", ["Panchayat"]), ("series", ["Sacred Games"]), ("series", ["The Family Man"]), ("series", ["Squid Game"]),
           ("series", ["Crash Landing on You"]), ("series", ["Breaking Bad"]), ("series", ["Stranger Things"]),
           ("series", ["The Crown"]), ("anime", ["Attack on Titan"]), ("anime", ["Death Note"]), ("anime", ["Your Name."]),
           ("series", ["Panchayat", "Breaking Bad"])]


def learned(tmdb_ids):
    n = len(tmdb_ids); row_of = {t: i for i, t in enumerate(tmdb_ids)}; r, c, v = [], [], []
    for f in ("drama_neighbors.json", "anime_neighbors.json"):
        p = MODELS / f
        if p.exists():
            for a, nbs in json.loads(p.read_text())["neighbors"].items():
                for b, x in nbs:
                    if int(a) in row_of and b in row_of:
                        r.append(row_of[int(a)]); c.append(row_of[b]); v.append(x)
    m = sp.csr_matrix((v, (r, c)), shape=(n, n), dtype=np.float32)
    return m.maximum(m.T).tocsr()


def main():
    engine, movies, _ = build_engine()
    cat = engine.cat
    ids = movies["tmdb_id"].tolist()
    cat.series_sim = learned(ids)
    graph = ai_graph.build(ids, movies["title"].tolist(), movies["year"].astype(float).tolist(), movies["title_type"].tolist(),
                           json.loads((MODELS / "ai_similar.json").read_text(encoding="utf-8"))["titles"])
    print(f"graph edges: {graph.nnz // 2} pairs; titles with at least one: {int((graph.getnnz(axis=1) > 0).sum())} of {cat.n}")
    title_row = {}
    for i, (t, k) in enumerate(zip(cat.titles, cat.kind)):
        if k != "movie":
            title_row.setdefault(t, (i, np.nan_to_num(cat.votes[i])))
            if cat.votes[i] > title_row[t][1]:
                title_row[t] = (i, cat.votes[i])
    changed = named = total = 0
    for kind, likes in VIEWERS:
        rows_ = [title_row[t][0] for t in likes if t in title_row]
        if not rows_:
            print(f"\n## {likes}: not in catalog"); continue
        st = UserState(likes=set(rows_))
        cat.gemini_sim = None
        before, _ = engine.kind_rank(st, kind)
        cat.gemini_sim = graph
        after, _ = engine.kind_rank(st, kind)
        b, a = before[:10].tolist(), after[:10].tolist()
        nb = {int(x) for r in rows_ for x in graph[r].indices}
        changed += len(set(a) - set(b)); named += sum(x in nb for x in a); total += 10
        print(f"\n## likes {likes} ({kind})")
        for n in range(10):
            f = lambda r: f"{cat.titles[r]} ({cat.language[r]}, {int(cat.year[r]) if cat.year[r] == cat.year[r] else '?'})"
            print(f"  {n + 1:>2}. {f(b[n]):<46} | {f(a[n])}{'  *' if a[n] in nb else ''}")
    print(f"\nacross {len(VIEWERS)} viewers: {changed} of {total} top-10 places are new titles; {named} of {total} are Gemini-named neighbours (*)")


if __name__ == "__main__":
    main()
