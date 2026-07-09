# Test Plan — Searchable Folder Simulation

> **Goal**: Validate the `--process-searchable --simulate` mode of the pipeline using 10 real files already in the searchable folder (`/Volumes/Administratif/00-ScansNonTries`).
>
> **Mode**: Simulation only — no files are moved, deleted, or modified.
>
> **Command**: `python pipeline.py --process-searchable --simulate --config config.test.yaml`

---

## 1. Prerequisites

| Requirement | Verification | How to Check |
|------------|-------------|-------------|
| NAS `/Volumes/Administratif/` mounted | ✅ | `ls /Volumes/Administratif/00-ScansNonTries/` shows files |
| NAS `/Volumes/Public/` mounted | ✅ | `ls /Volumes/Public/-ScansImprimante/` exists |
| Ollama running with `qwen2.5:7b` | ⚠️ **Must verify** | `curl http://localhost:11434/api/tags` |
| Python dependencies installed | ⚠️ **Must verify** | `pip list 2>/devware/null | grep -E 'pytesseract|PyMuPDF|requests|pyyaml'` |
| Tesseract with `fra` + `eng` languages | ⚠️ **Must verify** | `tesseract --list-langs` shows `fra` and `eng` |
| Current working directory is project root | ✅ | The project is at `/Volumes/Public/Hobbies/VibeCoding/MyAdminDocumentsSecretary` |

---

## 2. Test Files Selection

10 files selected for diversity across all 6 people and multiple categories:

| # | File | Expected Person | Expected Category | Test Focus |
|---|------|----------------|-------------------|------------|
| 1 | `SCN_0002.pdf` | TBD by AI | TBD by AI | SCN prefix → tests AI renaming logic |
| 2 | `SCN_0004.pdf` | TBD by AI | TBD by AI | SCN prefix → tests AI renaming logic |
| 3 | `1509 Certificat Sport Elisa.pdf` | **Elisa** | `80-Sante` or `60-Loisirs` | Descriptive name → kept as-is |
| 4 | `1603 BulletinScolaireLoicGrandeSection.pdf` | **Loic** | `40-ActiviteProf` | School document for Loic |
| 5 | `1602 BNP relevé epargne Sophie 2015 .pdf` | **Sophie** | `90-Financier` | Sophie's bank savings statement |
| 6 | `1603 Fiche Sanitaire liaison Eva Autun.pdf` | **Eva** | `80-Sante` | Health form for Eva |
| 7 | `160704 ENGIE.pdf` | **Famille** | `20-Achats&Fournisseurs` | Energy bill → tests sub-folder routing |
| 8 | `160705 EDF Plan Mensualisation.pdf` | **Famille** | `20-Achats&Fournisseurs` | Electricity bill → tests sub-folder routing |
| 9 | `160419 ORANGE CONTRAT FIBRE.pdf` | **Eric** | `20-Achats&Fournisseurs` or `70-Digital` | Internet contract for Eric |
| 10 | `150724 CPAM versements.pdf` | **Eric** or **Famille** | `90-Financier` or `80-Sante` | Health insurance payments |

### Coverage Matrix

| Dimension | Coverage |
|-----------|----------|
| **People** | Elisa, Loic, Sophie, Eva, Eric, Famille (6/6 ✓) |
| **Categories** | Sante, ActiviteProf, Financier, Achats&Fournisseurs, Digital (5/8) |
| **Naming patterns** | 2 SCN-prefixed + 8 descriptive names |
| **Sub-folder routing** | ENGIE + EDF → potential `30-FournisseursEnergie` sub-folder |

---

## 3. Pre-Test Verification Steps

### 3.1 Verify NAS mount

```bash
ls "/Volumes/Administratif/00-ScansNonTries/"
# Should show many PDF files including the 10 test files
```

### 3.2 Verify Ollama is running

```bash
curl -s http://localhost:11434/api/tags | python -m json.tool
# Should show qwen2.5:7b in the models list
```

### 3.3 Verify Python dependencies

```bash
python -c "import pytesseract, fitz, requests, yaml; print('All deps OK')"
```

### 3.4 Verify Tesseract languages

```bash
tesseract --list-langs 2>&1 | grep -E 'fra|eng'
# Should show both fra and eng
```

### 3.5 Verify test config

```bash
python -c "
from src.config_manager import ConfigManager
c = ConfigManager('config.test.yaml')
print(f'Searchable folder: {c.searchable_pdf_folder}')
print(f'Test mode: {c.test_mode_enabled}')
print(f'AI model: {c.ai_model}')
print(f'Confidence threshold: {c.ai_confidence_threshold}')
print(f'Rename prefix: {c.rename_prefix}')
"
```

Expected output:
```
Searchable folder: /Volumes/Administratif/00-ScansNonTries
Test mode: True
AI model: qwen2.5:7b
Confidence threshold: 0.7
Rename prefix: SCN
```

---

## 4. Execution

### 4.1 Run Simulation

```bash
cd /Volumes/Public/Hobbies/VibeCoding/MyAdminDocumentsSecretary
python pipeline.py --process-searchable --simulate --config config.test.yaml
```

This will:
1. Scan `/Volumes/Administratif/00-ScansNonTries` for all PDF files
2. For each file, extract text via PyMuPDF (fast path — no full OCR)
3. Run AI classification via Ollama `qwen2.5:7b` to determine person, category, and suggested filename
4. Display a **simulation table** with all results
5. **NO files are moved, copied, or deleted**

### 4.2 What the Simulation Table Shows

The `print_simulation_table()` function produces a formatted table with these columns:

| Column | Description |
|--------|-------------|
| `#` | File index number |
| `Source File` | Original filename |
| `Person` | AI-predicted person (e.g., "Eric") |
| `Category` | AI-predicted category (e.g., "20-Achats&Fournisseurs") |
| `Suggested Filename` | AI-suggested descriptive filename |
| `Confidence` | AI confidence score (0.0–1.0) |
| `Status` | `✅ Route` if confidence ≥ 0.7, `⬇️ LowConf` if below, `❌ Error` if failed |

Below the table, **Full Destination Paths** are printed showing where each file *would* be routed.

---

## 5. Expected Results & Validation Criteria

### 5.1 Simulation Table Validation

Check these aspects of the output:

| Check | Pass/Fail | Criteria |
|-------|-----------|----------|
| All 10 files appear in table | ⬜ | Each file row present with source filename |
| SCN-prefixed files renamed | ⬜ | `SCN_0002.pdf` and `SCN_0004.pdf` should get AI-suggested names (e.g., `Facture_*.pdf`) |
| Non-SCN files kept as-is | ⬜ | Files like `BulletinScolaireLoic...` should keep original name (no rename needed) |
| Elisa correctly identified | ⬜ | `Certificat Sport Elisa` should route to Elisa |
| Loic correctly identified | ⬜ | `BulletinScolaireLoic` should route to Loic |
| Sophie correctly identified | ⬜ | `BNP relevé epargne Sophie` should route to Sophie |
| Eva correctly identified | ⬜ | `Fiche Sanitaire liaison Eva` should route to Eva |
| ENGIE/EDF sub-folder test | ⬜ | If `30-FournisseursEnergie` sub-folder exists under Famille, ENGIE/EDF should route there |
| Confidence threshold check | ⬜ | Files with confidence ≥ 0.7 show `✅ Route` status |
| No errors in pipeline | ⬜ | Pipeline completes without crashes |

### 5.2 Log File Validation

Check `logs/pipeline.test.log` (from `config.test.yaml`) for:

- `DEBUG` level messages showing each step
- AI classification decisions with reasoning
- No `ERROR` or `CRITICAL` messages
- `"Searchable-folder processing cycle complete"` at the end

### 5.3 File Integrity Validation

After simulation, verify:

- **No files were moved**: Confirm files still exist in `/Volumes/Administratif/00-ScansNonTries/`
- **No files were deleted**: Count files before and after
- **No files were modified**: Check timestamps (should be unchanged)

```bash
# Before simulation — take a snapshot
ls -la "/Volumes/Administratif/00-ScansNonTries/" > /tmp/searchable_files_before.txt

# After simulation — compare
ls -la "/Volumes/Administratif/00-ScansNonTries/" > /tmp/searchable_files_after.txt
diff /tmp/searchable_files_before.txt /tmp/searchable_files_after.txt
# Should show NO differences
```

---

## 6. Test Scenarios

### 6.1 Happy Path — All Files Classified Successfully

- **Expected**: 10/10 files appear in simulation table
- **Expected**: 8/10 files with `✅ Route` status (high confidence)
- **Expected**: 2/10 SCN files renamed (new suggested name)
- **Expected**: Pipeline exit code 0, `success_count` = 10

### 6.2 Sub-Folder Detection

If sub-folders exist under `20-Achats&Fournisseurs` for Famille or Eric:

| File | Expected Sub-Folder (if exists) |
|------|-------------------------------|
| `160704 ENGIE.pdf` | `30-FournisseursEnergie` under Famille/20-Achats&Fournisseurs |
| `160705 EDF Plan Mensualisation.pdf` | `30-FournisseursEnergie` under Famille/20-Achats&Fournisseurs |
| `160419 ORANGE CONTRAT FIBRE.pdf` | `40-FournisseursInternet` under Eric/20-Achats&Fournisseurs |

### 6.3 Low Confidence / Edge Cases

- Certificat Sport Elisa → could be classified as `80-Sante` (health) or `60-Loisirs` (sports/leisure)
- CPAM versements → could be `90-Financier` (payments) or `80-Sante` (health insurance)
- These edge cases test the AI's reasoning flexibility

---

## 7. Results Logging

| Data | Location | Format |
|------|----------|--------|
| Simulation table | Console stdout | Formatted text table |
| Full log output | `logs/pipeline.test.log` | Structured log (DEBUG level) |
| Command history | Terminal | Shell history |

To capture the output for review:

```bash
python pipeline.py --process-searchable --simulate --config config.test.yaml 2>&1 | tee /tmp/searchable_simulation_output.txt
```

---

## 8. Success Criteria

The test is considered **PASSED** if:

1. ✅ Pipeline runs without crashes for all 10 files
2. ✅ Simulation table displays 10 rows with source filenames
3. ✅ Each file shows an AI classification result (person + category)
4. ✅ SCN-prefixed files are suggested for renaming
5. ✅ No files were moved, deleted, or modified in the searchable folder
6. ✅ Log file contains classification decisions for all 10 files
7. ✅ No ERROR-level log messages

The test is considered **FAILED** if:

1. ❌ Pipeline crashes or hangs on any file
2. ❌ AI classifier returns empty results (Ollama not available)
3. ❌ Any files are moved or deleted from the searchable folder (simulation mode)
4. ❌ Log file shows ERROR messages

---

## 9. Cleanup

If any files were accidentally moved (bug in simulation mode):

```bash
# The cleanup script handles __TEST_* prefixed files only
# For the real files in searchable folder, no cleanup is needed
# since SIMULATION mode should NOT touch them
```

---

## 10. Quick-Start One-Liner

Once prerequisites are verified, run the test with a single command:

```bash
cd /Volumes/Public/Hobbies/VibeCoding/MyAdminDocumentsSecretary && python pipeline.py --process-searchable --simulate --config config.test.yaml 2>&1 | tee /tmp/searchable_simulation_output.txt