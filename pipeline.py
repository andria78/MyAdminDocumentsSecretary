#!/usr/bin/env python3
"""Document OCR Processing Pipeline — CLI Entry Point.

Usage:
    python pipeline.py --process                     # Process all new files
    python pipeline.py --process --config <path>     # With custom config
    python pipeline.py --help                        # Show help
"""

import argparse
import logging
import os
import re
import shutil
import sys
import hashlib

from src.config_manager import ConfigManager
from src.ocr_engine import OCREngine
from src.ai_classifier import AIClassifier


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
    if config.enable_subfolder_detection and ai_classifier is not None:
        sub_folders = scan_category_sub_folders(
            os.path.join(dest_base, person_folder), category
        )
        if sub_folders:
            logger.debug(
                "Found %d sub-folder(s) in %s/%s: %s",
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
                logger.info(
                    "Sub-folder detected: %s/%s/%s (confidence: %.2f)",
                    person_folder,
                    category,
                    sub_result["sub_folder"],
                    sub_result["confidence"],
                )
            else:
                logger.debug(
                    "Sub-folder: staying at top level of %s/%s "
                    "(success=%s, sub_folder=%s, confidence=%.2f)",
                    person_folder,
                    category,
                    sub_result.get("success"),
                    sub_result.get("sub_folder"),
                    sub_result.get("confidence", 0),
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


def process_all(config: ConfigManager) -> int:
    """
    Process all new PDF files in the raw scans folder.

    Args:
        config: Pipeline configuration.

    Returns:
        Number of files successfully processed.
    """
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

    success_count = 0
    fail_count = 0
    skipped_count = 0

    for filename in sorted(pdf_files):
        input_path = os.path.join(raw_folder, filename)
        output_path = os.path.join(output_folder, filename)

        logger.info("Processing: %s", filename)

        # Compute checksum before processing
        try:
            checksum_before = compute_sha256(input_path)
        except Exception as e:
            logger.error("Failed to read %s: %s", filename, e)
            fail_count += 1
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
            continue

        # Verify output exists
        if not os.path.isfile(output_path):
            logger.error(
                "Output file not found after OCR for %s. File preserved in raw folder.",
                filename,
            )
            fail_count += 1
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
                    # Only rename if effective filename starts with rename_prefix
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
                    # Empty rename_prefix means rename ALL files
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
            else:
                logger.warning(
                    "AI classification failed for %s: %s. "
                    "File left in intermediate folder for review.",
                    filename,
                    classification.get("error", "Unknown error"),
                )
        else:
            if ai_classifier is None:
                logger.warning(
                    "AI classifier not available. File left in intermediate folder: %s",
                    filename,
                )
            elif not ocr_text:
                logger.warning(
                    "No OCR text extracted for %s. File left in intermediate folder.",
                    filename,
                )

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
            routing_ok = route_to_destination(
                source_path=output_path,
                dest_base=dest_base,
                person=person,
                category=category,
                filename=final_filename,
                config=config,
                ai_classifier=ai_classifier,
                ocr_text=ocr_text,
            )

            if routing_ok:
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
                    # Non-fatal — destination copy exists

                # Safe deletion: delete raw scan from scanner folder
                try:
                    os.remove(input_path)
                    logger.info("Deleted raw scan: %s", filename)
                except Exception as e:
                    logger.error(
                        "Failed to delete raw scan %s: %s", filename, e
                    )
                    # Non-fatal — destination copy exists

                logger.info(
                    "Successfully processed and routed %s → %s/%s/%s",
                    filename,
                    person,
                    category,
                    final_filename,
                )
                success_count += 1
            else:
                logger.error(
                    "Routing failed for %s. File preserved in intermediate folder.",
                    filename,
                )
                # Do NOT delete raw scan — file needs attention
                fail_count += 1
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

    logger.info(
        "Processing cycle complete: %d succeeded, %d failed, %d skipped (not routed) out of %d",
        success_count,
        fail_count,
        skipped_count,
        len(pdf_files),
    )

    return success_count


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Document OCR Processing Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python pipeline.py --process                     Process all new files\n"
            "  python pipeline.py --process --config test.yaml  Use custom config\n"
        ),
    )

    parser.add_argument(
        "--process",
        action="store_true",
        help="Process all new PDF files in the raw scans folder",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)",
    )

    args = parser.parse_args()

    if not args.process:
        parser.print_help()
        sys.exit(0)

    # Load configuration
    try:
        config = ConfigManager(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
        sys.exit(1)

    # Setup logging
    setup_logging(config)

    logger = logging.getLogger("pipeline")
    logger.info("Pipeline started with config: %s", args.config)

    # Process files
    processed = process_all(config)

    if processed == 0:
        logger.info("No files were processed.")
    else:
        logger.info("Pipeline completed: %d file(s) processed successfully.", processed)


if __name__ == "__main__":
    main()
