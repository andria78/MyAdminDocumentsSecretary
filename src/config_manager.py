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
        self._person_categories_cache = None

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

    # ── Phase 2: AI properties ──────────────────────────────────────────────

    @property
    def ai_engine(self) -> str:
        """AI engine name (e.g. 'ollama')."""
        return self.get("pipeline.ai.engine", "ollama")

    @property
    def ai_model(self) -> str:
        """Ollama model name (e.g. 'qwen2.5:7b')."""
        return self.get("pipeline.ai.model", "qwen2.5:7b")

    @property
    def ai_temperature(self) -> float:
        """Temperature for LLM sampling (0.0–1.0)."""
        return self.get("pipeline.ai.temperature", 0.1)

    @property
    def ai_max_tokens(self) -> int:
        """Maximum tokens for LLM response."""
        return self.get("pipeline.ai.max_tokens", 500)

    @property
    def ai_confidence_threshold(self) -> float:
        """Minimum confidence for auto-routing (0.0–1.0)."""
        return self.get("pipeline.ai.confidence_threshold", 0.7)

    @property
    def person_categories_path(self) -> str:
        """Path to the person/categories YAML file."""
        return self.get("pipeline.person_categories_path", "person_categories.yaml")

    @property
    def rename_prefix(self) -> str:
        """
        Prefix for filenames that should be renamed by AI.
        Only files whose original name starts with this prefix will be renamed.
        Empty string "" means rename ALL files.
        Default: "SCN" (files like SCN_0042.pdf from the scanner).
        """
        return self.get("pipeline.rename_prefix", "SCN")

    @property
    def rename_pdfsam(self) -> bool:
        """
        Whether to rename files containing 'pdfsam' in their name.
        When True, files like 'pdfsam_basic_12345.pdf' will be renamed
        to their AI-suggested filename, in addition to SCN-prefixed files.
        Default: True.
        """
        return self.get("pipeline.rename_pdfsam", True)

    @property
    def enable_subfolder_detection(self) -> bool:
        """Whether to scan for and route into existing sub-folders in category directories."""
        return self.get("pipeline.routing.enable_subfolder_detection", True)

    @property
    def subfolder_confidence_threshold(self) -> float:
        """Minimum confidence for AI sub-folder classification (0.0–1.0)."""
        return self.get("pipeline.routing.subfolder_confidence_threshold", 0.5)

    # ── Person categories loader ────────────────────────────────────────────

    def load_person_categories(self) -> dict:
        """
        Load the person/category hierarchy from person_categories.yaml.

        Returns:
            dict with:
                - people: list of {name, prefix, categories: [...]}
        """
        if self._person_categories_cache is not None:
            return self._person_categories_cache

        path = self.person_categories_path
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Person categories file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self._person_categories_cache = data
        return data

    def clear_person_categories_cache(self) -> None:
        """Clear the person categories cache (useful for testing)."""
        self._person_categories_cache = None
