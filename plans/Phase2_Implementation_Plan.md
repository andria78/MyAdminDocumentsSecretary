# Phase 2: AI Classification + Intelligent Renaming — Implementation Plan

> **Based on**: `DocumentOCRProcessingPipeline_Final.md`
> **Goal**: Add AI-powered document classification using Ollama + Qwen2.5 7B to identify the person, category, and suggest a meaningful filename for each document. After classification, route the searchable PDF to its destination (`{Person}/{Category}`) and rename it intelligently.
> **Phase 1 delivers**: OCR → searchable PDF in intermediate folder. Phase 2 extends this with AI classification → routing to final destination with intelligent naming.

---

## 1. Overview of Changes

### What Phase 2 Adds

| Component | New/Modified | Description |
|-----------|-------------|-------------|
| [`src/ai_classifier.py`](#2-ai-classifier-srcai_classifierpy) | **New** | Ollama API integration for document classification |
| [`pipeline.py`](#4-updated-pipeline-flow) | **Modified** | Adds AI classification stage + file routing after OCR |
| [`src/config_manager.py`](#3-config-manager-updates) | **Modified** | Adds AI-related config properties + `person_categories_path` |
| [`config.yaml`](#config-file-changes) | **Modified** | Person categories path added |
| [`config.test.yaml`](#config-file-changes) | **Modified** | Person categories path added |
| [`tests/real_sources.yaml`](#52-testsreal_sourcesyaml--new-file) | **New** | Configuration file listing 10 real documents to use for validation |
| [`scripts/copy_real_test_data.py`](#53-scriptscopy_real_test_datapy--new-file) | **New** | Copies real documents (from `real_sources.yaml`) to the scanner folder with `__TEST_R__` prefix |

### What Phase 2 Does NOT Include (reserved for Phases 3–5)

- SQLite database (Phase 3)
- SHA-256 duplicate detection via index (Phase 3)
- APScheduler polling (Phase 3)
- Web UI (Phase 4)

### Assumptions

- **Phase 1 is fully implemented and validated**: OCR works, searchable PDFs are produced
- **Ollama is installed and running** with Qwen2.5 7B model pulled (`ollama pull qwen2.5:7b`)
- **`person_categories.yaml`** already exists at project root
- **NAS volumes** (`/Volumes/Public/`, `/Volumes/Administratif/`) are mounted and accessible

---

## 2. AI Classifier — `src/ai_classifier.py`

### 2.1 Purpose

Takes OCR-extracted text from a document and uses Ollama (Qwen2.5 7B) to determine:
1. **Person** — which person this document belongs to (from `person_categories.yaml`)
2. **Category** — the most appropriate category for this person
3. **Suggested filename** — a meaningful human-readable filename (without extension) based on document content
4. **Confidence score** — how confident the model is about its classification (0.0–1.0)

### 2.2 Interface

```python
class AIClassifier:
    def __init__(self, config: ConfigManager):
        """
        Initialize the AI classifier.
        
        Args:
            config: Pipeline configuration (reads ai.* and person_categories.yaml).
        """
        ...
    
    def classify(self, ocr_text: str, filename: str, page_count: int) -> dict:
        """
        Classify a document based on its OCR text.
        
        Args:
            ocr_text: Full text extracted by OCR engine.
            filename: Original filename (for context).
            page_count: Number of pages in the document.
        
        Returns:
            dict with:
                - success: bool
                - person: str (e.g. "Eric")
                - category: str (e.g. "20-Achats&Fournisseurs")
                - suggested_filename: str (e.g. "Facture_Orange_2024-03")
                - confidence: float (0.0–1.0)
                - reasoning: str (brief explanation from AI)
                - error: str (if failed)
        """
        ...

    def _build_prompt(self, ocr_text: str, filename: str, page_count: int) -> str:
        """Construct the prompt for the LLM."""
        ...

    def _call_ollama(self, prompt: str) -> dict:
        """Make the API call to Ollama and parse the JSON response."""
        ...

    def _parse_response(self, raw_response: str) -> dict:
        """Parse the JSON response from the LLM."""
        ...

    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize a suggested filename:
        - Replace spaces with underscores
        - Replace special characters with underscores
        - Limit length to 100 characters
        - Remove any path separators
        """
        ...
```

### 2.3 Prompt Template

The prompt is the core of the classifier. It must be carefully designed to produce consistent, parseable JSON output.

```
You are a document classification assistant for an administrative document management system.

Document details:
- Filename: {filename}
- Page count: {page_count}
- OCR Text:
---
{ocr_text}
---

Available people and their categories (only 2 levels: Person > Category):
{person_category_hierarchy}

Tasks:
1. Identify which person this document belongs to. Choose ONLY from the list above.
2. Identify the most appropriate category for this person. Choose ONLY from the categories listed for that person.
3. Suggest a meaningful filename (no extension, no path) based on document content. Examples:
   - "Facture_Orange_2024-03" (not "SCN_0042")
   - "Convention_Stage_Loic_Fev_2025"
   - "Releve_Bancaire_Compte_Conjoint_2024-06"
   - Use underscores, not spaces
   - Include date or period if present
   - Maximum 100 characters
4. Provide a confidence score between 0.0 and 1.0.
5. Provide a one-sentence reasoning for your choices.

Return ONLY valid JSON with no markdown formatting, no code fences, no extra text:
{
  "person": "Eric",
  "category": "20-Achats&Fournisseurs",
  "suggested_filename": "Facture_Orange_2024-03",
  "confidence": 0.95,
  "reasoning": "The document is an Orange internet invoice addressed to Eric at his home address."
}
```

### 2.4 Person/Category Hierarchy Format

The `_build_prompt` method reads [`person_categories.yaml`](person_categories.yaml) and formats it into a readable text block:

```
Famille (prefix 20-): 10-DocumentsOfficiels, 20-Achats&Fournisseurs, 30-SousTraitance, 40-ActiviteProf, 50-Projets, 60-Loisirs, 70-Digital, 90-Financier
Eric (prefix 30-): 10-DocumentsOfficiels, 20-Achats&Fournisseurs, 40-ActiviteProf, 50-Projets, 60-Loisirs, 70-Digital, 80-Sante, 90-Financier
Sophie (prefix 40-): ...
...
```

### 2.5 Ollama API Call

- **Endpoint**: `http://localhost:11434/api/generate`
- **Method**: POST
- **Request body**:
  ```json
  {
    "model": "qwen2.5:7b",
    "prompt": "...",
    "stream": false,
    "temperature": 0.1,
    "max_tokens": 500
  }
  ```
- **Response parsing**: Extract `response` field, parse as JSON
- **Error handling**:
  - Connection refused → return `{"success": false, "error": "Ollama server not reachable"}`
  - Timeout → return `{"success": false, "error": "Ollama request timed out"}`
  - Invalid JSON response → attempt to extract JSON from response body using regex
  - All errors are logged and the file is flagged for manual review

### 2.6 Response Parsing & Validation

After receiving the raw response from Ollama:

1. **Strip markdown fences** if present (```json ... ```)
2. **Parse JSON** with `json.loads()`
3. **Validate required fields**: `person`, `category`, `suggested_filename`, `confidence`
4. **Validate person** exists in [`person_categories.yaml`](person_categories.yaml)
5. **Validate category** is valid for that person
6. **Validate confidence** is a float between 0.0 and 1.0
7. **Sanitize `suggested_filename`**:
   - Strip file extension if accidentally included
   - Replace spaces → underscores
   - Replace `/ \ : * ? " < > |` → underscores
   - Collapse multiple underscores → single underscore
   - Strip leading/trailing underscores, dots, spaces
   - Truncate to 100 characters

If validation fails at any point → log warning, return `success: false` with descriptive error.

### 2.7 Confidence Threshold

- **Default threshold**: `0.70` (configurable via `pipeline.ai.confidence_threshold`)
- **Above threshold**: Document proceeds to routing (copy to destination)
- **Below threshold**: Document flagged for manual review; searchable PDF is **left in the intermediate folder** (`00-ScansNonTries`), NOT routed
- **Error / failed classification**: Same as below threshold — file left in intermediate folder

### 2.8 Error Handling Strategy

| Scenario | Behavior |
|----------|----------|
| Ollama not running | Log error, return `success: false`. File stays in intermediate folder. |
| Ollama returns gibberish | Log warning, attempt regex extraction. If still invalid → `success: false`. |
| Person not in hierarchy | Log error, return `success: false`. File stays in intermediate folder. |
| Category not valid for person | Log error, attempt fuzzy match. If no match → `success: false`. |
| JSON parse error | Log warning, try to extract JSON with regex. If fails → `success: false`. |
| Timeout (>30s) | Log error, return `success: false`. File stays in intermediate folder. |

---

## 3. Config Manager Updates

### 3.1 New Properties for [`src/config_manager.py`](src/config_manager.py)

Add the following properties to the existing [`ConfigManager`](src/config_manager.py:10) class:

```python
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
```

### 3.2 Person Categories Loader

Also add a method to load the person/categories hierarchy:

```python
def load_person_categories(self) -> dict:
    """
    Load the person/category hierarchy from person_categories.yaml.
    
    Returns:
        dict with:
            - people: list of {name, prefix, categories: [...]}
    """
    path = self.person_categories_path
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Person categories file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data
```

---

## 4. Updated Pipeline Flow

### 4.1 New Flow in [`pipeline.py`](pipeline.py)

The existing `process_all()` function is extended to add AI classification and file routing after successful OCR.

**New high-level flow** (modified section in [`process_all()`](pipeline.py:49)):

```
For each PDF file:
  1. Compute SHA-256 checksum (before processing)
  2. Run OCR → searchable PDF in intermediate folder
  3. Verify output exists + checksum integrity
  4. ✅ NEW: Run AI classification on OCR text
  5. ✅ NEW: Determine final filename:
       a. Check if original filename starts with rename_prefix (configurable, default "SCN")
       b. In test mode: strip test_mode.file_prefix before checking
       c. If yes (e.g. SCN_0042.pdf) → use AI-suggested filename
       d. If no (e.g. Devis_2024.pdf) → keep original filename
       e. If rename_prefix is "" → always use AI-suggested filename
  6. ✅ NEW: If confidence >= threshold:
       a. Sanitize final filename (spaces/special chars → underscores, limit 100 chars)
       b. Build destination path: {Person}/{Category}/{final_filename}.pdf
       c. Create destination directories if needed
       d. Copy searchable PDF to destination path
       e. Verify destination file exists + checksum matches
       f. Delete searchable PDF from intermediate folder (safe deletion)
       g. Log full lifecycle: original → searchable → destination
  7. ✅ NEW: If confidence < threshold:
       a. Log warning
       b. Leave searchable PDF in intermediate folder for manual review
       c. Do NOT delete raw scan yet
       d. (Raw scan deletion still governed by OCR success)
  8. Delete raw scan from scanner folder (only after OCR success + destination verified)
```

### 4.2 New Functions in `pipeline.py`

```python
def load_person_hierarchy(config: ConfigManager) -> dict:
    """Load and return the person/category hierarchy from YAML."""
    ...

def build_destination_path(
    config: ConfigManager,
    person: str,
    category: str,
    filename: str
) -> str:
    """
    Build the full destination path.
    Example: /Volumes/Administratif/30-Eric/20-Achats&Fournisseurs/Facture_Orange_2024-03.pdf
    
    Uses the prefix from person_categories.yaml to construct the person folder name
    (e.g., "Eric" + prefix "30-" → "30-Eric").
    """
    ...

def route_to_destination(
    source_path: str,
    dest_path: str
) -> bool:
    """
    Copy file to destination and verify integrity.
    
    Steps:
    1. Ensure destination directory exists (os.makedirs)
    2. Copy file (shutil.copy2)
    3. Verify destination exists
    4. Compute SHA-256 of destination
    5. Log result
    
    Returns:
        True if routing succeeded and file is verified
    """
    ...
```

### 4.3 CLI Changes

No new CLI arguments for Phase 2. The existing `--process` command now includes AI classification automatically. However, if Ollama is not available, the pipeline should gracefully degrade:

- **Ollama not reachable**: Log error, skip classification, leave files in intermediate folder, continue processing remaining files
- **Classification error on one file**: Log error, skip routing for that file, continue with next file

### 4.4 Safe Deletion Refinements

The safe deletion protocol from Phase 1 is extended:

| Stage | Location | Deleted When |
|-------|----------|-------------|
| **0** | Scanner folder (raw scan) | After OCR success **AND** (routing success OR confidence < threshold — file stays for review) |
| **1** | Intermediate folder (searchable PDF) | Only after destination copy is **verified** by checksum |
| **2** | Destination folder (final) | Never deleted |

**Important change**: If confidence < threshold, the raw scan is STILL deleted (OCR succeeded), but the searchable PDF remains in the intermediate folder for manual review. This prevents the scanner folder from filling up with already-OCR'd files.

---

## 5. File-by-File Specification

### 5.1 [`src/ai_classifier.py`](src/ai_classifier.py) — NEW FILE

**Dependencies**:
- `requests` (HTTP calls to Ollama)
- `json`, `re`, `logging`
- `src.config_manager.ConfigManager`

**Structure**:

```
src/ai_classifier.py
├── imports
├── logger
├── class AIClassifier
│   ├── __init__(self, config: ConfigManager)
│   │   └── Load config, load person_categories.yaml, build hierarchy string
│   ├── classify(self, ocr_text, filename, page_count) -> dict
│   │   ├── Build prompt via _build_prompt()
│   │   ├── Call Ollama via _call_ollama()
│   │   ├── Parse response via _parse_response()
│   │   └── Validate and return result
│   ├── _build_prompt(self, ocr_text, filename, page_count) -> str
│   │   └── Format the prompt template with document details + hierarchy
│   ├── _call_ollama(self, prompt) -> str
│   │   ├── POST to http://localhost:11434/api/generate
│   │   ├── Handle connection errors, timeouts
│   │   └── Return raw response text
│   ├── _parse_response(self, raw_response) -> dict
│   │   ├── Strip markdown fences
│   │   ├── Parse JSON
│   │   ├── Validate fields
│   │   └── Sanitize suggested_filename via _sanitize_filename()
│   ├── _validate_person_category(self, person, category) -> bool
│   │   └── Check person + category against loaded hierarchy
│   ├── _sanitize_filename(self, filename) -> str
│   │   └── Clean up suggested filename
│   └── _format_hierarchy(self, data) -> str
│       └── Convert person_categories dict to readable text
```

### 5.2 [`pipeline.py`](pipeline.py) — MODIFIED

**Changes**:
1. Add `from src.ai_classifier import AIClassifier` import
2. Add `import shutil` for file operations
3. Add helper functions: `load_person_hierarchy()`, `build_destination_path()`, `route_to_destination()`
4. Modify `process_all()` to add AI classification and routing after OCR step
5. Update logging messages

### 5.3 [`src/config_manager.py`](src/config_manager.py) — MODIFIED

**Changes**: Add 7 new properties (see [Section 3.1](#31-new-properties-in-srcconfig_managerpy)) and `load_person_categories()` method.

### 5.4 [`config.yaml`](config.yaml) & [`config.test.yaml`](config.test.yaml) — MODIFIED

**Changes**: Add `person_categories_path` and `rename_prefix` under `pipeline`:

```yaml
pipeline:
  # ... existing config ...
  person_categories_path: "person_categories.yaml"  # NEW
  rename_prefix: "SCN"                                # NEW — only rename files starting with this prefix
  # ... rest of config ...
```

The `rename_prefix` controls which files get renamed by AI:
- `"SCN"` (default): only files starting with `SCN` (e.g., `SCN_0042.pdf`) will be renamed
- `""` (empty string): ALL files will be renamed (opt-in to rename everything)
- Any other string: files starting with that string will be renamed
- In test mode, the `test_mode.file_prefix` is stripped before checking `rename_prefix`

### 5.5 [`tests/real_sources.yaml`](tests/real_sources.yaml) — NEW FILE

**Purpose**: Configuration file listing real documents to copy for testing with `__TEST_R__` prefix. This enables testing the AI classifier and pipeline against real-world scanned documents (variable quality, realistic OCR challenges), not just clean synthetic PDFs.

**Format**:

```yaml
# List of real documents to copy for testing
# Source paths are on the NAS, destination is the scanner folder
# Each file will be copied with __TEST_R__ prefix
# use_scn_prefix: true  → copied as __TEST_R01__SCN_{original_name} (will be renamed by AI)
# use_scn_prefix: false → copied as __TEST_R01__{original_name} (keeps original name)
real_documents:
  - source: "/Volumes/Administratif/30-Eric/10-DocumentsOfficiels/Passport_2023.pdf"
    expected_person: "Eric"
    expected_category: "10-DocumentsOfficiels"
    use_scn_prefix: true
    notes: "Clean passport scan — tests rename on SCN prefix"
  - source: "/Volumes/Administratif/40-Sophie/20-Achats&Fournisseurs/Amazon_commande_2024.pdf"
    expected_person: "Sophie"
    expected_category: "20-Achats&Fournisseurs"
    use_scn_prefix: false
    notes: "Online order receipt — tests no-rename on non-SCN name"
  # ... add 8 more real documents (mix of use_scn_prefix: true/false)
```

**Selection criteria for the 10 real documents** (from the master plan):
- 3 documents from different people (Eric, Sophie, Famille, etc.)
- 3 documents with different quality levels (clean, slightly skewed, low contrast)
- 2 multi-page documents (tests OCR across pages)
- 1 document that is mostly handwritten (tough OCR challenge)
- 1 document mixing French and English
- **rename_prefix coverage**: Mix of `use_scn_prefix: true` and `false` entries (e.g., 5 SCN + 5 non-SCN) to test both rename paths

**Safety**: The file only lists source paths. It NEVER moves or modifies the originals. The copy script creates duplicates with the `__TEST_R__` prefix.

### 5.6 [`scripts/copy_real_test_data.py`](scripts/copy_real_test_data.py) — NEW FILE

**Purpose**: Reads `tests/real_sources.yaml`, copies each listed document to `/Volumes/Public/-ScansImprimante/` with the `__TEST_R__{NN}__` prefix, and records the mapping in a JSON manifest for traceability.

**Interface**:

```bash
python scripts/copy_real_test_data.py                          # Copy all 10 real docs
python scripts/copy_real_test_data.py --config tests/real_sources.yaml  # Custom source list
python scripts/copy_real_test_data.py --dry-run                 # Show what would be copied
python scripts/copy_real_test_data.py --manifest tests/test_data/REAL/manifest.json  # Custom manifest path
```

**Behavior**:
1. Reads `tests/real_sources.yaml`
2. For each entry, checks `use_scn_prefix`:
   - `true` → copies as `/Volumes/Public/-ScansImprimante/__TEST_R{NN:02d}__SCN_{original_name}` — tests SCN rename logic
   - `false` (default) → copies as `/Volumes/Public/-ScansImprimante/__TEST_R{NN:02d}__{original_name}` — tests no-rename behavior
3. Creates `tests/test_data/REAL/manifest.json` with the mapping (source → copy name)
4. Outputs a summary of what was copied

**Safety checks**:
- Verifies source file exists before copying (skip with warning if not found)
- Refuses to overwrite existing files in scanner folder (unless `--force` flag is passed)
- Never modifies or touches the original source file

---

## 6. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Ollama HTTP API** | `requests` library | Simple, synchronous, widely available. No need for async in Phase 2. |
| **Temperature** | 0.1 (very low) | Classification needs consistency, not creativity. Lower temperature = more deterministic output. |
| **Max tokens** | 500 | JSON response is typically ~150-200 tokens. 500 gives comfortable margin. |
| **Prompt format** | Detailed with examples | Few-shot examples improve JSON compliance and classification quality. |
| **JSON parsing** | `json.loads` + regex fallback | Ollama sometimes wraps JSON in markdown fences. Regex handles edge cases. |
| **Filename sanitization** | Replace special chars, truncate at 100 | Prevents filesystem issues (illegal chars on macOS/Linux). 100 chars is descriptive enough. |
| **Graceful degradation** | Skip file, continue processing | One failed classification should not block other documents. |
| **File routing** | `shutil.copy2` (copy, not move) | Copy + verify + delete original is safer than move (preserves original if copy fails). |
| **Person folder naming** | `{prefix}{name}` (e.g., `30-Eric`) | Uses prefix from `person_categories.yaml` for consistent sorting. |
| **Rename prefix check** | Configurable `rename_prefix` (default `"SCN"`) | Scanner produces `SCN_xxxx.pdf` files. Already-named documents should not be renamed. Empty string = rename all. |

---

## 7. Dependencies

Add to [`requirements.txt`](requirements.txt):

```
requests>=2.28.0          # HTTP client for Ollama API
```

The existing dependencies remain:
```
pytesseract>=0.3.10
PyMuPDF>=1.23.0
Pillow>=10.0.0
PyYAML>=6.0
requests>=2.28.0          # NEW
```

---

## 8. Pre-Implementation Checklist

Before Code mode starts, ensure:

- [ ] **Ollama installed**: Run `ollama --version`
- [ ] **Qwen2.5 7B model pulled**: Run `ollama pull qwen2.5:7b`
- [ ] **Ollama is running**: Run `curl http://localhost:11434/api/tags` — should return JSON list of models
- [ ] **Python dependencies installed**: `pip install requests` (or `pip install -r requirements.txt` with updated file)
- [ ] **Phase 1 validated**: OCR pipeline works correctly with test data
- [ ] **NAS volumes mounted**: `/Volumes/Public/` and `/Volumes/Administratif/`
- [ ] **For real document testing**: `tests/real_sources.yaml` filled in with 10 real document paths
- [ ] **For real document testing**: Source files listed in `real_sources.yaml` actually exist on the NAS

---

## 9. Order of Implementation

1. **Update `requirements.txt`** — Add `requests`
2. **Update `src/config_manager.py`** — Add AI-related properties + `load_person_categories()`
3. **Create `src/ai_classifier.py`** — The core new module
4. **Update `config.yaml`** and **`config.test.yaml`** — Add `person_categories_path`
5. **Update `pipeline.py`** — Integrate AI classification + file routing
6. **Create [`tests/real_sources.yaml`](tests/real_sources.yaml)** — Configure 10 real document paths (user fills in actual paths)
7. **Create [`scripts/copy_real_test_data.py`](scripts/copy_real_test_data.py)** — Script to copy real docs with `__TEST_R__` prefix
8. **Update [`scripts/generate_test_data.py`](scripts/generate_test_data.py)** — Modify naming: 5 files with `SCN` base name (S01, S02, S03, S07, S08, S10) and 4 files with descriptive base name (S04, S05, S06, S09) to test `rename_prefix` logic
9. **Step 1 validation: synthetic test data** — Validate classification accuracy + rename_prefix behavior with known ground truth
10. **Step 2 validation: real test data** — Validate classification robustness with real-world documents

---

## 10. Phase 2 Validation Procedure

The validation is split into **two tracks**: one for synthetic documents (known ground truth) and one for real documents (real-world quality).

### 10.1 Step 1 — Synthetic Document Validation (Known Ground Truth)

```bash
# Ensure Ollama is running
ollama serve  # (if not already running)

# Generate synthetic PDFs and copy to scanner folder
python scripts/generate_test_data.py
cp tests/test_data/SYNTHETIC/__TEST_S*.pdf /Volumes/Public/-ScansImprimante/

# Run pipeline with test config
python pipeline.py --config config.test.yaml --process

# Check logs for AI classification output per file
tail -n 50 logs/pipeline.test.log
```

After the pipeline completes, verify:

1. **All 10 files processed**: Check the success count in logs
2. **Classification accuracy**: Compare each file's AI output against the [Classification Accuracy Table](#classification-accuracy-table-synthetic) below
3. **Correct routing**: Each file is in its expected destination folder
4. **rename_prefix behavior** (critical):
   - Files S01, S02, S03, S07, S08, S10 (base name starts with `SCN`) → **must be renamed** to AI-suggested name
   - Files S04, S05, S06, S09 (base name starts with descriptive text) → **must keep original name** (e.g., `Passeport_Sophie_2025.pdf`)
   - The test prefix `__TEST_Sxx__` is stripped before checking `rename_prefix`
5. **Intelligent filenames**: Renamed files have meaningful names (e.g., `Facture_Orange_2024-03.pdf`)
6. **Intermediate folder**: Only files with confidence < 0.70 remain in `00-ScansNonTries`
7. **Scanner folder**: All raw scans deleted

**Minimum acceptance**: At least **7 out of 10** synthetic documents must be classified to the **correct person**. All `SCN`-prefixed files must be renamed, and all non-`SCN` files must keep their original name.

### 10.2 Step 2 — Real Document Validation (Real-World Quality)

Before running this step, you must fill in [`tests/real_sources.yaml`](tests/real_sources.yaml) with paths to 10 real documents on your NAS (see [Section 5.5](#55-testsreal_sourcesyaml--new-file) for selection criteria).

```bash
# Copy 10 real documents to scanner folder with __TEST_R__ prefix
python scripts/copy_real_test_data.py

# Run pipeline with test config
python pipeline.py --config config.test.yaml --process

# Check logs for AI classification output on real documents
tail -n 50 logs/pipeline.test.log

# Check each destination folder — verify files arrived with correct person/category
ls /Volumes/Administratif/30-Eric/20-Achats&Fournisseurs/
ls /Volumes/Administratif/*/*/
```

After the pipeline completes, manually verify for each document:

1. **Was it OCR'd successfully?** Open the searchable PDF and check text selectability
2. **Was the person correctly identified?** Check the destination folder path
3. **Was the category appropriate?** Even if not exact, is it sensible?
4. **Confidence score**: Is it above or below 0.70?
5. **rename_prefix behavior**:
   - Documents copied with `use_scn_prefix: true` → must be renamed by AI (check filename in destination)
   - Documents copied with `use_scn_prefix: false` → must keep original name (check filename in destination)

**Acceptance criteria**: All 10 real documents must be OCR'd successfully. AI classification quality is assessed but not strictly pass/fail at this stage — results inform model tuning or prompt refinement.

### 10.3 Cleanup (Run After Both Tracks)

```bash
bash scripts/cleanup_test_data.sh
```

### Acceptance Criteria

| # | Criterion | Pass/Fail |
|---|-----------|-----------|
| 1 | All 10 synthetic PDFs classified without errors | |
| 2 | At least 7 out of 10 classified to the **correct person** | |
| 3 | At least 7 out of 10 classified to the **correct category** | |
| 4 | AI-suggested filenames are meaningful (contain document type + date) | |
| 5 | Files starting with `SCN` (S01, S02, S03, S07, S08, S10) are **renamed** by AI | |
| 6 | Files NOT starting with `SCN` (S04, S05, S06, S09) **keep original name** | |
| 7 | All filenames use underscores, no spaces or special characters | |
| 8 | Files with confidence >= 0.70 are routed to correct destination folders | |
| 9 | Destination folders are created automatically | |
| 10 | Raw scans are deleted from scanner folder | |
| 11 | Intermediate folder contains only files with confidence < 0.70 (if any) | |
| 12 | Pipeline handles missing Ollama gracefully (logs error, continues) | |
| 13 | Pipeline handles invalid person/category gracefully (flags for review) | |

### Classification Accuracy Table (Known Ground Truth)

| # | Filename | Starts with `SCN`? | Expected Person | Expected Category | AI Person | AI Category | Confidence | Renamed? | Match? |
|---|----------|-------------------|----------------|-------------------|-----------|-------------|------------|----------|--------|
| S01 | `__TEST_S01__SCN_0042.pdf` | ✅ Yes | Eric | 20-Achats&Fournisseurs | | | | ✅ | |
| S02 | `__TEST_S02__SCN_0043.pdf` | ✅ Yes | Famille | 90-Financier | | | | ✅ | |
| S03 | `__TEST_S03__SCN_0044.pdf` | ✅ Yes | Eric | 40-ActiviteProf | | | | ✅ | |
| S04 | `__TEST_S04__Passeport_Sophie_2025.pdf` | ❌ No | Sophie | 10-DocumentsOfficiels | | | | ❌ | |
| S05 | `__TEST_S05__Certificat_Scolarite_Elisa_2024-2025.pdf` | ❌ No | Elisa | 10-DocumentsOfficiels | | | | ❌ | |
| S06 | `__TEST_S06__Contrat_Stage_Loic_Fev_2025.pdf` | ❌ No | Loic | 40-ActiviteProf | | | | ❌ | |
| S07 | `__TEST_S07__SCN_0047.pdf` | ✅ Yes | Famille | 20-Achats&Fournisseurs | | | | ✅ | |
| S08 | `__TEST_S08__SCN_0048.pdf` | ✅ Yes | Eric | 80-Sante | | | | ✅ | |
| S09 | `__TEST_S09__Invoice_Software_License_EN.pdf` | ❌ No | Eric | 70-Digital | | | | ❌ | |
| S10 | `__TEST_S10__SCN_0050.pdf` | ✅ Yes | Famille | 20-Achats&Fournisseurs | | | | ✅ | |

---

## 11. Folder Structure After Phase 2

```
MyAdminDocumentsSecretary/
├── config.yaml                     # Production config (updated)
├── config.test.yaml                # Test config (updated)
├── person_categories.yaml          # Person/category hierarchy
├── pipeline.py                     # CLI entry point (UPDATED with AI + routing)
├── requirements.txt                # Updated with requests
├── .gitignore
│
├── src/
│   ├── __init__.py
│   ├── config_manager.py           # UPDATED with AI properties
│   ├── ocr_engine.py               # Unchanged from Phase 1
│   └── ai_classifier.py            # NEW — AI classification module
│
├── scripts/
│   ├── generate_test_data.py       # Unchanged from Phase 1
│   ├── copy_real_test_data.py      # NEW — copies real docs for testing
│   └── cleanup_test_data.sh        # Unchanged from Phase 1 (now also handles __TEST_R__)
│
├── tests/
│   ├── real_sources.yaml           # NEW — config listing 10 real document paths
│   └── test_data/
│       ├── SYNTHETIC/              # 10 synthetic test PDFs
│       └── REAL/                   # NEW — created at runtime by copy_real_test_data.py
│           └── manifest.json       # NEW — mapping of source → copy filenames
│
├── logs/
└── data/                           # Created but empty (for Phase 3)
```

---

## 12. Potential Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Ollama not running** | Medium | High — no classification | Graceful degradation: skip classification, leave files for later |
| **Qwen2.5 7B misclassifies** | Medium | Medium — wrong destination | Confidence threshold + manual review flagging |
| **Ollama response timeout** | Low | Low — one file delayed | Per-file timeout (30s), continue with next file |
| **JSON parsing fails** | Medium | Medium — file left behind | Regex fallback + logging + manual review |
| **Destination path too long** | Low | Low — file copy fails | Sanitize + truncate filename; log error |
| **Wrong person prefix in YAML** | Low | High — wrong destination folder | Validation in classifier against loaded hierarchy |
| **rename_prefix misconfigured** | Low | Medium — files not renamed or wrongly renamed | Default `"SCN"` matches scanner output; empty string renames all; documented in config |
| **Test prefix interferes with rename_prefix check** | Low | Medium — SCN prefix never matches in test mode | Pipeline strips `test_mode.file_prefix` before checking `rename_prefix` |
| **Real document is not found on NAS** | Medium | Low — one file skipped | `copy_real_test_data.py` skips with warning, continues with next |
| **Real document has unreadable scanner quality** | High | Medium — OCR failure or low confidence | Expected for real-world data; flagged for manual review |
| **Real document contains sensitive PII in tests** | Medium | Medium — data leakage risk | `__TEST_R__` prefix makes copies identifiable; cleanup script deletes all test copies |