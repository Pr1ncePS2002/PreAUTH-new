#!/usr/bin/env python3
"""
Claim Document Merge Service.

Merges multiple PDFs into a single final claim package:
  1. TPA Claim Form PDF
  2. PPN Declaration PDF (if GIPSA case)
  3. Uploaded document attachments (PDFs + images converted to PDF)

Usage:
    from services.pdf.merge_claim_documents import merge_claim_documents

    final_path = merge_claim_documents(
        tpa_pdf="output/ericson_filled.pdf",
        ppn_pdf="output/ppn_filled.pdf",   # or None
        attachments=["uploads/aadhaar.jpg", "uploads/policy.pdf"],
        output_path="output/final_claim.pdf",
    )
"""

import io
import logging
from pathlib import Path
from typing import Optional

from PyPDF2 import PdfReader, PdfWriter
from PIL import Image

logger = logging.getLogger(__name__)

# Supported image extensions (will be converted to PDF pages)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".gif", ".webp"}


def _image_to_pdf_bytes(image_path: str) -> bytes:
    """Convert an image file to a single-page PDF (in memory)."""
    img = Image.open(image_path)

    # Convert RGBA/P to RGB for PDF compatibility
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=150)
    buf.seek(0)
    return buf.read()


def merge_claim_documents(
    tpa_pdf: str,
    ppn_pdf: Optional[str] = None,
    attachments: Optional[list[str]] = None,
    output_path: Optional[str] = None,
) -> str:
    """
    Merge all claim documents into a single PDF.

    Order:
      1. TPA Claim Form
      2. PPN Declaration Form (if provided)
      3. Attachment files (PDFs appended, images converted to PDF pages)

    Args:
        tpa_pdf: Path to the filled TPA form PDF.
        ppn_pdf: Path to the filled PPN declaration PDF (None if not GIPSA).
        attachments: List of file paths (PDFs / images) to append.
        output_path: Where to save the merged PDF.

    Returns:
        Path to the final merged claim package PDF.
    """
    writer = PdfWriter()
    page_count = 0
    components = []

    # ── 1. TPA Claim Form ──
    tpa_path = Path(tpa_pdf)
    if not tpa_path.exists():
        raise FileNotFoundError(f"TPA PDF not found: {tpa_pdf}")

    tpa_reader = PdfReader(str(tpa_path))
    for page in tpa_reader.pages:
        writer.add_page(page)
        page_count += 1
    components.append(f"TPA Form ({len(tpa_reader.pages)} pages)")
    logger.info("Merged TPA form: %d pages", len(tpa_reader.pages))

    # ── 2. PPN Declaration Form ──
    if ppn_pdf:
        ppn_path = Path(ppn_pdf)
        if ppn_path.exists():
            ppn_reader = PdfReader(str(ppn_path))
            for page in ppn_reader.pages:
                writer.add_page(page)
                page_count += 1
            components.append(f"PPN Declaration ({len(ppn_reader.pages)} pages)")
            logger.info("Merged PPN declaration: %d pages", len(ppn_reader.pages))
        else:
            logger.warning("PPN PDF not found, skipping: %s", ppn_pdf)

    # ── 3. Attachments ──
    if attachments:
        for file_path in attachments:
            fp = Path(file_path)
            if not fp.exists():
                logger.warning("Attachment not found, skipping: %s", file_path)
                continue

            ext = fp.suffix.lower()
            try:
                if ext == ".pdf":
                    reader = PdfReader(str(fp))
                    for page in reader.pages:
                        writer.add_page(page)
                        page_count += 1
                    components.append(f"{fp.name} ({len(reader.pages)} pages)")
                    logger.info("Merged PDF attachment: %s (%d pages)", fp.name, len(reader.pages))

                elif ext in IMAGE_EXTENSIONS:
                    pdf_bytes = _image_to_pdf_bytes(str(fp))
                    reader = PdfReader(io.BytesIO(pdf_bytes))
                    for page in reader.pages:
                        writer.add_page(page)
                        page_count += 1
                    components.append(f"{fp.name} (image → 1 page)")
                    logger.info("Merged image attachment: %s", fp.name)

                else:
                    logger.warning("Unsupported attachment type, skipping: %s", fp.name)

            except Exception as e:
                logger.error("Failed to merge attachment %s: %s", fp.name, e)
                components.append(f"{fp.name} (ERROR: {e})")

    # ── Write output ──
    if not output_path:
        output_dir = Path(__file__).resolve().parent.parent.parent / "output"
        output_dir.mkdir(exist_ok=True)
        output_path = str(output_dir / "final_claim_package.pdf")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as f:
        writer.write(f)

    logger.info(
        "Final claim package: %s (%d pages, %d components: %s)",
        output_path, page_count, len(components), ", ".join(components),
    )

    return output_path
