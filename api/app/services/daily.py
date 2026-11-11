"""One seed per person per day, so Home looks different every day but not on every reload.

The day changes at midnight India time (Asia/Calcutta), because that is where the audience is. The seed is a hash of the
user id, the date and a label, so the same person sees the same page all day and another person sees another one.
"""
import datetime as dt
import hashlib

import numpy as np

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def today() -> dt.date:
    return dt.datetime.now(IST).date()


def seed(user_id: int, label: str = "", day: dt.date | None = None) -> int:
    key = f"{user_id}:{day or today()}:{label}"
    return int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)


def rng(user_id: int, label: str = "", day: dt.date | None = None) -> np.random.Generator:
    return np.random.default_rng(seed(user_id, label, day))
