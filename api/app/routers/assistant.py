"""AI assistant endpoints (Gemini Flash). See app/services/assistant.py."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import current_user
from app.config import get_settings
from app.db import get_db
from app.services import assistant as ai
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


@router.post("/chat")
def chat(body: ChatBody, user=Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if not available():
        raise HTTPException(503, "The assistant is switched off right now.")
    msgs = [{"role": "user" if m.role == "user" else "assistant", "text": m.text.strip()[:ai.MAX_CHARS]} for m in body.messages if m.text.strip()]
    msgs = msgs[-ai.MAX_TURNS:]
    if not msgs or msgs[-1]["role"] != "user":
        raise HTTPException(422, "Send a question first.")
    ai.spend(user["id"], user["is_guest"])
    system = "\n\n".join(x for x in (ai.SYSTEM, ai.taste_summary(db, user["id"]), ai.named_titles(db, msgs[-1]["text"])) if x)
    reply = ai.ask_gemini(msgs, system)
    ids = ai.resolve_titles(db, reply)
    return {"reply": reply, "items": cards(db, ids, user["id"]) if ids else [], "remaining": ai.remaining(user["id"], user["is_guest"])}
