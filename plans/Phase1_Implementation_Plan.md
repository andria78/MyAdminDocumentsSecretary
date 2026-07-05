# Phase 1: Core OCR Pipeline — Refined Implementation Plan

> **Based on**: `DocumentOCRProcessingPipeline_Final.md`
> **Goal**: End-to-end OCR pipeline that reads raw scanned PDFs, OCRs them, and outputs searchable PDFs
> **No AI, no database, no web UI yet** — that comes in Phases 2-4

---

## 1. Project Structure (to create)

```
document-pipeline/
├── config.yaml                     # Production config
├── config.test.yaml                # Test config (debug, manual trigger)
├── person_categories.yaml          # Person/category hierarchy for later AI use
├── pipeline.py                     # CLI entry point (--process only for Phase 1)
├── requirements.txt                # Python deps
├── .gitignore
│
├── src/
│   ├── __init__.py
│   ├── ocr_engine.py               # Core OCR: extract pages, OCR, embed text layer
│   └── config_manager.py           # YAML config loader
│
├── scripts/
│   ├── generate_test_data.py       # Creates 10 synthetic PDFs
│   └── cleanup_test_data.sh        # Removes all __TEST__ files from NAS
│
├── tests/
│   └── test_data/
│       └── SYNTHETIC/              # Generated test PDFs land here
│
├── logs/                           # Log output directory
└── data/                           # Database directory (for Phase 3)
```

**Phase 1 ONLY creates files marked above**. Files for Phases 2-5 (`ai_classifier.py`, `file_router.py`, `duplicate_detector.py`, `database.py`, `scheduler.py`, `web/`, `tests/`) are NOT created yet.

---

## 2. File-by-File Specifications

### 2.1 `config.yaml` — Production Configuration

- Standard YAML with all pipeline settings
- Paths point to real NAS locations:
  - `raw_scans_folder`: `/Volumes/Public/-ScansImprimante`
  - `searchable_pdf_folder`: `/Volumes/Administratif/00-ScansNonTries`
  - `destination_base_folder`: `/Volumes/Administratif`
- OCR settings: Tesseract, `fra+eng`, 300 DPI
- AI section included but unused until Phase 2
- Logging level: `INFO`

### 2.2 `config.test.yaml` — Test Configuration

- Same NAS paths as production (test files get the `__TEST__` prefix)
- Polling disabled (manual trigger only)
- Logging level: `DEBUG`
- Web UI disabled
- Added `test_mode.enabled: true` and `test_mode.file_prefix: "__TEST__"`

### 2.3 `person_categories.yaml`

- Complete hierarchy for all 6 people: Famille, Eric, Sophie, Elisa, Eva, Loic
- Each has appropriate categories (8 categories each)
- Used by AI in Phase 2, but created now so structure exists

### 2.4 `requirements.txt`

```
pytesseract>=0.3.10
PyMuPDF>=1.23.0
Pillow>=10.0.0
PyYAML>=6.0
```

### 2.5 `src/__init__.py`

- Empty file marking `src/` as a Python package

### 2.6 `src/config_manager.py`

**Purpose**: Load and validate YAML configuration files.

**Interface**:
```python
class ConfigManager:
    def __init__(self, config_path: str): ...
    def get(self, key: str, default=None): ...   # Dot-notation access
    @property
    def raw_scans_folder(self) -> str: ...
    @property
    def searchable_pdf_folder(self) -> str: ...
    @property
    def ocr_languages(self) -> list: ...
    @property
    def ocr_dpi(self) -> int: ...
```

### 2.7 `src/ocr_engine.py` — THE CORE MODULE

**Purpose**: The heart of Phase 1. Takes a raw scanned PDF and produces a searchable PDF.

**Process flow**:
1. Open PDF with PyMuPDF (`fitz.open`)
2. For each page:
   a. Render page as image at configured DPI (default 300)
   b. Save as PIL Image (temporarily)
   c. Run Tesseract OCR with configured languages (`fra+eng`)
   d. Get text and bounding box data
3. Embed text layer into original PDF pages using PyMuPDF
4. Save searchable PDF to output path

**Interface**:
```python
class OCREngine:
    def __init__(self, config: ConfigManager): ...
    
    def process_pdf(self, pdf_path: str, output_path: str) -> dict:
        """
        Process a single PDF file.
        Returns dict with:
          - success: bool
          - text: str (full extracted text)
          - page_count: int
          - error: str (if failed)
        """
        ...

    def _extract_text_from_page(self, page, dpi: int) -> str: ...
    def _embed_text_layer(self, page, text_data: str): ...
```

**Error handling**:
- Invalid PDF → return `{success: false, error: "..."}` — DO NOT crash
- Tesseract failure per page → log warning, continue with other pages
- File not found → return error, do NOT create output file
- Output directory doesn't exist → create it automatically

### 2.8 `pipeline.py` — CLI Entry Point

**Purpose**: Main entry point for the pipeline.

**Commands for Phase 1** (only `--process` is active):
```
python pipeline.py --process                     # Process all new files
python pipeline.py --process --config config.test.yaml  # With test config
python pipeline.py --help                        # Show help
```

**Flow for `--process`**:
1. Load config (default `config.yaml`, overridable with `--config`)
2. Initialize OCREngine with config
3. Scan `raw_scans_folder` for PDF files
4. For each PDF file:
   a. Generate output path in `searchable_pdf_folder`
   b. Call `ocr_engine.process_pdf(input_path, output_path)`
   c. Log success/failure
5. Report summary

**Simple logic**: No duplicate detection, no AI, no database.
**Safe deletion**: After successful OCR + output verification, delete the raw scan. On failure, leave it.

### 2.9 `scripts/generate_test_data.py`

**Purpose**: Generate 10 synthetic PDFs with known content for testing.

**Implementation approach**:
- Use PyMuPDF to create PDFs from scratch
- Each PDF has realistic French/English text matching its document type
- Filenames follow pattern: `__TEST_S{NN}__{DescriptiveName}.pdf`
- Content includes: headers, dates, names, amounts, tables
- Different people (Eric, Sophie, Famille, Elisa, Loic) appear in different docs
- Output directory: `tests/test_data/SYNTHETIC/`

**The 10 documents** (from the plan):

| # | Expected Person | Category | Content Theme |
|---|----------------|----------|---------------|
| S01 | Eric | 20-Achats&Fournisseurs | Internet invoice (Orange) |
| S02 | Famille | 90-Financier | Bank statement |
| S03 | Eric | 40-ActiviteProf | Pay slip |
| S04 | Sophie | 10-DocumentsOfficiels | Passport copy |
| S05 | Elisa | 10-DocumentsOfficiels | School certificate |
| S06 | Loic | 40-ActiviteProf | Internship agreement |
| S07 | Famille | 20-Achats&Fournisseurs | Water bill (Veolia) |
| S08 | Eric | 80-Sante | Medical prescription |
| S09 | Eric | 70-Digital | Software invoice (English) |
| S10 | Famille | 20-Achats&Fournisseurs | Gas bill (Engie) |

### 2.10 `scripts/cleanup_test_data.sh`

**Purpose**: Safety net — deletes all `__TEST__` files from all pipeline folders.

**Behavior**:
1. Scan these folders for files containing `__TEST__`:
   - `/Volumes/Public/-ScansImprimante/`
   - `/Volumes/Administratif/00-ScansNonTries/`
   - `/Volumes/Administratif/30-Eric/`
   - `/Volumes/Administratif/40-Sophie/`
   - `/Volumes/Administratif/50-Elisa/`
   - `/Volumes/Administratif/60-Eva/`
   - `/Volumes/Administratif/70-Loic/`
   - `/Volumes/Administratif/20-Famille/`
2. Display the list of found files
3. Ask for confirmation before deleting
4. Delete all matching files
5. Report summary

**Safety**: ONLY targets files containing `__TEST__` in filename. Cannot affect real documents.

### 2.11 `.gitignore`

```
logs/
data/
*.pyc
__pycache__/
.env
.DS_Store
```

---

## 3. Design Decisions for Phase 1

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **OCR library** | Tesseract via pytesseract | Best French+English, mature, produces HOCR for text positioning |
| **PDF manipulation** | PyMuPDF (fitz) | Can both render pages AND embed text layers — single library |
| **Text embedding** | PyMuPDF `insert_text` per page | Inserts invisible/selectable text at correct positions |
| **Config format** | YAML via PyYAML | Human-readable, supports comments, nested structure |
| **CLI parsing** | `argparse` | Built-in, sufficient for Phase 1, easy to extend |
| **Image format for OCR** | PIL/Pillow | pytesseract works with PIL images directly |
| **Error handling** | Return dicts with success/error | Defensive — never crash. Log all errors. |
| **Output file naming** | Keep original filename | AI renaming comes in Phase 2 |
| **Safe deletion** | Delete raw scan only after verifying output exists | Zero data loss guarantee |

---

## 4. Pre-Implementation Checklist

Before Code mode starts, ensure:

- [ ] Tesseract 5+ installed? Run `tesseract --version` to check
- [ ] French + English language packs installed? Run `tesseract --list-langs | grep -E 'fra|eng'`
- [ ] If not: `brew install tesseract tesseract-lang` (includes many languages)
- [ ] NAS volumes mounted? `/Volumes/Public/` and `/Volumes/Administratif/` should exist
- [ ] Python 3.10+ available? Run `python3 --version`

---

## 5. Phase 1 Validation Procedure

After implementation, run this test to validate:

```bash
# Step 1: Install dependencies
pip install -r requirements.txt

# Step 2: Generate 10 synthetic test PDFs
python scripts/generate_test_data.py

# Step 3: Copy them to the scanner folder
cp tests/test_data/SYNTHETIC/__TEST_S*.pdf /Volumes/Public/-ScansImprimante/

# Step 4: Run the pipeline with test config
python pipeline.py --config config.test.yaml --process

# Step 5: Verify results
# - Check /Volumes/Administratif/00-ScansNonTries/ for searchable PDFs
# - Open a searchable PDF and confirm text is selectable
# - Check scanner folder — raw scans should be deleted
# - Check logs/pipeline.test.log for processing details

# Step 6: Cleanup
bash scripts/cleanup_test_data.sh
```

**Acceptance criteria**:
- All 10 synthetic PDFs processed without errors
- Searchable PDFs present in `/Volumes/Administratif/00-ScansNonTries/`
- Each searchable PDF has selectable text (open in Preview or similar)
- Raw scans deleted from scanner folder
- Cleanup script successfully removes all `__TEST__` files

---

## 6. Order of Implementation

1. **`.gitignore`** — trivial, create first
2. **`requirements.txt`** — defines dependencies
3. **`src/__init__.py`** — package marker
4. **`src/config_manager.py`** — needed by everything else
5. **`config.yaml`** and **`config.test.yaml`** — needed by config_manager
6. **`person_categories.yaml`** — static data, needed by later phases but created now
7. **`src/ocr_engine.py`** — THE core module, most complex
8. **`pipeline.py`** — CLI, ties everything together
9. **`scripts/generate_test_data.py`** — test data for validation
10. **`scripts/cleanup_test_data.sh`** — safety net
11. **Validate** — run the test procedure