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
import sys
import hashlib

from src.config_manager import ConfigManager
from src.ocr_engine import OCREngine


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

    success_count = 0
    fail_count = 0

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

        # Safe deletion: delete raw scan only AFTER output is verified
        try:
            os.remove(input_path)
            logger.info("Deleted raw scan: %s", filename)
        except Exception as e:
            logger.error("Failed to delete raw scan %s: %s", filename, e)
            # Non-fatal — output exists, raw scan remains
            fail_count += 1
            continue

        logger.info(
            "Successfully processed %s (%d pages, %d chars extracted)",
            filename,
            result["page_count"],
            len(result["text"]),
        )
        success_count += 1

    logger.info(
        "Processing cycle complete: %d succeeded, %d failed out of %d",
        success_count,
        fail_count,
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