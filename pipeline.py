#!/usr/bin/env python3
"""Document OCR Processing Pipeline — CLI Entry Point.

Usage:
    python pipeline.py --process                          # Process raw scans
    python pipeline.py --process --simulate               # Preview classification for raw scans
    python pipeline.py --process-searchable                # Process files already in searchable folder
    python pipeline.py --process-searchable --simulate     # Preview classification for searchable files
    python pipeline.py --process --config <path>           # With custom config
    python pipeline.py --help                              # Show help
"""

import argparse
import logging
import os
import re
import shutil
import signal
import sys
import hashlib
from datetime import datetime

from src.config_manager import ConfigManager
from src.ocr_engine import OCREngine
from src.ai_classifier import AIClassifier


# ── Global interrupt flag for graceful Ctrl+C handling ──────────────────────
_interrupted: bool = False


def signal_handler(sig, frame):
    """
    SIGINT handler — sets global flag for graceful shutdown.

    The current file processing completes, then reports are generated.
    A second Ctrl+C forces immediate exit.
    """
    global _interrupted
    logger = logging.getLogger("pipeline")
    if not _interrupted:
        logger.warning(
            "\n⚠️  SIGINT received. Finishing current file, "
            "then generating reports and exiting..."
        )
        _interrupted = True
    else:
        logger.warning("⚠️  Second SIGINT received. Forcing immediate exit...")
        sys.exit(1)


def setup_logging(config: ConfigManager) -> None:
    """Configure logging based on pipeline config."""
    log_level = getattr(logging, config.logging_level.upper(), logging.INFO)
    log_file = config.logging_file

    # Ensure log directory exists
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def compute_sha256(filepath: str) -> str:
    """Compute SHA-256 checksum of a file."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def strip_test_prefix(filename: str) -> str:
    """
    Strip the test prefix from a filename if present.

    Test files have the format: __TEST_S01__SCN_0042.pdf or __TEST_R01__Devis_2024.pdf
    This strips the __TEST_[SR]xx__ prefix.

    Args:
        filename: Original filename.

    Returns:
        Filename with test prefix removed, or original if no test prefix.
    """
    return re.sub(r'^__TEST_[SR]\d{2}__', '', filename)


def load_person_hierarchy(config: ConfigManager) -> dict:
    """Load and return the person/category hierarchy from YAML."""
    return config.load_person_categories()


def build_destination_path(
    config: ConfigManager,
    person: str,
    category: str,
    filename: str,
) -> str:
    """
    Build the full destination path.

    Example: /Volumes/Administratif/30-Eric/20-Achats&Fournisseurs/Facture_Orange_2024-03.pdf

    Uses the prefix from person_categories.yaml to construct the person folder name
    (e.g., "Eric" + prefix "30-" → "30-Eric").

    Args:
        config: Pipeline configuration.
        person: Person name (e.g., "Eric").
        category: Category name (e.g., "20-Achats&Fournisseurs").
        filename: Final filename (e.g., "Facture_Orange_2024-03.pdf").

    Returns:
        Full destination path string.
    """
    hierarchy = config.load_person_categories()
    prefix = ""
    for p in hierarchy.get("people", []):
        if p["name"].lower() == person.lower():
            prefix = p.get("prefix", "")
            break

    person_folder = f"{prefix}{person}"
    dest_base = config.destination_base_folder
    return os.path.join(dest_base, person_folder, category, filename)


def scan_category_sub_folders(
    person_folder_path: str,
    category: str,
) -> list[str]:
    """
    Scan a category directory for immediate sub-folders.

    Args:
        person_folder_path: Full path to the person's folder (e.g.,
            '/Volumes/Administratif/30-Eric').
        category: Category name (e.g., '20-Achats&Fournisseurs').

    Returns:
        Sorted list of sub-folder names found.
        Returns empty list if category dir doesn't exist or has no sub-folders.
        Hidden folders (starting with '.') are excluded.
    """
    category_path = os.path.join(person_folder_path, category)
    if not os.path.isdir(category_path):
        return []
    return sorted([
        entry.name for entry in os.scandir(category_path)
        if entry.is_dir() and not entry.name.startswith(".")
    ])


def route_to_destination(
    source_path: str,
    dest_base: str,
    person: str,
    category: str,
    filename: str,
    config: ConfigManager,
    ai_classifier: AIClassifier | None = None,
    ocr_text: str = "",
    subfolder_info_ref: dict | None = None,
) -> bool:
    """
    Route a file to its final destination, optionally detecting sub-folders.

    Steps:
    1. Build person folder path from dest_base + prefix + person name
    2. If enable_subfolder_detection is true:
       a. Scan category directory for existing sub-folders
       b. If sub-folders found → call ai_classifier.classify_subfolder()
       c. If valid sub-folder chosen → append to destination path
    3. Ensure destination directory exists (os.makedirs)
    4. Copy file (shutil.copy2)
    5. Verify destination exists
    6. Compute SHA-256 of destination
    7. Log result

    Args:
        source_path: Path to the source file (searchable PDF in intermediate folder).
        dest_base: Base destination folder (e.g., '/Volumes/Administratif').
        person: Person name (e.g., 'Eric').
        category: Category name (e.g., '20-Achats&Fournisseurs').
        filename: Final filename (e.g., 'Facture_Orange_2024-03.pdf').
        config: Pipeline configuration.
        ai_classifier: Optional AI classifier for sub-folder detection.
        ocr_text: OCR text for sub-folder classification.

    Returns:
        True if routing succeeded and file is verified.
    """
    logger = logging.getLogger("pipeline")

    # Build person folder path using prefix
    hierarchy = config.load_person_categories()
    prefix = ""
    for p in hierarchy.get("people", []):
        if p["name"].lower() == person.lower():
            prefix = p.get("prefix", "")
            break
    person_folder = f"{prefix}{person}"
    category_path = os.path.join(dest_base, person_folder, category)

    # Sub-folder detection
    dest_path = category_path
    sub_folder_info = {
        "enabled": config.enable_subfolder_detection,
        "sub_folders_found": [],
        "sub_folder_chosen": None,
        "sub_folder_confidence": None,
    }
    
    # Update external reference if provided
    if subfolder_info_ref is not None:
        subfolder_info_ref["enabled"] = config.enable_subfolder_detection
        subfolder_info_ref["sub_folders_found"] = []
        subfolder_info_ref["sub_folder_chosen"] = None
        subfolder_info_ref["sub_folder_confidence"] = None
    
    if config.enable_subfolder_detection and ai_classifier is not None:
        sub_folders = scan_category_sub_folders(
            os.path.join(dest_base, person_folder), category
        )
        sub_folder_info["sub_folders_found"] = sub_folders
        if subfolder_info_ref is not None:
            subfolder_info_ref["sub_folders_found"] = sub_folders.copy()
        
        if sub_folders:
            logger.info(
                "📁 Sub-folder detection: found %d sub-folder(s) in %s/%s: %s",
                len(sub_folders),
                person_folder,
                category,
                sub_folders,
            )
            sub_result = ai_classifier.classify_subfolder(
                ocr_text, person, category, sub_folders
            )
            if (sub_result.get("success")
                    and sub_result.get("sub_folder")
                    and sub_result["sub_folder"] != "top-level"
                    and sub_result.get("confidence", 0) >= config.subfolder_confidence_threshold):
                dest_path = os.path.join(category_path, sub_result["sub_folder"])
                sub_folder_info["sub_folder_chosen"] = sub_result["sub_folder"]
                sub_folder_info["sub_folder_confidence"] = sub_result["confidence"]
                if subfolder_info_ref is not None:
                    subfolder_info_ref["sub_folder_chosen"] = sub_result["sub_folder"]
                    subfolder_info_ref["sub_folder_confidence"] = sub_result["confidence"]
                logger.info(
                    "📁 Sub-folder routed: %s/%s/%s (confidence: %.2f, threshold: %.2f)",
                    person_folder,
                    category,
                    sub_result["sub_folder"],
                    sub_result["confidence"],
                    config.subfolder_confidence_threshold,
                )
            else:
                sub_folder_info["sub_folder_chosen"] = "top-level"
                sub_folder_info["sub_folder_confidence"] = sub_result.get("confidence", 0)
                if subfolder_info_ref is not None:
                    subfolder_info_ref["sub_folder_chosen"] = "top-level"
                    subfolder_info_ref["sub_folder_confidence"] = sub_result.get("confidence", 0)
                logger.info(
                    "📁 Sub-folder: staying at top level of %s/%s "
                    "(success=%s, sub_folder=%s, confidence=%.2f, threshold=%.2f)",
                    person_folder,
                    category,
                    sub_result.get("success"),
                    sub_result.get("sub_folder"),
                    sub_result.get("confidence", 0),
                    config.subfolder_confidence_threshold,
                )
        else:
            logger.info(
                "📁 Sub-folder detection: no sub-folders in %s/%s, routing to top level",
                person_folder,
                category,
            )
    else:
        logger.info(
            "📁 Sub-folder detection: disabled (enable_subfolder_detection=%s)",
            config.enable_subfolder_detection,
        )

    # Ensure destination directory exists
    os.makedirs(dest_path, exist_ok=True)
    full_dest = os.path.join(dest_path, filename)

    # Copy file (copy2 preserves metadata)
    shutil.copy2(source_path, full_dest)
    logger.info("Copied to: %s", full_dest)

    # Verify destination exists
    if not os.path.isfile(full_dest):
        logger.error("Destination file not found after copy: %s", full_dest)
        return False

    # Checksum verification
    src_checksum = compute_sha256(source_path)
    dst_checksum = compute_sha256(full_dest)
    if src_checksum != dst_checksum:
        logger.error(
            "Checksum mismatch for %s → %s", source_path, full_dest
        )
        return False

    logger.info(
        "Successfully routed to: %s (checksum verified)", full_dest
    )
    return True


# ── Simulation helpers ─────────────────────────────────────────────────────


def collect_simulation_row(
    source: str,
    filename: str,
    classification: dict | None,
    config: ConfigManager,
    subfolder_info: dict | None = None,
) -> dict:
    """
    Collect a single row of simulation data without performing any file operations.

    Args:
        source: Full path to source file.
        filename: Original filename.
        classification: AI classification result dict (or None).
        config: Pipeline configuration.
        subfolder_info: Optional sub-folder detection info dict with keys:
            - enabled: bool
            - sub_folders_found: list[str]
            - sub_folder_chosen: str | None
            - sub_folder_confidence: float | None

    Returns:
        dict with row data for the simulation table.
    """
    row: dict = {
        "source_file": os.path.basename(source),
        "source_path": source,
        "person": "N/A",
        "category": "N/A",
        "suggested_filename": "N/A",
        "confidence": None,
        "destination_path": "N/A",
        "subfolder": "N/A",
        "subfolder_enabled": False,
        "subfolder_found": [],
        "subfolder_chosen": None,
        "subfolder_confidence": None,
        "status": "⚠️",
    }

    if classification and classification.get("success"):
        person = classification["person"]
        category = classification["category"]
        suggested = classification["suggested_filename"]
        confidence = classification["confidence"]

        row["person"] = person
        row["category"] = category
        row["suggested_filename"] = suggested
        row["confidence"] = confidence

        # Determine final filename (same logic as in process_all)
        effective_filename = filename
        if config.test_mode_enabled:
            effective_filename = strip_test_prefix(filename)

        rename_prefix = config.rename_prefix
        if rename_prefix:
            if effective_filename.startswith(rename_prefix):
                final_filename = f"{suggested}.pdf"
            else:
                final_filename = filename
        else:
            final_filename = f"{suggested}.pdf"

        # Build destination path (in-memory only — no file operations)
        dest_path = build_destination_path(config, person, category, final_filename)
        row["destination_path"] = dest_path

        if confidence >= config.ai_confidence_threshold:
            row["status"] = "✅ Route"
        else:
            row["status"] = f"⬇️ LowConf ({confidence:.2f})"

    # Process sub-folder info
    if subfolder_info:
        row["subfolder_enabled"] = subfolder_info.get("enabled", False)
        row["subfolder_found"] = subfolder_info.get("sub_folders_found", [])
        row["subfolder_chosen"] = subfolder_info.get("sub_folder_chosen")
        row["subfolder_confidence"] = subfolder_info.get("sub_folder_confidence")
        
        # Update subfolder display string
        if row["subfolder_enabled"]:
            if row["subfolder_chosen"] and row["subfolder_chosen"] != "top-level":
                row["subfolder"] = f"{row['subfolder_chosen']} ({row['subfolder_confidence']:.2f})"
            elif row["subfolder_chosen"] == "top-level":
                row["subfolder"] = "top-level"
            elif row["subfolder_found"]:
                row["subfolder"] = f"Available: {', '.join(row['subfolder_found'])}"
            else:
                row["subfolder"] = "No sub-folders"
        else:
            row["subfolder"] = "Disabled"

    else:
        row["subfolder_enabled"] = False
        row["subfolder"] = "N/A"

    return row


def print_simulation_table(results: list[dict]) -> None:
    """
    Print simulation results as a formatted table.
    Uses Python's built-in string formatting (no external deps required).

    Args:
        results: List of dicts from collect_simulation_row().
    """
    if not results:
        print("\n  No files to simulate.\n")
        return

    print()
    print("=" * 160)
    print("  SIMULATION RESULTS — Classification & Routing Preview")
    print("=" * 160)

    # Header row (with sub-folder columns)
    header = (
        f"{'#':<4} {'Source File':<36} {'Person':<12} {'Category':<28} "
        f"{'Suggested Filename':<42} {'Confidence':<10} {'Status':<12} "
        f"{'Sub-folder':<15} {'Sub-Found':<30}"
    )
    print(header)
    print("-" * 160)

    for i, row in enumerate(results, 1):
        source = row.get("source_file", "")
        person = row.get("person", "N/A")
        category = row.get("category", "N/A")
        suggested = row.get("suggested_filename", "N/A")
        conf_val = row.get("confidence")
        confidence = f"{conf_val:.2f}" if conf_val is not None else "N/A"
        status = row.get("status", "⚠️")
        subfolder = row.get("subfolder", "N/A")
        sub_found = row.get("subfolder_found", [])
        sub_found_str = ", ".join(sub_found) if sub_found else "—"
        
        # Truncate long strings for display
        source_display = source if len(source) <= 35 else source[:32] + "..."
        suggested_display = suggested if len(suggested) <= 41 else suggested[:38] + "..."
        subfolder_display = subfolder if len(subfolder) <= 14 else subfolder[:11] + "..."
        sub_found_display = sub_found_str if len(sub_found_str) <= 29 else sub_found_str[:26] + "..."

        print(
            f"{i:<4} {source_display:<36} {person:<12} {category:<28} "
            f"{suggested_display:<42} {confidence:<10} {status:<12} "
            f"{subfolder_display:<15} {sub_found_display:<30}"
        )

    print("-" * 160)
    print(f"  Total: {len(results)} file(s) simulated")
    print("=" * 160)

    # Print full destination paths with sub-folder info
    print("\n  Full Destination Paths & Sub-folder Details:")
    for i, row in enumerate(results, 1):
        dest = row.get("destination_path", "N/A")
        subfolder_chosen = row.get("subfolder_chosen")
        subfolder_confidence = row.get("subfolder_confidence")
        subfolder_enabled = row.get("subfolder_enabled", False)
        
        subfolder_detail = ""
        if subfolder_enabled:
            if subfolder_chosen and subfolder_chosen != "top-level":
                subfolder_detail = f" → {subfolder_chosen} (conf: {subfolder_confidence:.2f})"
            elif subfolder_chosen == "top-level":
                subfolder_detail = " → top-level"
            else:
                subfolder_detail = " → no sub-folder match"
        
        print(f"  {i}. {dest}{subfolder_detail}")
    print()


# ── Report-generation helpers ──────────────────────────────────────────────


def generate_report_filename(prefix: str) -> str:
    """Generate a timestamped report filename (legacy, for one-off exports)."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"{prefix}_{timestamp}.md"


def _write_run_header(f, title: str) -> None:
    """Write a run separator and header to an append-mode report file."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    f.write("\n\n")
    f.write("─" * 80)
    f.write("\n\n")
    f.write(f"## Run: {now}\n\n")


def write_success_report(results: list[dict], output_dir: str) -> str:
    """
    Append the success results to a cumulative Markdown report.

    Previous runs are preserved; a new section is added for this run.

    Args:
        results: List of success result dicts with fields:
            source_file, person, category, destination_path,
            final_filename, confidence, routed_successfully
        output_dir: Directory to write the report to.

    Returns:
        Path to the written report file.
    """
    report_path = os.path.join(output_dir, "searchable_success.md")
    os.makedirs(output_dir, exist_ok=True)

    is_new = not os.path.isfile(report_path)

    successful = [r for r in results if r.get("routed_successfully")]
    not_routed = [r for r in results if not r.get("routed_successfully")]

    with open(report_path, "a", encoding="utf-8") as f:
        # Write document title only for the first run
        if is_new:
            f.write("# Searchable Folder Processing \u2014 Success Report\n\n")
            f.write(
                "This report accumulates results across all pipeline runs. "
                "Each run is separated by a horizontal rule.\n\n"
            )

        _write_run_header(f, "Searchable Folder Processing \u2014 Success Report")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total successful: {len(successful)}")
        f.write(f" | Total not routed: {len(not_routed)}")
        f.write(f" | Total processed: {len(results)}\n\n")

        if successful:
            f.write("### Routed Files\n\n")
            f.write(
                "| # | Source File | Person | Category | "
                "Destination Path | Final Filename | Confidence | Sub-folder |\n"
            )
            f.write(
                "|---|------------|--------|----------|"
                "-----------------|---------------|------------|------------|\n"
            )
            for i, row in enumerate(successful, 1):
                sub_folder = row.get('sub_folder')
                sub_confidence = row.get('sub_folder_confidence')
                if sub_folder and sub_folder != "top-level" and sub_confidence:
                    sub_folder_str = f"{sub_folder} ({sub_confidence:.2f})"
                elif sub_folder == "top-level":
                    sub_folder_str = "top-level"
                else:
                    sub_folder_str = "N/A"
                f.write(
                    f"| {i} "
                    f"| {row['source_file']} "
                    f"| {row['person']} "
                    f"| {row['category']} "
                    f"| {row['destination_path']} "
                    f"| {row['final_filename']} "
                    f"| {row['confidence']:.2f} "
                    f"| {sub_folder_str} |\n"
                )

        if not_routed:
            f.write("\n### Not Routed (High Confidence, Routing Failed)\n\n")
            f.write(
                "| # | Source File | Person | Category | "
                "Destination Path | Final Filename | Confidence | Sub-folder |\n"
            )
            f.write(
                "|---|------------|--------|----------|"
                "-----------------|---------------|------------|------------|\n"
            )
            for i, row in enumerate(not_routed, 1):
                sub_folder = row.get('sub_folder')
                sub_confidence = row.get('sub_folder_confidence')
                if sub_folder and sub_folder != "top-level" and sub_confidence:
                    sub_folder_str = f"{sub_folder} ({sub_confidence:.2f})"
                elif sub_folder == "top-level":
                    sub_folder_str = "top-level"
                else:
                    sub_folder_str = "N/A"
                f.write(
                    f"| {i} "
                    f"| {row['source_file']} "
                    f"| {row['person']} "
                    f"| {row['category']} "
                    f"| {row['destination_path']} "
                    f"| {row['final_filename']} "
                    f"| {row['confidence']:.2f} "
                    f"| {sub_folder_str} |\n"
                )
            
            # Add Sub-folder Summary section
            f.write("\n### Sub-folder Detection Summary\n\n")
            f.write("| Metric | Value |\n")
            f.write("|--------|-------|\n")
            f.write(f"| **Enable Sub-folder Detection** | Yes |\n")
            
            # Collect all unique sub-folders seen
            all_sub_folders = set()
            routed_to_subfolder = 0
            routed_to_top_level = 0
            for row in results:
                sf = row.get('sub_folder')
                if sf and sf != "N/A" and sf != "top-level":
                    all_sub_folders.add(sf)
                    routed_to_subfolder += 1
                elif sf == "top-level":
                    routed_to_top_level += 1
            
            f.write(f"| **Sub-folders Found** | {', '.join(sorted(all_sub_folders)) if all_sub_folders else 'None yet'} |\n")
            f.write(f"| **Routed to Sub-folder** | {routed_to_subfolder} |\n")
            f.write(f"| **Routed to Top-level** | {routed_to_top_level} |\n")
            f.write(f"| **Total Files Processed** | {len(results)} |\n")

    logger = logging.getLogger("pipeline")
    logger.info("Success report appended to: %s", report_path)
    return report_path


def _generate_suggestion(failure: dict, threshold: float) -> str:
    """Generate a human-readable suggestion for prompt refinement."""
    reason = failure.get("failure_reason", "")

    if reason == "INVALID_PERSON_CATEGORY":
        person = failure.get("ai_person", "?")
        category = failure.get("ai_category", "?")
        return (
            f"Person '{person}' not in hierarchy, or category '{category}' "
            f"not valid for that person. Consider adding to person_categories.yaml "
            f"or improving person detection rules in the prompt."
        )
    elif reason == "LOW_CONFIDENCE":
        conf = failure.get("confidence", 0.0)
        return (
            f"Confidence {conf:.2f} below threshold {threshold:.2f}. "
            f"Consider lowering threshold or improving document type "
            f"detection rules in the prompt."
        )
    elif reason == "TEXT_EXTRACTION_FAILED":
        return (
            "File may be corrupt or password-protected. "
            "Verify the file manually and re-scan if needed."
        )
    elif reason == "CLASSIFICATION_FAILED":
        return (
            "AI call error. Check Ollama availability and model health "
            f"({failure.get('error_details', '')})."
        )
    elif reason == "ROUTING_FAILED":
        return (
            "Destination copy or checksum verification failed. "
            "Check disk space, permissions, and destination volume mount."
        )
    elif reason == "NO_TEXT":
        return (
            "No OCR text could be extracted. File may be an image-only scan "
            "without a text layer, or OCR failed."
        )
    elif reason == "NO_CLASSIFIER":
        return (
            "Ollama server not reachable. Start Ollama with 'ollama serve' "
            "and ensure model 'qwen2.5:7b' is pulled."
        )
    else:
        return (
            f"Unhandled failure reason: {reason}. "
            f"Review logs for more details."
        )


def write_failure_report(
    failures: list[dict],
    confidence_threshold: float,
    output_dir: str,
    subfolder_threshold: float = 0.5,
) -> str:
    """
    Append the failure results to a cumulative Markdown report.

    Previous runs are preserved; a new section is added for this run.

    Args:
        failures: List of failure result dicts with fields:
            source_file, failure_reason, ai_person, ai_category,
            ai_filename, confidence, error_details
        confidence_threshold: The confidence threshold used.
        output_dir: Directory to write the report to.
        subfolder_threshold: The sub-folder confidence threshold used.

    Returns:
        Path to the written report file.
    """
    report_path = os.path.join(output_dir, "searchable_failure.md")
    os.makedirs(output_dir, exist_ok=True)

    is_new = not os.path.isfile(report_path)

    with open(report_path, "a", encoding="utf-8") as f:
        # Write document title only for the first run
        if is_new:
            f.write("# Searchable Folder Processing \u2014 Failure Report\n\n")
            f.write(
                "This report accumulates failures across all pipeline runs. "
                "Each run is separated by a horizontal rule.\n\n"
            )

        _write_run_header(f, "Searchable Folder Processing \u2014 Failure Report")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total failed: {len(failures)}")
        f.write(f" | Confidence threshold: {confidence_threshold:.2f}")
        f.write(f" | Sub-folder threshold: {subfolder_threshold:.2f}\n\n")

        if not failures:
            f.write("No failures recorded. All files processed successfully.\n\n")
        else:
            f.write(
                "| # | Source File | Failure Reason | AI Person | "
                "AI Category | AI Filename | Confidence | Sub-folder | Suggestion |\n"
            )
            f.write(
                "|---|------------|---------------|-----------|"
                "-------------|------------|------------|------------|------------|\n"
            )

            for i, row in enumerate(failures, 1):
                suggestion = _generate_suggestion(row, confidence_threshold)
                conf_str = (
                    f"{row['confidence']:.2f}"
                    if row.get("confidence") is not None
                    else "N/A"
                )
                
                # Get sub-folder info if available
                sub_folder = row.get('sub_folder', 'N/A')
                sub_confidence = row.get('sub_folder_confidence')
                if sub_folder and sub_folder != 'N/A' and sub_confidence:
                    sub_folder_str = f"{sub_folder} ({sub_confidence:.2f})"
                else:
                    sub_folder_str = str(sub_folder) if sub_folder else "N/A"

                f.write(
                    f"| {i} "
                    f"| {row['source_file']} "
                    f"| {row['failure_reason']} "
                    f"| {row.get('ai_person', 'N/A')} "
                    f"| {row.get('ai_category', 'N/A')} "
                    f"| {row.get('ai_filename', 'N/A')} "
                    f"| {conf_str} "
                    f"| {sub_folder_str} "
                    f"| {suggestion} |\n"
                )
            
            # Add Sub-folder Failure Summary
            f.write("\n### Sub-folder Failure Summary\n\n")
            f.write("| Metric | Value |\n")
            f.write("|--------|-------|\n")
            f.write(f"| **Sub-folder Confidence Threshold** | {subfolder_threshold:.2f} |\n")
            
            subfolder_failures = [f for f in failures if f.get('failure_reason') == 'SUBFOLDER_CLASSIFICATION_FAILED']
            routing_failures = [f for f in failures if f.get('failure_reason') == 'ROUTING_FAILED']
            other_failures = [f for f in failures if f.get('failure_reason') not in ['SUBFOLDER_CLASSIFICATION_FAILED', 'ROUTING_FAILED']]
            
            f.write(f"| **Sub-folder Classification Failures** | {len(subfolder_failures)} |\n")
            f.write(f"| **Routing Failures** | {len(routing_failures)} |\n")
            f.write(f"| **Other Failures** | {len(other_failures)} |\n")
            f.write(f"| **Total Failures** | {len(failures)} |\n")

    logger = logging.getLogger("pipeline")
    logger.info("Failure report appended to: %s", report_path)
    return report_path


def write_reports(
    all_results: list[dict],
    failures: list[dict],
    confidence_threshold: float,
    report_dir: str,
) -> tuple[str, str]:
    """
    Write both success and failure reports.

    Args:
        all_results: All processed file results (success report input).
        failures: Failed file records (failure report input).
        confidence_threshold: Confidence threshold used.
        report_dir: Directory to write reports to.

    Returns:
        Tuple of (success_report_path, failure_report_path).
    """
    # Ensure report directory exists before writing reports
    os.makedirs(report_dir, exist_ok=True)
    
    success_path = write_success_report(all_results, report_dir)
    failure_path = write_failure_report(failures, confidence_threshold, report_dir, subfolder_threshold=0.5)
    return success_path, failure_path


def print_report_summary(success_path: str, failure_path: str, results: list[dict] | None = None) -> None:
    """Print a summary of generated reports to stdout.
    
    Args:
        success_path: Path to the success report file.
        failure_path: Path to the failure report file.
        results: Simulation results to display (optional, falls back to module-level results).
    """
    # Use provided results or fall back to module-level results
    display_results = results if results is not None else globals().get("results", [])
    
    print()
    print("=" * 70)
    print("  REPORTS GENERATED")
    print("=" * 70)
    print(f"  Success: {success_path}")
    print(f"  Failure: {failure_path}")
    print("=" * 70)
    print()
    print("=" * 130)
    print("  SIMULATION RESULTS — Classification & Routing Preview")
    print("=" * 130)

    if not display_results:
        print("\n  No simulation results to display.\n")
        print("=" * 130)
        return

    # Header row
    header = f"{'#':<4} {'Source File':<36} {'Person':<12} {'Category':<28} {'Suggested Filename':<42} {'Confidence':<10} {'Status':<12}"
    print(header)
    print("-" * 130)

    for i, row in enumerate(display_results, 1):
        source = row.get("source_file", "")
        person = row.get("person", "N/A")
        category = row.get("category", "N/A")
        suggested = row.get("suggested_filename", "N/A")
        conf_val = row.get("confidence")
        confidence = f"{conf_val:.2f}" if conf_val is not None else "N/A"
        status = row.get("status", "⚠️")

        # Truncate long strings for display
        source_display = source if len(source) <= 35 else source[:32] + "..."
        suggested_display = suggested if len(suggested) <= 41 else suggested[:38] + "..."

        print(
            f"{i:<4} {source_display:<36} {person:<12} {category:<28} "
            f"{suggested_display:<42} {confidence:<10} {status:<12}"
        )

    print("-" * 130)
    print(f"  Total: {len(display_results)} file(s) simulated")
    print("=" * 130)

    # Print full destination paths
    print("\n  Full Destination Paths:")
    for i, row in enumerate(display_results, 1):
        dest = row.get("destination_path", "N/A")
        print(f"  {i}. {dest}")
    print()


# ── Main processing functions ──────────────────────────────────────────────


def process_all(
    config: ConfigManager,
    simulate: bool = False,
    report_dir: str = "",
) -> int:
    """
    Process all new PDF files in the raw scans folder.

    Args:
        config: Pipeline configuration.
        simulate: If True, run classification only and display results as a
                  table without moving or deleting any files.
        report_dir: Directory to write Markdown reports to. If empty, reports
                    are not generated.

    Returns:
        Number of files successfully processed (or simulated).
    """
    global _interrupted
    logger = logging.getLogger("pipeline")
    raw_folder = config.raw_scans_folder
    output_folder = config.searchable_pdf_folder

    logger.info("Starting processing cycle")
    logger.info("Raw scans folder: %s", raw_folder)
    logger.info("Searchable PDF folder: %s", output_folder)

    # Ensure output folder exists
    os.makedirs(output_folder, exist_ok=True)

    if not os.path.isdir(raw_folder):
        logger.error("Raw scans folder does not exist: %s", raw_folder)
        return 0

    # Collect PDF files
    pdf_files = [
        f for f in os.listdir(raw_folder)
        if f.lower().endswith(".pdf") and os.path.isfile(os.path.join(raw_folder, f))
    ]

    if not pdf_files:
        logger.info("No PDF files found in %s", raw_folder)
        return 0

    logger.info("Found %d PDF file(s) to process", len(pdf_files))

    # Initialize OCR engine
    ocr_engine = OCREngine(config)

    # Initialize AI classifier (graceful if Ollama is not available)
    ai_classifier = None
    try:
        ai_classifier = AIClassifier(config)
        logger.info("AI classifier initialized (model: %s)", config.ai_model)
    except Exception as e:
        logger.warning(
            "Failed to initialize AI classifier: %s. "
            "Pipeline will run OCR only (no classification/routing).",
            e,
        )

    # ── Install SIGINT handler for graceful shutdown ──────────────────────
    _interrupted = False
    original_handler = signal.signal(signal.SIGINT, signal_handler)

    success_count = 0
    fail_count = 0
    skipped_count = 0
    simulation_results: list[dict] = []
    all_results: list[dict] = []
    failure_records: list[dict] = []
    
    # Track sub-folder info for simulation results
    current_subfolder_info: dict = {
        "enabled": False,
        "sub_folders_found": [],
        "sub_folder_chosen": None,
        "sub_folder_confidence": None,
    }

    for filename in sorted(pdf_files):
        # Check for interruption at the start of each file
        if _interrupted:
            logger.warning("Interrupted — stopping before processing %s", filename)
            break
        input_path = os.path.join(raw_folder, filename)
        output_path = os.path.join(output_folder, filename)

        logger.info("Processing: %s", filename)

        # Compute checksum before processing
        try:
            checksum_before = compute_sha256(input_path)
        except Exception as e:
            logger.error("Failed to read %s: %s", filename, e)
            fail_count += 1
            failure_records.append({
                "source_file": filename,
                "failure_reason": "CHECKSUM_FAILED",
                "ai_person": "",
                "ai_category": "",
                "ai_filename": "",
                "confidence": None,
                "error_details": str(e),
            })
            continue

        # Run OCR
        result = ocr_engine.process_pdf(input_path, output_path)

        if not result["success"]:
            logger.error(
                "OCR failed for %s: %s. File preserved in raw folder.",
                filename,
                result["error"],
            )
            fail_count += 1
            failure_records.append({
                "source_file": filename,
                "failure_reason": "OCR_FAILED",
                "ai_person": "",
                "ai_category": "",
                "ai_filename": "",
                "confidence": None,
                "error_details": result.get("error", ""),
            })
            continue

        # Verify output exists
        if not os.path.isfile(output_path):
            logger.error(
                "Output file not found after OCR for %s. File preserved in raw folder.",
                filename,
            )
            fail_count += 1
            failure_records.append({
                "source_file": filename,
                "failure_reason": "OCR_OUTPUT_MISSING",
                "ai_person": "",
                "ai_category": "",
                "ai_filename": "",
                "confidence": None,
                "error_details": "OCR output file not found",
            })
            continue

        # Verify output checksum matches (integrity check)
        try:
            checksum_after = compute_sha256(output_path)
        except Exception as e:
            logger.error(
                "Failed to verify output checksum for %s: %s. File preserved.",
                filename,
                e,
            )
            fail_count += 1
            failure_records.append({
                "source_file": filename,
                "failure_reason": "CHECKSUM_VERIFY_FAILED",
                "ai_person": "",
                "ai_category": "",
                "ai_filename": "",
                "confidence": None,
                "error_details": str(e),
            })
            continue

        if checksum_before != checksum_after:
            logger.warning(
                "Checksum mismatch for %s (file may have been modified by OCR metadata). "
                "Output exists and is searchable. Proceeding.",
                filename,
            )
        else:
            logger.debug("Checksum verified for %s", filename)

        # ── Phase 2: AI Classification ──────────────────────────────────────
        ocr_text = result.get("text", "")
        page_count = result.get("page_count", 0)

        classification = None
        should_route = False
        final_filename = filename
        dest_path_str = ""

        if ai_classifier is not None and ocr_text:
            try:
                classification = ai_classifier.classify(
                    ocr_text=ocr_text,
                    filename=filename,
                    page_count=page_count,
                )
            except Exception as e:
                logger.error(
                    "AI classification failed for %s: %s. "
                    "File will remain in intermediate folder.",
                    filename,
                    e,
                )
                classification = {"success": False, "error": str(e)}

            if classification.get("success"):
                person = classification["person"]
                category = classification["category"]
                confidence = classification["confidence"]
                suggested_filename = classification["suggested_filename"]

                logger.info(
                    "AI classification: person=%s, category=%s, "
                    "confidence=%.2f, suggested=%s",
                    person,
                    category,
                    confidence,
                    suggested_filename,
                )
                logger.debug("AI reasoning: %s", classification.get("reasoning", ""))

                # Determine final filename based on rename_prefix
                # In test mode, strip test prefix first
                effective_filename = filename
                if config.test_mode_enabled:
                    effective_filename = strip_test_prefix(filename)

                rename_prefix = config.rename_prefix
                if rename_prefix:
                    if effective_filename.startswith(rename_prefix):
                        final_filename = f"{suggested_filename}.pdf"
                        logger.info(
                            "Filename renamed: %s → %s (prefix '%s' matched)",
                            filename,
                            final_filename,
                            rename_prefix,
                        )
                    else:
                        final_filename = filename
                        logger.info(
                            "Filename kept: %s (prefix '%s' not matched on '%s')",
                            filename,
                            rename_prefix,
                            effective_filename,
                        )
                else:
                    final_filename = f"{suggested_filename}.pdf"
                    logger.info(
                        "Filename renamed (rename_prefix=''): %s → %s",
                        filename,
                        final_filename,
                    )

                # Check confidence threshold
                if confidence >= config.ai_confidence_threshold:
                    should_route = True
                else:
                    logger.warning(
                        "Confidence %.2f below threshold %.2f for %s. "
                        "File left in intermediate folder for review.",
                        confidence,
                        config.ai_confidence_threshold,
                        filename,
                    )
                    failure_records.append({
                        "source_file": filename,
                        "failure_reason": "LOW_CONFIDENCE",
                        "ai_person": person,
                        "ai_category": category,
                        "ai_filename": suggested_filename,
                        "confidence": confidence,
                        "error_details": "",
                    })
            else:
                error_msg = classification.get("error", "Unknown error")
                logger.warning(
                    "AI classification failed for %s: %s. "
                    "File left in intermediate folder for review.",
                    filename,
                    error_msg,
                )
                # Determine failure reason
                if "Invalid person/category" in error_msg:
                    reason = "INVALID_PERSON_CATEGORY"
                else:
                    reason = "CLASSIFICATION_FAILED"
                failure_records.append({
                    "source_file": filename,
                    "failure_reason": reason,
                    "ai_person": classification.get("person", ""),
                    "ai_category": classification.get("category", ""),
                    "ai_filename": classification.get("suggested_filename", ""),
                    "confidence": classification.get("confidence"),
                    "error_details": error_msg,
                })
        else:
            if ai_classifier is None:
                logger.warning(
                    "AI classifier not available. File left in intermediate folder: %s",
                    filename,
                )
                failure_records.append({
                    "source_file": filename,
                    "failure_reason": "NO_CLASSIFIER",
                    "ai_person": "",
                    "ai_category": "",
                    "ai_filename": "",
                    "confidence": None,
                    "error_details": "AI classifier not initialized",
                })
            elif not ocr_text:
                logger.warning(
                    "No OCR text extracted for %s. File left in intermediate folder.",
                    filename,
                )
                failure_records.append({
                    "source_file": filename,
                    "failure_reason": "NO_TEXT",
                    "ai_person": "",
                    "ai_category": "",
                    "ai_filename": "",
                    "confidence": None,
                    "error_details": "No OCR text extracted",
                })

        # ── Simulation Mode (collect results, do NOT route) ────────────────
        if simulate:
            # Update current_subfolder_info for simulation display
            simulation_results.append(
                collect_simulation_row(
                    source=input_path,
                    filename=filename,
                    classification=classification,
                    config=config,
                    subfolder_info=current_subfolder_info,
                )
            )
            logger.info(
                "Simulation: %s → person=%s, category=%s, confidence=%s, subfolder=%s",
                filename,
                classification.get("person", "N/A") if classification else "N/A",
                classification.get("category", "N/A") if classification else "N/A",
                f"{classification.get('confidence', 0.0):.2f}" if classification else "N/A",
                current_subfolder_info.get("sub_folder_chosen", "N/A"),
            )
            success_count += 1
            continue

        # ── Phase 2: File Routing ───────────────────────────────────────────
        if should_route and classification:
            person = classification["person"]
            category = classification["category"]
            suggested_filename = classification["suggested_filename"]

            # Determine final filename (same logic as above for consistency)
            effective_filename = filename
            if config.test_mode_enabled:
                effective_filename = strip_test_prefix(filename)

            rename_prefix = config.rename_prefix
            if rename_prefix:
                if effective_filename.startswith(rename_prefix):
                    final_filename = f"{suggested_filename}.pdf"
                else:
                    final_filename = filename
            else:
                final_filename = f"{suggested_filename}.pdf"

            # Route to destination
            dest_base = config.destination_base_folder
            
            # Reset subfolder info before routing
            current_subfolder_info = {
                "enabled": config.enable_subfolder_detection,
                "sub_folders_found": [],
                "sub_folder_chosen": None,
                "sub_folder_confidence": None,
            }
            
            routing_ok = route_to_destination(
                source_path=output_path,
                dest_base=dest_base,
                person=person,
                category=category,
                filename=final_filename,
                config=config,
                ai_classifier=ai_classifier,
                ocr_text=ocr_text,
                subfolder_info_ref=current_subfolder_info,
            )

            if routing_ok:
                # Build destination path string for report
                dest_path_str = build_destination_path(
                    config, person, category, final_filename
                )

                # Safe deletion: delete intermediate searchable PDF
                try:
                    os.remove(output_path)
                    logger.info("Deleted intermediate file: %s", output_path)
                except Exception as e:
                    logger.error(
                        "Failed to delete intermediate file %s: %s",
                        output_path,
                        e,
                    )

                # Safe deletion: delete raw scan from scanner folder
                try:
                    os.remove(input_path)
                    logger.info("Deleted raw scan: %s", filename)
                except Exception as e:
                    logger.error(
                        "Failed to delete raw scan %s: %s", filename, e
                    )

                logger.info(
                    "Successfully processed and routed %s → %s/%s/%s",
                    filename,
                    person,
                    category,
                    final_filename,
                )
                success_count += 1
                all_results.append({
                    "source_file": filename,
                    "person": person,
                    "category": category,
                    "destination_path": dest_path_str,
                    "final_filename": final_filename,
                    "confidence": classification["confidence"],
                    "routed_successfully": True,
                    "sub_folder": current_subfolder_info.get("sub_folder_chosen"),
                    "sub_folder_confidence": current_subfolder_info.get("sub_folder_confidence"),
                })
            else:
                logger.error(
                    "Routing failed for %s. File preserved in intermediate folder.",
                    filename,
                )
                fail_count += 1
                failure_records.append({
                    "source_file": filename,
                    "failure_reason": "ROUTING_FAILED",
                    "ai_person": person,
                    "ai_category": category,
                    "ai_filename": suggested_filename,
                    "confidence": classification["confidence"],
                    "error_details": "route_to_destination returned False",
                })
        else:
            # File not routed — leave in intermediate folder
            # But still delete raw scan (OCR succeeded)
            try:
                os.remove(input_path)
                logger.info("Deleted raw scan (OCR done, not routed): %s", filename)
            except Exception as e:
                logger.error(
                    "Failed to delete raw scan %s: %s", filename, e
                )

            logger.info(
                "OCR completed for %s (%d pages, %d chars). "
                "File left in intermediate folder (not routed).",
                filename,
                page_count,
                len(ocr_text),
            )
            skipped_count += 1

    # ── Print simulation table if in simulation mode ──────────────────────
    if simulate and simulation_results:
        print_simulation_table(simulation_results)

    # ── Generate Markdown reports ─────────────────────────────────────────
    if report_dir:
        success_path, failure_path = write_reports(
            all_results, failure_records, config.ai_confidence_threshold, report_dir
        )
        print_report_summary(success_path, failure_path)

    # ── Restore original signal handler ───────────────────────────────────
    signal.signal(signal.SIGINT, original_handler)

    if _interrupted:
        logger.warning(
            "Pipeline interrupted by user. Reports were saved. "
            "%d succeeded, %d failed, %d skipped out of %d processed.",
            success_count,
            fail_count,
            skipped_count,
            success_count + fail_count + skipped_count,
        )
    else:
        logger.info(
            "Processing cycle complete: %d succeeded, %d failed, %d skipped (not routed) out of %d",
            success_count,
            fail_count,
            skipped_count,
            len(pdf_files),
        )

    return success_count


def process_searchable(
    config: ConfigManager,
    simulate: bool = False,
    report_dir: str = "",
) -> int:
    """
    Process PDF files already in the searchable PDF folder.

    These files are already digital/searchable, so they skip the full OCR step
    and go directly to AI classification + routing. If a file has no text layer,
    OCR is run as a fallback.

    Args:
        config: Pipeline configuration.
        simulate: If True, run classification only and display results as a
                  table without moving or deleting any files.
        report_dir: Directory to write Markdown reports to. If empty, reports
                    are not generated.

    Returns:
        Number of files successfully processed (or simulated).
    """
    global _interrupted
    logger = logging.getLogger("pipeline")
    folder = config.searchable_pdf_folder

    logger.info("Starting searchable-folder processing cycle")
    logger.info("Searchable PDF folder: %s", folder)

    if not os.path.isdir(folder):
        logger.error("Searchable PDF folder does not exist: %s", folder)
        return 0

    # Collect PDF files
    pdf_files = [
        f for f in os.listdir(folder)
        if f.lower().endswith(".pdf")
        and os.path.isfile(os.path.join(folder, f))
    ]

    if not pdf_files:
        logger.info("No PDF files found in %s", folder)
        return 0

    logger.info("Found %d PDF file(s) in searchable folder", len(pdf_files))

    # Initialize OCR engine (needed for text extraction + OCR fallback)
    ocr_engine = OCREngine(config)

    # Initialize AI classifier (graceful if Ollama is not available)
    ai_classifier = None
    try:
        ai_classifier = AIClassifier(config)
        logger.info("AI classifier initialized (model: %s)", config.ai_model)
    except Exception as e:
        logger.warning(
            "Failed to initialize AI classifier: %s. "
            "Searchable files cannot be classified.",
            e,
        )
        return 0

    # ── Install SIGINT handler for graceful shutdown ──────────────────────
    _interrupted = False
    original_handler = signal.signal(signal.SIGINT, signal_handler)

    success_count = 0
    fail_count = 0
    simulation_results: list[dict] = []
    all_results: list[dict] = []
    failure_records: list[dict] = []

    for filename in sorted(pdf_files):
        # Check for interruption at the start of each file
        if _interrupted:
            logger.warning("Interrupted — stopping before processing %s", filename)
            break

        filepath = os.path.join(folder, filename)
        logger.info("Processing: %s", filename)

        # ── Step 1: Direct text extraction (fast path) ────────────────────
        result = ocr_engine.extract_text_direct(filepath)
        if not result["success"]:
            logger.error(
                "Text extraction failed for %s: %s", filename, result["error"]
            )
            fail_count += 1
            failure_records.append({
                "source_file": filename,
                "failure_reason": "TEXT_EXTRACTION_FAILED",
                "ai_person": "",
                "ai_category": "",
                "ai_filename": "",
                "confidence": None,
                "error_details": result.get("error", ""),
            })
            continue

        ocr_text = result.get("text", "")
        page_count = result.get("page_count", 0)
        logger.info(
            "Text extracted: %d pages, %d chars", page_count, len(ocr_text)
        )

        # ── Step 2: AI Classification ─────────────────────────────────────
        classification = None
        should_route = False
        final_filename = filename
        dest_path_str = ""

        if ai_classifier is not None and ocr_text:
            try:
                classification = ai_classifier.classify(
                    ocr_text=ocr_text,
                    filename=filename,
                    page_count=page_count,
                )
            except Exception as e:
                logger.error(
                    "AI classification failed for %s: %s. "
                    "File left in searchable folder.",
                    filename,
                    e,
                )
                classification = {"success": False, "error": str(e)}

            if classification.get("success"):
                person = classification["person"]
                category = classification["category"]
                confidence = classification["confidence"]
                suggested_filename = classification["suggested_filename"]

                logger.info(
                    "AI classification: person=%s, category=%s, "
                    "confidence=%.2f, suggested=%s",
                    person,
                    category,
                    confidence,
                    suggested_filename,
                )
                logger.debug(
                    "AI reasoning: %s", classification.get("reasoning", "")
                )

                # Determine final filename
                effective_filename = filename
                if config.test_mode_enabled:
                    effective_filename = strip_test_prefix(filename)

                rename_prefix = config.rename_prefix
                if rename_prefix:
                    if effective_filename.startswith(rename_prefix):
                        final_filename = f"{suggested_filename}.pdf"
                        logger.info(
                            "Filename renamed: %s → %s (prefix '%s' matched)",
                            filename,
                            final_filename,
                            rename_prefix,
                        )
                    else:
                        final_filename = filename
                        logger.info(
                            "Filename kept: %s (prefix '%s' not matched on '%s')",
                            filename,
                            rename_prefix,
                            effective_filename,
                        )
                else:
                    final_filename = f"{suggested_filename}.pdf"
                    logger.info(
                        "Filename renamed (rename_prefix=''): %s → %s",
                        filename,
                        final_filename,
                    )

                if confidence >= config.ai_confidence_threshold:
                    should_route = True
                else:
                    logger.warning(
                        "Confidence %.2f below threshold %.2f for %s. "
                        "File left in searchable folder for review.",
                        confidence,
                        config.ai_confidence_threshold,
                        filename,
                    )
                    failure_records.append({
                        "source_file": filename,
                        "failure_reason": "LOW_CONFIDENCE",
                        "ai_person": person,
                        "ai_category": category,
                        "ai_filename": suggested_filename,
                        "confidence": confidence,
                        "error_details": "",
                    })
            else:
                error_msg = classification.get("error", "Unknown error")
                logger.warning(
                    "AI classification failed for %s: %s. "
                    "File left in searchable folder for review.",
                    filename,
                    error_msg,
                )
                # Determine failure reason
                if "Invalid person/category" in error_msg:
                    reason = "INVALID_PERSON_CATEGORY"
                else:
                    reason = "CLASSIFICATION_FAILED"
                failure_records.append({
                    "source_file": filename,
                    "failure_reason": reason,
                    "ai_person": classification.get("person", ""),
                    "ai_category": classification.get("category", ""),
                    "ai_filename": classification.get("suggested_filename", ""),
                    "confidence": classification.get("confidence"),
                    "error_details": error_msg,
                })
        else:
            if ai_classifier is None:
                logger.warning(
                    "AI classifier not available. File left in searchable folder: %s",
                    filename,
                )
                failure_records.append({
                    "source_file": filename,
                    "failure_reason": "NO_CLASSIFIER",
                    "ai_person": "",
                    "ai_category": "",
                    "ai_filename": "",
                    "confidence": None,
                    "error_details": "AI classifier not initialized",
                })
            elif not ocr_text:
                logger.warning(
                    "No text extracted for %s. File left in searchable folder.",
                    filename,
                )
                failure_records.append({
                    "source_file": filename,
                    "failure_reason": "NO_TEXT",
                    "ai_person": "",
                    "ai_category": "",
                    "ai_filename": "",
                    "confidence": None,
                    "error_details": "No text extracted from PDF",
                })

        # ── Simulation Mode (collect results, do NOT route) ────────────────
        if simulate:
            simulation_results.append(
                collect_simulation_row(
                    source=filepath,
                    filename=filename,
                    classification=classification,
                    config=config,
                )
            )
            logger.info(
                "Simulation: %s → person=%s, category=%s, confidence=%s",
                filename,
                classification.get("person", "N/A") if classification else "N/A",
                classification.get("category", "N/A") if classification else "N/A",
                f"{classification.get('confidence', 0.0):.2f}" if classification else "N/A",
            )
            success_count += 1
            continue

        # ── Step 3: File Routing ──────────────────────────────────────────
        if should_route and classification:
            person = classification["person"]
            category = classification["category"]
            suggested_filename = classification["suggested_filename"]

            # Determine final filename (same logic as above)
            effective_filename = filename
            if config.test_mode_enabled:
                effective_filename = strip_test_prefix(filename)

            rename_prefix = config.rename_prefix
            if rename_prefix:
                if effective_filename.startswith(rename_prefix):
                    final_filename = f"{suggested_filename}.pdf"
                else:
                    final_filename = filename
            else:
                final_filename = f"{suggested_filename}.pdf"

            # Route to destination
            dest_base = config.destination_base_folder
            routing_ok = route_to_destination(
                source_path=filepath,
                dest_base=dest_base,
                person=person,
                category=category,
                filename=final_filename,
                config=config,
                ai_classifier=ai_classifier,
                ocr_text=ocr_text,
            )

            if routing_ok:
                # Build destination path string for report
                dest_path_str = build_destination_path(
                    config, person, category, final_filename
                )

                # Safe deletion: delete file from searchable folder
                try:
                    os.remove(filepath)
                    logger.info("Deleted from searchable folder: %s", filename)
                except Exception as e:
                    logger.error(
                        "Failed to delete %s from searchable folder: %s",
                        filename,
                        e,
                    )

                logger.info(
                    "Successfully processed and routed %s → %s/%s/%s",
                    filename,
                    person,
                    category,
                    final_filename,
                )
                success_count += 1
                all_results.append({
                    "source_file": filename,
                    "person": person,
                    "category": category,
                    "destination_path": dest_path_str,
                    "final_filename": final_filename,
                    "confidence": classification["confidence"],
                    "routed_successfully": True,
                })
            else:
                logger.error(
                    "Routing failed for %s. File preserved in searchable folder.",
                    filename,
                )
                fail_count += 1
                failure_records.append({
                    "source_file": filename,
                    "failure_reason": "ROUTING_FAILED",
                    "ai_person": person,
                    "ai_category": category,
                    "ai_filename": suggested_filename,
                    "confidence": classification["confidence"],
                    "error_details": "route_to_destination returned False",
                })
        else:
            logger.info(
                "Text extracted for %s (%d pages, %d chars). "
                "File left in searchable folder (not routed).",
                filename,
                page_count,
                len(ocr_text),
            )
            fail_count += 1

    # ── Print simulation table if in simulation mode ──────────────────────
    if simulate and simulation_results:
        print_simulation_table(simulation_results)

    # ── Generate Markdown reports ─────────────────────────────────────────
    if report_dir:
        success_path, failure_path = write_reports(
            all_results, failure_records, config.ai_confidence_threshold, report_dir
        )
        print_report_summary(success_path, failure_path)

    # ── Restore original signal handler ───────────────────────────────────
    signal.signal(signal.SIGINT, original_handler)

    if _interrupted:
        logger.warning(
            "Pipeline interrupted by user. Reports were saved. "
            "%d succeeded, %d failed out of %d processed.",
            success_count,
            fail_count,
            success_count + fail_count,
        )
    else:
        logger.info(
            "Searchable-folder processing cycle complete: "
            "%d succeeded, %d failed out of %d",
            success_count,
            fail_count,
            len(pdf_files),
        )

    return success_count


# ── Report rebuild from log ────────────────────────────────────────────────


def _parse_log_timestamp(line: str) -> datetime | None:
    """Extract timestamp from a log line.
    
    Args:
        line: A log line starting with a timestamp.
        
    Returns:
        Parsed datetime, or None if no timestamp found.
    """
    try:
        # Log format: 2024-01-01 12:00:00,123 [INFO] pipeline: Message
        timestamp_str = line[:19]
        return datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
    except (ValueError, IndexError):
        return None


def rebuild_reports_from_log(
    log_path: str | None = None,
    report_dir: str = "",
    config: ConfigManager | None = None,
) -> tuple[str, str]:
    """
    Rebuild success and failure markdown reports from the log file.
    
    Parses log entries to extract file processing results and generates
    markdown reports in the specified report directory.
    
    Args:
        log_path: Path to the log file. If None, uses config to determine path.
        report_dir: Directory to write reports to. If empty, uses logs/ directory.
        config: Optional ConfigManager instance. If None, creates one from default config.
        
    Returns:
        Tuple of (success_report_path, failure_report_path).
        
    Raises:
        FileNotFoundError: If log file does not exist.
    """
    # Determine log path
    if log_path is None:
        if config is None:
            try:
                config = ConfigManager("config.yaml")
            except (FileNotFoundError, ValueError):
                config = ConfigManager("config.yaml")
        log_path = config.logging_file
    
    # Ensure log file exists
    if not os.path.isfile(log_path):
        raise FileNotFoundError(f"Log file not found: {log_path}")
    
    # Determine report directory
    if not report_dir:
        report_dir = os.path.join(os.path.dirname(log_path) or "logs", "reports")
    os.makedirs(report_dir, exist_ok=True)
    
    # Parse log file
    success_records: list[dict] = []
    failure_records: list[dict] = []
    
    # Regex patterns for log parsing
    routed_pattern = re.compile(
        r"Successfully routed to: (.+?) \((checksum verified|checksum mismatch)\)"
    )
    routing_failed_pattern = re.compile(
        r"Routing failed for (.+?)\. File (preserved|deleted)"
    )
    ai_classification_pattern = re.compile(
        r"AI classification: person=(.+?), category=(.+?), confidence=([0-9.]+), suggested=(.+?)(?:,|$)"
    )
    filename_renamed_pattern = re.compile(
        r"Filename (renamed|kept): (.+?) → (.+?) \((.+?)\)"
    )
    low_confidence_pattern = re.compile(
        r"Confidence ([0-9.]+) below threshold ([0-9.]+) for (.+?)"
    )
    ocr_failed_pattern = re.compile(
        r"OCR failed for (.+?): (.+?)(?:\. File|$)"
    )
    ocr_completed_pattern = re.compile(
        r"OCR completed for (.+?) \(([0-9]+) pages, ([0-9]+) chars\)"
    )
    simulation_pattern = re.compile(
        r"Simulation: (.+?) → person=(.+?), category=(.+?), confidence=([0-9.]*)"
    )
    subfolder_routed_pattern = re.compile(
        r"📁 Sub-folder routed: (.+?)/(.+?)/(.*?) \(confidence: ([0-9.]+), threshold: ([0-9.]+)\)"
    )
    subfolder_top_level_pattern = re.compile(
        r"📁 Sub-folder: staying at top level of (.+?)/(.*?) "
    )
    subfolder_detection_pattern = re.compile(
        r"📁 Sub-folder detection: found ([0-9]+) sub-folder\(s\) in (.+?)/(.*?): (.+)"
    )
    subfolder_disabled_pattern = re.compile(
        r"📁 Sub-folder detection: disabled \(enable_subfolder_detection=(.+)\)"
    )
    subfolder_no_subfolders_pattern = re.compile(
        r"📁 Sub-folder detection: no sub-folders in (.+?)/(.*?), routing to top level"
    )
    
    # State tracking for multi-line log entries
    current_file = None
    current_ai_data = {}
    current_filename_change = {}
    
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            # Extract timestamp
            timestamp = _parse_log_timestamp(line)
            
            # Track current file from source messages
            file_start_match = re.search(r"Processing: (.+?)$", line)
            if file_start_match:
                current_file = file_start_match.group(1)
                current_ai_data = {}
                current_filename_change = {}
            
            # AI classification data
            ai_match = ai_classification_pattern.search(line)
            if ai_match:
                current_ai_data = {
                    "person": ai_match.group(1),
                    "category": ai_match.group(2),
                    "confidence": float(ai_match.group(3)),
                    "suggested_filename": ai_match.group(4).rstrip(","),
                }
            
            # Filename change
            rename_match = filename_renamed_pattern.search(line)
            if rename_match:
                action = rename_match.group(1)
                if action == "renamed":
                    current_filename_change["final_filename"] = rename_match.group(3)
                else:
                    current_filename_change["final_filename"] = rename_match.group(2)
            
            # Low confidence
            low_conf_match = low_confidence_pattern.search(line)
            if low_conf_match:
                confidence = float(low_conf_match.group(1))
                threshold = float(low_conf_match.group(2))
                source = low_conf_match.group(3).strip()
                failure_records.append({
                    "source_file": source,
                    "failure_reason": "LOW_CONFIDENCE",
                    "ai_person": current_ai_data.get("person", ""),
                    "ai_category": current_ai_data.get("category", ""),
                    "ai_filename": current_ai_data.get("suggested_filename", ""),
                    "confidence": confidence,
                    "error_details": f"Confidence {confidence:.2f} below threshold {threshold:.2f}",
                    "timestamp": timestamp,
                })
            
            # Sub-folder routed detection
            subfolder_routed_match = subfolder_routed_pattern.search(line)
            routed_match_local = routed_pattern.search(line)
            if subfolder_routed_match and routed_match_local:
                if not hasattr(current_ai_data, '_subfolder'):
                    current_ai_data['_subfolder'] = {
                        "routed": True,
                        "sub_folder": None,
                        "confidence": float(subfolder_routed_match.group(4)),
                    }
                    # Extract sub-folder name from destination path
                    dest_path_for_subfolder = routed_match_local.group(1)
                    # Parse sub-folder from path like "30-Eric/20-Achats&Fournisseurs/30-FournisseursEnergie/file.pdf"
                    path_parts = dest_path_for_subfolder.split('/')
                    if len(path_parts) >= 4:
                        current_ai_data['_subfolder']['sub_folder'] = path_parts[-2]
            
            # Successfully routed (success)
            routed_match = routed_pattern.search(line)
            if routed_match:
                dest_path = routed_match.group(1)
                checksum_status = routed_match.group(2)
                
                # Extract just the filename from destination path
                filename = os.path.basename(dest_path)
                
                # Extract sub-folder info if available
                sub_folder = None
                sub_confidence = None
                if '_subfolder' in current_ai_data:
                    sub_data = current_ai_data['_subfolder']
                    if sub_data.get("routed") and sub_data.get("sub_folder"):
                        sub_folder = sub_data["sub_folder"]
                        sub_confidence = sub_data["confidence"]
                    del current_ai_data['_subfolder']
                
                success_records.append({
                    "source_file": current_file or filename,
                    "person": current_ai_data.get("person", "N/A"),
                    "category": current_ai_data.get("category", "N/A"),
                    "destination_path": dest_path,
                    "final_filename": current_filename_change.get("final_filename", filename),
                    "confidence": current_ai_data.get("confidence", 0.0),
                    "routed_successfully": True,
                    "checksum_status": checksum_status,
                    "timestamp": timestamp,
                    "sub_folder": sub_folder,
                    "sub_folder_confidence": sub_confidence,
                })
                
                # Reset state after routing
                current_file = None
                current_ai_data = {}
                current_filename_change = {}
            
            # Routing failed
            routing_failed_match = routing_failed_pattern.search(line)
            if routing_failed_match:
                source = routing_failed_match.group(1)
                action = routing_failed_match.group(2)
                
                failure_records.append({
                    "source_file": source,
                    "failure_reason": "ROUTING_FAILED",
                    "ai_person": current_ai_data.get("person", ""),
                    "ai_category": current_ai_data.get("category", ""),
                    "ai_filename": current_ai_data.get("suggested_filename", ""),
                    "confidence": current_ai_data.get("confidence"),
                    "error_details": f"File {action} in searchable folder",
                    "timestamp": timestamp,
                })
            
            # OCR failed
            ocr_failed_match = ocr_failed_pattern.search(line)
            if ocr_failed_match:
                source = ocr_failed_match.group(1)
                error = ocr_failed_match.group(2)
                failure_records.append({
                    "source_file": source,
                    "failure_reason": "OCR_FAILED",
                    "ai_person": "",
                    "ai_category": "",
                    "ai_filename": "",
                    "confidence": None,
                    "error_details": error,
                    "timestamp": timestamp,
                })
            
            # OCR completed (not routed)
            ocr_completed_match = ocr_completed_pattern.search(line)
            if ocr_completed_match:
                source = ocr_completed_match.group(1)
                page_count = int(ocr_completed_match.group(2))
                char_count = int(ocr_completed_match.group(3))
                
                # This is a success but not routed (low confidence or no AI)
                if not current_ai_data:
                    success_records.append({
                        "source_file": source,
                        "person": "N/A",
                        "category": "N/A",
                        "destination_path": "N/A",
                        "final_filename": source,
                        "confidence": 0.0,
                        "routed_successfully": False,
                        "timestamp": timestamp,
                    })
    
    # Write success report
    success_path = write_success_report(success_records, report_dir)
    
    # Write failure report
    failure_path = write_failure_report(
        failure_records,
        config.ai_confidence_threshold if config else 0.7,
        report_dir
    )
    
    # Print summary
    print()
    print("=" * 70)
    print("  REPORTS REBUILT FROM LOG")
    print("=" * 70)
    print(f"  Log file: {log_path}")
    print(f"  Success records: {len(success_records)}")
    print(f"  Failure records: {len(failure_records)}")
    print(f"  Success report: {success_path}")
    print(f"  Failure report: {failure_path}")
    print("=" * 70)
    print()
    
    return success_path, failure_path


# ── CLI entry point ────────────────────────────────────────────────────────


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Document OCR Processing Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python pipeline.py --process                          "
            "Process raw scans\n"
            "  python pipeline.py --process --config test.yaml       "
            "Use custom config\n"
            "  python pipeline.py --process --simulate               "
            "Preview classification\n"
            "  python pipeline.py --process-searchable                "
            "Process searchable folder\n"
            "  python pipeline.py --process-searchable --simulate     "
            "Preview searchable folder\n"
            "  python pipeline.py --rebuild-from-log                  "
            "Rebuild reports from log file\n"
            "  python pipeline.py --rebuild-from-log --report-dir /path\n"
            "Rebuild to custom directory\n"
        ),
    )

    parser.add_argument(
        "--process",
        action="store_true",
        help="Process all new PDF files in the raw scans folder",
    )
    parser.add_argument(
        "--process-searchable",
        action="store_true",
        help=(
            "Process PDF files already in the searchable folder "
            "(skip OCR, go direct to AI classification)"
        ),
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help=(
            "Run in simulation mode: show classification results as a table "
            "without moving or deleting any files"
        ),
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)",
    )
    parser.add_argument(
        "--report-dir",
        type=str,
        default="",
        help=(
            "Directory to write Markdown reports (success and failure). "
            "If not specified, reports are not generated."
        ),
    )
    parser.add_argument(
        "--rebuild-from-log",
        action="store_true",
        help=(
            "Rebuild success and failure reports from the existing log file. "
            "Does not process any files - only parses logs and generates reports."
        ),
    )

    args = parser.parse_args()

    # Load configuration early for rebuild mode
    config = None
    if args.rebuild_from_log or args.process or args.process_searchable:
        try:
            config = ConfigManager(args.config)
        except (FileNotFoundError, ValueError) as e:
            print(f"Error loading configuration: {e}", file=sys.stderr)
            sys.exit(1)

    # Handle rebuild from log
    if args.rebuild_from_log:
        if config is None:
            config = ConfigManager(args.config)
        
        log_path = config.logging_file
        report_dir = args.report_dir if args.report_dir else ""
        
        print(f"Rebuilding reports from log: {log_path}")
        
        try:
            success_path, failure_path = rebuild_reports_from_log(
                log_path=log_path,
                report_dir=report_dir,
                config=config,
            )
            print(f"Reports rebuilt successfully.")
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if not args.process and not args.process_searchable:
        parser.print_help()
        sys.exit(0)

    # Setup logging (config is guaranteed to be non-None here)
    if config is not None:
        setup_logging(config)

        logger = logging.getLogger("pipeline")
        logger.info("Pipeline started with config: %s", args.config)

        if args.simulate:
            logger.info("SIMULATION MODE — no files will be moved or deleted")

        if args.report_dir:
            logger.info("Reports will be written to: %s", args.report_dir)

        # Process files
        processed = 0
        if args.process_searchable:
            processed = process_searchable(
                config, simulate=args.simulate, report_dir=args.report_dir
            )
        elif args.process:
            processed = process_all(
                config, simulate=args.simulate, report_dir=args.report_dir
            )

        if processed == 0:
            logger.info("No files were processed.")
        else:
            logger.info("Pipeline completed: %d file(s) processed successfully.", processed)
    else:
        print("Error: Configuration not available for processing.", file=sys.stderr)
        sys.exit(1)

    if processed == 0:
        logger.info("No files were processed.")
    else:
        logger.info("Pipeline completed: %d file(s) processed successfully.", processed)


if __name__ == "__main__":
    main()
