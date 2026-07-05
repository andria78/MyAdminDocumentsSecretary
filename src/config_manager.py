"""Configuration manager for the document pipeline.

Loads and validates YAML configuration files with dot-notation access.
"""

import os
import yaml


class ConfigManager:
    """Loads and provides access to pipeline configuration."""

    def __init__(self, config_path: str):
        """
        Initialize config manager from a YAML file path.

        Args:
            config_path: Path to the YAML configuration file.

        Raises:
            FileNotFoundError: If the config file does not exist.
            yaml.YAMLError: If the config file is invalid YAML.
        """
        self._config_path = config_path
        self._data = self._load(config_path)

    def _load(self, path: str) -> dict:
        """Load and return the YAML configuration."""
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Configuration file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid configuration: expected a top-level mapping in {path}")
        return data

    def get(self, key: str, default=None):
        """
        Access configuration values using dot notation.

        Example: config.get("pipeline.ocr.languages") -> ["fra", "eng"]

        Args:
            key: Dot-separated path to the configuration value.
            default: Value returned if the key path is not found.

        Returns:
            The configuration value at the given key path, or default.
        """
        keys = key.split(".")
        value = self._data
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    @property
    def raw_scans_folder(self) -> str:
        """Path to the raw scanned documents folder."""
        return self.get("pipeline.raw_scans_folder", "/Volumes/Public/-ScansImprimante")

    @property
    def searchable_pdf_folder(self) -> str:
        """Path to the intermediate searchable PDF folder."""
        return self.get("pipeline.searchable_pdf_folder", "/Volumes/Administratif/00-ScansNonTries")

    @property
    def destination_base_folder(self) -> str:
        """Root path for the person/category destination hierarchy."""
        return self.get("pipeline.destination_base_folder", "/Volumes/Administratif")

    @property
    def ocr_languages(self) -> list:
        """List of Tesseract language codes (e.g. ['fra', 'eng'])."""
        return self.get("pipeline.ocr.languages", ["fra", "eng"])

    @property
    def ocr_dpi(self) -> int:
        """DPI resolution for OCR processing."""
        return self.get("pipeline.ocr.dpi", 300)

    @property
    def logging_level(self) -> str:
        """Logging level string (e.g. 'INFO', 'DEBUG')."""
        return self.get("pipeline.logging.level", "INFO")

    @property
    def logging_file(self) -> str:
        """Path to the log file."""
        return self.get("pipeline.logging.file", "logs/pipeline.log")

    @property
    def test_mode_enabled(self) -> bool:
        """Whether test mode is enabled."""
        return self.get("pipeline.test_mode.enabled", False)

    @property
    def test_file_prefix(self) -> str:
        """File prefix for test documents."""
        return self.get("pipeline.test_mode.file_prefix", "__TEST__")

    @property
    def raw_data(self) -> dict:
        """Return the full raw configuration dictionary."""
        return self._data
