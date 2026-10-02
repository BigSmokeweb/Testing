from pathlib import Path
from typing import Any, Dict, List
import yaml


class Config:
    def __init__(self, data: Dict[str, Any]):
        self.base_url: str = data.get("base_url", "")
        self.login_url_hints: List[str] = data.get("login_url_hints", [])
        self.allowed_domains: List[str] = data.get("allowed_domains", [])
        self.never_click: List[str] = data.get("never_click", [])
        self.extra_headers: Dict[str, str] = data.get("extra_headers", {})
        self.alert: Dict[str, Any] = data.get("alert", {"type": "none", "slack_webhook": ""})
        self.engines: List[str] = data.get("engines", ["chromium"])
        self.link_check_pages: List[str] = data.get("link_check_pages", [])

    def __repr__(self) -> str:
        return (
            f"Config(base_url={self.base_url!r}, "
            f"login_url_hints={self.login_url_hints!r}, "
            f"allowed_domains={self.allowed_domains!r}, "
            f"engines={self.engines!r})"
        )


def load_config(config_path: str = "config.yaml") -> Config:
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"Config file not found at '{path.resolve()}'. "
            "Please copy config.example.yaml to config.yaml and customize."
        )

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return Config(data)
