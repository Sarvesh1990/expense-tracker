"""
Expense categorisation engine with persistent merchant overrides.
"""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "categories.json"
OVERRIDES_PATH = Path(__file__).resolve().parent.parent / "config" / "overrides.json"


@dataclass
class CategoryConfig:
    rules: dict[str, list[str]] = field(default_factory=dict)
    icons: dict[str, str] = field(default_factory=dict)
    uncategorised_label: str = "Other / Uncategorised"
    uncategorised_icon: str = "❓"
    itemised_threshold: float = 30.0

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "CategoryConfig":
        data = json.loads(path.read_text())
        rules: dict[str, list[str]] = {}
        icons: dict[str, str] = {}
        for name, info in data["categories"].items():
            rules[name] = [kw.lower() for kw in info["keywords"]]
            icons[name] = info.get("icon", "")
        return cls(
            rules=rules,
            icons=icons,
            uncategorised_label=data.get("uncategorized", {}).get("label", "Other / Uncategorised"),
            uncategorised_icon=data.get("uncategorized", {}).get("icon", "❓"),
            itemised_threshold=data.get("itemised_threshold_gbp", 30.0),
        )


class OverrideStore:
    """Persists merchant -> category overrides to config/overrides.json."""

    def __init__(self, path: Path = OVERRIDES_PATH):
        self.path = path
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False))

    def get(self, description: str) -> str | None:
        return self._data.get(description.lower().strip())

    def set(self, description: str, category: str) -> None:
        self._data[description.lower().strip()] = category
        self._save()

    def remove(self, description: str) -> None:
        key = description.lower().strip()
        if key in self._data:
            del self._data[key]
            self._save()

    def all_overrides(self) -> dict[str, str]:
        return dict(self._data)


class Categoriser:
    def __init__(self, config: CategoryConfig | None = None, overrides: OverrideStore | None = None):
        self.config = config or CategoryConfig.load()
        self.overrides = overrides or OverrideStore()

    def categorise(self, description: str) -> str:
        override = self.overrides.get(description)
        if override is not None:
            return override
        desc_lower = description.lower()
        for category, keywords in self.config.rules.items():
            for keyword in keywords:
                if keyword in desc_lower:
                    return category
        return self.config.uncategorised_label

    def recategorise(self, description: str, new_category: str) -> None:
        self.overrides.set(description, new_category)

    def get_icon(self, category: str) -> str:
        if category == self.config.uncategorised_label:
            return self.config.uncategorised_icon
        return self.config.icons.get(category, "")

    def all_categories(self) -> list[str]:
        return list(self.config.rules.keys()) + [self.config.uncategorised_label]
