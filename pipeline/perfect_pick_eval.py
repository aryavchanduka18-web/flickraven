"""Before/after check for Perfect Pick eligibility and tone rules (no database, no personal taste).

Reads a compact catalog export (id, title, type, genres, keywords, language, runtime, episodes, votes) built from the raw TMDB
files, runs the Perfect Pick selection and ranking from two versions of perfect_pick.py on a fixed list of answer sets, and
writes each top-10 with its tier. Relevance is a fame proxy (TMDB vote-count percentile), because there is no user here:
this checks WHO qualifies and in which group, not personal ranking.

  python pipeline/perfect_pick_eval.py CATALOG.json BEFORE.py AFTER.py OUT.json
"""
import importlib.util
import json
import sys

sys.path.insert(0, "engine")
from cinematch_engine.tonight import matches_mood, moods  # noqa: E402


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


CASES = [  # id, kind, genres, mood, languages, time
    (1, "series", ["Crime"], "Intense", ["en"], "any"),
    (2, "series", ["Crime", "Comedy"], "Intense", ["en"], "any"),
    (3, "series", ["Crime"], None, ["en"], "any"),
    (4, "series", ["Horror"], "Intense", [], "any"),
    (5, "series", ["Thriller"], "Intense", [], "any"),
    (6, "series", ["Romance"], "Feel-good", [], "any"),
    (7, "series", ["Romance"], "Intense", [], "any"),
    (8, "series", ["Romance"], "Romantic", ["ko"], "h20"),
    (9, "series", ["Comedy"], "Funny", [], "any"),
    (10, "series", ["Drama"], "Emotional", [], "any"),
    (11, "movie", ["Crime"], "Intense", [], "any"),
    (12, "movie", ["Horror"], "Scary", [], "any"),
    (13, "movie", ["Comedy"], "Feel-good", [], "any"),
    (14, "movie", ["Thriller"], "Mind-bending", [], "any"),
    (15, "movie", ["Romance"], "Feel-good", [], "any"),
    (16, "series", ["Anime"], "Intense", [], "any"),
    (17, "series", ["Crime", "Thriller", "Drama"], "Intense", ["en"], "any"),
]


def build_items(pp, rows, kind):
    out = []
    for r in rows:
        is_series = r["tt"] in ("series", "anime")
        if (kind == "movie") == is_series:
            continue
        genres = list(r["g"])
        inferred = frozenset()
        if is_series:
            genres, inferred = pp.series_genres(genres, r["k"])
            ep, rt = r.get("ep"), r.get("rt")
            minutes = (ep * rt) if ep and rt else None
        else:
            minutes = r.get("rt")
        kw = dict(anime=(r["tt"] == "anime") or (is_series and r["l"] == "ja" and "Animation" in r["g"])) if "anime" in pp.Item.__dataclass_fields__ else {}
        out.append(pp.Item(r["id"], "series" if is_series else "movie", genres, list(r["k"]), r["l"] or "", minutes, r.get("se"),
                           r.get("st"), float(r["vc"]), 0.5, r.get("ep"), inferred, **kw))
    return out


def run(pp, rows, case):
    cid, kind, genres, mood, langs, time = case
    kb = moods()
    pf = pp.Prefs(kind=kind, mood=mood, genres=genres, languages=langs, time=time, adventure="familiar")
    items = build_items(pp, rows, kind)
    rule = kb.get(mood) if mood else None
    sel = pp.select(items, pf, rule, matches_mood)
    by = {i.id: i for i in sel.exact + [i for i, _ in sel.near]}
    top = pp.choose(pp.rank(sel.exact, pf, rule, matches_mood), "familiar", k=10) if sel.exact else []
    res = [{"id": c.id, "tier": "exact"} for c in top]
    if len(res) < 10:
        for c, misses in pp.pick_alternatives(sel.near, pf, rule, matches_mood, 10 - len(res)):
            res.append({"id": c.id, "tier": "alt:" + "+".join(misses)})
    return {"n_exact": len(sel.exact), "n_near": len(sel.near), "top": res, "_by": by}


def main(catalog, before, after, out):
    rows = json.load(open(catalog))
    title = {r["id"]: f'{r["t"]} ({r["y"]}) [{", ".join(r["g"])}]' for r in rows}
    result = []
    for case in CASES:
        entry = {"case": case[0], "kind": case[1], "genres": case[2], "mood": case[3], "languages": case[4], "time": case[5]}
        for name, path in (("before", before), ("after", after)):
            r = run(load(path, f"pp_{name}"), rows, case)
            entry[name] = {"n_exact": r["n_exact"], "n_near": r["n_near"],
                           "top": [{"title": title[t["id"]], "tier": t["tier"]} for t in r["top"]]}
        result.append(entry)
    json.dump(result, open(out, "w"), indent=1)
    for e in result:
        print(f'#{e["case"]} {e["kind"]} {e["genres"]} {e["mood"]}: exact {e["before"]["n_exact"]} -> {e["after"]["n_exact"]}')


if __name__ == "__main__":
    main(*sys.argv[1:5])
