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
TITLE_RE = re.compile(r"\[\[(.+?)\]\]")

# A message is a request for suggestions when it uses one of these words. Questions of fact ("who directed Heat?")
# get no shortlist, so nothing personal-derived is sent with them.
ASKS = re.compile(r"\b(recommend\w*|suggest\w*|what (should|can|could) i watch|something (like|to watch|new|good)|"
                  r"anything (like|good)|similar|like [a-z]|in the mood|pick (me|something)|ideas?|binge|watch next|for me|"
                  r"i want (?!to (know|understand|ask|see how)\b)|any good\b|give me (a|an|some|something)\b|looking for (a|an|some|something)\b|"
                  r"i('d| would) like (a|an|some|something)\b|i need (a|an|some|something)\b)", re.I)

LANGUAGES = {
    "ko": r"korean|k-?dramas?|kdramas?", "hi": r"hindi|bollywood", "ta": r"tamil|kollywood", "te": r"telugu|tollywood",
    "ml": r"malayalam", "bn": r"bengali", "es": r"spanish", "fr": r"french", "ja": r"japanese|j-?dramas?",
    "zh": r"chinese|c-?dramas?", "tr": r"turkish", "de": r"german", "it": r"italian", "th": r"thai",
}
GENRES = {
    "Comedy": r"comed\w*|funny|laugh\w*|sitcoms?", "Romance": r"romance|romantic|love stor\w*", "Horror": r"horror|scary",
    "Thriller": r"thriller\w*|suspense\w*|psychological", "Crime": r"crime|heist\w*|gangsters?|detectives?", "Drama": r"\bdrama\b",
    "Action": r"(?<!live-)(?<!live )action", "Science Fiction": r"sci-?fi|science fiction", "Fantasy": r"fantasy", "Mystery": r"myster\w*",
    "Animation": r"animated|cartoons?", "Documentary": r"documentar\w*", "Family": r"family|kids",
}


def wants_suggestions(message: str) -> bool:
    return bool(ASKS.search(message))


NEGATION = re.compile(r"\b(not|no|without|except|excluding|exclude|avoid|never|skip|nothing|don'?t|do not|dont|didn'?t|doesn'?t|"
                      r"won'?t|can'?t|cannot|rather than|instead of)\b", re.I)
CONTRAST = re.compile(r"\b(?:but|however|although|though|yet)\b", re.I)
KIND_WORDS = {
    "anime": r"anime",
    "series": r"series|shows?|tv|dramas?|k-?dramas?|j-?dramas?|c-?dramas?|sitcoms?|seasons?|episodes?",
    "movie": r"films?|movies?|cinema",
}


def _mentions(m: str, pattern: str) -> tuple[bool, bool]:
    """(asked for, ruled out) for a word in the message. A mention is ruled out when a negation word comes before it in the
    same clause, close by ("not anime", "no Hindi", "I don't want Hindi recommendations", "a movie, not a series").
    A clause ends at . ; ! ? or a comma that is followed by a new request ("but ..."). Only the nearest 6 words count."""
    asked = ruled = False
    for hit in re.finditer(rf"\b({pattern})\b", m):
        clause = CONTRAST.split(re.split(r"[.;!?]", m[:hit.start()])[-1])[-1]       # "no Hindi, but Korean is fine": Korean is not ruled out
        near = " ".join(clause.split()[-6:])
        # "a movie, not a series": the comma belongs to the series part; "a series, not anime" likewise. A negation
        # earlier than a comma does not reach past it ("not anime, a Japanese series" keeps the series).
        near = near.split(",")[-1]
        if NEGATION.search(near):
            ruled = True
        else:
            asked = True
    return asked, ruled


def intent(message: str) -> dict:
    """Kinds, languages and genres the message asks for, read locally from its words, with negations. Japanese is a
    language, not anime: "Japanese shows" means live-action series; only the word anime asks for anime, and "not anime"
    rules it out. Returns kinds (asked for, or movie+series when nothing is named, minus any ruled out), languages and
    genres asked for, and exclude_languages / exclude_genres the person ruled out."""
    m = message.lower()
    asked_k, ruled_k = [], set()
    for kind, pat in KIND_WORDS.items():
        a, r = _mentions(m, pat)
        if a:
            asked_k.append(kind)
        if r:
            ruled_k.add(kind)
    # "anime" beats the generic "shows/series" words when both are asked for, as before
    asked_k = [k for k in asked_k if k not in ruled_k]       # a later "but not X" beats an earlier "X"
    if "anime" in asked_k:
        kinds = ["anime"]
    elif asked_k:
        kinds = [k for k in ("series", "movie") if k in asked_k]
    else:
        kinds = [k for k in ("movie", "series") if k not in ruled_k] or ["movie", "series"]
    langs, no_langs = [], []
    for code, pat in LANGUAGES.items():
        a, r = _mentions(m, pat)
        if r:
            no_langs.append(code)
        elif a:
            langs.append(code)
    genres, no_genres = [], []
    for g, pat in GENRES.items():
        a, r = _mentions(m, pat)
        if r:
            no_genres.append(g)
        elif a:
            genres.append(g)
    return {"kinds": kinds, "languages": langs, "genres": genres, "exclude_languages": no_langs, "exclude_genres": no_genres,
            "kind_asked": bool(asked_k), "exclude_kinds": sorted(ruled_k)}


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


def kinds_for_named(want: dict, named_kind: str) -> list[str]:
    """Kinds to search when the message names a title ("something like Death Note"): that title's own kind, unless the
    person already said a kind or ruled that kind out ("... but not anime" keeps movies and series)."""
    if want["kind_asked"] or named_kind in want["exclude_kinds"]:
        return want["kinds"]
    return [named_kind]


def named_kind(db: Session, message: str) -> str | None:
    """Kind (movie, series or anime) of the best-known catalog title the message names, or None. Runs of 1 to 6 words;
    one-word runs need 5+ letters, like the assistant's catalog-facts lookup."""
    words = re.findall(r"[\w'&.:-]+", message.lower())
    runs = {" ".join(words[i:i + n]).strip(".:-") for n in range(1, 7) for i in range(len(words) - n + 1)}
    runs = [r for r in runs if len(r) >= 5 or (" " in r and len(r) >= 3)][:200]
    if not runs:
        return None
    row = db.execute(text("SELECT title_type FROM movies WHERE lower(title) = ANY(:t) ORDER BY tmdb_vote_count DESC NULLS LAST LIMIT 1"),
                     {"t": runs}).first()
    return row[0] if row else None


def request_plan(db: Session, message: str) -> dict:
    """What the message asks for, read locally, with the kind a named title implies ("something like Death Note" means
    anime) unless the person gave a kind or ruled that kind out. One plan serves both the shortlist and the check on
    Gemini's answer, so the two cannot disagree. `kind_inferred` marks a kind that came from the title."""
    want = intent(message)
    kind = named_kind(db, message)
    want["kind_inferred"] = False
    if kind and not want["kind_asked"] and kind not in want["exclude_kinds"]:
        want["kinds"] = [kind]
        want["kind_inferred"] = True
    return want


def like_state(st, row: int):
    """For "like X" requests: the person's state with X as the only taste signal, keeping every exclusion (watched,
    rated, disliked, disliked genres), so the request leads and their own no-gos still hold."""
    from dataclasses import replace
    return replace(st, likes={row}, picks=set(), in_list=set(),
                   ratings={r: v for r, v in st.ratings.items() if v <= 4})


def shortlist(engine, st, want: dict, blocked_rows: set[int], n: int = SHORTLIST) -> list[int]:
    """Catalog rows, best first, for this person and this request: films from the hybrid rail score, series and anime
    from kind_rank (which already drops what they rated, watched, liked, disliked or whose genre they dislike).
    Hard rules, never relaxed: the kind, a language they asked for, a language or genre they ruled out. Soft: the genre
    they asked for, relaxed (language kept) when fewer than 5 titles fit. If nothing fits the hard rules the list is
    empty, and shortlist_prompt then tells Gemini to say so honestly instead of substituting other languages."""
    cat = engine.cat
    per_kind = max(n // len(want["kinds"]), 5)
    no_lang, no_genre = set(want.get("exclude_languages") or []), set(want.get("exclude_genres") or [])
    out: list[int] = []
    for kind in want["kinds"]:
        if kind == "movie":
            s = engine.rail_scores(st)
            ranked = [int(r) for r in np.argsort(-s)[:3000] if np.isfinite(s[r])]
        else:
            ranked = [int(r) for r in engine.kind_rank(st, kind)[0][:3000]]
        hard = [r for r in ranked if r not in blocked_rows
                and (not want["languages"] or cat.language[r] in want["languages"])
                and cat.language[r] not in no_lang and not (no_genre & set(cat.genres[r]))]
        fit = [r for r in hard if not want["genres"] or set(want["genres"]) & set(cat.genres[r])]
        out += (fit if len(fit) >= 5 else hard)[:per_kind]
    return out[:n]


def shortlist_prompt(engine, rows: list[int], want: dict | None = None) -> str:
    """Catalog facts only: no scores, no reasons, nothing about the person. With no rows but a hard request (a language),
    a note that tells Gemini to say honestly that FlickRaven has nothing matching."""
    cat = engine.cat
    if not rows:
        if want and want.get("languages"):
            return ("FlickRaven has no titles of the kind and language this person asked for that it can suggest right now. "
                    "Tell them so plainly, and do not offer titles in other languages as a substitute. You may mention titles "
                    "you are sure exist in that language and kind, but say FlickRaven may not have them.")
        return ""
    lines = []
    for r in rows:
        year = "" if np.isnan(cat.year[r]) else f"{int(cat.year[r])}, "
        lines.append(f"- {cat.titles[r]} ({year}{cat.kind[r]}, language {cat.language[r] or '?'}, {', '.join(cat.genres[r][:3])})")
    return ("FlickRaven's picks for this request, best first (real titles on the site). When the person asks for suggestions, "
            "choose mainly from these and write them as [[Title (Year)]]; add another title only if none of these fits. "
            "Keep to the kind and language they asked for:\n" + "\n".join(lines))


YEAR = re.compile(r"\((?:19|20)\d{2}\)")
WORDS = re.compile(r"[\w'&.:-]+")
FALLBACK = ("I held back a suggestion because you told FlickRaven you did not like it. Tell me what you are in the mood "
            "for and I will try other ideas.")


def blocked_titles(db: Session, ids: set[int]) -> dict[str, list[str]]:
    """{lowercase title: [exact spellings]} for the blocked ids."""
    if not ids:
        return {}
    out: dict[str, list[str]] = {}
    for (t,) in db.execute(text("SELECT title FROM movies WHERE id = ANY(:i)"), {"i": list(ids)}):
        out.setdefault(str(t).lower(), []).append(str(t))
    return out


def scrub_reply(reply: str, titles: dict[str, list[str]], allowed: str = "", bad_marks: set[str] | None = None) -> tuple[str, int]:
    """Remove every sentence that presents a blocked title (disliked or rated 4 or lower), so it cannot appear in the
    written reply either. Two channels are checked independently of the prose:
    - [[Title (Year)]] marks, the structured channel the model is told to use for recommendations: any mark naming a
      blocked title removes its sentence, always;
    - plain mentions: a run of words (as long as the longest blocked title) equal to a blocked title. A multi-word title matches ignoring case; a
      one-word title must be 5+ letters and spelled exactly as in the catalog (capitalised), so common words ("up",
      "her", "it", "heat" in a sentence about weather) are left alone. Titles the person typed themselves
      (`allowed`, their latest message) may be named in plain text, never as a [[mark]]. `bad_marks` are marked titles that break the
    request's language or kind (see off_request_marks); their sentences go too.
    Returns (clean reply, number of sentences removed)."""
    if not titles and not bad_marks:
        return reply, 0
    own = allowed.lower()
    lengths = sorted({len(WORDS.findall(t)) for t in titles} - {0})        # every blocked title length, in words: no cap
    bad_marks = {m.lower() for m in (bad_marks or set())}

    def blocked_mark(sentence: str) -> bool:
        for raw in TITLE_RE.findall(sentence):
            name = re.sub(r"\s*\(\d{4}\)\s*$", "", raw).strip().lower()
            if name in titles or name in bad_marks:
                return True
        return False

    def blocked_plain(sentence: str) -> bool:
        words = WORDS.findall(TITLE_RE.sub(" ", sentence))
        for k in lengths:
            for i in range(len(words) - k + 1):
                run = " ".join(words[i:i + k]).strip(".:-")
                low = run.lower()
                if low not in titles or low in own:
                    continue
                if k > 1 or (len(low) >= 5 and run in titles[low]):
                    return True
        return False

    def blocked_dated(sentence: str) -> bool:
        """"Heat (1995)": a name followed by a year is a title mention whatever its length or spelling."""
        plain = TITLE_RE.sub(" ", sentence)
        for m in YEAR.finditer(plain):
            before = WORDS.findall(plain[:m.start()])
            for k in lengths:
                low = " ".join(before[-k:]).strip(".:-").lower() if len(before) >= k else ""
                if low and low in titles and low not in own:
                    return True
        return False

    # A full stop inside a blocked title ("Mr. Robot") must not end a sentence: hide those dots while splitting.
    masked = reply
    for low in set(titles) | bad_marks:
        if "." in low:
            masked = re.sub(re.escape(low), lambda m_: m_.group(0).replace(".", "\u2024"), masked, flags=re.I)
    parts = [x.replace("\u2024", ".") for x in re.findall(r".*?(?:[.!?](?=\s|$)|\n+|$)\s*", masked, flags=re.S) if x]
    kept, removed = [], 0
    for sent in parts:
        if sent.strip() and (blocked_mark(sent) or blocked_plain(sent) or blocked_dated(sent)):
            removed += 1
            continue
        kept.append(sent)
    text_ = "".join(kept).strip()
    return (text_ or FALLBACK), removed


def off_request_marks(db: Session, reply: str, want: dict) -> set[str]:
    """Lowercase names of [[marked]] titles in the reply that FlickRaven has and that break what the person asked for:
    a kind they named (or ruled out), a language they named, a language they ruled out. A prompt cannot guarantee
    this, so it is checked after Gemini answers. Titles FlickRaven does not have cannot be checked and are left."""
    allowed_kinds = set(want["kinds"]) if (want.get("kind_asked") or want.get("kind_inferred")) else {"movie", "series", "anime"} - set(want.get("exclude_kinds") or [])
    bad: set[str] = set()
    for raw in dict.fromkeys(TITLE_RE.findall(reply)):
        m = re.match(r"(.+?)\s*\((\d{4})\)\s*$", raw)
        name, year = (m.group(1), int(m.group(2))) if m else (raw, None)
        row = db.execute(text("""SELECT title_type, original_language FROM movies WHERE lower(title) = lower(:t)
            AND (CAST(:y AS int) IS NULL OR year = CAST(:y AS int)) ORDER BY tmdb_vote_count DESC NULLS LAST LIMIT 1"""),
                         {"t": name.strip(), "y": year}).first()
        if not row:
            continue
        kind, lang = row
        if kind not in allowed_kinds or (want.get("languages") and lang not in want["languages"]) \
                or lang in (want.get("exclude_languages") or []):
            bad.add(name.strip().lower())
    return bad
