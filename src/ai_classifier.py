"""AI Document Classifier — Ollama integration for document classification.

Uses Ollama + Qwen2.5 7B to classify documents by:
1. Person — which person this document belongs to
2. Category — the most appropriate category for that person
3. Suggested filename — meaningful human-readable name
4. Sub-folder — optional sub-folder routing within a category
"""

import json
import logging
import re

import requests

from src.config_manager import ConfigManager

logger = logging.getLogger(__name__)

# Default Ollama endpoint
OLLAMA_API_URL = "http://localhost:11434/api/generate"


class AIClassifier:
    """AI-powered document classifier using Ollama LLM."""

    def __init__(self, config: ConfigManager):
        """
        Initialize the AI classifier.

        Args:
            config: Pipeline configuration (reads ai.* and person_categories.yaml).
        """
        self._config = config
        self._model = config.ai_model
        self._temperature = config.ai_temperature
        self._max_tokens = config.ai_max_tokens
        self._confidence_threshold = config.ai_confidence_threshold
        self._api_url = config.get("pipeline.ai.api_url", OLLAMA_API_URL)

        # Load person/category hierarchy
        try:
            self._hierarchy = config.load_person_categories()
            self._hierarchy_str = self._format_hierarchy(self._hierarchy)
            logger.debug(
                "Loaded person categories for %d people",
                len(self._hierarchy.get("people", [])),
            )
        except (FileNotFoundError, ValueError) as e:
            logger.error("Failed to load person categories: %s", e)
            self._hierarchy = {"people": []}
            self._hierarchy_str = ""

    # ── Public API ──────────────────────────────────────────────────────────

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
        # Check hierarchy is loaded
        if not self._hierarchy.get("people"):
            return {
                "success": False,
                "person": "",
                "category": "",
                "suggested_filename": "",
                "confidence": 0.0,
                "reasoning": "",
                "error": "Person categories hierarchy not loaded",
            }

        # Build prompt
        prompt = self._build_prompt(ocr_text, filename, page_count)

        # Call Ollama
        raw_response = self._call_ollama(prompt, max_tokens=self._max_tokens)
        if not raw_response.get("success"):
            return {
                "success": False,
                "person": "",
                "category": "",
                "suggested_filename": "",
                "confidence": 0.0,
                "reasoning": "",
                "error": raw_response.get("error", "Ollama call failed"),
            }

        # Parse response
        result = self._parse_response(raw_response["response"])
        if not result.get("success"):
            return {
                "success": False,
                "person": "",
                "category": "",
                "suggested_filename": "",
                "confidence": 0.0,
                "reasoning": "",
                "error": result.get("error", "Failed to parse AI response"),
            }

        # Validate person and category against hierarchy
        person = result.get("person", "")
        category = result.get("category", "")
        if not self._validate_person_category(person, category):
            logger.warning(
                "AI returned invalid person/category: %s / %s", person, category
            )
            return {
                "success": False,
                "person": person,
                "category": category,
                "suggested_filename": result.get("suggested_filename", ""),
                "confidence": result.get("confidence", 0.0),
                "reasoning": result.get("reasoning", ""),
                "error": f"Invalid person/category: {person} / {category}",
            }

        # Sanitize suggested filename
        suggested_filename = self._sanitize_filename(
            result.get("suggested_filename", "")
        )

        confidence = float(result.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        return {
            "success": True,
            "person": person,
            "category": category,
            "suggested_filename": suggested_filename,
            "confidence": confidence,
            "reasoning": result.get("reasoning", ""),
            "error": None,
        }

    def classify_subfolder(
        self,
        ocr_text: str,
        person: str,
        category: str,
        sub_folders: list[str],
    ) -> dict:
        """
        Determine if a document should go into an existing sub-folder
        or stay at the top level of the category.

        Args:
            ocr_text: Full OCR-extracted text.
            person: Already-classified person (e.g., 'Eric').
            category: Already-classified category (e.g., '20-Achats&Fournisseurs').
            sub_folders: List of existing sub-folder names (e.g.,
                ['30-FournisseursEnergie', '40-FournisseursInternet']).

        Returns:
            dict with:
                - success: bool
                - sub_folder: str or None ('top-level' or a sub-folder name)
                - confidence: float (0.0–1.0)
                - reasoning: str (brief explanation)
                - error: str (if failed)
        """
        if not sub_folders:
            return {
                "success": True,
                "sub_folder": "top-level",
                "confidence": 1.0,
                "reasoning": "No sub-folders exist in this category.",
                "error": None,
            }

        # Build sub-folder prompt
        prompt = self._build_subfolder_prompt(ocr_text, person, category, sub_folders)

        # Call Ollama with lower max_tokens for simpler response
        raw_response = self._call_ollama(prompt, max_tokens=200)
        if not raw_response.get("success"):
            logger.warning(
                "Sub-folder AI call failed for %s/%s: %s. Falling back to top-level.",
                person,
                category,
                raw_response.get("error"),
            )
            return {
                "success": False,
                "sub_folder": "top-level",
                "confidence": 0.0,
                "reasoning": "Sub-folder AI call failed, falling back to top-level.",
                "error": raw_response.get("error"),
            }

        # Parse response
        try:
            parsed = self._parse_subfolder_response(raw_response["response"])
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(
                "Failed to parse sub-folder response for %s/%s: %s. Falling back to top-level.",
                person,
                category,
                e,
            )
            return {
                "success": False,
                "sub_folder": "top-level",
                "confidence": 0.0,
                "reasoning": "Failed to parse sub-folder AI response.",
                "error": str(e),
            }

        # Validate sub_folder name
        sub_folder = parsed.get("sub_folder", "top-level")
        if sub_folder != "top-level" and sub_folder not in sub_folders:
            logger.warning(
                "AI returned invalid sub-folder '%s' for %s/%s. Valid options: %s. "
                "Falling back to top-level.",
                sub_folder,
                person,
                category,
                sub_folders,
            )
            return {
                "success": False,
                "sub_folder": "top-level",
                "confidence": 0.0,
                "reasoning": f"Invalid sub-folder name: {sub_folder}",
                "error": f"'{sub_folder}' is not in the list of existing sub-folders",
            }

        confidence = float(parsed.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        return {
            "success": True,
            "sub_folder": sub_folder,
            "confidence": confidence,
            "reasoning": parsed.get("reasoning", ""),
            "error": None,
        }

    # ── Prompt builders ─────────────────────────────────────────────────────

    def _build_prompt(self, ocr_text: str, filename: str, page_count: int) -> str:
        """Construct the primary classification prompt for the LLM."""
        prompt = (
            "You are a document classification assistant for an administrative "
            "document management system.\n\n"
            f"Document details:\n"
            f"- Filename: {filename}\n"
            f"- Page count: {page_count}\n"
            f"- OCR Text:\n"
            f"---\n"
            f"{ocr_text}\n"
            f"---\n\n"
            f"Available people and their categories (only 2 levels: Person > Category):\n"
            f"{self._hierarchy_str}\n\n"
            f"CRITICAL: The 'person' field MUST be EXACTLY one of the names listed above. "
            f"Do NOT use full names like 'Eric Martin' or 'Famille Martin'. "
            f"Use only: 'Famille', 'Eric', 'Sophie', 'Elisa', 'Eva', 'Loic'.\n\n"
            f"Rules for determining the person:\n"
            f"- If the document is addressed to a couple "
            f"(\"M. et Mme\", \"Mr and Mrs\", both spouses named), the person is 'Famille'.\n"
            f"- If the document mentions only one individual, use that person's name.\n"
            f"- Joint accounts, family bills (water, electricity, gas, rent, "
            f"insurance for the home), 'Compte Conjoint' → person is 'Famille'.\n"
            f"- School/certificate documents for a child → that child ('Elisa', 'Loic').\n"
            f"- Pay slips, professional documents → the individual employee.\n"
            f"- Personal medical documents → the individual patient.\n\n"
            f"EXPLICIT PERSON ASSOCIATIONS (CRITICAL - HIGHEST PRIORITY):\n"
            f"When the following names appear in the document, classify them as the associated person:\n\n"
            f"ALWAYS classify as 'Sophie' (NOT 'Famille' or 'Eric'):\n"
            f"- 'André CORSELLE' or 'André Corselle' → Sophie\n"
            f"- 'Monique CORSELLE' or 'Monique Corselle' → Sophie\n"
            f"- 'Monique LEMAIRE' or 'Monique Lemaire' → Sophie\n"
            f"- 'Laurent GRAJNERT' or 'Laurent Grajnert' → Sophie\n\n"
            f"ALWAYS classify as 'Eric' (NOT 'Famille'):\n"
            f"- 'Daniel ANDRIANARISON' or 'Daniel Andrianarison' → Eric\n"
            f"- 'Mireille ANDRIANARISON' or 'Mireille Andrianarison' → Eric\n"
            f"- 'Daniel JUSTET' or 'Daniel Justet' → Eric\n"
            f"- 'Marcel JUSTET' or 'Marcel Justet' → Eric\n"
            f"- 'Paulette JUSTET' or 'Paulette Justet' → Eric\n\n"
            f"Rules for determining the category:\n"
            f"- Pay slips, salary statements, payroll documents → 40-ActiviteProf "
            f"(professional activity), NOT 90-Financier.\n"
            f"- Software licenses, SaaS subscriptions, digital products, IT purchases → "
            f"70-Digital, NOT 20-Achats&Fournisseurs.\n"
            f"- Utility bills (electricity, gas, water, waste disposal) → "
            f"20-Achats&Fournisseurs (suppliers/purchases), NOT 90-Financier.\n"
            f"- Medical invoices, pharmacy receipts, doctor bills → 80-Sante (health), "
            f"NOT 20-Achats&Fournisseurs.\n"
            f"- Bank statements, investment reports, loan documents → 90-Financier.\n"
            f"- Invoices for physical goods (hardware, office supplies, furniture) → "
            f"20-Achats&Fournisseurs.\n"
            f"- Official documents (passports, IDs, birth certificates, school "
            f"certificates) → 10-DocumentsOfficiels.\n\n"
            f"Tasks:\n"
            f"1. Identify which person this document belongs to. Choose ONLY from the list above.\n"
            f"2. Identify the most appropriate category for this person. "
            f"Choose ONLY from the categories listed for that person.\n"
            f"3. Suggest a descriptive, detailed filename (no extension, no path) based on document content. "
            f"The filename should be LONG and INFORMATIVE, combining: document type + person/entity + "
            f"vendor/provider + date/period. Minimum 30 characters, maximum 100 characters.\n"
            f"   Good examples (long and descriptive):\n"
            f'   - "Facture_Orange_Internet_Eric_Mars_2024" (not "Facture_Orange_2024-03")\n'
            f'   - "Convention_Stage_Developpeur_Full_Stack_Loic_Fev_2025"\n'
            f'   - "Releve_Bancaire_Compte_Conjoint_Famille_Juin_2024"\n'
            f'   - "Bulletin_Salaire_Eric_Martin_Avril_2024"\n'
            f'   - "Certificat_Scolarite_College_Saint_Exupery_Elisa_2024_2025"\n'
            f'   - "Ordonnance_Amoxicilline_Dr_Dupont_Eric_Janvier_2025"\n'
            f'   - "Facture_EDF_Electricite_Famille_Novembre_Decembre_2024"\n'
            f'   - "Commande_Amazon_Livre_Disque_Dur_Eric_Janvier_2025"\n'
            f"   - Use underscores, not spaces\n"
            f"   - Include the full date or period (month written out, not just numbers)\n"
            f"   - Include the vendor/provider name when present\n"
            f"   - Minimum 30 characters, maximum 100 characters\n"
            f"4. Provide a confidence score between 0.0 and 1.0.\n"
            f"5. Provide a one-sentence reasoning for your choices.\n\n"
            f"Return ONLY valid JSON with no markdown formatting, no code fences, no extra text:\n"
            f"{{\n"
            f'  "person": "Eric",\n'
            f'  "category": "20-Achats&Fournisseurs",\n'
            f'  "suggested_filename": "Facture_Orange_2024-03",\n'
            f'  "confidence": 0.95,\n'
            f'  "reasoning": "The document is an Orange internet invoice addressed to Eric at his home address."\n'
            f"}}"
        )
        return prompt

    def _build_subfolder_prompt(
        self,
        ocr_text: str,
        person: str,
        category: str,
        sub_folders: list[str],
    ) -> str:
        """Construct the prompt for sub-folder classification."""
        sub_folder_list = "\n".join(f"- {sf}" for sf in sub_folders)
        prompt = (
            "You are a document filing assistant. A document has already been classified\n"
            f"as belonging to {person} > {category}.\n\n"
            f"Document OCR Text:\n"
            f"---\n"
            f"{ocr_text}\n"
            f"---\n\n"
            f'The category "{category}" already contains these sub-folders:\n'
            f"{sub_folder_list}\n\n"
            f"Task: Decide whether this document should be filed into one of the\n"
            f'existing sub-folders, or stay at the top level of "{category}".\n\n'
            f"- If the document's content clearly matches a sub-folder, choose that name.\n"
            f'- If no sub-folder is a good fit, choose "top-level".\n'
            f"- Provide a confidence score between 0.0 and 1.0.\n\n"
            f"Return ONLY valid JSON with no markdown, no code fences:\n"
            f"{{\n"
            f'  "sub_folder": "30-FournisseursEnergie",\n'
            f'  "confidence": 0.85,\n'
            f'  "reasoning": "The document is an Engie gas bill, matching the FournisseursEnergie sub-folder."\n'
            f"}}"
        )
        return prompt

    # ── Ollama API call ─────────────────────────────────────────────────────

    def _call_ollama(self, prompt: str, max_tokens: int = 500) -> dict:
        """
        Make the API call to Ollama and return the raw response text.

        Args:
            prompt: The prompt to send to the model.
            max_tokens: Maximum tokens for the response.

        Returns:
            dict with:
                - success: bool
                - response: str (raw response text)
                - error: str (if failed)
        """
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "temperature": self._temperature,
            "max_tokens": max_tokens,
        }

        try:
            logger.debug("Calling Ollama model '%s' (max_tokens=%d)...", self._model, max_tokens)
            resp = requests.post(
                self._api_url,
                json=payload,
                timeout=60,  # 60 second timeout for LLM inference
            )
            resp.raise_for_status()
            data = resp.json()
            raw_text = data.get("response", "").strip()
            if not raw_text:
                return {
                    "success": False,
                    "response": "",
                    "error": "Ollama returned empty response",
                }
            logger.debug("Ollama response received (%d chars)", len(raw_text))
            return {"success": True, "response": raw_text, "error": None}

        except requests.exceptions.ConnectionError:
            logger.error("Ollama server not reachable at %s", self._api_url)
            return {
                "success": False,
                "response": "",
                "error": "Ollama server not reachable",
            }
        except requests.exceptions.Timeout:
            logger.error("Ollama request timed out after 60s")
            return {
                "success": False,
                "response": "",
                "error": "Ollama request timed out",
            }
        except requests.exceptions.RequestException as e:
            logger.error("Ollama request failed: %s", e)
            return {
                "success": False,
                "response": "",
                "error": f"Ollama request failed: {e}",
            }
        except (ValueError, json.JSONDecodeError) as e:
            logger.error("Failed to parse Ollama JSON response: %s", e)
            return {
                "success": False,
                "response": "",
                "error": f"Invalid JSON from Ollama: {e}",
            }

    # ── Response parsing ────────────────────────────────────────────────────

    def _parse_response(self, raw_response: str) -> dict:
        """
        Parse the JSON response from the LLM.

        Args:
            raw_response: Raw text response from Ollama.

        Returns:
            dict with parsed fields or error.
        """
        # Try to extract JSON from the response
        json_str = self._extract_json(raw_response)
        if not json_str:
            return {
                "success": False,
                "error": "No JSON found in AI response",
            }

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning("JSON parse error: %s. Raw: %s", e, raw_response[:200])
            return {
                "success": False,
                "error": f"JSON parse error: {e}",
            }

        # Validate required fields
        required_fields = ["person", "category", "suggested_filename", "confidence"]
        missing = [f for f in required_fields if f not in data]
        if missing:
            return {
                "success": False,
                "error": f"Missing required fields in AI response: {missing}",
            }

        # Validate confidence is a number
        try:
            confidence = float(data["confidence"])
        except (ValueError, TypeError):
            return {
                "success": False,
                "error": f"Invalid confidence value: {data['confidence']}",
            }

        if confidence < 0.0 or confidence > 1.0:
            return {
                "success": False,
                "error": f"Confidence out of range (0.0-1.0): {confidence}",
            }

        return {
            "success": True,
            "person": str(data["person"]).strip(),
            "category": str(data["category"]).strip(),
            "suggested_filename": str(data["suggested_filename"]).strip(),
            "confidence": confidence,
            "reasoning": str(data.get("reasoning", "")).strip(),
        }

    def _parse_subfolder_response(self, raw_response: str) -> dict:
        """
        Parse the JSON response from the LLM for sub-folder classification.

        Args:
            raw_response: Raw text response from Ollama.

        Returns:
            dict with 'sub_folder', 'confidence', 'reasoning' keys.

        Raises:
            json.JSONDecodeError: If JSON parsing fails.
            ValueError: If required fields are missing.
        """
        json_str = self._extract_json(raw_response)
        if not json_str:
            raise ValueError("No JSON found in sub-folder AI response")

        data = json.loads(json_str)

        if "sub_folder" not in data:
            raise ValueError("Missing 'sub_folder' field in sub-folder AI response")

        if "confidence" not in data:
            raise ValueError("Missing 'confidence' field in sub-folder AI response")

        confidence = float(data["confidence"])
        if confidence < 0.0 or confidence > 1.0:
            raise ValueError(f"Confidence out of range: {confidence}")

        return {
            "sub_folder": str(data["sub_folder"]).strip(),
            "confidence": confidence,
            "reasoning": str(data.get("reasoning", "")).strip(),
        }

    @staticmethod
    def _extract_json(text: str) -> str | None:
        """
        Extract JSON from a response that may contain markdown fences or extra text.

        Args:
            text: Raw text that may contain JSON.

        Returns:
            Extracted JSON string, or None if no JSON found.
        """
        if not text:
            return None

        # Strip markdown code fences (```json ... ``` or ``` ... ```)
        text = text.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        text = text.strip()

        # Try to find JSON object in the text
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            return json_match.group(0)

        return None

    # ── Validation ──────────────────────────────────────────────────────────

    def _validate_person_category(self, person: str, category: str) -> bool:
        """
        Validate that person and category exist in the loaded hierarchy.

        Args:
            person: Person name (e.g., "Eric").
            category: Category name (e.g., "20-Achats&Fournisseurs").

        Returns:
            True if the person and category are valid.
        """
        if not person or not category:
            return False

        for p in self._hierarchy.get("people", []):
            if p["name"].lower() == person.lower():
                # Check if category exists for this person (case-insensitive)
                return any(
                    c.lower() == category.lower() for c in p.get("categories", [])
                )

        return False

    # ── Filename sanitization ───────────────────────────────────────────────

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """
        Sanitize a suggested filename:
        - Strip file extension if accidentally included
        - Replace spaces with underscores
        - Replace special characters with underscores
        - Collapse multiple underscores
        - Strip leading/trailing underscores, dots, spaces
        - Limit length to 100 characters

        Args:
            filename: Raw suggested filename.

        Returns:
            Sanitized filename (without extension).
        """
        if not filename:
            return "unnamed_document"

        # Remove file extension if present (.pdf, .PDF, .txt, etc.)
        filename = re.sub(r'\.\w+$', '', filename)

        # Replace spaces and special characters with underscores
        # Keep: letters (including accented), digits, underscores, hyphens, dots, ampersands
        filename = re.sub(r'[^\w\s\-\.&]', '_', filename, flags=re.UNICODE)
        filename = re.sub(r'\s+', '_', filename)

        # Collapse multiple underscores
        filename = re.sub(r'_+', '_', filename)

        # Strip leading/trailing underscores, dots, spaces
        filename = filename.strip('_. ')

        # Truncate to 100 characters
        filename = filename[:100]

        # If after sanitization we have an empty string, return a default
        if not filename:
            return "unnamed_document"

        return filename

    # ── Hierarchy formatting ────────────────────────────────────────────────

    @staticmethod
    def _format_hierarchy(data: dict) -> str:
        """
        Convert the person_categories dict into a readable text format.

        Args:
            data: Dictionary with 'people' list from person_categories.yaml.

        Returns:
            Formatted string like:
                Famille (prefix 20-): 10-DocumentsOfficiels, 20-Achats&Fournisseurs, ...
                Eric (prefix 30-): 10-DocumentsOfficiels, ...
        """
        lines = []
        for person in data.get("people", []):
            name = person.get("name", "")
            prefix = person.get("prefix", "")
            categories = ", ".join(person.get("categories", []))
            lines.append(f"{name}  (prefix {prefix}):  {categories}")
        return "\n".join(lines)
