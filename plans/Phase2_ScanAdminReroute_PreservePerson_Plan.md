# Plan: Preserve Person When Rerouting in scan-admin

## Problem

When running `python pipeline.py --scan-admin --reroute`, the current implementation always calls the AI to classify **both** person and category. If a file is already inside a person's folder (e.g., `30-Eric/20-Achats&Fournisseurs/SCN_0042.pdf`), the AI might classify it to a **different person**, causing the file to be moved to the wrong person's folder.

**Example scenario:**
- File: `/Volumes/Administratif/30-Eric/20-Achats&Fournisseurs/SCN_0042.pdf`
- AI classifies as: `person="Famille"`, `category="20-Achats&Fournisseurs"`
- Current behavior: file gets re-routed to `/Volumes/Administratif/20-Famille/20-Achats&Fournisseurs/...`
- **Desired behavior**: keep `person="Eric"` (since file is already in Eric's folder), only change category if needed

## Solution

When `--scan-admin --reroute` is used and the file is already inside a person's folder (detected by matching the directory path against the person hierarchy), we should:

1. **Extract the person** from the directory path (e.g., `30-Eric` → `Eric`)
2. **Only ask the AI to classify the category** (not the person), using a new `classify_category_only()` method
3. **Route the file** to the correct category within the same person's folder

If the file is NOT inside any person's folder (e.g., directly in `00-ScansNonTries` or the root), use the full AI classification as before.

## Files to Modify

| File | Changes |
|------|---------|
| [`pipeline.py`](pipeline.py) | Add `extract_person_from_path()` helper + modify `scan_admin_folder()` reroute logic |
| [`src/ai_classifier.py`](src/ai_classifier.py) | Add `classify_category_only()` method |

## Design Details

### 1. New helper: `extract_person_from_path()`

```python
def extract_person_from_path(
    file_path: str,
    config: ConfigManager,
) -> str | None:
    """
    Check if a file is already inside a person's folder.
    
    Walks up the directory tree from the file, checking if any parent
    directory matches a person folder pattern (prefix + name) from the
    person_categories hierarchy.
    
    Args:
        file_path: Full path to the file.
        config: Pipeline configuration.
    
    Returns:
        Person name (e.g., "Eric") if file is inside a person's folder,
        or None if not inside any known person folder.
    """
    hierarchy = config.load_person_categories()
    dirpath = os.path.dirname(file_path)
    
    # Build set of known person folder names (e.g., {"30-Eric", "40-Sophie", ...})
    person_folders = {}
    for p in hierarchy.get("people", []):
        folder_name = f"{p.get('prefix', '')}{p['name']}"
        person_folders[folder_name.lower()] = p["name"]
    
    # Walk up the directory tree
    parts = dirpath.split(os.sep)
    for i in range(len(parts) - 1, -1, -1):
        # Check if this part or any parent matches a person folder
        # We need to check if any segment matches a person folder name
        pass
    
    # Simpler approach: check each parent directory
    current = dirpath
    while current and current != "/":
        basename = os.path.basename(current)
        if basename.lower() in person_folders:
            return person_folders[basename.lower()]
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    
    return None
```

### 2. New method: `AIClassifier.classify_category_only()`

```python
def classify_category_only(
    self,
    ocr_text: str,
    filename: str,
    page_count: int,
    person: str,
) -> dict:
    """
    Classify only the category for a document, given a known person.
    
    Unlike classify(), this method does NOT determine the person — it
    only determines the best category for the given person.
    
    Args:
        ocr_text: Full OCR-extracted text.
        filename: Original filename.
        page_count: Number of pages.
        person: Known person name (e.g., "Eric").
    
    Returns:
        dict with:
            - success: bool
            - category: str (e.g., "20-Achats&Fournisseurs")
            - suggested_filename: str
            - confidence: float
            - reasoning: str
            - error: str (if failed)
    """
```

The prompt for this method will be similar to the main `classify()` prompt but:
- Removes the person identification task
- Fixes the person to the known value
- Only asks for category + suggested_filename

### 3. Modified `scan_admin_folder()` reroute logic

In the reroute branch (around line 2679 in [`pipeline.py`](pipeline.py)):

```python
if reroute:
    # Check if file is already inside a person's folder
    known_person = extract_person_from_path(full_path, config)
    
    if known_person:
        # Person is known from folder path — only classify category
        logger.info(
            "File is inside %s's folder. Preserving person, classifying category only.",
            known_person,
        )
        category_result = ai_classifier.classify_category_only(
            ocr_text=ocr_text,
            filename=filename,
            page_count=page_count,
            person=known_person,
        )
        
        if category_result.get("success"):
            person = known_person  # Preserve the known person
            category = category_result["category"]
            confidence = category_result["confidence"]
            suggested_filename = category_result["suggested_filename"]
        else:
            # Fall back to full classification if category-only fails
            logger.warning(
                "Category-only classification failed for %s. Falling back to full classification.",
                filename,
            )
            # ... use existing full classification logic
    else:
        # File is not in any known person folder — use full classification
        # ... existing logic
```

### 4. Simulation mode update

When `--simulate` is used with `--scan-admin --reroute`, the simulation should also show:
- Whether the person was preserved (from folder path) or AI-classified
- The original person folder vs. the AI-suggested person (if different)

## Behavior Matrix

| Scenario | Current Behavior | New Behavior |
|----------|-----------------|--------------|
| File in `30-Eric/20-Achats/SCN_0042.pdf`, AI says Eric/80-Sante | Re-routes to `30-Eric/80-Sante/` (same person, different category) | Same (no change needed) |
| File in `30-Eric/20-Achats/SCN_0042.pdf`, AI says Famille/20-Achats | Re-routes to `20-Famille/20-Achats/` (WRONG — moves to different person) | Keeps person=Eric, only changes category if needed |
| File in `00-ScansNonTries/SCN_0042.pdf` (no person folder) | Full AI classification | Same (no change — no person folder detected) |
| File in root admin folder `SCN_0042.pdf` | Full AI classification | Same (no change — no person folder detected) |

## Implementation Order

1. Add `extract_person_from_path()` helper function to [`pipeline.py`](pipeline.py) (near other helper functions, around line 200)
2. Add `classify_category_only()` method to [`src/ai_classifier.py`](src/ai_classifier.py) (after `classify_subfolder()` around line 252)
3. Modify the reroute branch in `scan_admin_folder()` at [`pipeline.py:2679`](pipeline.py:2679) to use person preservation logic
4. Update simulation mode in `scan_admin_folder()` to show person preservation info
5. Test with various scenarios

## Files NOT Modified

- [`src/config_manager.py`](src/config_manager.py) — No new config properties needed
- [`src/ocr_engine.py`](src/ocr_engine.py) — No changes needed
- [`config.yaml`](config.yaml) — No changes needed
- [`person_categories.yaml`](person_categories.yaml) — No changes needed
