#!/bin/bash
# Safety net: removes all __TEST_S*__ and __TEST_R*__ files from all pipeline
# folders, and cleans up test sub-folders created for sub-folder validation.
#
# This script targets files matching the glob pattern *__TEST_*, which covers:
#   - Synthetic test files:  __TEST_S01__, __TEST_S02__, ..., __TEST_S12__
#   - Real document copies:  __TEST_R01__, __TEST_R02__, ..., __TEST_R10__
# It NEVER touches original source files.
#
# Usage:
#     bash scripts/cleanup_test_data.sh
#     bash scripts/cleanup_test_data.sh --force    # Skip confirmation prompt
#     bash scripts/cleanup_test_data.sh --no-subfolders  # Skip sub-folder cleanup

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

# Test sub-folders created for sub-folder routing validation (Phase 2)
TEST_SUB_FOLDERS=(
    "/Volumes/Administratif/30-Eric/20-Achats&Fournisseurs/30-FournisseursEnergie"
    "/Volumes/Administratif/30-Eric/20-Achats&Fournisseurs/40-FournisseursInternet"
    "/Volumes/Administratif/20-Famille/20-Achats&Fournisseurs/30-FournisseursEnergie"
)

DATABASE_FILE="data/pipeline.db"

# ── Functions ────────────────────────────────────────────────────────────────

print_banner() {
    echo "============================================"
    echo "  Test Data Cleanup Script"
    echo "  Target: All __TEST_* files in pipeline folders"
    echo "============================================"
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
    echo "  Removed $count file(s)."
}

cleanup_sub_folders() {
    echo
    echo "Cleaning up test sub-folders created for sub-folder validation..."
    echo

    local count=0
    for subfolder in "${TEST_SUB_FOLDERS[@]}"; do
        if [ -d "$subfolder" ]; then
            # Only remove if empty (safety: never remove non-empty dirs)
            if [ -z "$(ls -A "$subfolder" 2>/dev/null)" ]; then
                rmdir "$subfolder"
                echo "  ✗ Removed empty sub-folder: $subfolder"
                count=$((count + 1))
            else
                echo "  ⚠  Skipping non-empty sub-folder: $subfolder"
                echo "     (Remove manually after inspecting contents)"
            fi
        else
            echo "  - Sub-folder does not exist: $subfolder"
        fi
    done

    echo
    echo "  Cleaned up $count sub-folder(s)."
}

cleanup_database() {
    if [ -f "$DATABASE_FILE" ]; then
        echo
        echo "Database found at: $DATABASE_FILE"
        echo "  Test entries can be identified by '__TEST_' prefix in filenames."
        echo "  To remove them manually, run:"
        echo "    sqlite3 $DATABASE_FILE \"DELETE FROM pipeline_files WHERE original_filename LIKE '%__TEST_%';\""
        echo "  (The database schema is not yet created — this is for future phases.)"
    fi
}

# ── Main ─────────────────────────────────────────────────────────────────────

DO_SUBFOLDERS=true
if [ "${1:-}" == "--no-subfolders" ] || [ "${2:-}" == "--no-subfolders" ]; then
    DO_SUBFOLDERS=false
fi

print_banner

# Find all test files
echo "Scanning pipeline folders..."
echo

all_files=()
for folder in "${SCAN_FOLDERS[@]}"; do
    if [ -d "$folder" ]; then
        while IFS= read -r -d '' file; do
            all_files+=("$file")
        done < <(find "$folder" -maxdepth 1 -type f -name "*__TEST_*" -print0 2>/dev/null || true)
    else
        echo "  [SKIP] Folder does not exist: $folder"
    fi
done

total=${#all_files[@]}

if [ "$total" -eq 0 ]; then
    echo "  No __TEST_* files found. Pipeline folders are clean."
    echo
else
    echo "Found $total __TEST_* file(s):"
    echo
    for file in "${all_files[@]}"; do
        echo "  • $file"
    done
    echo

    # Confirm deletion unless --force
    if [ "${1:-}" != "--force" ] && [ "${2:-}" != "--force" ]; then
        read -p "Delete all $total test file(s)? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Operation cancelled."
            exit 0
        fi
    fi

    echo
    delete_files "${all_files[@]}"
fi

# Phase 2: Clean up test sub-folders (unless --no-subfolders)
if [ "$DO_SUBFOLDERS" = true ]; then
    cleanup_sub_folders
fi

cleanup_database
echo
echo "Cleanup complete."