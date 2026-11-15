"""Reading the anime model file (pipeline/anime_model.py writes it) and the one rule for which liked anime it knows.

Used by the site (api/app/services/recommender.py), the engine (OnlineEngine.anime_scores) and the real-user tier count
(pipeline/anime_tier_counts.py), so all three agree. Anything unexpected in the file means no model at all: the anime
lists then keep the earlier order instead of the site failing to start.

File format: a NumPy .npz (no pickled objects) with, per tier ("long", "mid", "short"), three 1-D arrays of equal
length: `<tier>_src` (tmdb id of the anime that votes), `<tier>_dst` (tmdb id it votes for), `<tier>_w` (the vote).
Plus `settings`: a JSON string with the build settings and the SHA-256 of its inputs. Loading it costs about what the
matrices cost (about 8 MB); a JSON file of the same votes took about 220 MB extra while it was read (2026-11-15).
"""
from __future__ import annotations

import json

import numpy as np
import scipy.sparse as sp

TIERS = ("long", "mid", "short")
KNOWN_REF = "mid"        # a liked anime counts when its row in this model gives at least one vote (inside the catalog)


class BadModelFile(ValueError):
    """The file opens but is not a usable anime model."""


def _arrays(data, name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    try:
        src, dst, w = (np.asarray(data[f"{name}_{k}"]) for k in ("src", "dst", "w"))
    except KeyError:
        raise BadModelFile(f"model '{name}' is missing") from None
    if src.ndim != 1 or dst.ndim != 1 or w.ndim != 1 or not len(src) == len(dst) == len(w):
        raise BadModelFile(f"model '{name}': arrays are not three 1-D arrays of one length")
    if src.dtype.kind not in "iu" or dst.dtype.kind not in "iu":
        raise BadModelFile(f"model '{name}': title ids are not integers")
    if w.dtype.kind != "f":
        raise BadModelFile(f"model '{name}': votes are not numbers")
    for ids in (src, dst):
        if len(ids) and (ids.min() <= 0 or ids.max() > np.iinfo(np.int64).max):
            raise BadModelFile(f"model '{name}': a title id is out of range")
    with np.errstate(over="ignore"):
        w32 = w.astype(np.float32)              # checked AFTER the conversion: 1e300 is finite but becomes inf in float32
    if not (np.isfinite(w32).all() and (w32 > 0).all()):
        raise BadModelFile(f"model '{name}': a vote is not a finite number above 0 (the builder writes only positive votes)")
    return src.astype(np.int64), dst.astype(np.int64), w32


def parse(data, tmdb_ids) -> dict[str, sp.csr_matrix]:
    """{"long", "mid", "short": n x n csr over the catalog rows (row = the anime that votes)} from the file's arrays
    (an opened .npz or any mapping of arrays). Raises BadModelFile for any problem, and when a tier has no vote between
    two catalog titles."""
    cat = np.asarray(tmdb_ids, dtype=np.int64)
    n = len(cat)
    if n == 0:
        raise BadModelFile("the catalog is empty")
    order = np.argsort(cat, kind="stable")
    sorted_cat = cat[order]

    def rows(ids):
        pos = np.clip(np.searchsorted(sorted_cat, ids), 0, n - 1)
        return order[pos], sorted_cat[pos] == ids

    out = {}
    for name in TIERS:
        src, dst, w = _arrays(data, name)
        (r, ok_r), (c, ok_c) = rows(src), rows(dst)
        keep = ok_r & ok_c
        if not keep.any():
            raise BadModelFile(f"model '{name}' has no vote between two catalog titles")
        out[name] = sp.csr_matrix((w[keep], (r[keep], c[keep])), shape=(n, n))
    return out


def load(path, tmdb_ids) -> dict[str, sp.csr_matrix]:
    """Open the .npz without allowing pickled objects and parse it. Raises (BadModelFile, OSError, a zip error) on a
    missing or broken file; the caller turns any of those into "no model"."""
    with np.load(path, allow_pickle=False) as data:
        return parse(data, tmdb_ids)


def settings(path) -> dict:
    """The build settings and input checksums stored in the file."""
    with np.load(path, allow_pickle=False) as data:
        return json.loads(str(data["settings"]))


def known_inputs(sims: dict[str, sp.csr_matrix], rows) -> list[int]:
    """The rows (liked anime) the model can use: their row in the reference model holds a vote. This number picks the
    tier (OnlineEngine.anime_scores), so the tier count must use it too."""
    ref = sims[KNOWN_REF]
    return [r for r in rows if ref.indptr[r + 1] > ref.indptr[r]]
