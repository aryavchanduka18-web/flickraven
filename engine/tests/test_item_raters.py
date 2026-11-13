"""item_raters: the compact item -> raters view used by neighbor_votes equals the old full CSC column."""
import numpy as np
import scipy.sparse as sp

from cinematch_engine.online import item_raters


def _train(seed=0, users=50, items=30):
    rng = np.random.default_rng(seed)
    m = (rng.random((users, items)) < 0.3) * rng.integers(1, 11, (users, items))
    return sp.csr_matrix(m.astype(np.float32))


def _same_as_csc(train, raters):
    indptr, indices, data = raters
    csc = train.tocsc()
    for u in range(train.shape[1]):
        col = csc[:, u]
        old = dict(zip(col.indices.tolist(), col.data.tolist()))
        new = dict(zip(indices[indptr[u]:indptr[u + 1]].tolist(), data[indptr[u]:indptr[u + 1]].astype(float).tolist()))
        if old != new:
            return False
    return True


def test_whole_number_ratings_become_uint8_and_match():
    t = _train()
    r = item_raters(t)
    assert r[2].dtype == np.uint8 and _same_as_csc(t, r)


def test_shares_index_arrays_when_structure_matches():
    t = _train(1)
    shared = t.T.tocsr()
    shared.sort_indices()
    r = item_raters(t, shared)
    assert r[0] is shared.indptr and r[1] is shared.indices and _same_as_csc(t, r)


def test_fast_path_from_centred_matrix_is_exact():
    from cinematch_engine.sources import SourceModels
    t = _train(4, users=80, items=40)
    src = SourceModels.__new__(SourceModels)
    means = (np.asarray(t.sum(axis=1)).ravel() / np.maximum(np.diff(t.indptr), 1)).astype(np.float32)
    from cinematch_engine.models._cf import center_by_user
    rc_t = center_by_user(t, means).T.tocsr()
    r = item_raters(t, rc_t, means)
    assert r[1] is rc_t.indices and r[2].dtype == np.uint8 and _same_as_csc(t, r)


def test_fractional_ratings_stay_float_and_mismatched_structure_is_not_shared():
    t = _train(2)
    t.data = t.data + 0.5
    other = _train(3).T.tocsr()
    r = item_raters(t, other)
    assert r[2].dtype == np.float32 and r[1] is not other.indices and _same_as_csc(t, r)
