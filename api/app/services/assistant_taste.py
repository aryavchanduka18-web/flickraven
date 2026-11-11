"""The opt-in taste summary for the assistant (Aryav, 2026-11-11: option A of the "let Gemini see my taste" design).

Off by default. When a person turns it on (Account > AI assistant), a suggestion request also sends Gemini ONE coarse line
about their taste, for example:

    enjoys Thriller, Crime and Drama; mostly in Korean and English; mostly TV series; drawn to slow-burn storytelling and
    psychological tension; tends to avoid graphic violence; does not want Horror

What it can contain, and nothing else: up to 3 genre names, up to 2 language names, the kinds of title they like (films,
TV series, anime), up to 3 Taste DNA trait phrases they lean towards, up to 2 they avoid, and up to 2 genres they marked
as disliked. Every word comes from a fixed list (genre names from the catalog's genre table, language names, the trait
phrases in taste_dna.py), so no title, rating, count, score, date, id, name or email can reach the line, and nothing the
person typed into the site either. Needs 3 liked titles; below that there is no summary and nothing extra is sent.
"""
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

MIN_LIKED = 3
SAFE = re.compile(r"^[A-Za-z][A-Za-z &'-]{0,30}$")       # genre and language names: plain words only
KIND_NAMES = {"movie": "films", "series": "TV series", "anime": "anime"}


def enabled(db: Session, user_id: int) -> bool:
    return bool(db.execute(text("SELECT ai_taste_sharing FROM user_preferences WHERE user_id = :u"), {"u": user_id}).scalar())


def set_enabled(db: Session, user_id: int, on: bool) -> None:
    db.execute(text("""INSERT INTO user_preferences (user_id, ai_taste_sharing, updated_at) VALUES (:u, :on, now())
        ON CONFLICT (user_id) DO UPDATE SET ai_taste_sharing = :on, updated_at = now()"""), {"u": user_id, "on": on})
    db.commit()


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _safe(words) -> list[str]:
    return [str(w) for w in words if w and SAFE.match(str(w))]


def summary(db: Session, user_id: int) -> str | None:
    """The one line described above, or None when the person has fewer than 3 liked titles."""
    from app.routers.taste import profile_for
    from app.services import taste_dna as dna
    from cinematch_engine.online import LANGUAGE_NAMES

    prof, sig = profile_for(db, user_id)
    liked = [m for m, w in sig.weights.items() if w > 0]
    if len(liked) < MIN_LIKED:
        return None
    p = {"ids": liked}
    genres = _safe(g for (g,) in db.execute(text("""SELECT g.name FROM movie_genres mg JOIN genres g ON g.id = mg.genre_id
        WHERE mg.movie_id = ANY(:ids) GROUP BY g.name ORDER BY count(*) DESC, g.name LIMIT 3"""), p))
    langs = _safe(LANGUAGE_NAMES.get(l) for (l,) in db.execute(text("""SELECT original_language FROM movies WHERE id = ANY(:ids)
        AND original_language IS NOT NULL GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 2"""), p))
    kinds = db.execute(text("""SELECT title_type, count(*) FROM movies WHERE id = ANY(:ids) AND title_type IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC, 1"""), p).all()
    total = sum(n for _, n in kinds) or 1
    kind_words = [KIND_NAMES[k] for k, n in kinds if k in KIND_NAMES and n / total >= 0.25]
    no_genres = _safe(g for (g,) in db.execute(text("""SELECT g.name FROM user_preferences up, unnest(up.disliked_genre_ids) gid
        JOIN genres g ON g.id = gid WHERE up.user_id = :u ORDER BY g.name LIMIT 2"""), {"u": user_id}))
    traits_ready = prof.titles >= MIN_LIKED
    drawn = [dna.TRAIT[k].phrase for k in prof.preferred()[:3]] if traits_ready else []
    avoid = [dna.TRAIT[k].phrase for k in prof.avoided()[:2]] if traits_ready else []

    parts = []
    if genres:
        parts.append(f"enjoys {_join(genres)}")
    if langs:
        parts.append(f"mostly in {_join(langs)}")
    if kind_words:
        parts.append(("mostly " if len(kind_words) == 1 else "") + _join(kind_words))
    if drawn:
        parts.append(f"drawn to {_join(drawn)}")
    if avoid:
        parts.append(f"tends to avoid {_join(avoid)}")
    if no_genres:
        parts.append(f"does not want {_join(no_genres)}")
    return "; ".join(parts) or None


def prompt(line: str) -> str:
    return ("Taste summary this person chose to share (coarse, no viewing history): " + line + ".\n"
            "Use it to choose among FlickRaven's picks and to say in a few words why a pick suits their taste. What they ask "
            "for right now comes first. You do not know which titles they have seen; never claim to.")
