# FlickRaven architecture

```
             OFFLINE (pipeline/, run by us)
  MovieLens 32M + TMDB + Wikidata
        -> 01-05 catalog (parts A-D), gate, colors, awards
        -> 06-07 ratings sample (30,000 users), time splits, new-movie holdout
        -> 08    content features
        -> 09    tune + train models on validation      -> artifacts/models/*.json, fitted.npz
        -> 10    stage blend weights + Match % calibration
        -> 11    final evaluation + experiments           -> artifacts/metrics/*.json
        -> 12    load catalog into PostgreSQL
        -> 13-15 shilling, taste map, NCF (lab only)      -> artifacts/lab/*.json

             ONLINE (the website)
  Browser (React, Vite)  <-- /api -->  FastAPI  <-->  PostgreSQL (catalog, users, feedback, logs)
                                          |
                                          +-- loads artifacts/models once (OnlineEngine)
                                          +-- cinematch_engine: profile -> 6 sources -> candidate pool
                                              -> percentile normalization -> stage blend -> Match %
                                              -> MMR / Discovery Mode -> explanations -> rails
```

- `engine/cinematch_engine` is one package used by the pipeline (evaluation) and the API (serving):
  the model that is evaluated is the model that is served.
- Product catalog = parts A-D (~33,000 titles: films, then series and anime stored with tmdb_id = 10,000,000 + TV id
  and `movies.title_type`). Evaluation universe = part A minus the holdout (~9,500 MovieLens films), so comparisons
  stay fair. Everything added after the first build (wider catalog, series, new releases) has no MovieLens ratings,
  is outside the evaluation universe and gets its own content stage (`added_on`, `catalog_stage`), so saved model
  columns never move.
- Series and anime: no FlickRaven or MovieLens ratings. The movie rails never pick them (`Catalog.non_movie_rows`);
  `OnlineEngine.kind_rank` ranks them for a user by content similarity + popularity, and, where real viewer lists were
  learned offline (MyDramaList for Asian dramas, the Kaggle anime lists for older anime; only similarities are kept in
  `artifacts/models/{drama,anime}_neighbors.json`), 0.45 learned + 0.30 content + 0.25 popularity. Themed Home rows:
  `api/app/services/series_rails.py`, endpoint `/api/recs/series-rails`.
- Explicit feedback: ratings, likes, dislikes. Implicit: views, Quick Views, search clicks, list,
  watched (weights in `engine/cinematch_engine/config/event_weights.yaml`).
- Stage = behavioral count only (onboarding never counts): cold 0-2, warming 3-10, established 11+.