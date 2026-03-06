"""
TPA Claim Form PDF Generator

Thin wrapper around FormEngine.populate() that conforms to the
services/pdf/ module interface expected by the generation pipeline.

Usage:
    from services.pdf.generate_tpa_pdf import generate_tpa_pdf

    output = generate_tpa_pdf(
        data={"patient_name": "John", ...},
        template_name="Ericson TPA Preauth",
        schema_name="Ericson TPA Preauth",
    )
"""

import logging
from pathlib import Path
from typing import Optional

from services.form_engine import FormEngine

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
SCHEMAS_DIR = BASE_DIR / "analyzed"
OUTPUT_DIR = BASE_DIR / "output"


def generate_tpa_pdf(
    data: dict,
    template_name: str,
    schema_name: str,
    output_path: Optional[str] = None,
) -> str:
    """
    Generate a filled TPA claim form PDF.

    Args:
        data: Dict of {field_id: value} — already mapped to schema field IDs.
        template_name: Stem name of the template (e.g. "Ericson TPA Preauth").
        schema_name: Stem name of the schema JSON (usually same as template_name).
        output_path: Where to write the filled PDF. Auto-generated if None.

    Returns:
        Absolute path to the generated TPA PDF.
    """
    template_pdf = str(TEMPLATES_DIR / f"{template_name}.pdf")
    schema_json = str(SCHEMAS_DIR / f"{schema_name}.json")

    if not output_path:
        OUTPUT_DIR.mkdir(exist_ok=True)
        output_path = str(OUTPUT_DIR / f"{template_name}_filled.pdf")

    engine = FormEngine()
    result = engine.populate(
        template_pdf=template_pdf,
        schema_json=schema_json,
        data=data,
        output_path=output_path,
    )

    logger.info("TPA PDF generated: %s", result)
    return result
