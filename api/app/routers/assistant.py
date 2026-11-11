"""AI assistant endpoints (Gemini Flash). See app/services/assistant.py."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import current_user
from app.config import get_settings
from app.db import get_db
from app.services import assistant as ai
from app.services import assistant_context as ctx
from app.services import recommender as rec
from app.services.movies import cards

router = APIRouter(prefix="/assistant", tags=["assistant"])


def available() -> bool:
    s = get_settings()
    return bool(s.assistant_enabled and s.gemini_api_key)


class Msg(BaseModel):
    role: str          # user | assistant
    text: str


class ChatBody(BaseModel):
    messages: list[Msg]


@router.get("/status")
def status(user=Depends(current_user)) -> dict:
    return {"enabled": available(), "remaining": ai.remaining(user["id"], user["is_guest"]), "cap": ai.cap_for(user["is_guest"])}


def picks(db: Session, user_id: int, message: str, blocked: set[int]) -> str:
    """The engine's shortlist for a suggestion request, as catalog facts (assistant_context.py); empty for other
    messages, before the models are built, or on any engine problem (the chat must not break)."""
    if not ctx.wants_suggestions(message) or not rec.artifacts_ready():
        return ""
    try:
        engine = rec.load_engine(db)
        st = rec.user_state(db, user_id, engine)
        row_of = engine.cat.row_of
        want = ctx.intent(message)
        named = ctx.named_row(engine, message)
        if named is not None:       # "something like X": X leads, in X's own kind unless the message names one
            st = ctx.like_state(st, named)
            if want["kinds"] == ["movie", "series"]:
                want["kinds"] = [engine.cat.kind[named]]
        rows = ctx.shortlist(engine, st, want, {row_of[i] for i in blocked if i in row_of})
        return ctx.shortlist_prompt(engine, rows)
    except Exception:
        db.rollback()
        ai.log.exception("assistant shortlist failed; answering without it")
        return ""


@router.post("/chat")
def chat(body: ChatBody, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if not available():
        raise HTTPException(503, "The assistant is switched off right now.")
    msgs = [{"role": "user" if m.role == "user" else "assistant", "text": m.text.strip()[:ai.MAX_CHARS]} for m in body.messages if m.text.strip()]
    msgs = msgs[-ai.MAX_TURNS:]
    if not msgs or msgs[-1]["role"] != "user":
        raise HTTPException(422, "Send a question first.")
    ai.spend(user["id"], user["is_guest"])
    try:
        blocked = ctx.blocked_ids(db, user["id"])
        system = "\n\n".join(x for x in (ai.SYSTEM, picks(db, user["id"], msgs[-1]["text"], blocked),
                                           ai.named_titles(db, msgs[-1]["text"])) if x)
        reply = ai.ask_gemini(msgs, system)
        ids = [i for i in ai.resolve_titles(db, reply) if i not in blocked]      # hard exclusions win over Gemini
    except HTTPException:
        ai.refund(user["id"], user["is_guest"])
        raise
    except Exception:
        ai.refund(user["id"], user["is_guest"])
        ai.log.exception("assistant failed")
        raise HTTPException(502, "The assistant hit a problem. Try again in a moment.")
    return {"reply": reply, "items": cards(db, ids, user["id"]) if ids else [], "remaining": ai.remaining(user["id"], user["is_guest"])}
