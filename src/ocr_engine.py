"""OCR Engine module for the document pipeline.

Uses Tesseract (via pytesseract) for OCR and PyMuPDF (fitz) for PDF
manipulation. Handles:
- PDF page rendering at configurable DPI
- Tesseract OCR with configurable language packs (fra+eng)
- Text layer embedding into the original PDF
- Searchable PDF output
"""

import io
import logging
import os

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

from src.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class OCREngine:
    """Core OCR engine that processes PDF files and produces searchable PDFs."""

    def __init__(self, config: ConfigManager):
        """
        Initialize the OCR engine with pipeline configuration.

        Args:
            config: A ConfigManager instance with pipeline settings.
        """
        self._config = config
        self._dpi = config.ocr_dpi
        self._languages = "+".join(config.ocr_languages)  # "fra+eng"

    def process_pdf(self, pdf_path: str, output_path: str) -> dict:
        """
        Process a single PDF file: render pages, OCR, embed text layer.

        Args:
            pdf_path: Path to the input PDF file.
            output_path: Path where the searchable PDF will be saved.

        Returns:
            dict with keys:
                - success (bool): True if processing succeeded.
                - text (str): Full extracted text from all pages.
                - page_count (int): Number of pages processed.
                - error (str): Error message if success is False.
        """
        if not os.path.isfile(pdf_path):
            return {
                "success": False,
                "text": "",
                "page_count": 0,
                "error": f"File not found: {pdf_path}",
            }

        try:
            doc = fitz.open(pdf_path)
        except Exception as e:
            return {
                "success": False,
                "text": "",
                "page_count": 0,
                "error": f"Failed to open PDF: {e}",
            }

        page_count = len(doc)
        full_text = ""
        pages_ok = 0
        pages_failed = 0

        for page_num in range(page_count):
            page = doc[page_num]
            try:
                page_text = self._extract_text_from_page(page)
                full_text += page_text + "\n\n"
                pages_ok += 1
            except Exception as e:
                logger.warning("OCR failed on page %d of %s: %s", page_num + 1, pdf_path, e)
                pages_failed += 1

        if pages_ok == 0:
            doc.close()
            return {
                "success": False,
                "text": "",
                "page_count": page_count,
                "error": "OCR failed on all pages",
            }

        # Ensure output directory exists
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        try:
            doc.save(output_path, incremental=False, deflate=True)
            logger.info("Saved searchable PDF: %s", output_path)
        except Exception as e:
            doc.close()
            return {
                "success": False,
                "text": full_text,
                "page_count": page_count,
                "error": f"Failed to save output PDF: {e}",
            }

        doc.close()

        return {
            "success": True,
            "text": full_text.strip(),
            "page_count": page_count,
            "error": None,
        }

    def _extract_text_from_page(self, page: fitz.Page) -> str:
        """
        Render a PDF page as an image, run Tesseract OCR, and embed the
        resulting text layer back into the page.

        Args:
            page: A PyMuPDF Page object.

        Returns:
            The OCR-extracted text for this page.
        """
        # Render page to image at configured DPI
        zoom = self._dpi / 72.0  # PyMuPDF default is 72 DPI
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)

        # Convert PyMuPDF pixmap to PIL Image
        img_data = pix.tobytes("png")
        pil_image = Image.open(io.BytesIO(img_data))

        # Run Tesseract OCR
        ocr_data = pytesseract.image_to_data(
            pil_image,
            lang=self._languages,
            output_type=pytesseract.Output.DICT,
        )

        # Build full text from OCR
        page_text_lines = []
        for i, text in enumerate(ocr_data["text"]):
            if text and text.strip():
                page_text_lines.append(text.strip())

        page_text = " ".join(page_text_lines)

        # Embed text layer into the PDF page
        self._embed_text_layer(page, ocr_data, pix.width, pix.height)

        return page_text

    def _embed_text_layer(
        self,
        page: fitz.Page,
        ocr_data: dict,
        page_width: int,
        page_height: int,
    ) -> None:
        """
        Embed OCR text as an invisible selectable layer on the PDF page.

        Uses word-level bounding box data from Tesseract to position text
        accurately over the original scanned image.

        Args:
            page: A PyMuPDF Page object to modify.
            ocr_data: Dictionary from pytesseract.image_to_data with
                      'left', 'top', 'width', 'height', 'text' keys.
            page_width: Width of the rendered page image in pixels.
            page_height: Height of the rendered page image in pixels.
        """
        rect = page.rect
        page_w = rect.width
        page_h = rect.height

        scale_x = page_w / page_width
        scale_y = page_h / page_height

        for i in range(len(ocr_data["text"])):
            text = ocr_data["text"][i].strip()
            if not text:
                continue

            conf = int(ocr_data["conf"][i]) if ocr_data["conf"][i] != "-1" else 0
            if conf < 30:
                continue  # Skip low-confidence text

            x = ocr_data["left"][i] * scale_x
            y = ocr_data["top"][i] * scale_y
            w = ocr_data["width"][i] * scale_x
            h = ocr_data["height"][i] * scale_y

            # Define text position rectangle
            text_rect = fitz.Rect(x, y, x + w, y + h)

            # Insert text as invisible (opacity=0) so it's selectable/searchable
            # but not visually displayed over the scanned image
            page.insert_textbox(
                text_rect,
                text,
                fontsize=h * 0.8,
                fontname="helv",
                render_mode=3,  # 3 = invisible text (renders but doesn't display)
                color=(0, 0, 0),
            )