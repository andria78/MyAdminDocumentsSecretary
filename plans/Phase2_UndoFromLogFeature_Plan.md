# Undo from Log — Feature Plan

## 1. Overview

The `undo from log` feature enables restoring files that were previously classified and routed from the searchable folder (`/Volumes/Administratif/00-ScansNonTries`) to their final destinations, by parsing the pipeline log file.

### 1.1 Problem Statement

When the pipeline processes files:
1. Files are OCR'd and placed in the searchable folder
2. AI classifies them (person, category, suggested filename, confidence)
3. Files are routed to their final destination (e.g., `/Volumes/Administratif/30-Eric/20-Achats&Fournisseurs/Facture_Orange_2024-03.pdf`)
4. Files are deleted from the searchable folder and raw scans folder

Currently, if a file was misclassified or the user wants to reorganize, there's no easy way to:
- Identify which files were routed where
- Restore them back to the searchable folder for re-processing
- Filter by date, person, category, or confidence

### 1.2 Solution

Create a new CLI command `--undo-from-log` that:
1. Parses the log file to extract routing information
2. Copies files back from their destination to the searchable folder
3. Optionally renames them back to their original names
4. Generates an undo report

---

## 2. Log Analysis

### 2.1 Key Log Patterns for Undo

The following log entries contain all the data needed for undo:

| Pattern | Data Extracted | Example |
|---------|---------------|---------|
| `Processing: SCN_0042.pdf` | Source filename | `SCN_0042.pdf` |
| `AI classification: person=Eric, category=20-Achats&Fournisseurs, confidence=0.95, suggested=Facture_Orange_2024-03` | Person, Category, Confidence, Suggested filename | `Eric`, `20-Achats&Fournisseurs`, `0.95`, `Facture_Orange_2024-03` |
| `Filename renamed: SCN_0042.pdf → Facture_Orange_2024-03.pdf (prefix 'SCN' matched)` | Original → Final filename | `SCN_0042.pdf` → `Facture_Orange_2024-03.pdf` |
| `Copied to: /Volumes/Administratif/30-Eric/20-Achats&Fournisseurs/Facture_Orange_2024-03.pdf` | Full destination path | `/Volumes/Administratif/30-Eric/20-Achats&Fournisseurs/Facture_Orange_2024-03.pdf` |
| `📁 Sub-folder routed: 30-Eric/20-Achats&Fournisseurs/30-FournisseursEnergie/file.pdf` | Sub-folder info | `30-FournisseursEnergie` |
| `Deleted intermediate file: /Volumes/Administratif/00-ScansNonTries/SCN_0042.pdf` | Searchable folder path | `/Volumes/Administratif/00-ScansNonTries/SCN_0042.pdf` |
| `Deleted raw scan: SCN_0042.pdf` | Raw scan path | `/Volumes/Public/-ScansImprimante/SCN_0042.pdf` |
| `Successfully routed to: ... (checksum verified)` | Confirmation | Checksum status |

### 2.2 Data Model for Undo Records

```python
@dataclass
class UndoRecord:
    """Represents a file that can be undone."""
    source_file: str                    # Original filename (e.g., SCN_0042.pdf)
    final_filename: str                 # Final filename after routing (e.g., Facture_Orange_2024-03.pdf)
    person: str                         # Classified person (e.g., Eric)
    category: str                       # Classified category (e.g., 20-Achats&Fournisseurs)
    destination_path: str               # Full destination path
    confidence: float                   # Classification confidence
    sub_folder: str | None              # Sub-folder if routed (e.g., 30-FournisseursEnergie)
    timestamp: datetime | None          # Log timestamp
    checksum_status: str                # "checksum verified" or "checksum mismatch"
    original_path_in_dest: str          # Full path to file in destination
    searchable_path: str                # Path where file should be restored
```

### 2.3 Feasibility Assessment

| Requirement | Feasibility | Notes |
|------------|-------------|-------|
| Extract person/category | ✅ | Directly from log pattern |
| Extract destination path | ✅ | Directly from "Copied to:" line |
| Extract original filename | ✅ | From "Processing:" line |
| Extract confidence | ✅ | From AI classification line |
| Extract sub-folder | ✅ | From sub-folder patterns |
| Locate file in destination | ✅ | File exists at destination_path |
| Restore to searchable folder | ✅ | Use config.searchable_pdf_folder |
| Handle renamed files | ✅ | Track original → final mapping |
| Handle sub-folder files | ✅ | Parse sub-folder from path |
| Filter by date range | ✅ | Timestamps available in log |
| Filter by person | ✅ | Person field available |
| Filter by category | ✅ | Category field available |
| Filter by confidence | ✅ | Confidence field available |
| Dry-run mode | ✅ | Simulate without copying |
| Batch undo | ✅ | Process multiple files |

---

## 3. Feature Design

### 3.1 CLI Interface

```bash
# Undo all files from log
python pipeline.py --undo-from-log

# Undo with dry-run (preview only)
python pipeline.py --undo-from-log --dry-run

# Undo files after a specific date
python pipeline.py --undo-from-log --after 2026-07-08

# Undo files before a specific date
python pipeline.py --undo-from-log --before 2026-07-09

# Undo files for a specific person
python pipeline.py --undo-from-log --person Eric

# Undo files for a specific category
python pipeline.py --undo-from-log --category 20-Achats&Fournisseurs

# Undo files with confidence below threshold
python pipeline.py --undo-from-log --max-confidence 0.8

# Undo specific file by name
python pipeline.py --undo-from-log --file SCN_0042.pdf

# Restore with original filename
python pipeline.py --undo-from-log --restore-name

# Number of most recent files to undo
python pipeline.py --undo-from-log --count 50
```

### 3.2 Command Combinations

| Combination | Behavior |
|------------|----------|
| `--undo-from-log --dry-run` | Show what would be undone without copying |
| `--undo-from-log --restore-name` | Copy back with original filename (not suggested) |
| `--undo-from-log --count N` | Undo only the N most recent files |
| `--undo-from-log --after DATE --person P` | Combined date + person filter |
| `--undo-from-log --max-confidence C` | Undo only files with confidence ≤ C |

### 3.3 Workflow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        UNDO FROM LOG FLOW                           │
└─────────────────────────────────────────────────────────────────────┘

1. Parse Log File
   ├── Read pipeline.log
   ├── Extract routing entries
   ├── Build UndoRecord list
   └── Apply filters (date, person, category, confidence, count)

2. Locate Files
   ├── For each UndoRecord:
   │   ├── Check file exists at destination_path
   │   ├── Verify file is accessible
   │   └── Compute expected searchable path
   └── Report any missing files

3. Preview (if --dry-run)
   ├── Display table of files to undo
   ├── Show source → destination → searchable path
   └── Wait for confirmation (or exit)

4. Execute Undo
   ├── For each file:
   │   ├── Copy file to searchable_pdf_folder
   │   ├── Use original name (if --restore-name) or final name
   │   ├── Log each undo operation
   │   └── Verify copy with checksum
   └── Generate undo report

5. Report
   ├── Success count / failure count
   ├── List of restored files with paths
   └── Append to searchable_undo.md report
```

---

## 4. Implementation Plan

### 4.1 New Functions in `pipeline.py`

#### 4.1.1 `parse_undo_records(log_path: str, config: ConfigManager) -> list[UndoRecord]`

Parses the log file and returns a list of undo records.

**Steps:**
1. Open log file
2. Iterate through lines, tracking state per file
3. Match patterns:
   - `Processing: <filename>` → start new record
   - `AI classification: person=<p>, category=<c>, confidence=<conf>, suggested=<s>` → update record
   - `Filename renamed/kept: <orig> → <final>` → update filename mapping
   - `Copied to: <path>` → set destination path
   - `📁 Sub-folder routed: ...` or `📁 Sub-folder: staying at top level of ...` → set sub-folder
   - `Successfully routed to: <path> (<checksum>)` → finalize record
4. Return list of UndoRecords

#### 4.1.2 `filter_undo_records(records: list[UndoRecord], **filters) -> list[UndoRecord]`

Applies filters to the undo records.

**Filters:**
- `after: datetime` — only records after this date
- `before: datetime` — only records before this date
- `person: str` — only records for this person
- `category: str` — only records for this category
- `max_confidence: float` — only records with confidence ≤ this value
- `min_confidence: float` — only records with confidence ≥ this value
- `file: str` — only records matching this filename
- `count: int` — only the N most recent records

#### 4.1.3 `undo_from_log(config: ConfigManager, **options) -> tuple[int, int]`

Main undo function. Returns (success_count, failure_count).

**Steps:**
1. Parse log file → records
2. Apply filters
3. Locate files
4. Preview (if dry-run)
5. Execute copy operations
6. Generate report

#### 4.1.4 `print_undo_preview(records: list[UndoRecord]) -> None`

Displays a table of files to be undone.

**Table columns:**
| # | Original Name | Final Name | Person | Category | Destination | Confidence | Sub-folder |

#### 4.1.5 `write_undo_report(success_records: list[UndoRecord], failures: list[dict], report_dir: str) -> str`

Appends undo results to a cumulative report file (`searchable_undo.md`).

### 4.2 CLI Argument Additions

Add to the existing argument parser:

```python
parser.add_argument(
    "--undo-from-log",
    action="store_true",
    help="Undo routed files by parsing the log file. "
         "Copies files back from their destination to the searchable folder.",
)
parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Preview undo operations without actually copying files.",
)
parser.add_argument(
    "--after",
    type=str,
    help="Only undo files processed after this date (YYYY-MM-DD).",
)
parser.add_argument(
    "--before",
    type=str,
    help="Only undo files processed before this date (YYYY-MM-DD).",
)
parser.add_argument(
    "--person",
    type=str,
    help="Only undo files for this person.",
)
parser.add_argument(
    "--category",
    type=str,
    help="Only undo files for this category.",
)
parser.add_argument(
    "--max-confidence",
    type=float,
    help="Only undo files with confidence at or below this value.",
)
parser.add_argument(
    "--min-confidence",
    type=float,
    help="Only undo files with confidence at or above this value.",
)
parser.add_argument(
    "--file",
    type=str,
    help="Only undo this specific file (by original name).",
)
parser.add_argument(
    "--restore-name",
    action="store_true",
    help="Restore files with their original name (not the suggested name).",
)
parser.add_argument(
    "--count",
    type=int,
    help="Only undo the N most recent files.",
)
```

### 4.3 Main Function Update

Update `main()` to handle the new `--undo-from-log` flag:

```python
if args.undo_from_log:
    config = ConfigManager(args.config)
    setup_logging(config)
    
    # Parse date filters
    after_dt = datetime.strptime(args.after, "%Y-%m-%d") if args.after else None
    before_dt = datetime.strptime(args.before, "%Y-%m-%d") if args.before else None
    
    # Execute undo
    success, failures = undo_from_log(
        config=config,
        dry_run=args.dry_run,
        after=after_dt,
        before=before_dt,
        person=args.person,
        category=args.category,
        max_confidence=args.max_confidence,
        min_confidence=args.min_confidence,
        file=args.file,
        restore_name=args.restore_name,
        count=args.count,
    )
    
    logger.info("Undo complete: %d succeeded, %d failed", success, failures)
    return
```

---

## 5. Report Format

### 5.1 Undo Report (`searchable_undo.md`)

```markdown
# Searchable Folder Processing — Undo Report

This report accumulates undo results across all pipeline runs.

## Run: 2026-07-09 08:00:00

Generated: 2026-07-09 08:00:00
Total undone: 50
Total failures: 2

### Restored Files

| # | Original Name | Final Name | Person | Category | Destination | Confidence | Sub-folder |
|---|--------------|------------|--------|----------|-------------|------------|------------|
| 1 | SCN_0042.pdf | Facture_Orange_2024-03.pdf | Eric | 20-Achats&Fournisseurs | /Volumes/Administratif/30-Eric/20-Achats&Fournisseurs/Facture_Orange_2024-03.pdf | 0.95 | N/A |
| 2 | SCN_0043.pdf | Relevé_Bancaire_Famille.pdf | Famille | 90-Financier | /Volumes/Administratif/20-Famille/90-Financier/SNCF/Releve_Bancaire_Famille.pdf | 0.92 | SNCF |

### Failures

| # | Source File | Error |
|---|------------|-------|
| 1 | SCN_0050.pdf | File not found at destination |
| 2 | SCN_0051.pdf | Copy failed - disk full |
```

---

## 6. Edge Cases & Considerations

### 6.1 Edge Cases

| Edge Case | Handling |
|-----------|----------|
| File deleted from destination | Report as failure, continue with others |
| File renamed manually after routing | Use destination_path from log, not current filesystem |
| Multiple routing entries for same file | Use the most recent entry |
| Log file rotated/old | Support `--after` to limit scope |
| Files in sub-folders | Parse sub-folder from path correctly |
| Test mode files (`__TEST_S01__SCN_0042.pdf`) | Strip test prefix correctly |
| Files with special characters in path | Handle Unicode, spaces, ampersands |
| Empty log file | Report "No records found" |
| Very large log file | Process line-by-line (streaming) |

### 6.2 Configuration Options

Add to `config.yaml`:

```yaml
  undo:
    default_count: 100          # Default number of files to undo
    default_restore_name: false # Whether to restore original name by default
    report_file: "searchable_undo.md"
    create_backup: false        # Create .undo_backup copy before removing from destination
```

---

## 7. Implementation Phases

### Phase 1: Core Functionality (Priority: High)

- [ ] Add `UndoRecord` dataclass
- [ ] Implement `parse_undo_records()` — basic log parsing
- [ ] Implement `undo_from_log()` — core copy-back logic
- [ ] Add `--undo-from-log` CLI flag
- [ ] Add `--dry-run` support
- [ ] Write basic undo report

### Phase 2: Filtering & Options (Priority: Medium)

- [ ] Implement filter functions (date, person, category, confidence)
- [ ] Add CLI filter arguments
- [ ] Implement `--restore-name` option
- [ ] Implement `--count` option
- [ ] Improve preview table with all fields

### Phase 3: Robustness & Polish (Priority: Medium)

- [ ] Handle edge cases (missing files, special characters)
- [ ] Add checksum verification for undo operations
- [ ] Support partial undo (selective file selection)
- [ ] Add `--file` for single file undo
- [ ] Improve error handling and reporting

### Phase 4: Advanced Features (Priority: Low)

- [ ] Add `--after`/`--before` date filtering
- [ ] Support log file rotation
- [ ] Add undo history tracking
- [ ] Consider `--redo` (reverse of undo — move back to destination)

---

## 8. Code Location

All changes will be made in [`pipeline.py`](../pipeline.py):

- **UndoRecord dataclass**: After existing imports (~line 20-30)
- **parse_undo_records()**: After `rebuild_reports_from_log()` (~line 2076)
- **filter_undo_records()**: After `parse_undo_records()`
- **undo_from_log()**: After `filter_undo_records()`
- **print_undo_preview()**: After `undo_from_log()`
- **write_undo_report()**: After `print_undo_preview()`
- **CLI arguments**: In `main()` argument parser (~line 2105)
- **Undo handling in main()**: After existing rebuild handling (~line 2182)

---

## 9. Example Usage Scenarios

### Scenario 1: Undo all recent files
```bash
python pipeline.py --undo-from-log --count 100
```
→ Parses the last 100 routing entries, copies files back to searchable folder.

### Scenario 2: Undo Eric's invoices
```bash
python pipeline.py --undo-from-log --person Eric --category 20-Achats&Fournisseurs
```
→ Finds all files classified to Eric > 20-Achats&Fournisseurs, restores them.

### Scenario 3: Preview before undo
```bash
python pipeline.py --undo-from-log --dry-run
```
→ Shows table of files that would be undone without copying.

### Scenario 4: Undo low-confidence classifications
```bash
python pipeline.py --undo-from-log --max-confidence 0.8
```
→ Restores files with confidence ≤ 0.8 for re-classification.

### Scenario 5: Undo after a specific date
```bash
python pipeline.py --undo-from-log --after 2026-07-08 --restore-name
```
→ Restores files processed after July 8th, using their original filenames.

---

## 10. Summary

The `undo from log` feature is **highly feasible** given the current log structure:

1. ✅ All required data (person, category, destination path, filename, confidence, sub-folder) is captured in the log
2. ✅ Files are verified with checksums during routing, so we know they exist at destination
3. ✅ The searchable folder path is configurable and consistent
4. ✅ The existing `rebuild_reports_from_log()` function provides a pattern for log parsing
5. ✅ No changes needed to `config.yaml` for basic functionality
6. ✅ The feature can be implemented incrementally (Phases 1-4)

**Estimated implementation effort**: 2-3 days for Phase 1-2, 4-5 days for full implementation.
