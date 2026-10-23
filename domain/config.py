"""Typed view of domain/config.yaml."""

from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

from domain.scoring import COMPONENTS, WEIGHT_TOLERANCE


class ScoringConfig(BaseModel):
    score_name: str
    weights: dict[str, float]
    window_months: int
    high_load_factor_pct: float
    cargo_seat_threshold: float

    @model_validator(mode="after")
    def _weights_are_complete_and_sum_to_one(self) -> "ScoringConfig":
        if set(self.weights) != set(COMPONENTS):
            raise ValueError(f"weights must be exactly {list(COMPONENTS)}")
        if abs(sum(self.weights.values()) - 1) > WEIGHT_TOLERANCE:
            raise ValueError("weights must sum to 1")
        return self


class MetricDefinition(BaseModel):
    key: str
    label: str
    definition: str


class Config(BaseModel):
    scoring: ScoringConfig
    regions: dict[str, list[str]]
    aliases: dict[str, list[str]]
    metrics: list[MetricDefinition]
    does_not_measure: list[str]  # always included in the methodology answer
    caveats: dict[str, list[str]]


def load_config(path: Path) -> Config:
    return Config(**yaml.safe_load(path.read_text(encoding="utf-8")))
