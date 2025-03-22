from __future__ import annotations

import argparse
from pathlib import Path
from typing import ClassVar

import requests

from dsbase.files import FileManager
from dsbase.log import LocalLogger
from dsbase.shell import confirm_action
from dsbase.text.diff import show_diff
from dsbase.version import PackageSource, VersionChecker

from configs.config_file import ConfigFile


class CodeConfigs:
    """Class to manage all code-related config files."""

    # Config files to manage
    CONFIGS: ClassVar[list[ConfigFile]] = [
        ConfigFile("ruff.toml"),
        ConfigFile("mypy.ini"),
    ]

    # Package name for version checking
    PACKAGE_NAME: ClassVar[str] = "configs"

    # Comment format for version tracking in config files
    VERSION_COMMENT_FORMAT: ClassVar[dict[str, tuple[str, str]]] = {
        ".ini": ("; ", ""),
        ".json": ("// ", ""),
        ".py": ("# ", ""),
        ".toml": ("# ", ""),
        ".yaml": ("# ", ""),
        ".yml": ("# ", ""),
    }

    # Source for version checking
    VERSION_SOURCE: ClassVar[PackageSource] = PackageSource.AUTO

    def __init__(self, skip_confirm: bool = False):
        self.logger = LocalLogger().get_logger()
        self.files = FileManager()
        self.version_checker = VersionChecker()
        self.version_info = self.version_checker.check_package(
            self.PACKAGE_NAME, source=self.VERSION_SOURCE
        )

        # Check if this is a first-time setup and skip confirmation if so, or if -y was used
        self.auto_confirm: bool = skip_confirm or self.first_time_setup
        if self.first_time_setup:
            self.logger.info("No configs found. Downloading all available configs.")

        # Log version information
        if self.version_info.current:
            self.logger.info("Using config version %s", self.version_info.current)
        else:
            self.logger.warning("Package not installed. Using development version.")

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
                # Add version information to the content
                versioned_content = self.add_version_to_content(content, config.name)
                config.repo_path.write_text(versioned_content)

                if config.local_path.exists():
                    # Check if config file needs updating
                    if self.needs_update(config.local_path):
                        result = self.update_existing_config(
                            config, versioned_content, self.auto_confirm
                        )
                        if result:
                            updated_configs.append(config.name)
                        else:
                            unchanged_configs.append(config.name)
                    else:
                        unchanged_configs.append(config.name)
                elif self.create_new_config(config, versioned_content, self.auto_confirm):
                    updated_configs.append(config.name)
                else:
                    unchanged_configs.append(config.name)

            # Try to use the fallback config if the remote fetch failed
            elif self.use_fallback_config(config):
                updated_configs.append(config.name)
            else:
                failed_configs.append(config.name)

        return updated_configs, failed_configs, unchanged_configs

    def needs_update(self, config_path: Path) -> bool:
        """Check if a config file needs updating based on its embedded version and content."""
        if not config_path.exists():
            return True

        # Extract version from config file
        config_version = self.extract_version_from_file(config_path)
        current_version = self.version_info.current or "dev"

        # If versions don't match, update is needed
        if not config_version or config_version != current_version:
            return True

        # Even if versions match, check content to be sure
        content = config_path.read_text()
        repo_path = self.get_repo_path_for_config(config_path)

        if not repo_path.exists():
            # Can't compare content, so assume update is needed
            return True

        repo_content = repo_path.read_text()

        # Compare content ignoring version lines
        return not self.is_content_identical(content, repo_content)

    def get_repo_path_for_config(self, config_path: Path) -> Path:
        """Get the repository path for a given config file path."""
        for config in self.CONFIGS:
            if config.local_path == config_path:
                return config.repo_path
        # If not found, use a fallback approach
        return Path(
            str(config_path).replace(str(config_path.parent), str(self.CONFIGS[0].repo_path.parent))
        )

    def add_version_to_content(self, content: str, filename: str) -> str:
        """Add version information to the content."""
        suffix = Path(filename).suffix
        comment_start, comment_end = self.VERSION_COMMENT_FORMAT.get(suffix, ("# ", ""))

        version_str = self.version_info.current or "dev"
        version_line = f"{comment_start}Config version: {version_str} (auto-managed){comment_end}\n"

        # If there's already a version line, replace it
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if "Config version:" in line and "auto-managed" in line:
                lines[i] = version_line.strip()
                return "\n".join(lines)

        # Otherwise, add it at the top
        return f"{version_line}\n{content}"

    def extract_version_from_file(self, file_path: Path) -> str | None:
        """Extract version information from a file."""
        if not file_path.exists():
            return None

        content = file_path.read_text()
        for line in content.splitlines():
            if "Config version:" in line and "auto-managed" in line:
                try:
                    return line.split("Config version:")[1].split("(auto-managed)")[0].strip()
                except IndexError:
                    pass
        return None

    def is_content_identical(self, content1: str, content2: str) -> bool:
        """Check if content is identical ignoring version lines."""
        lines1 = [
            line
            for line in content1.splitlines()
            if "Config version:" not in line or "auto-managed" not in line
        ]
        lines2 = [
            line
            for line in content2.splitlines()
            if "Config version:" not in line or "auto-managed" not in line
        ]

        return lines1 == lines2

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
        current_version = self.extract_version_from_file(config.local_path)
        new_version = self.version_info.current or "dev"

        # If only the version line is different, show a simplified message
        if self.is_content_identical(current, content):
            if current_version != new_version:
                if auto_confirm or confirm_action(
                    f"Update {config.name} config version from {current_version} to {new_version}?",
                    default_to_yes=True,
                ):
                    config.local_path.write_text(content)
                    self.logger.info(
                        "Updated %s config version from %s to %s.",
                        config.name,
                        current_version,
                        new_version,
                    )
                    return True
                return False
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
