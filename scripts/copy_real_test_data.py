#!/usr/bin/env python3
"""Copy real documents for testing with __TEST_R__ prefix.

Reads tests/real_sources.yaml, copies each listed document to the scanner
folder with the __TEST_R{NN}__ prefix, and records the mapping in a JSON
manifest for traceability.

Usage:
    python scripts/copy_real_test_data.py                          # Copy all 10 real docs
    python scripts/copy_real_test_data.py --config tests/real_sources.yaml  # Custom source list
    python scripts/copy_real_test_data.py --dry-run                # Show what would be copied
    python scripts/copy_real_test_data.py --manifest tests/test_data/REAL/manifest.json  # Custom manifest

Safety:
    - Verifies source file exists before copying (skip with warning)
    - Refuses to overwrite existing files (unless --force)
    - NEVER modifies or touches the original source file
"""

import argparse
import json
import os
import shutil
import sys

import yaml


DEFAULT_CONFIG = "tests/real_sources.yaml"
DEFAULT_SCANNER_FOLDER = "/Volumes/Public/-ScansImprimante"
DEFAULT_MANIFEST = "tests/test_data/REAL/manifest.json"


def load_config(config_path: str) -> dict:
    """Load the real_sources.yaml configuration."""
    if not os.path.isfile(config_path):
        print(f"Error: Configuration file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "real_documents" not in data:
        print(
            f"Error: Invalid configuration format in {config_path}. "
            f"Expected top-level 'real_documents' key.",
            file=sys.stderr,
        )
        sys.exit(1)

    return data


def copy_real_documents(
    config_path: str,
    scanner_folder: str,
    manifest_path: str,
    dry_run: bool = False,
    force: bool = False,
) -> None:
    """
    Copy real documents to the scanner folder with __TEST_R__ prefix.

    Args:
        config_path: Path to real_sources.yaml.
        scanner_folder: Destination scanner folder.
        manifest_path: Path to write the manifest JSON.
        dry_run: If True, only show what would be copied.
        force: If True, overwrite existing files in scanner folder.
    """
    config = load_config(config_path)
    documents = config["real_documents"]

    if not os.path.isdir(scanner_folder):
        if dry_run:
            print(f"[DRY-RUN] Would create directory: {scanner_folder}")
        else:
            os.makedirs(scanner_folder, exist_ok=True)
            print(f"Created directory: {scanner_folder}")

    manifest = {}
    success_count = 0
    skip_count = 0
    error_count = 0

    print("=" * 60)
    print("  Real Document Copy Script")
    print(f"  Config: {config_path}")
    print(f"  Destination: {scanner_folder}")
    if dry_run:
        print("  *** DRY RUN — No files will be copied ***")
    print("=" * 60)
    print()

    for i, doc in enumerate(documents, start=1):
        source = doc.get("source", "")
        expected_person = doc.get("expected_person", "?")
        expected_category = doc.get("expected_category", "?")
        use_scn_prefix = doc.get("use_scn_prefix", False)
        notes = doc.get("notes", "")

        print(f"  [{i:02d}] {os.path.basename(source)}")

        # Check source exists
        if not os.path.isfile(source):
            print(f"        ⚠  SKIP: Source file not found: {source}")
            skip_count += 1
            continue

        # Build destination filename
        original_name = os.path.basename(source)
        if use_scn_prefix:
            dest_filename = f"__TEST_R{i:02d}__SCN_{original_name}"
        else:
            dest_filename = f"__TEST_R{i:02d}__{original_name}"

        dest_path = os.path.join(scanner_folder, dest_filename)

        # Check if destination already exists
        if os.path.exists(dest_path) and not force:
            print(f"        ⚠  SKIP: Destination already exists: {dest_filename}")
            print(f"        Use --force to overwrite.")
            skip_count += 1
            continue

        # Copy file
        if dry_run:
            print(f"        → Would copy to: {dest_filename}")
            print(f"        Person: {expected_person}, Category: {expected_category}")
            if notes:
                print(f"        Notes: {notes}")
            manifest[dest_filename] = {
                "source": source,
                "expected_person": expected_person,
                "expected_category": expected_category,
                "use_scn_prefix": use_scn_prefix,
                "notes": notes,
            }
            success_count += 1
        else:
            try:
                shutil.copy2(source, dest_path)
                print(f"        ✓ Copied to: {dest_filename}")
                print(f"        Person: {expected_person}, Category: {expected_category}")
                if notes:
                    print(f"        Notes: {notes}")
                manifest[dest_filename] = {
                    "source": source,
                    "expected_person": expected_person,
                    "expected_category": expected_category,
                    "use_scn_prefix": use_scn_prefix,
                    "notes": notes,
                }
                success_count += 1
            except Exception as e:
                print(f"        ✗ ERROR: Failed to copy: {e}")
                error_count += 1

        print()

    # Write manifest
    if not dry_run:
        manifest_dir = os.path.dirname(manifest_path)
        if manifest_dir:
            os.makedirs(manifest_dir, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        print(f"  Manifest written to: {manifest_path}")
    else:
        print(f"  [DRY-RUN] Would write manifest to: {manifest_path}")

    # Summary
    print()
    print("─" * 60)
    print(f"  Summary: {success_count} copied, {skip_count} skipped, {error_count} errors")
    print("─" * 60)

    # Mix statistics
    scn_count = sum(1 for d in documents if d.get("use_scn_prefix"))
    non_scn_count = sum(1 for d in documents if not d.get("use_scn_prefix"))
    print(f"  SCN prefix: {scn_count}, Non-SCN: {non_scn_count}")


def main():
    parser = argparse.ArgumentParser(
        description="Copy real documents for pipeline testing with __TEST_R__ prefix"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=DEFAULT_CONFIG,
        help=f"Path to real_sources.yaml (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--scanner-folder",
        type=str,
        default=DEFAULT_SCANNER_FOLDER,
        help=f"Scanner folder destination (default: {DEFAULT_SCANNER_FOLDER})",
    )
    parser.add_argument(
        "--manifest",
        type=str,
        default=DEFAULT_MANIFEST,
        help=f"Output manifest path (default: {DEFAULT_MANIFEST})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied without actually copying",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files in scanner folder",
    )
    args = parser.parse_args()

    copy_real_documents(
        config_path=args.config,
        scanner_folder=args.scanner_folder,
        manifest_path=args.manifest,
        dry_run=args.dry_run,
        force=args.force,
    )


if __name__ == "__main__":
    main()