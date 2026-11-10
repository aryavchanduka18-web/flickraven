"""Evaluation by segment: does the Match % mean the same thing for every kind of film and every kind of user?

    python -m pipeline.segment_eval --users 600

For each user (history cut to 2 ratings = cold, 6 = warming, all = established) the engine scores every film the user
rated later (test split and the 500 hold-out films). A rating of 7+ is a positive. Per segment we report:
  n            ratings in the segment
  positive     share rated 7+ (what actually happened)
  match        mean Match % the engine would have shown
  gap          match/100 - positive: above 0 means the Match % promised more than users gave
  auc          probability that a positive film scored above a non-positive one, within users (ranking quality)
Segments: user stage, film language, film country, and whether the film has MovieLens collaborative factors.
Film vs series cannot be evaluated this way: series have no ratings in MovieLens; they are checked by the learned
hit@10 tests in pipeline/drama_cf.py and pipeline/anime_cf.py instead.
"""
import argparse
import json
from collections import defaultdict

import numpy as np

from cinematch_engine.online import UserState
from pipeline.availability_calibration import REGIMES, build_engine, sample
from pipeline.common import ARTIFACTS, get_logger, write_json

log = get_logger("segment_eval")
MIN_N = 100
LANGS = {"en": "English", "hi": "Hindi", "ko": "Korean", "ja": "Japanese", "fr": "French", "es": "Spanish"}
COUNTRIES = {"US": "United States", "GB": "United Kingdom", "IN": "India", "KR": "South Korea", "JP": "Japan", "FR": "France"}


def auc(pos: np.ndarray, neg: np.ndarray) -> float | None:
    if not len(pos) or not len(neg):
        return None
    allv = np.concatenate([pos, neg])
    ranks = np.argsort(np.argsort(allv)) + 1.0
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def collect(engine, movies, ml2row, hold_rows, users, groups, stage_name, n_ratings):
    hold = set(hold_rows.tolist())
    rows_out = []                      # one record per (user, rated film)
    for u in users:
        r = groups["train"].get_group(u)
        if n_ratings:
            r = r.sample(min(n_ratings, len(r)), random_state=1)
        st = UserState()
        st.ratings = {ml2row[int(a)]: float(b) for a, b in zip(r.ml_movie_id, r.rating) if int(a) in ml2row}
        st.behavioral_count = len(st.ratings)
        if len(st.ratings) < 2:
            continue
        lab = {}
        for part in ("test", "new"):
            g = groups[part].get_group(u)
            lab.update({ml2row[int(a)]: float(b) for a, b in zip(g.ml_movie_id, g.rating) if int(a) in ml2row})
        if not lab:
            continue
        rail = engine.rail_scores(st)
        idx = np.array(list(lab))
        s = rail[idx]
        ok = np.isfinite(s)
        match = engine.cal.match_pct(st.stage, s[ok])
        for row, m, y in zip(idx[ok], match, np.array(list(lab.values()))[ok]):
            rows_out.append((u, stage_name, int(row), float(m), bool(y >= 7), row in hold, float(rail[row])))
    return rows_out


def summarise(recs, movies) -> dict:
    lang, country = movies["original_language"].to_numpy(), movies["countries"].to_numpy()
    seg = defaultdict(list)
    for rec in recs:
        u, stage, row, m, y, held, score = rec
        keys = [("user stage", stage), ("film source", "no MovieLens factors" if held else "MovieLens factors")]
        keys.append(("film language", LANGS.get(lang[row], "Other languages")))
        cs = list(country[row]) if country[row] is not None else []
        keys.append(("film country", next((COUNTRIES[c] for c in cs if c in COUNTRIES), "Other countries")))
        for k in keys:
            seg[k].append(rec)
    out = []
    for (kind, name), items in sorted(seg.items()):
        if len(items) < MIN_N:
            continue
        pos = np.array([i[4] for i in items])
        match = np.array([i[3] for i in items])
        per_user = defaultdict(lambda: ([], []))
        for i in items:
            per_user[i[0]][0 if i[4] else 1].append(i[6])
        aucs = [a for a in (auc(np.array(p), np.array(n)) for p, n in per_user.values()) if a is not None]
        out.append({"segment": kind, "name": name, "n": len(items), "positive_rate": round(float(pos.mean()), 3),
                    "mean_match": round(float(match.mean()), 1), "gap": round(float(match.mean() / 100 - pos.mean()), 3),
                    "auc": round(float(np.mean(aucs)), 3) if aucs else None, "users_with_auc": len(aucs)})
    return out


def recalibration(recs, movies) -> dict:
    """The shipped Match % calibrator was fitted (and checked, pipeline/11_evaluate.py calibration_check) on scores from the
    candidate pool, but the app applies it to the catalog-wide hybrid score (rail_scores). Here a one-feature logistic
    fit on that catalog-wide score is made on half the users and judged on the other half, per stage."""
    from sklearn.linear_model import LogisticRegression
    users = sorted({r[0] for r in recs})
    fit_users = set(users[::2])
    out = {}
    held = []
    for stage in REGIMES:
        a = [r for r in recs if r[1] == stage and r[0] in fit_users]
        b = [r for r in recs if r[1] == stage and r[0] not in fit_users]
        m = LogisticRegression(C=1e6).fit(np.array([[r[6]] for r in a]), np.array([r[4] for r in a], int))
        p = m.predict_proba(np.array([[r[6]] for r in b]))[:, 1]
        y = np.array([r[4] for r in b])
        bins = np.quantile(p, np.linspace(0, 1, 11))
        ece = 0.0
        for lo, hi in zip(bins[:-1], bins[1:]):
            sel = (p >= lo) & (p <= hi)
            ece += abs(p[sel].mean() - y[sel].mean()) * sel.sum() / len(p) if sel.sum() else 0
        shipped = np.array([r[3] for r in b]) / 100
        out[stage] = {"n_test_ratings": len(b), "observed_positive": round(float(y.mean()), 3),
                      "shipped_mean_match": round(float(shipped.mean() * 100), 1), "shipped_gap": round(float(shipped.mean() - y.mean()), 3),
                      "refit_mean_match": round(float(p.mean() * 100), 1), "refit_gap": round(float(p.mean() - y.mean()), 3),
                      "refit_ece": round(float(ece), 3), "coef": float(m.coef_[0, 0]), "intercept": float(m.intercept_[0])}
        held += [(r[0], stage, r[2], float(pp * 100), r[4], r[5], r[6]) for r, pp in zip(b, p)]
    out["segments_after_refit"] = summarise(held, movies)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=600)
    a = ap.parse_args()
    engine, movies, f = build_engine()
    ml2row, hold_rows, users, groups = sample(engine, movies, f, a.users)
    recs = []
    for name, n in REGIMES.items():
        recs += collect(engine, movies, ml2row, hold_rows, users, groups, name, n)
        log.info("%s collected, %d records", name, len(recs))
    report = {"users_sampled": int(len(users)), "min_n_per_segment": MIN_N, "segments": summarise(recs, movies),
              "recalibration_on_catalog_scores": recalibration(recs, movies)}
    write_json(ARTIFACTS / "metrics" / "segments.json", report)
    print(json.dumps({k: v for k, v in report["recalibration_on_catalog_scores"].items() if k != "segments_after_refit"}, indent=1))
    for s in report["recalibration_on_catalog_scores"]["segments_after_refit"]:
        print(s)


if __name__ == "__main__":
    main()
