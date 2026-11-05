"""Loads Invest Detroit credit guidelines (config/credit_guidelines.yaml)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@lru_cache(maxsize=1)
def load_guidelines() -> dict:
    return yaml.safe_load((CONFIG_DIR / "credit_guidelines.yaml").read_text())


def product(key: str) -> dict:
    g = load_guidelines()
    if key not in g["products"]:
        raise KeyError(f"Unknown product '{key}'. Options: {', '.join(g['products'])}")
    return g["products"][key]
