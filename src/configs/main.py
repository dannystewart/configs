from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

import requests

from dsbase.files import FileManager
from dsbase.log import LocalLogger
from dsbase.shell import confirm_action
from dsbase.text.diff import show_diff
from configs.config_file import ConfigFile


class CodeConfigs:
    """Class to manage all code-related config files."""

    CONFIGS: ClassVar[list[ConfigFile]] = [
        ConfigFile("ruff.toml"),
        ConfigFile("mypy.ini"),
    ]

    def __init__(self, skip_confirm: bool = False):
        self.logger = LocalLogger().get_logger()
        self.files = FileManager()

        # Check if this is a first-time setup and skip confirmation if so, or if -y was used
        self.auto_confirm: bool = skip_confirm or self.first_time_setup
        if self.first_time_setup:
            self.logger.info("No configs found. Downloading all available configs.")

        self.update_and_log()

    def update_and_log(self) -> None:
        """Update config files from remote source. Skip confirmation if auto_confirm is True."""
        updated_configs, failed_configs, unchanged_configs = self.update_configs()

        if updated_configs:
            self.logger.info("Updated configs: %s", ", ".join(updated_configs))
        if unchanged_configs:
            self.logger.info("Already up-to-date: %s", ", ".join(unchanged_configs))
        if failed_configs:
            self.logger.warning("Failed to update: %s", ", ".join(failed_configs))

        if not updated_configs and not unchanged_configs and not failed_configs:
            self.logger.info("No configs processed.")
        elif not updated_configs:
            if failed_configs and not unchanged_configs:
                self.logger.info("No configs updated due to errors.")
            else:
                self.logger.info("No configs needed updating.")

    def update_configs(self) -> tuple[list[str], list[str], list[str]]:
        """Update config files from remote source."""
        updated_configs = []
        failed_configs = []
        unchanged_configs = []

        for config in self.CONFIGS:
            # Update the repo copy first, then the local copy
            if content := self.fetch_remote_content(config):
                config.repo_path.write_text(content)

                if config.local_path.exists():
                    result = self.update_existing_config(config, content, self.auto_confirm)
                    if result:
                        updated_configs.append(config.name)
                    else:
                        unchanged_configs.append(config.name)
                elif self.create_new_config(config, content, self.auto_confirm):
                    updated_configs.append(config.name)
                else:
                    unchanged_configs.append(config.name)

            # Try to use the fallback config if the remote fetch failed
            elif self.use_fallback_config(config):
                updated_configs.append(config.name)
            else:
                failed_configs.append(config.name)

        return updated_configs, failed_configs, unchanged_configs

    def fetch_remote_content(self, config: ConfigFile) -> str | None:
        """Fetch content from remote URL. Returns None if the fetch fails."""
        try:
            response = requests.get(config.url)
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            self.logger.warning("Failed to download %s from %s", config.name, config.url)
            return None

    def update_existing_config(self, config: ConfigFile, content: str, auto_confirm: bool) -> bool:
        """Update an existing config file if needed.

        Args:
            config: The config file to update.
            content: The new content to update the config file with.
            auto_confirm: If True, skip the confirmation prompt and write the file directly.

        Returns:
            True if the file was updated, False otherwise.
        """
        current = config.local_path.read_text()
        if current == content:
            return False

        if not auto_confirm:
            show_diff(current, content, config.local_path.name)

        if auto_confirm or confirm_action(f"Update {config.name} config?", default_to_yes=True):
            config.local_path.write_text(content)
            self.logger.info("Updated %s config.", config.name)
            return True

        return False

    def create_new_config(self, config: ConfigFile, content: str, auto_confirm: bool) -> bool:
        """Create a new config file.

        Args:
            config: The config file to create.
            content: The content to write to the config file.
            auto_confirm: If True, skip the confirmation prompt and write the file directly.

        Returns:
            True if the file was updated, False otherwise.
        """
        if auto_confirm or confirm_action(f"Create new {config.name} config?", default_to_yes=True):
            config.local_path.write_text(content)
            self.logger.info("Created new %s config.", config.name)
            return True

        self.logger.debug("Skipped creation of %s config.", config.name)
        return False

    def use_fallback_config(self, config: ConfigFile) -> bool:
        """Use fallback config when remote fetch fails. Returns True if the fallback was used."""
        if not config.repo_path.exists():
            self.logger.error("No fallback available for %s config.", config.name)
            return False

        if config.local_path.exists():
            if not confirm_action(
                f"Use repository version of {config.name} config?", default_to_yes=True
            ):
                return False

        self.files.copy(config.repo_path, config.local_path)
        self.logger.warning("Used repository version for %s config.", config.name)
        return True

    @property
    def first_time_setup(self) -> bool:
        """Check if this is a first-time setup (no configs exist yet)."""
        return not any(config.local_path.exists() for config in self.CONFIGS)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Update config files from central repository")
    parser.add_argument("-y", action="store_true", help="update files without confirmation")
    return parser.parse_args()


def main() -> None:
    """Fetch and update the config files."""
    args = parse_args()
    CodeConfigs(skip_confirm=args.y)


if __name__ == "__main__":
    main()
