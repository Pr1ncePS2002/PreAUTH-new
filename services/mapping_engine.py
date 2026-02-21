#!/usr/bin/env python3
"""
Semantic Mapping Engine — Maps Document AI / OCR output keys to JSON schema field IDs.

Strategy (in order of priority):
  1. Exact match: OCR key matches a field_id directly
  2. Alias match: OCR key matches one of the predefined aliases in field_mapping.json
  3. Fuzzy match: rapidfuzz token_sort_ratio > threshold
  4. Gemini fallback: Ask Gemini to suggest mappings for remaining unmatched keys
  5. Log unmatched: Store for manual review

Usage:
    from services.mapping_engine import MappingEngine

    engine = MappingEngine()
    mapped = engine.map_ocr_to_schema(ocr_output, schema_fields)
"""

import json
import os
import re
import logging
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz, process
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
FIELD_MAPPING_PATH = BASE_DIR / "config" / "field_mapping.json"
FUZZY_THRESHOLD = 70  # Minimum score for fuzzy match acceptance
GEMINI_THRESHOLD = 0.8  # Minimum confidence for Gemini suggestions


# ---------------------------------------------------------------------------
# Mapping Engine
# ---------------------------------------------------------------------------
class MappingEngine:
    """Maps OCR-extracted keys to coordinate-schema field_ids."""

    def __init__(self, mapping_path: Optional[str] = None):
        self.mapping_path = Path(mapping_path) if mapping_path else FIELD_MAPPING_PATH
        self.field_mapping = self._load_mapping()
        self._alias_index = self._build_alias_index()
        self.unmatched_log: list[dict] = []

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def _load_mapping(self) -> dict:
        """Load field_mapping.json."""
        if not self.mapping_path.exists():
            logger.warning("field_mapping.json not found at %s", self.mapping_path)
            return {}
        with open(self.mapping_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _build_alias_index(self) -> dict[str, str]:
        """Build a reverse index: normalised alias -> field_id."""
        index = {}
        for field_id, meta in self.field_mapping.items():
            # Add field_id itself
            index[self._normalise(field_id)] = field_id
            # Add all aliases
            for alias in meta.get("aliases", []):
                index[self._normalise(alias)] = field_id
        return index

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalise(text: str) -> str:
        """Normalise a string for comparison: lowercase, strip, collapse whitespace, remove punctuation."""
        text = text.lower().strip()
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    # ------------------------------------------------------------------
    # Core mapping pipeline
    # ------------------------------------------------------------------
    def map_ocr_to_schema(
        self,
        ocr_output: dict,
        schema_fields: Optional[list[str]] = None,
        document_type: str = "preauth_form",
    ) -> dict:
        """
        Map OCR key-value pairs to schema field_ids.

        Args:
            ocr_output: Dict of {ocr_key: extracted_value} from Document AI
            schema_fields: Optional list of valid field_ids to restrict results to
            document_type: Type of source document for context-aware matching

        Returns:
            Dict of {field_id: value} ready for the form filler engine
        """
        mapped_result: dict = {}
        unmatched: dict[str, str] = {}
        claimed_fields: set[str] = set()  # Prevent multiple OCR keys mapping to same field

        valid_fields = set(schema_fields) if schema_fields else set(self.field_mapping.keys())

        # Two passes: exact+alias first, fuzzy second (to prioritise strong matches)
        pending: list[tuple[str, str]] = []

        for ocr_key, value in ocr_output.items():
            field_id = self._resolve_key_exact(ocr_key, valid_fields)
            if field_id and field_id not in claimed_fields:
                mapped_result[field_id] = value
                claimed_fields.add(field_id)
                logger.debug("Exact/alias mapped '%s' -> '%s'", ocr_key, field_id)
            else:
                pending.append((ocr_key, str(value) if not isinstance(value, bool) else value))

        # Second pass: fuzzy match remaining
        for ocr_key, value in pending:
            available = valid_fields - claimed_fields
            field_id = self._fuzzy_match(self._normalise(ocr_key), available)
            if field_id:
                mapped_result[field_id] = ocr_output[ocr_key]
                claimed_fields.add(field_id)
                logger.debug("Fuzzy mapped '%s' -> '%s'", ocr_key, field_id)
            else:
                unmatched[ocr_key] = ocr_output[ocr_key]
                logger.info("Unmatched OCR key: '%s'", ocr_key)

        # Log unmatched for review
        if unmatched:
            self.unmatched_log.append({
                "document_type": document_type,
                "unmatched_keys": list(unmatched.keys()),
                "count": len(unmatched),
            })
            logger.warning(
                "%d OCR keys could not be mapped: %s",
                len(unmatched),
                list(unmatched.keys()),
            )

        return mapped_result

    def _resolve_key_exact(
        self,
        ocr_key: str,
        valid_fields: set[str],
    ) -> Optional[str]:
        """Resolve using exact match or alias only (no fuzzy)."""
        if ocr_key in valid_fields:
            return ocr_key
        normalised = self._normalise(ocr_key)
        if normalised in self._alias_index:
            candidate = self._alias_index[normalised]
            if candidate in valid_fields:
                return candidate
        return None

    def _resolve_key(
        self,
        ocr_key: str,
        valid_fields: set[str],
        document_type: str,
    ) -> Optional[str]:
        """
        Resolve a single OCR key to a field_id using the 4-layer strategy.

        Returns field_id or None.
        """
        # Layer 1: Exact match on field_id
        if ocr_key in valid_fields:
            return ocr_key

        normalised = self._normalise(ocr_key)

        # Layer 2: Alias match (case-insensitive, punctuation-stripped)
        if normalised in self._alias_index:
            candidate = self._alias_index[normalised]
            if candidate in valid_fields:
                return candidate

        # Layer 3: Fuzzy match against all aliases
        fuzzy_match = self._fuzzy_match(normalised, valid_fields)
        if fuzzy_match:
            return fuzzy_match

        return None

    def _fuzzy_match(self, normalised_key: str, valid_fields: set[str]) -> Optional[str]:
        """Use rapidfuzz to find the best matching field_id."""
        # Build candidates: alias -> field_id (only for valid fields)
        candidates = {}
        for alias_norm, field_id in self._alias_index.items():
            if field_id in valid_fields:
                candidates[alias_norm] = field_id

        if not candidates:
            return None

        # Find best match
        result = process.extractOne(
            normalised_key,
            list(candidates.keys()),
            scorer=fuzz.token_sort_ratio,
            score_cutoff=FUZZY_THRESHOLD,
        )

        if result:
            matched_alias, score, _ = result
            field_id = candidates[matched_alias]
            logger.debug(
                "Fuzzy matched '%s' -> '%s' (via alias '%s', score=%d)",
                normalised_key, field_id, matched_alias, score,
            )
            return field_id

        return None

    # ------------------------------------------------------------------
    # Gemini fallback (Layer 4)
    # ------------------------------------------------------------------
    def gemini_suggest_mappings(
        self,
        unmatched_keys: list[str],
        schema_fields: list[str],
    ) -> dict[str, str]:
        """
        Ask Gemini to suggest mappings for unmatched OCR keys.

        Returns dict of {ocr_key: suggested_field_id}.
        """
        try:
            from google import genai
        except ImportError:
            logger.warning("google-genai not installed; skipping Gemini fallback")
            return {}

        api_key = os.getenv("GEMINI_API_KEY")
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        if not api_key:
            logger.warning("GEMINI_API_KEY not set; skipping Gemini fallback")
            return {}

        # Build context of what each schema field means
        field_descriptions = {}
        for fid in schema_fields:
            meta = self.field_mapping.get(fid, {})
            field_descriptions[fid] = meta.get(
                "gemini_description", fid.replace("_", " ")
            )

        prompt = f"""You are an expert in Indian health insurance pre-authorization forms.

I have OCR-extracted keys from a medical document that need to be mapped to standardised schema field IDs.

UNMATCHED OCR KEYS:
{json.dumps(unmatched_keys, indent=2)}

AVAILABLE SCHEMA FIELD IDs (with descriptions):
{json.dumps(field_descriptions, indent=2)}

For each unmatched OCR key, suggest the best matching schema field_id.
If no good match exists, map it to null.

Return ONLY a valid JSON object like:
{{
  "OCR Key 1": "schema_field_id_1",
  "OCR Key 2": null,
  ...
}}
"""
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model,
                contents=prompt,
            )
            text = response.text.strip()
            # Extract JSON from response
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            suggestions = json.loads(text)
            # Filter out null and invalid suggestions
            return {
                k: v
                for k, v in suggestions.items()
                if v and v in set(schema_fields)
            }
        except Exception as e:
            logger.error("Gemini mapping fallback failed: %s", e)
            return {}

    # ------------------------------------------------------------------
    # Full pipeline with Gemini fallback
    # ------------------------------------------------------------------
    def map_with_gemini_fallback(
        self,
        ocr_output: dict,
        schema_fields: list[str],
        document_type: str = "preauth_form",
    ) -> dict:
        """
        Full mapping pipeline: alias + fuzzy + Gemini fallback.

        Returns dict of {field_id: value}.
        """
        # First pass: alias + fuzzy
        mapped = self.map_ocr_to_schema(ocr_output, schema_fields, document_type)

        # Find unmatched keys
        mapped_ocr_keys = set()
        for ocr_key in ocr_output:
            normalised = self._normalise(ocr_key)
            if ocr_key in mapped.values():
                continue
            for field_id in mapped:
                # Check if this ocr_key was the source
                if self._resolve_key(ocr_key, set(schema_fields), document_type) == field_id:
                    mapped_ocr_keys.add(ocr_key)
                    break

        unmatched_keys = [k for k in ocr_output if k not in mapped_ocr_keys and
                          self._resolve_key(k, set(schema_fields), document_type) is None]

        if unmatched_keys:
            logger.info("Trying Gemini fallback for %d unmatched keys...", len(unmatched_keys))
            suggestions = self.gemini_suggest_mappings(unmatched_keys, schema_fields)
            for ocr_key, field_id in suggestions.items():
                if field_id not in mapped:
                    mapped[field_id] = ocr_output[ocr_key]
                    logger.info("Gemini mapped '%s' -> '%s'", ocr_key, field_id)

        return mapped

    # ------------------------------------------------------------------
    # Manual override / confirm
    # ------------------------------------------------------------------
    def confirm_mapping(self, ocr_key: str, field_id: str) -> None:
        """
        Manually confirm or override a mapping by adding ocr_key as an alias.

        Persists to field_mapping.json.
        """
        if field_id not in self.field_mapping:
            logger.error("field_id '%s' not in field_mapping.json", field_id)
            return

        aliases = self.field_mapping[field_id].get("aliases", [])
        if ocr_key not in aliases:
            aliases.append(ocr_key)
            self.field_mapping[field_id]["aliases"] = aliases
            self._save_mapping()
            # Rebuild index
            self._alias_index = self._build_alias_index()
            logger.info("Added alias '%s' -> '%s'", ocr_key, field_id)

    def _save_mapping(self) -> None:
        """Persist current field_mapping to disk."""
        with open(self.mapping_path, "w", encoding="utf-8") as f:
            json.dump(self.field_mapping, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Gender convenience handler
    # ------------------------------------------------------------------
    def handle_gender(self, mapped_data: dict) -> dict:
        """
        If mapped data contains a 'gender' value (e.g. from Aadhaar OCR),
        convert it to the appropriate checkbox field_ids.
        """
        gender_value = None
        # Check multiple possible keys
        for key in ("gender", "sex", "Gender", "Sex"):
            if key in mapped_data:
                gender_value = mapped_data.pop(key)
                break

        if gender_value:
            gender_lower = gender_value.strip().lower()
            mapped_data["gender_male"] = gender_lower in ("male", "m")
            mapped_data["gender_female"] = gender_lower in ("female", "f")
            mapped_data["gender_third_gender"] = gender_lower in (
                "third gender", "other", "transgender",
            )

        return mapped_data

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def get_mapping_report(self) -> dict:
        """Return a report of all mapped and unmatched keys from last run."""
        return {
            "total_fields_in_mapping": len(self.field_mapping),
            "total_aliases": sum(
                len(m.get("aliases", [])) for m in self.field_mapping.values()
            ),
            "unmatched_log": self.unmatched_log,
        }


# ---------------------------------------------------------------------------
# CLI: Test mapping with sample data
# ---------------------------------------------------------------------------
def main():
    """Test the mapping engine with sample OCR-like data."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Simulate Document AI output with typical OCR key names
    sample_ocr_output = {
        "Policy Holder Name": "RAJESH KUMAR SHARMA",
        "Date of Birth": "15/03/1979",
        "Gender": "Male",
        "Contact Number": "9876543210",
        "Insured Card ID number": "SHI-2024-78456123",
        "Policy Number": "POL-2024-567890 / TCS Ltd.",
        "Employee ID": "EMP-TCS-45678",
        "Name of treating Doctor": "Dr. Priya Nair",
        "Doctor Contact Number": "9445566778",
        "Nature of Illness": "Acute Appendicitis with peritonitis",
        "Relevant Critical Findings": "Elevated WBC, CT shows inflamed appendix",
        "Duration of Present Ailment (Days)": "3",
        "Date of first consultation": "10/01/2025",
        "Past Medical History": "No significant past history",
        "ICD 10 Code": "K35.80",
        "Surgical Management": True,
        "Name of Surgery": "Laparoscopic Appendectomy",
        "ICD 10 PCS Code": "0DTJ4ZZ",
        "Date of Admission": "12/01/2025",
        "Time of Admission": "14:30",
        "Emergency": True,
        "Expected Hospital Days": "5",
        "ICU Days": "1",
        "Room Type": "Semi-Private",
        "Room Rent": "3500",
        "Investigation Cost": "8000",
        "ICU Charges": "12000",
        "OT Charges": "15000",
        "Professional Fees": "25000",
        "Medicine Cost": "10000",
        "Other Expenses": "3000",
        "Total Estimated Cost": "95000",
        "Sum Insured": "500000",  # Extra key not in schema — should be unmatched
    }

    # Load schema field_ids from analyzed JSON
    schema_path = BASE_DIR / "analyzed" / "Ericson TPA Preauth.json"
    if schema_path.exists():
        with open(schema_path) as f:
            schema = json.load(f)
        schema_fields = [f["field_id"] for f in schema["fields"]]
    else:
        schema_fields = list(
            json.load(open(FIELD_MAPPING_PATH)).keys()
        )

    print("=" * 60)
    print("MAPPING ENGINE TEST")
    print("=" * 60)

    engine = MappingEngine()

    # Run mapping
    mapped = engine.map_ocr_to_schema(sample_ocr_output, schema_fields)

    # Handle gender
    mapped = engine.handle_gender(mapped)

    print(f"\n--- MAPPED ({len(mapped)} fields) ---")
    for field_id, value in sorted(mapped.items()):
        display_val = str(value)[:50]
        print(f"  {field_id:55s} = {display_val}")

    # Show unmatched
    all_mapped_fields = set(mapped.keys())
    unmatched_ocr = [
        k for k in sample_ocr_output
        if engine._resolve_key(k, set(schema_fields), "preauth_form") is None
        and k.lower() not in ("gender", "sex")
    ]
    if unmatched_ocr:
        print(f"\n--- UNMATCHED OCR KEYS ({len(unmatched_ocr)}) ---")
        for k in unmatched_ocr:
            print(f"  ? {k} = {sample_ocr_output[k]}")

    # Report
    report = engine.get_mapping_report()
    print(f"\n--- REPORT ---")
    print(f"  Total fields in mapping: {report['total_fields_in_mapping']}")
    print(f"  Total aliases: {report['total_aliases']}")
    print(f"  Unmatched batches logged: {len(report['unmatched_log'])}")


if __name__ == "__main__":
    main()
