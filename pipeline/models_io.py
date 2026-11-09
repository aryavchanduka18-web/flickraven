"""Fit the tuned models once and save them to artifacts/models/, and load them back as SourceModels.

The website (Phase 8) loads the same files, so the evaluated model is the served model.
"""
import json

import numpy as np
import pandas as pd
import scipy.sparse as sp

from cinematch_engine.data.splits import SplitData
from cinematch_engine.models.als_implicit import ImplicitALS, implicit_strength
from cinematch_engine.models.content import BLOCKS, build_blocks, combine
from cinematch_engine.models.item_cf import ItemCF
from cinematch_engine.models.popularity import PopularityModel
from cinematch_engine.models.svd import FunkSVD
from cinematch_engine.sources import SourceModels
from pipeline.catalog import original_gate_mask
from pipeline.common import ARTIFACTS, PROCESSED, get_logger

log = get_logger("models_io")
MODELS = ARTIFACTS / "models"
STORED_ITEM_NEIGHBORS = 50          # spec: top-50 neighbors per film stored offline


def settings(name: str) -> dict:
    return json.loads((MODELS / f"{name}.json").read_text())["settings"]


def content_features() -> tuple[sp.csr_matrix, np.ndarray, np.ndarray]:
    """Tuned content features for the WHOLE product catalog (rows follow movies_clean order), and the
    columns learned from the original-gate films (vocabularies come from those films only, see
    original_gate_mask; labels seen only in films added later sit in extra columns)."""
    x, tmdb, feats, _ = content_layout()
    return x, tmdb, feats.fit_columns()


def catalog_stage(movies: pd.DataFrame) -> np.ndarray:
    """When a film joined the catalog: 0 first build, 1 relaxed metadata gate, 2 franchise rule, then one stage per run date of the widened catalog and
    monthly new releases (3 for the earliest run, 4 for the next, ...), so a later run never moves columns."""
    stage = np.zeros(len(movies), dtype=int)
    for k, flag in ((1, "relaxed_gate"), (2, "franchise_rule")):
        if flag in movies:
            stage[movies[flag].fillna(False).astype(bool).to_numpy()] = k
    if "added_on" in movies:
        for rank, day in enumerate(sorted(movies["added_on"].dropna().unique())):
            stage[(movies["added_on"] == day).to_numpy()] = 3 + rank
    return stage


def content_layout():
    """content_features() plus the ContentFeatures (column layout per stage) and each film's stage."""
    s = settings("content")
    movies = pd.read_parquet(PROCESSED / "movies_clean.parquet")
    credits = pd.read_parquet(PROCESSED / "credits_clean.parquet")
    stage = catalog_stage(movies)
    feats = combine(build_blocks(movies, credits, ngram_max=s["ngram_max"], fit_mask=original_gate_mask(movies),
                                 stage=stage), s["block_weights"])
    x = feats.matrix
    if s.get("thin_text_scale", 1.0) != 1.0:
        from importlib import import_module
        apply_thin = import_module("pipeline.09_train_models").apply_thin
        lo, hi = feats.block_columns["text"]
        x = apply_thin(x, movies["thin_text"].to_numpy(), lo, hi, s["thin_text_scale"])
    return x, movies["tmdb_id"].to_numpy(), feats, stage


def content_matrix() -> tuple[sp.csr_matrix, np.ndarray]:
    x, tmdb, _ = content_features()
    return x, tmdb


def save_models(data: SplitData) -> None:
    """Fit every tuned model on `data.train` and save what scoring needs."""
    MODELS.mkdir(parents=True, exist_ok=True)
    means = data.user_means()
    pop = PopularityModel(settings("popularity")["m"]).fit(data.train)
    x, tmdb = content_matrix()
    sp.save_npz(MODELS / "content_matrix.npz", x)
    pd.DataFrame({"row": range(len(tmdb)), "tmdb_id": tmdb}).to_parquet(MODELS / "content_rows.parquet", index=False)

    ic = settings("item_cf")
    item = ItemCF(shrinkages=(ic["shrinkage"],), max_neighbors=STORED_ITEM_NEIGHBORS).fit(data.train, means)
    idx, vals = item.neighbors[ic["shrinkage"]]

    sv = settings("svd")
    svd = FunkSVD(**{k: sv[k] for k in ("n_factors", "n_epochs", "lr_all", "reg_all")}).fit(data.train)
    al = settings("als")
    als = ImplicitALS(**{k: al[k] for k in ("factors", "regularization", "alpha", "iterations")}).fit(
        implicit_strength(data.train))

    np.savez_compressed(MODELS / "fitted.npz",
                        item_ids=data.item_ids, item_tmdb=data.item_tmdb, user_ids=data.user_ids,
                        popularity=pop.scores, item_counts=data.item_counts(),
                        item_nb_idx=idx, item_nb_vals=vals,
                        svd_mu=np.float32(svd.mu), svd_bi=svd.bi, svd_Q=svd.Q, svd_bu=svd.bu, svd_P=svd.P,
                        als_Y=als.Y, als_X=als.X)
    sp.save_npz(MODELS / "train_ratings.npz", data.train)
    log.info("saved fitted models to %s", MODELS)


def load_sources(data: SplitData, content_sim: np.ndarray) -> SourceModels:
    f = np.load(MODELS / "fitted.npz")
    assert (f["item_ids"] == data.item_ids).all(), "fitted models were saved for a different item space"
    uc, ic, sv, al = settings("user_cf"), settings("item_cf"), settings("svd"), settings("als")
    return SourceModels(
        train=data.train, popularity=f["popularity"], content_sim=content_sim,
        item_neighbors=(f["item_nb_idx"], f["item_nb_vals"]), item_k=ic["neighbors"], item_beta=ic["beta"],
        user_cf={"k": uc["k"], "min_overlap": uc["min_overlap"], "beta": uc["beta"]},
        svd={"mu": float(f["svd_mu"]), "bi": f["svd_bi"], "Q": f["svd_Q"], "reg": sv["reg_all"]},
        als={"Y": f["als_Y"], "alpha": al["alpha"], "reg": al["regularization"]},
    )


def universe_content_sim(data: SplitData) -> np.ndarray:
    x = sp.load_npz(MODELS / "content_matrix.npz")
    rows = pd.read_parquet(MODELS / "content_rows.parquet")
    row_of = dict(zip(rows["tmdb_id"], rows["row"]))
    xu = x[[row_of[t] for t in data.item_tmdb]]
    return (xu @ xu.T).toarray().astype(np.float32)

def content_sim_for(data: SplitData) -> np.ndarray:
    """Dense content similarity over `data`'s item space, from the saved tuned content matrix."""
    return universe_content_sim(data)


def fit_sources(data: SplitData, content_sim: np.ndarray) -> SourceModels:
    """Fit every tuned model on `data.train` in memory (no files) and wrap them as SourceModels."""
    means = data.user_means()
    pop = PopularityModel(settings("popularity")["m"]).fit(data.train)
    ic = settings("item_cf")
    item = ItemCF(shrinkages=(ic["shrinkage"],), max_neighbors=STORED_ITEM_NEIGHBORS).fit(data.train, means)
    sv = settings("svd")
    svd = FunkSVD(**{k: sv[k] for k in ("n_factors", "n_epochs", "lr_all", "reg_all")}).fit(data.train)
    al = settings("als")
    als = ImplicitALS(**{k: al[k] for k in ("factors", "regularization", "alpha", "iterations")}).fit(
        implicit_strength(data.train))
    uc = settings("user_cf")
    return SourceModels(
        train=data.train, popularity=pop.scores, content_sim=content_sim,
        item_neighbors=item.neighbors[ic["shrinkage"]], item_k=ic["neighbors"], item_beta=ic["beta"],
        user_cf={"k": uc["k"], "min_overlap": uc["min_overlap"], "beta": uc["beta"]},
        svd={"mu": svd.mu, "bi": svd.bi, "Q": svd.Q, "reg": sv["reg_all"]},
        als={"Y": als.Y, "alpha": al["alpha"], "reg": al["regularization"]},
    )