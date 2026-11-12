"""Neural Collaborative Filtering, NeuMF = GMF + MLP (He et al., 2017). Lab only (spec section 14.3).

Trained on implicit positives (ratings >= 7/10) with 4 randomly sampled negatives per positive and a
binary cross-entropy loss. Not served on the website: it learns one vector per training user and has no
cheap fold-in for new users.
"""
import numpy as np
import scipy.sparse as sp
import torch
from torch import nn


class NeuMF(nn.Module):
    def __init__(self, n_users: int, n_items: int, gmf_dim: int = 32, mlp_dims=(64, 32, 16)):
        super().__init__()
        self.gmf_u, self.gmf_i = nn.Embedding(n_users, gmf_dim), nn.Embedding(n_items, gmf_dim)
        self.mlp_u, self.mlp_i = nn.Embedding(n_users, mlp_dims[0] // 2), nn.Embedding(n_items, mlp_dims[0] // 2)
        layers, d = [], mlp_dims[0]
        for h in mlp_dims[1:]:
            layers += [nn.Linear(d, h), nn.ReLU()]
            d = h
        self.mlp = nn.Sequential(*layers)
        self.out = nn.Linear(gmf_dim + d, 1)
        for e in (self.gmf_u, self.gmf_i, self.mlp_u, self.mlp_i):
            nn.init.normal_(e.weight, std=0.01)

    def forward(self, u, i):
        gmf = self.gmf_u(u) * self.gmf_i(i)
        mlp = self.mlp(torch.cat([self.mlp_u(u), self.mlp_i(i)], dim=1))
        return self.out(torch.cat([gmf, mlp], dim=1)).squeeze(1)

    @torch.no_grad()
    def score_users(self, users: np.ndarray, n_items: int) -> np.ndarray:
        items = torch.arange(n_items)
        out = np.empty((len(users), n_items), dtype=np.float32)
        for r, u in enumerate(users):
            uu = torch.full((n_items,), int(u), dtype=torch.long)
            out[r] = self.forward(uu, items).numpy()
        return out


def train_ncf(train: sp.csr_matrix, epochs: int = 6, negatives: int = 4, batch: int = 8192, lr: float = 2e-3,
              seed: int = 42, log=None) -> NeuMF:
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    coo = train.tocoo()
    pos = coo.data >= 7
    pu, pi = coo.row[pos], coo.col[pos]
    n_users, n_items = train.shape
    rated = train.tocsr()
    model = NeuMF(n_users, n_items)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.BCEWithLogitsLoss()
    for ep in range(epochs):
        nu = np.repeat(pu, negatives)
        ni = rng.integers(0, n_items, size=len(nu))
        # resample negatives that the user actually rated (rare at this density, so one pass suffices)
        hit = np.asarray(rated[nu, ni]).ravel() > 0
        ni[hit] = rng.integers(0, n_items, size=int(hit.sum()))
        users = np.concatenate([pu, nu])
        items = np.concatenate([pi, ni])
        labels = np.concatenate([np.ones(len(pu)), np.zeros(len(nu))]).astype(np.float32)
        order = rng.permutation(len(users))
        total = 0.0
        for s in range(0, len(order), batch):
            b = order[s:s + batch]
            opt.zero_grad()
            loss = loss_fn(model(torch.from_numpy(users[b]).long(), torch.from_numpy(items[b]).long()),
                           torch.from_numpy(labels[b]))
            loss.backward()
            opt.step()
            total += float(loss) * len(b)
        if log:
            log.info("ncf epoch %d/%d loss %.4f", ep + 1, epochs, total / len(order))
    return model