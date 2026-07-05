#!/bin/bash
"""Safety net: removes all __TEST__ files from all pipeline folders.

Usage:
    bash scripts/cleanup_test_data.sh
    bash scripts/cleanup_test_data.sh --force    # Skip confirmation prompt

This script ONLY targets files containing __TEST__ in the filename.
It CANNOT affect real production documents.
"""

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────

# List all folders to scan for test files
SCAN_FOLDERS=(
    "/Volumes/Public/-ScansImprimante"
    "/Volumes/Administratif/00-ScansNonTries"
    "/Volumes/Administratif/30-Eric"
    "/Volumes/Administratif/40-Sophie"
    "/Volumes/Administratif/50-Elisa"
    "/Volumes/Administratif/60-Eva"
    "/Volumes/Administratif/70-Loic"
    "/Volumes/Administratif/20-Famille"
)

DATABASE_FILE="data/pipeline.db"

# ── Functions ────────────────────────────────────────────────────────────────

print_banner() {
    echo "============================================"
    echo "  Test Data Cleanup Script"
    echo "  Target: All __TEST__ files in pipeline folders"
    echo "============================================"
    echo
}

find_test_files() {
    local found_files=()
    for folder in "${SCAN_FOLDERS[@]}"; do
        if [ -d "$folder" ]; then
            while IFS= read -r file; do
                found_files+=("$file")
            done < <(find "$folder" -maxdepth 1 -type f -name "*__TEST__*" 2>/dev/null)
        else
            echo "  [SKIP] Folder does not exist: $folder"
        fi
    done
    echo "${found_files[@]}"
}

print_summary() {
    local total=$1
    echo "  $total test file(s) found."
    echo
}

delete_files() {
    local files=("$@")
    local count=0

    for file in "${files[@]}"; do
        if [ -f "$file" ]; then
            rm "$file"
            echo "  ✗ Deleted: $file"
            count=$((count + 1))
        fi
    done

    echo
    echo "Removed $count file(s)."
}

cleanup_database() {
    if [ -f "$DATABASE_FILE" ]; then
        echo
        echo "Database found at: $DATABASE_FILE"
        echo "  Test entries can be identified by '__TEST__' prefix in filenames."
        echo "  To remove them manually, run:"
        echo "    sqlite3 $DATABASE_FILE \"DELETE FROM pipeline_files WHERE original_filename LIKE '%__TEST__%';\""
        echo "  (The database schema is not yet created in Phase 1 — this is for future phases.)"
    fi
}

# ── Main ─────────────────────────────────────────────────────────────────────

print_banner

# Find all test files
echo "Scanning pipeline folders..."
echo

all_files=()
for folder in "${SCAN_FOLDERS[@]}"; do
    if [ -d "$folder" ]; then
        folder_files=$(find "$folder" -maxdepth 1 -type f -name "*__TEST__*" 2>/dev/null || true)
        for file in $folder_files; do
            all_files+=("$file")
        done
    fi
done

total=${#all_files[@]}

if [ "$total" -eq 0 ]; then
    echo "  No __TEST__ files found. Pipeline folders are clean."
    echo
    cleanup_database
    echo
    echo "Done."
    exit 0
fi

echo "Found $total __TEST__ file(s):"
echo
for file in "${all_files[@]}"; do
    echo "  • $file"
done
echo

# Confirm deletion unless --force
if [ "${1:-}" != "--force" ]; then
    read -p "Delete all $total test file(s)? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Operation cancelled."
        exit 0
    fi
fi

echo
delete_files "${all_files[@]}"
cleanup_database
echo
echo "Cleanup complete."