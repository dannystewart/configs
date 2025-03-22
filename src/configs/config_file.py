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
    local_path: Path = field(init=False)
    repo_path: Path = field(init=False)

    def __post_init__(self):
        self.url = f"{self.CONFIG_ROOT}/{self.name}"
        self.local_path = self.repo_root / self.name
        self.repo_path = self.repo_root / self.local_path.name
        self.repo_path.parent.mkdir(exist_ok=True)

    @property
    def repo_root(self) -> Path:
        """Get the root path of the repo."""
        this_script = Path(__file__)  # src/configs/configs.py
        configs_folder = this_script.parent  # src/configs
        src_folder = configs_folder.parent  # src
        return src_folder.parent  # repo root
