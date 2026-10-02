"""
Test helpers for generating deterministic in-memory PDF files.
"""

import io
import pypdf


def generate_test_pdf(pages: list[str]) -> bytes:
    """Generate a valid, deterministic PDF byte stream containing text on each page."""
    lines = ["%PDF-1.4"]
    offsets = []

    # Object 1: Catalog
    offsets.append(sum(len(l) + 1 for l in lines))
    lines.append("1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj")

    # Font object ID will be placed after all pages and contents
    font_id = 3 + len(pages) * 2

    # Object 2: Pages
    offsets.append(sum(len(l) + 1 for l in lines))
    kids = " ".join(f"{3 + i*2} 0 R" for i in range(len(pages)))
    lines.append(f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>\nendobj")

    for i, page_text in enumerate(pages):
        page_id = 3 + i * 2
        content_id = page_id + 1
        # Escape parentheses in page_text for PDF literal string format
        safe_text = page_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream_text = f"BT /F1 12 Tf 72 712 Td ({safe_text}) Tj ET"

        # Page object
        offsets.append(sum(len(l) + 1 for l in lines))
        lines.append(
            f"{page_id} 0 obj\n"
            f"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/MediaBox [0 0 612 792] /Contents {content_id} 0 R >>\nendobj"
        )

        # Content object
        offsets.append(sum(len(l) + 1 for l in lines))
        lines.append(
            f"{content_id} 0 obj\n<< /Length {len(stream_text)} >>\nstream\n{stream_text}\nendstream\nendobj"
        )

    # Font object
    offsets.append(sum(len(l) + 1 for l in lines))
    lines.append(f"{font_id} 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj")

    # Cross-reference table
    xref_offset = sum(len(l) + 1 for l in lines)
    total_objs = font_id + 1
    lines.append(f"xref\n0 {total_objs}\n0000000000 65535 f ")
    for off in offsets:
        lines.append(f"{off:010d} 00000 n ")
    lines.append(f"trailer\n<< /Size {total_objs} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF")

    return "\n".join(lines).encode("latin-1")


def generate_scanned_blank_pdf(num_pages: int = 1) -> bytes:
    """Generate a valid PDF containing pages with no extractable text, simulating a scanned document."""
    writer = pypdf.PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
