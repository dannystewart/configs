from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar


@dataclass
class ConfigFile:
    """Represents a config file that can be updated from a remote source."""

    CONFIG_ROOT: ClassVar[str] = (
        "https://raw.githubusercontent.com/dannystewart/configs/refs/heads/main"
    )

    name: str
    url: str = field(init=False)
    path: Path = field(init=False)

    def __post_init__(self):
        self.url = f"{self.CONFIG_ROOT}/{self.name}"
        self.path = Path.cwd() / self.name
