"""The pre-upload report for the Gemini similarity file, on a small made-up catalogue."""
from pipeline import ai_similar_check as C


def row(tid, title, year, kind, lang="en", votes=100):
    return dict(tmdb_id=tid, title=title, year=year, title_type=kind, original_language=lang, votes=votes)


ROWS = [row(1, "Death Note", 2006, "anime", "ja", 900), row(2, "Monster", 2004, "anime", "ja", 800),
        row(3, "Mindhunter", 2017, "series", "en", 700), row(4, "Panchayat", 2020, "series", "hi", 600),
        row(5, "Gullak", 2019, "series", "hi", 500), row(6, "Monster", 2022, "movie", "en", 50)]


def test_clean_removes_duplicates_and_self_links():
    by = {r["tmdb_id"]: r for r in ROWS}
    out, dups, selfs = C.clean_titles({"1": ["Monster (2004)", "monster (2004)", "Death Note (2006)", "Mindhunter (2017)"]}, by)
    assert out == {"1": ["Monster (2004)", "Mindhunter (2017)"]} and (dups, selfs) == (1, 1)


def test_report_flags_missing_seeds_language_gaps_and_missing_metadata():
    file = {"titles": {"1": ["Monster (2004)", "Mindhunter (2017)", "Not Stocked (2010)"], "4": ["Gullak (2019)"]}}
    rep = C.analyze(ROWS, file, None, limit=5)
    c = rep["checks"]
    assert c["1 every eligible seed processed"][0] == "FAIL"          # seeds 2, 3, 5 are missing
    assert rep["table"]["Hindi"] == {"catalogue": 2, "eligible": 2, "processed": 1, "matched": 1}
    assert rep["table"]["Other"]["processed"] == 1
    assert c["3 suggestions found in the catalog"][1].startswith("3 of 4")   # "Not Stocked" is a show we do not have
    assert c["8 metadata and checksum"][0] == "FAIL" and not rep["ok"]


def test_a_film_with_the_same_name_never_counts_as_a_series_suggestion():
    idx = C.build_index(ROWS)
    assert C.resolve(idx, "Monster", 2022) is None                     # only the film matches that year
    assert C.resolve(idx, "Monster", 2004)["tmdb_id"] == 2


def test_finalize_makes_a_complete_file_ready_and_detects_loss_versus_previous():
    full = {"titles": {str(r["tmdb_id"]): ["Mindhunter (2017)"] for r in ROWS if r["title_type"] != "movie" and r["tmdb_id"] != 3}
            | {"3": ["Monster (2004)"]}, "model": "gemini-x"}
    done = C.finalize(full, ROWS, 5)
    rep = C.analyze(ROWS, done, None, limit=5)
    assert rep["ok"] and done["meta"]["model"] == "gemini-x" and len(done["meta"]["checksum"]) == 64
    done["titles"]["1"].append("tampered (2000)")                      # changing the file breaks the checksum
    assert C.analyze(ROWS, done, None, 5)["checks"]["8 metadata and checksum"][0] == "FAIL"
    prev = {"titles": {"1": ["Monster (2004)"], "99": ["Monster (2004)"]}}
    assert C.analyze(ROWS, C.finalize(full, ROWS, 5), prev, 5)["checks"]["6 nothing lost versus the previous file"][0] == "FAIL"
