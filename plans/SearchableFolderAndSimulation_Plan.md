# Searchable Folder Processing + AI Simulation Mode — Implementation Plan

## Overview

Two new features to extend the pipeline's flexibility and testing capabilities:

1. **Process files already in the searchable folder** — handle digital-born PDFs that didn't come through the raw scanner
2. **Simulation mode** — dry-run the AI classifier to preview results without moving files

---

## Feature 1: Process Files from Searchable Folder

### Motivation

Currently, the pipeline only ingests files from `raw_scans_folder`, OCRs them, and outputs to `searchable_pdf_folder`. However, there may already be files in the searchable folder (placed manually, downloaded, emailed) that need classification and routing.

### Flow

```
searchable_pdf_folder (00-ScansNonTries/)
    │
    ▼
[Direct text extraction via PyMuPDF page.get_text()]
    │  (no Tesseract OCR — files are already searchable)
    ▼
[AI Classification]  (same as current pipeline)
    │
    ▼
[Routing to destination]  (same as current pipeline)
    │
    ▼
[Delete from searchable folder on success]
```

### Implementation

#### A. Add `extract_text_from_pdf()` to `OCREngine` (or a static utility)

Rather than re-running the full OCR pipeline (render → Tesseract → embed), use PyMuPDF's built-in `page.get_text()` to extract the existing text layer directly. This is orders of magnitude faster.

**New method in [`src/ocr_engine.py`](/src/ocr_engine.py) — around line 38:**

```python
def extract_text_direct(self, pdf_path: str) -> dict:
    """
    Extract text directly from an already-searchable PDF using PyMuPDF's
    built-in text extraction. Does NOT run Tesseract OCR.

    Args:
        pdf_path: Path to a searchable PDF file.

    Returns:
        dict with:
            - success: bool
            - text: str (extracted text from all pages)
            - page_count: int
            - error: str (if failed)
    """
    if not os.path.isfile(pdf_path):
        return {"success": False, "text": "", "page_count": 0,
                "error": f"File not found: {pdf_path}"}

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        return {"success": False, "text": "", "page_count": 0,
                "error": f"Failed to open PDF: {e}"}

    page_count = len(doc)
    full_text_parts = []
    for page_num in range(page_count):
        page = doc[page_num]
        text = page.get_text()  # Direct text extraction — no OCR needed
        full_text_parts.append(text)

    doc.close()

    full_text = "\n\n".join(full_text_parts).strip()

    # If no text was found via direct extraction, fall back to OCR
    if not full_text:
        logger.info(
            "No text layer found in %s — falling back to OCR", pdf_path
        )
        return self.process_pdf(pdf_path, pdf_path)  # OCR in-place

    return {
        "success": True,
        "text": full_text,
        "page_count": page_count,
        "error": None,
    }
```

#### B. New function `process_searchable()` in [`pipeline.py`](/pipeline.py)

This mirrors `process_all()` but:
- Scans `searchable_pdf_folder` instead of `raw_scans_folder`
- Uses `extract_text_direct()` instead of `ocr_engine.process_pdf()`
- Goes straight to AI classification + routing
- Deletes source file from searchable folder on successful routing

**New function — around line 252:**

```python
def process_searchable(config: ConfigManager, simulate: bool = False) -> int:
    """
    Process PDF files already in the searchable PDF folder.

    These files are already digital/searchable, so they skip the OCR step
    and go directly to AI classification + routing.

    Args:
        config: Pipeline configuration.
        simulate: If True, only show what would happen (no file moves).

    Returns:
        Number of files successfully processed (or simulated).
    """
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

    # Initialize AI classifier
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

    # Initialize OCR engine (needed only for text extraction)
    ocr_engine = OCREngine(config)

    success_count = 0
    fail_count = 0
    simulation_results = []  # Collect for --simulate mode

    for filename in sorted(pdf_files):
        filepath = os.path.join(folder, filename)
        logger.info("Processing: %s", filename)

        # ---- Step 1: Direct text extraction (no OCR) ----
        result = ocr_engine.extract_text_direct(filepath)
        if not result["success"]:
            logger.error("Text extraction failed for %s: %s", filename, result["error"])
            fail_count += 1
            continue

        ocr_text = result.get("text", "")
        page_count = result.get("page_count", 0)
        logger.info(
            "Text extracted: %d pages, %d chars", page_count, len(ocr_text)
        )

        # ---- Step 2: AI Classification ----
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
                logger.error("AI classification failed for %s: %s", filename, e)
                classification = {"success": False, "error": str(e)}

            # ... (same classification logic as process_all)
            # Determine person, category, suggested_filename, confidence
            # Check rename_prefix, confidence threshold
            # (exact same logic lines 387-454 from process_all)

        # ---- Step 3: Simulation or Routing ----
        if simulate:
            # Collect result for table display
            simulation_results.append(collect_simulation_row(
                source=filepath,
                filename=filename,
                classification=classification,
                config=config,
            ))
            success_count += 1  # Counted as "successfully simulated"
        elif should_route and classification:
            # Actual routing (same as process_all lines 468-537)
            # ...

    # Print simulation table if in simulate mode
    if simulate and simulation_results:
        print_simulation_table(simulation_results)

    return success_count
```

#### C. New CLI flags in `main()` — around line 569

Add two new arguments:

```python
parser.add_argument(
    "--process-searchable",
    action="store_true",
    help="Process PDF files already in the searchable folder (skip OCR, go direct to AI classification)",
)

parser.add_argument(
    "--simulate",
    action="store_true",
    help="Run in simulation mode: show classification results as a table without moving/copying any files",
)
```

And the execution logic:

```python
if args.process_searchable:
    if args.simulate:
        logger.info("SIMULATION MODE — no files will be moved or deleted")
    processed = process_searchable(config, simulate=args.simulate)
elif args.process:
    if args.simulate:
        logger.info("SIMULATION MODE — no files will be moved or deleted")
    processed = process_all(config, simulate=args.simulate)
```

This means `--simulate` can be combined with either `--process` or `--process-searchable`.

---

## Feature 2: Simulation Mode

### Motivation

Test the AI classification quality without actually moving files. Display results in a clean table so the user can verify:
- Is the AI identifying the correct person?
- Is the category appropriate?
- Is the suggested filename meaningful?
- What would the final destination path be?

### Implementation

#### A. Modify `process_all()` to accept `simulate` parameter

Add `simulate: bool = False` parameter to `process_all()`. When `True`:
- Run OCR as normal (needed for text extraction)
- Run AI classification as normal
- COLLECT results instead of calling `route_to_destination()`
- Do NOT delete raw scans or intermediate files
- Return collected results for table display

**Key differences when `simulate=True`:**
- Skip `route_to_destination()` — no file copy
- Skip `os.remove()` — no file deletion
- Build destination path string in-memory only
- Append result row to a list

#### B. Helper function `build_destination_path_str()`

Reuse the existing `build_destination_path()` function and just collect the path string without performing the copy.

#### C. Simulation table display

Use Python's built-in `tabulate` package (add to requirements.txt) or the `rich` library, or simply format with Python string formatting.

**Table columns:**

| # | Source File | Person | Category | Suggested Filename | Confidence | Destination Path | Subfolder | Status |
|---|------------|--------|----------|-------------------|-----------|-----------------|-----------|--------|
| 1 | SCN_0042.pdf | Eric | 20-Achats&Fournisseurs | Facture_Orange_2024-03 | 0.95 | /Volumes/.../30-Eric/20-Achats.../Facture_Orange_2024-03.pdf | top-level | ✅ Route |

**Implementation in [`pipeline.py`](/pipeline.py) — new function:**

```python
def print_simulation_table(results: list[dict]) -> None:
    """
    Print simulation results as a formatted table.
    Uses Python's built-in string formatting (no external deps required).
    """
    if not results:
        print("\nNo files to simulate.")
        return

    print("\n" + "=" * 120)
    print("  SIMULATION RESULTS — Classification & Routing Preview")
    print("=" * 120)

    # Header
    print(f"{'#':<4} {'Source File':<35} {'Person':<12} {'Category':<28} "
          f"{'Suggested Filename':<40} {'Confidence':<10} {'Status':<10}")
    print("-" * 120)

    for i, row in enumerate(results, 1):
        source = row.get("source_file", "")
        person = row.get("person", "N/A")
        category = row.get("category", "N/A")
        suggested = row.get("suggested_filename", "N/A")
        confidence = f"{row.get('confidence', 0.0):.2f}" if row.get("confidence") else "N/A"
        status = row.get("status", "⚠️")

        # Truncate long strings
        source = source[:34] if len(source) > 34 else source
        suggested = suggested[:39] if len(suggested) > 39 else suggested

        print(f"{i:<4} {source:<35} {person:<12} {category:<28} "
              f"{suggested:<40} {confidence:<10} {status:<10}")

    print("-" * 120)
    print(f"Total: {len(results)} file(s) simulated")
    print("=" * 120)

    # Optionally print full destination paths
    print("\n  Full Destination Paths:")
    for i, row in enumerate(results, 1):
        dest = row.get("destination_path", "N/A")
        print(f"  {i}. {dest}")
    print()
```

#### D. Helper `collect_simulation_row()`

```python
def collect_simulation_row(
    source: str,
    filename: str,
    classification: dict | None,
    config: ConfigManager,
) -> dict:
    """
    Collect a single row of simulation data without performing any file operations.

    Args:
        source: Full path to source file.
        filename: Original filename.
        classification: AI classification result dict (or None).
        config: Pipeline configuration.

    Returns:
        dict with row data for the simulation table.
    """
    row = {
        "source_file": os.path.basename(source),
        "source_path": source,
        "person": "N/A",
        "category": "N/A",
        "suggested_filename": "N/A",
        "confidence": None,
        "destination_path": "N/A",
        "subfolder": "N/A",
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

        # Build destination path (in-memory only)
        # Determine final filename
        effective_filename = filename
        rename_prefix = config.rename_prefix
        if rename_prefix and effective_filename.startswith(rename_prefix):
            final_filename = f"{suggested}.pdf"
        elif not rename_prefix:
            final_filename = f"{suggested}.pdf"
        else:
            final_filename = filename

        dest_path = build_destination_path(
            config, person, category, final_filename
        )

        row["destination_path"] = dest_path

        if confidence >= config.ai_confidence_threshold:
            row["status"] = "✅ Route"
        else:
            row["status"] = f"⬇️ LowConf ({confidence:.2f})"
    else:
        error = classification.get("error", "Unknown error") if classification else "No classification"
        row["status"] = f"❌ {error[:30]}"

    return row
```

---

## Files to Modify

| File | Changes |
|------|---------|
| [`pipeline.py`](/pipeline.py) | Add `--process-searchable` and `--simulate` CLI flags |
| | Add `process_searchable()` function |
| | Add `simulate` parameter to `process_all()` |
| | Add `print_simulation_table()`, `collect_simulation_row()` helpers |
| [`src/ocr_engine.py`](/src/ocr_engine.py) | Add `extract_text_direct()` method |
| [`requirements.txt`](/requirements.txt) | Add `tabulate` (optional, for nicer tables — fallback to manual formatting) |

---

## Dependencies

No new external dependencies for the core functionality. The table formatting uses Python's built-in string formatting. If `tabulate` or `rich` is available, we can use it for prettier output, but it's optional.

---

## Usage Examples

```bash
# Process new raw scans (existing behavior)
python pipeline.py --process

# Process raw scans in simulation mode (preview only)
python pipeline.py --process --simulate

# Process files already in the searchable folder
python pipeline.py --process-searchable

# Process searchable folder files in simulation mode
python pipeline.py --process-searchable --simulate

# With custom config
python pipeline.py --process-searchable --config config.test.yaml
```

---

## Edge Cases & Considerations

1. **Already-processed files**: Files in searchable folder that were already classified should be skipped. We can check if they were already processed via filename patterns or a processed index (Phase 3), but for now just process them — they'll be deleted after routing.

2. **Text extraction fails**: If a PDF in the searchable folder has no text layer (it was copied there mistakenly before OCR), fall back to running OCR on it. Log a warning.

3. **Simulation + --process-searchable**: Both flags can be combined. The simulation table shows results for searchable files only.

4. **Simulation + --process**: Both flags can be combined. The simulation table shows results for raw scans.

5. **No AI classifier available**: If Ollama is down, simulation mode falls back gracefully — it shows that classification was unavailable.

6. **Empty folders**: Graceful handling with "No files found" message.

---

## Architecture Diagram

```mermaid
flowchart TD
    subgraph CLI["CLI Entry Point main()"]
        C1[--process]
        C2[--process-searchable]
        C3[--simulate]
    end

    subgraph Process["process_all()"]
        RAW[raw_scans_folder] --> OCR[OCREngine.process_pdf]
        OCR --> AI_CLASSIFY[AIClassifier.classify]
    end

    subgraph ProcessSearchable["process_searchable()"]
        SEARCHABLE[searchable_pdf_folder] --> EXTRACT[OCREngine.extract_text_direct]
        EXTRACT --> AI_CLASSIFY2[AIClassifier.classify]
    end

    subgraph Simulate["Simulation Mode"]
        AI_CLASSIFY --> COLLECT[collect_simulation_row]
        AI_CLASSIFY2 --> COLLECT
        COLLECT --> TABLE[print_simulation_table]
        TABLE --> NOOP["No file moves / deletes"]
    end

    subgraph Route["Normal Mode"]
        AI_CLASSIFY --> ROUTE[route_to_destination]
        AI_CLASSIFY2 --> ROUTE
        ROUTE --> DELETE["Delete source files"]
    end

    C1 -- no --simulate --> Process --> Route
    C1 -- with --simulate --> Process --> Simulate
    C2 -- no --simulate --> ProcessSearchable --> Route
    C2 -- with --simulate --> ProcessSearchable --> Simulate