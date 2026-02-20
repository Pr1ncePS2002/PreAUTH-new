#!/usr/bin/env python3
"""
HIS (Hospital Information System) Integration Service — STUB.

This is a clearly-labelled stub that returns mock data.
Replace with real HIS API calls when the hospital endpoint is available.

Usage:
    from services.his_service import HISService

    his = HISService()
    patient = his.get_patient("MRD-2024-001234")
    documents = his.get_documents("MRD-2024-001234")
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# STUB DATA — Replace with real HIS API integration
# ---------------------------------------------------------------------------
_MOCK_PATIENTS = {
    "MRD-2024-001234": {
        "mrd_number": "MRD-2024-001234",
        "patient_name": "RAJESH KUMAR SHARMA",
        "date_of_birth": "15/03/1979",
        "age_years": "45",
        "age_months": "6",
        "gender": "Male",
        "contact_number": "9876543210",
        "email": "rajesh.sharma@email.com",
        "address": "42, MG Road, Andheri West, Mumbai - 400058",
        "occupation": "Software Engineer",
        "blood_group": "B+",
        "aadhaar_number": "XXXX-XXXX-1234",
        "emergency_contact": {
            "name": "Sunita Sharma",
            "relation": "Spouse",
            "phone": "9123456789",
        },
        "insurance": {
            "policy_number": "POL-2024-567890",
            "insurance_company": "Star Health Insurance Co. Ltd.",
            "card_id": "SHI-2024-78456123",
            "corporate_name": "TCS Ltd.",
            "employee_id": "EMP-TCS-45678",
            "sum_insured": "500000",
        },
    },
    "MRD-2024-005678": {
        "mrd_number": "MRD-2024-005678",
        "patient_name": "PRIYA MEHTA",
        "date_of_birth": "22/08/1985",
        "age_years": "40",
        "age_months": "5",
        "gender": "Female",
        "contact_number": "9988776655",
        "email": "priya.mehta@email.com",
        "address": "15, Park Street, Kolkata - 700016",
        "occupation": "Teacher",
        "blood_group": "O+",
        "aadhaar_number": "XXXX-XXXX-5678",
        "emergency_contact": {
            "name": "Amit Mehta",
            "relation": "Husband",
            "phone": "9876512345",
        },
        "insurance": {
            "policy_number": "POL-2024-123456",
            "insurance_company": "HDFC Ergo Health Insurance",
            "card_id": "HEH-2024-99887766",
            "corporate_name": "",
            "employee_id": "",
            "sum_insured": "300000",
        },
    },
}

_MOCK_DOCUMENTS = {
    "MRD-2024-001234": [
        {
            "document_id": "DOC-001",
            "type": "aadhaar",
            "filename": "aadhaar_rajesh.jpg",
            "upload_date": "2025-01-10",
            "status": "verified",
        },
        {
            "document_id": "DOC-002",
            "type": "policy_card",
            "filename": "star_health_card.pdf",
            "upload_date": "2025-01-10",
            "status": "verified",
        },
        {
            "document_id": "DOC-003",
            "type": "clinical_notes",
            "filename": "clinical_notes_appendicitis.pdf",
            "upload_date": "2025-01-12",
            "status": "pending_ocr",
        },
    ],
    "MRD-2024-005678": [
        {
            "document_id": "DOC-010",
            "type": "aadhaar",
            "filename": "aadhaar_priya.jpg",
            "upload_date": "2025-02-01",
            "status": "verified",
        },
    ],
}

_MOCK_ADMISSIONS = {
    "MRD-2024-001234": {
        "admission_id": "ADM-2025-0001",
        "mrd_number": "MRD-2024-001234",
        "admission_date": "12/01/2025",
        "admission_time": "14:30",
        "admission_type": "Emergency",
        "department": "General Surgery",
        "treating_doctor": "Dr. Priya Nair",
        "doctor_contact": "9445566778",
        "room_type": "Semi-Private",
        "room_number": "312",
        "diagnosis": "Acute Appendicitis with peritonitis",
        "icd10_code": "K35.80",
        "procedure_planned": "Laparoscopic Appendectomy",
        "icd10_pcs_code": "0DTJ4ZZ",
    },
}


# ---------------------------------------------------------------------------
# HIS Service
# ---------------------------------------------------------------------------
class HISService:
    """
    Hospital Information System integration.

    IMPORTANT: This is a STUB implementation using mock data.
    Replace the _fetch_* methods with real HTTP calls to your HIS API.
    """

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        """
        Args:
            base_url: HIS API base URL (e.g. "https://his.hospital.com/api/v1")
            api_key: Authentication key for HIS API
        """
        self.base_url = base_url
        self.api_key = api_key
        self._is_stub = base_url is None
        if self._is_stub:
            logger.warning("HIS Service running in STUB mode — using mock data")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_patient(self, mrd_number: str) -> Optional[dict]:
        """
        Fetch patient demographics by MRD number.

        Returns dict with patient info or None if not found.
        """
        if self._is_stub:
            return _MOCK_PATIENTS.get(mrd_number)
        return self._fetch_patient(mrd_number)

    def get_documents(self, mrd_number: str) -> list[dict]:
        """
        Fetch list of documents associated with a patient.

        Returns list of document metadata dicts.
        """
        if self._is_stub:
            return _MOCK_DOCUMENTS.get(mrd_number, [])
        return self._fetch_documents(mrd_number)

    def get_admission(self, mrd_number: str) -> Optional[dict]:
        """
        Fetch current/latest admission details.

        Returns admission dict or None.
        """
        if self._is_stub:
            return _MOCK_ADMISSIONS.get(mrd_number)
        return self._fetch_admission(mrd_number)

    def search_patients(self, query: str) -> list[dict]:
        """
        Search patients by name or MRD number.

        Returns list of matching patient summaries.
        """
        if self._is_stub:
            results = []
            query_lower = query.lower()
            for mrd, patient in _MOCK_PATIENTS.items():
                if (query_lower in mrd.lower() or
                    query_lower in patient["patient_name"].lower()):
                    results.append({
                        "mrd_number": mrd,
                        "patient_name": patient["patient_name"],
                        "date_of_birth": patient["date_of_birth"],
                        "gender": patient["gender"],
                    })
            return results
        return self._search_patients(query)

    def build_preauth_data(self, mrd_number: str) -> dict:
        """
        Build a pre-auth data dict from HIS data (demographics + admission).

        This merges patient demographics and admission details into
        a format ready for the mapping engine / form filler.
        """
        patient = self.get_patient(mrd_number)
        if not patient:
            return {}

        admission = self.get_admission(mrd_number)

        data = {
            "patient_name": patient.get("patient_name", ""),
            "gender": patient.get("gender", ""),
            "age_years_duration": patient.get("age_years", ""),
            "age_months_duration": patient.get("age_months", ""),
            "date_of_birth": patient.get("date_of_birth", ""),
            "patient_contact_number": patient.get("contact_number", ""),
            "insured_patient_current_address": patient.get("address", ""),
            "insured_patient_occupation": patient.get("occupation", ""),
            "patient_representative_email_id": patient.get("email", ""),
        }

        # Insurance info
        ins = patient.get("insurance", {})
        data.update({
            "insured_card_id_number": ins.get("card_id", ""),
            "policy_number_corporate_name": f"{ins.get('policy_number', '')} / {ins.get('corporate_name', '')}".strip(" /"),
            "employee_id": ins.get("employee_id", ""),
            "tpa_insurance_company_name": ins.get("insurance_company", ""),
        })

        # Emergency contact
        ec = patient.get("emergency_contact", {})
        data["attending_relative_contact_number"] = ec.get("phone", "")

        # Admission details
        if admission:
            data.update({
                "admission_date": admission.get("admission_date", ""),
                "admission_time": admission.get("admission_time", ""),
                "treating_doctor_name": admission.get("treating_doctor", ""),
                "treating_doctor_contact_number": admission.get("doctor_contact", ""),
                "nature_of_illness_complaint": admission.get("diagnosis", ""),
                "provisional_diagnosis_icd10_code": admission.get("icd10_code", ""),
                "surgery_name": admission.get("procedure_planned", ""),
                "surgical_icd10_pcs_code": admission.get("icd10_pcs_code", ""),
                "room_type": admission.get("room_type", ""),
            })

            if admission.get("admission_type") == "Emergency":
                data["hospitalization_event_emergency"] = True
            else:
                data["hospitalization_event_planned"] = True

        return data

    # ------------------------------------------------------------------
    # Real HIS API calls (implement when available)
    # ------------------------------------------------------------------
    def _fetch_patient(self, mrd_number: str) -> Optional[dict]:
        """Replace with real HIS API call."""
        raise NotImplementedError("Real HIS integration not yet configured")

    def _fetch_documents(self, mrd_number: str) -> list[dict]:
        """Replace with real HIS API call."""
        raise NotImplementedError("Real HIS integration not yet configured")

    def _fetch_admission(self, mrd_number: str) -> Optional[dict]:
        """Replace with real HIS API call."""
        raise NotImplementedError("Real HIS integration not yet configured")

    def _search_patients(self, query: str) -> list[dict]:
        """Replace with real HIS API call."""
        raise NotImplementedError("Real HIS integration not yet configured")


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    his = HISService()

    print("=" * 60)
    print("HIS SERVICE TEST (STUB MODE)")
    print("=" * 60)

    # Search
    print("\n--- Search 'rajesh' ---")
    results = his.search_patients("rajesh")
    for r in results:
        print(f"  {r['mrd_number']}: {r['patient_name']} ({r['gender']}, DOB: {r['date_of_birth']})")

    # Get patient
    mrd = "MRD-2024-001234"
    print(f"\n--- Patient {mrd} ---")
    patient = his.get_patient(mrd)
    if patient:
        print(f"  Name: {patient['patient_name']}")
        print(f"  DOB: {patient['date_of_birth']}")
        print(f"  Insurance: {patient['insurance']['insurance_company']}")

    # Get documents
    print(f"\n--- Documents for {mrd} ---")
    docs = his.get_documents(mrd)
    for d in docs:
        print(f"  [{d['status']}] {d['type']}: {d['filename']}")

    # Build pre-auth data
    print(f"\n--- Pre-auth data for {mrd} ---")
    preauth = his.build_preauth_data(mrd)
    for k, v in sorted(preauth.items()):
        if v:
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
