from functools import lru_cache
from importlib.resources import files

import yaml


@lru_cache
def event_weights() -> dict[str, float]:
    """Load the implicit-feedback event weights from event_weights.yaml."""
    text = files(__package__).joinpath("event_weights.yaml").read_text(encoding="utf-8")
    return {k: float(v) for k, v in yaml.safe_load(text).items()}
