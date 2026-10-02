"""
PDF text extraction service using pypdf.

Extracts text from PDF documents page-by-page, validating usable text content
without introducing heavy OCR or third-party document processing dependencies.
"""

from dataclasses import dataclass
import io
import logging
import re

import pypdf

logger = logging.getLogger(__name__)


class PDFExtractionError(Exception):
    """User-safe exception raised when PDF extraction or validation fails."""
    pass


@dataclass(frozen=True)
class ExtractedPage:
    """Represents text extracted from an individual page of a PDF document."""

    page_number: int  # 1-indexed
    text: str


def extract_text_from_pdf(pdf_bytes: bytes) -> list[ExtractedPage]:
    """Extract and validate text from PDF bytes.

    Extracts text page-by-page to preserve document location metadata.
    Detects empty or scanned image-only PDFs and fails gracefully with an
    informative user-facing error.

    Raises:
        PDFExtractionError: If the PDF is corrupt, has no pages, or contains
        no usable text (e.g., scanned/image-only document).
    """
    if not pdf_bytes:
        raise PDFExtractionError("Uploaded PDF file is empty (0 bytes).")

    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    except Exception as exc:
        logger.warning("Failed to parse PDF bytes: %s", exc)
        raise PDFExtractionError(f"Invalid or corrupted PDF file: {exc}") from exc

    if len(reader.pages) == 0:
        raise PDFExtractionError("PDF contains no pages.")

    extracted_pages: list[ExtractedPage] = []
    total_text_chars = 0

    for idx, page in enumerate(reader.pages, start=1):
        try:
            raw_text = page.extract_text() or ""
        except Exception as exc:
            logger.warning("Failed to extract text from PDF page %d: %s", idx, exc)
            raw_text = ""

        # Normalize line endings and strip whitespace
        cleaned_text = re.sub(r"\r\n?", "\n", raw_text).strip()
        if cleaned_text:
            extracted_pages.append(ExtractedPage(page_number=idx, text=cleaned_text))
            # Count alphanumeric characters to measure usable content
            total_text_chars += len(re.findall(r"\w", cleaned_text))

    # If no pages yielded text or total alphanumeric character count is clearly unusable (< 10 chars)
    if not extracted_pages or total_text_chars < 10:
        logger.info(
            "PDF extraction failed usability check: extracted %d pages, %d alphanumeric chars",
            len(extracted_pages),
            total_text_chars,
        )
        raise PDFExtractionError(
            "Text could not be extracted from this PDF. "
            "The document may be scanned/image-based and may require OCR."
        )

    return extracted_pages
