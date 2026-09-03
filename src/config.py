"""Configuration loader for the pipeline.

Loads YAML config files from the config/ directory.
"""
import yaml
from pathlib import Path
from typing import Any


class Config:
    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)
        self.skills = self._load("skills.yaml")
        self.sources = self._load("sources.yaml")
        self.pipeline = self._load("pipeline.yaml")

    def _load(self, filename: str) -> dict[str, Any]:
        path = self.config_dir / filename
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def get_skills(self) -> list[dict]:
        return self.skills.get("skills", [])

    def get_countries(self) -> list[str]:
        return self.pipeline.get("countries", ["Global", "United States", "United Kingdom", "India", "Germany", "Australia", "Canada", "Singapore"])

    def get_pipeline_settings(self) -> dict:
        return self.pipeline.get("pipeline", {})

    def get_scoring_weights(self) -> dict:
        return self.pipeline.get("pipeline", {}).get("scoring", {})


def load_config(config_dir: Path) -> Config:
    return Config(config_dir)
