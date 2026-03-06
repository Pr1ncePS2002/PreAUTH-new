#!/usr/bin/env python3
"""
Form Population Engine — Populates TPA pre-auth PDFs using coordinate JSON schemas.

This is the service-layer wrapper around the existing tpa_form_filler.py engine.
It orchestrates: schema loading → data mapping → PDF filling → output.

Usage:
    from services.form_engine import FormEngine

    engine = FormEngine()
    output_path = engine.populate(
        template_pdf="templates/Ericson TPA Preauth.pdf",
        schema_json="analyzed/Ericson TPA Preauth.json",
        data={"patient_name": "John Doe", ...},
        output_path="output/filled.pdf",
    )
"""

import json
import io
import logging
from pathlib import Path
from typing import Optional

from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent


class FormEngine:
    """Populates TPA pre-auth PDF forms using coordinate-based overlays."""

    def __init__(self):
        self.schemas_dir = BASE_DIR / "analyzed"
        self.templates_dir = BASE_DIR / "templates"
        self.output_dir = BASE_DIR / "output"
        self.output_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def populate(
        self,
        template_pdf: str,
        schema_json: str,
        data: dict,
        output_path: Optional[str] = None,
    ) -> str:
        """
        Populate a TPA form with data.

        Args:
            template_pdf: Path to blank PDF template
            schema_json: Path to coordinate JSON schema
            data: Dict of {field_id: value} — already mapped to schema field IDs
            output_path: Where to save filled PDF (auto-generated if None)

        Returns:
            Path to the filled PDF file
        """
        template_path = Path(template_pdf)
        schema_path = Path(schema_json)

        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema not found: {schema_path}")

        # Load schema
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)

        # Auto-generate output path if not provided
        if not output_path:
            output_path = str(
                self.output_dir / f"{template_path.stem}_filled.pdf"
            )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Handle gender convenience alias
        data = self._handle_gender(data)

        # Fill the form
        self._fill_pdf(template_path, schema, data, output_path)

        logger.info("Form populated: %s", output_path)
        return output_path

    def list_templates(self) -> list[dict]:
        """List all available PDF templates."""
        templates = []
        for pdf_file in sorted(self.templates_dir.glob("*.pdf")):
            schema_file = self.schemas_dir / f"{pdf_file.stem}.json"
            templates.append({
                "filename": pdf_file.name,
                "stem": pdf_file.stem,
                "has_schema": schema_file.exists(),
                "template_path": str(pdf_file),
                "schema_path": str(schema_file) if schema_file.exists() else None,
            })
        return templates

    def list_schemas(self) -> list[dict]:
        """List all analyzed schemas with matching template info."""
        schemas = []
        for json_file in sorted(self.schemas_dir.glob("*.json")):
            if json_file.name.endswith("_gemini_raw.json"):
                continue
            try:
                with open(json_file) as f:
                    data = json.load(f)
                # Find matching PDF template
                template_name = json_file.stem + ".pdf"
                template_path = self.templates_dir / template_name
                has_template = template_path.exists()
                schemas.append({
                    "filename": json_file.name,
                    "form_title": data.get("form_title", json_file.stem),
                    "total_pages": data.get("total_pages", 0),
                    "total_fields": len(data.get("fields", [])),
                    "template_name": template_name if has_template else None,
                    "has_template": has_template,
                    "schema_path": str(json_file),
                })
            except Exception:
                pass
        return schemas

    def get_schema_fields(self, schema_json: str) -> list[dict]:
        """Get all field definitions from a schema."""
        with open(schema_json, "r", encoding="utf-8") as f:
            schema = json.load(f)
        return schema.get("fields", [])

    # ------------------------------------------------------------------
    # PDF filling
    # ------------------------------------------------------------------
    def _fill_pdf(
        self,
        template_path: Path,
        schema: dict,
        data: dict,
        output_path: str,
    ) -> None:
        """Core PDF filling logic using overlay approach."""
        template = PdfReader(str(template_path))
        output = PdfWriter()

        total_pages = len(template.pages)

        for page_num in range(total_pages):
            page = template.pages[page_num]
            page_number = page_num + 1

            # Get fields for this page
            page_fields = [
                f for f in schema["fields"] if f["page"] == page_number
            ]

            if page_fields:
                overlay = self._create_overlay(
                    page_number, page_fields, data, schema
                )
                if overlay:
                    page.merge_page(overlay.pages[0])

            output.add_page(page)

        with open(output_path, "wb") as f:
            output.write(f)

    def _get_page_height(self, schema: dict, page_num: int) -> float:
        """Get page height for coordinate conversion."""
        heights = schema.get("page_heights", {})
        return float(heights.get(str(page_num), 842))

    def _create_overlay(
        self,
        page_num: int,
        fields: list[dict],
        data: dict,
        schema: dict,
    ) -> Optional[PdfReader]:
        """Create an overlay PDF page with filled data."""
        packet = io.BytesIO()
        page_height = self._get_page_height(schema, page_num)
        page_size = (A4[0], page_height)
        can = canvas.Canvas(packet, pagesize=page_size)
        can.setFont("Helvetica", 10)

        has_content = False

        for field in fields:
            field_id = field["field_id"]
            value = data.get(field_id)

            if value is None or value == "":
                continue

            field_type = field.get("type", "text_line")

            if field_type in ("text_line", "date_field"):
                self._draw_text(can, field, value, page_height)
                has_content = True
            elif field_type == "text_box":
                self._draw_text_box(can, field, value, page_height)
                has_content = True
            elif field_type == "checkbox":
                if value is True:
                    self._draw_checkbox(can, field, page_height)
                    has_content = True

        if not has_content:
            return None

        can.save()
        packet.seek(0)
        return PdfReader(packet)

    def _draw_text(self, can, field: dict, value, page_height: float):
        """Draw text at field coordinates."""
        x = field["coordinates"]["x"]
        y = page_height - field["coordinates"]["y"]
        font_size = field.get("font_size", 10)
        # Use bold font for "ESTIMATE ATTACHED" banner text
        if str(value).strip().upper() == "ESTIMATE ATTACHED":
            can.setFont("Helvetica-Bold", max(font_size, 11))
        else:
            can.setFont("Helvetica", font_size)
        can.drawString(x, y, str(value))

    def _draw_text_box(self, can, field: dict, value, page_height: float):
        """Draw text inside a box field."""
        x = field["coordinates"]["x"] + 2
        y = page_height - field["coordinates"]["y"] - field.get("height", 20) + 5
        font_size = field.get("font_size", 10)
        can.setFont("Helvetica", font_size)
        can.drawString(x, y, str(value))

    def _draw_checkbox(self, can, field: dict, page_height: float):
        """Draw an X for a checked checkbox."""
        x = field["coordinates"]["x"]
        y = page_height - field["coordinates"]["y"]
        can.setFont("Helvetica-Bold", 12)
        can.drawString(x + 2, y - 2, "X")

    # ------------------------------------------------------------------
    # Gender handling
    # ------------------------------------------------------------------
    @staticmethod
    def _handle_gender(data: dict) -> dict:
        """Convert gender string to checkbox booleans."""
        data = dict(data)  # Don't mutate original
        gender = data.pop("gender", None)
        if gender:
            g = gender.strip().lower()
            data.setdefault("gender_male", g in ("male", "m"))
            data.setdefault("gender_female", g in ("female", "f"))
            data.setdefault("gender_third_gender", g in ("third gender", "other", "transgender"))
        return data

    # ------------------------------------------------------------------
    # Preview (return bytes instead of saving)
    # ------------------------------------------------------------------
    def populate_to_bytes(
        self,
        template_pdf: str,
        schema_json: str,
        data: dict,
    ) -> bytes:
        """
        Populate a form and return the PDF as bytes (for streaming to frontend).
        """
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            self.populate(template_pdf, schema_json, data, tmp_path)
            return Path(tmp_path).read_bytes()
        finally:
            Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
def main():
    """Quick test of the form engine."""
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    engine = FormEngine()

    print("=" * 60)
    print("FORM ENGINE — Available Templates")
    print("=" * 60)
    for t in engine.list_templates():
        status = "✓ schema" if t["has_schema"] else "✗ no schema"
        print(f"  [{status}] {t['filename']}")

    print(f"\n{'='*60}")
    print("FORM ENGINE — Available Schemas")
    print("=" * 60)
    for s in engine.list_schemas():
        print(f"  {s['filename']}: {s['total_fields']} fields, {s['total_pages']} pages")

    # If sample data exists, do a test fill
    sample_data_path = BASE_DIR / "test_data" / "ericson_test_data.json"
    schema_path = BASE_DIR / "analyzed" / "Ericson TPA Preauth.json"
    template_path = BASE_DIR / "templates" / "Ericson TPA Preauth.pdf"

    if all(p.exists() for p in [sample_data_path, schema_path, template_path]):
        with open(sample_data_path) as f:
            data = json.load(f)

        output = engine.populate(
            str(template_path),
            str(schema_path),
            data,
            str(BASE_DIR / "output" / "form_engine_test.pdf"),
        )
        print(f"\n✓ Test fill saved to: {output}")


if __name__ == "__main__":
    main()
