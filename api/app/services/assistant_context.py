"""What the assistant knows about the person, kept inside FlickRaven (local-first personalisation).

Aryav's rule (2026-11-11): nothing from a person's taste profile, ratings, likes, dislikes, Taste DNA or history is sent to
the free Gemini tier. Instead FlickRaven's own engine reads all of that here, picks a shortlist of real catalog titles that
fit the current request, and only the shortlist (title, year, kind, language, genres: catalog facts, no scores and no
reasons) goes to Gemini, and only when the message asks for suggestions. Gemini then talks about those titles.

Hard exclusions stay here too: titles the person disliked or rated 4 or lower are never shortlisted and never linked,
whatever Gemini writes. A future paid tier could send more; that would be a new, explicit setting and a privacy-page change.
"""
import re

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

SHORTLIST = 15

# A message is a request for suggestions when it uses one of these words. Questions of fact ("who directed Heat?")
# get no shortlist, so nothing personal-derived is sent with them.
ASKS = re.compile(r"\b(recommend\w*|suggest\w*|what (should|can|could) i watch|something (like|to watch|new|good)|"
                  r"anything (like|good)|similar|like [a-z]|in the mood|pick (me|something)|ideas?|binge|watch next|for me)\b", re.I)

LANGUAGES = {
    "ko": r"korean|k-?dramas?|kdramas?", "hi": r"hindi|bollywood", "ta": r"tamil|kollywood", "te": r"telugu|tollywood",
    "ml": r"malayalam", "bn": r"bengali", "es": r"spanish", "fr": r"french", "ja": r"japanese|j-?dramas?",
    "zh": r"chinese|c-?dramas?", "tr": r"turkish", "de": r"german", "it": r"italian", "th": r"thai",
}
GENRES = {
    "Comedy": r"comed\w*|funny|laugh\w*|sitcoms?", "Romance": r"romance|romantic|love stor\w*", "Horror": r"horror|scary",
    "Thriller": r"thriller\w*|suspense\w*", "Crime": r"crime|heist\w*|gangsters?|detectives?", "Drama": r"\bdrama\b",
    "Action": r"action", "Science Fiction": r"sci-?fi|science fiction", "Fantasy": r"fantasy", "Mystery": r"myster\w*",
    "Animation": r"animated|cartoons?", "Documentary": r"documentar\w*", "Family": r"family|kids",
}


def wants_suggestions(message: str) -> bool:
    return bool(ASKS.search(message))


def intent(message: str) -> dict:
    """Kinds, languages and genres the message asks for, read locally from its words. Japanese is a language, not
    anime: "Japanese shows" means live-action series; only the word anime asks for anime."""
    m = message.lower()
    if re.search(r"\banime\b", m):
        kinds = ["anime"]
    elif re.search(r"\b(series|shows?|tv|dramas?|k-?dramas?|j-?dramas?|c-?dramas?|sitcoms?|seasons?|episodes?)\b", m):
        kinds = ["series"]
    elif re.search(r"\b(films?|movies?|cinema)\b", m):
        kinds = ["movie"]
    else:
        kinds = ["movie", "series"]
    langs = [code for code, pat in LANGUAGES.items() if re.search(rf"\b({pat})\b", m)]
    genres = [g for g, pat in GENRES.items() if re.search(rf"\b({pat})\b", m)]
    return {"kinds": kinds, "languages": langs, "genres": genres}


def blocked_ids(db: Session, user_id: int) -> set[int]:
    """Titles the person disliked or rated 4 or lower: never suggested by FlickRaven, never linked in a reply."""
    return {r[0] for r in db.execute(text("""SELECT movie_id FROM reactions WHERE user_id = :u AND value = -1
        UNION SELECT movie_id FROM ratings WHERE user_id = :u AND rating <= 4"""), {"u": user_id})}


def named_row(engine, message: str) -> int | None:
    """The catalog row of a title the message names ("something like Death Note"), the most-voted one when several share
    the name; runs of 1 to 6 words, one-word runs need 5+ letters so ordinary words rarely match."""
    words = re.findall(r"[\w'&.:-]+", message.lower())
    runs = {" ".join(words[i:i + k]).strip(".:-") for k in range(1, 7) for i in range(len(words) - k + 1)}
    runs = {r for r in runs if len(r) >= 5 or " " in r}
    cat, best = engine.cat, None
    for r, t in enumerate(cat.titles):
        tl = str(t).lower()
        if tl in runs and (best is None or (len(tl), cat.votes[r]) > (len(str(cat.titles[best])), cat.votes[best])):
            best = r
    return best


def like_state(st, row: int):
    """For "like X" requests: the person's state with X as the only taste signal, keeping every exclusion (watched,
    rated, disliked, disliked genres), so the request leads and their own no-gos still hold."""
    from dataclasses import replace
    return replace(st, likes={row}, picks=set(), in_list=set(),
                   ratings={r: v for r, v in st.ratings.items() if v <= 4})


def shortlist(engine, st, want: dict, blocked_rows: set[int], n: int = SHORTLIST) -> list[int]:
    """Catalog rows, best first, for this person and this request: films from the hybrid rail score, series and anime
    from kind_rank (which already drops what they rated, watched, liked, disliked or whose genre they dislike). The
    request's language and genres are filters; if they leave nothing, the filter is dropped rather than guessed."""
    cat = engine.cat
    per_kind = max(n // len(want["kinds"]), 5)
    out: list[int] = []
    for kind in want["kinds"]:
        if kind == "movie":
            s = engine.rail_scores(st)
            ranked = [int(r) for r in np.argsort(-s)[:3000] if np.isfinite(s[r])]
        else:
            ranked = [int(r) for r in engine.kind_rank(st, kind)[0][:3000]]
        ranked = [r for r in ranked if r not in blocked_rows]
        lang = [r for r in ranked if not want["languages"] or cat.language[r] in want["languages"]]
        fit = [r for r in lang if not want["genres"] or set(want["genres"]) & set(cat.genres[r])]
        pick = fit[:per_kind]
        if len(pick) < 5:          # too few for both filters: fill with the language alone, then with anything
            pick += [r for r in (lang or ranked) if r not in pick][:per_kind - len(pick)]
        out += pick
    return out[:n]


def shortlist_prompt(engine, rows: list[int]) -> str:
    """Catalog facts only: no scores, no reasons, nothing about the person."""
    cat = engine.cat
    if not rows:
        return ""
    lines = []
    for r in rows:
        year = "" if np.isnan(cat.year[r]) else f"{int(cat.year[r])}, "
        lines.append(f"- {cat.titles[r]} ({year}{cat.kind[r]}, language {cat.language[r] or '?'}, {', '.join(cat.genres[r][:3])})")
    return ("FlickRaven's picks for this request, best first (real titles on the site). When the person asks for suggestions, "
            "choose mainly from these and write them as [[Title (Year)]]; add another title only if none of these fits:\n" + "\n".join(lines))
