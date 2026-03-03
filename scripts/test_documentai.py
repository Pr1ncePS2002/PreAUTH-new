#!/usr/bin/env python3
"""
Test Script — Validate Google Cloud Document AI integration.

Run this to verify Document AI is working:

    cd "PreAUTH new"
    .\\venv\\Scripts\\python.exe scripts\\test_documentai.py

With a specific file:
    .\\venv\\Scripts\\python.exe scripts\\test_documentai.py uploads\\heritage_form.pdf estimate

Compare Gemini vs Document AI:
    .\\venv\\Scripts\\python.exe scripts\\test_documentai.py uploads\\bajaj_form.pdf estimate --compare
"""

import json
import os
import sys
import time
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def test_config():
    """Step 1: Verify .env configuration is correct."""
    print("\n" + "=" * 60)
    print("STEP 1: Checking .env configuration")
    print("=" * 60)

    required = {
        "GOOGLE_CLOUD_PROJECT": os.getenv("GOOGLE_CLOUD_PROJECT"),
        "DOCUMENT_AI_LOCATION": os.getenv("DOCUMENT_AI_LOCATION"),
        "DOCUMENT_AI_FORM_PROCESSOR_ID": os.getenv("DOCUMENT_AI_FORM_PROCESSOR_ID"),
    }

    all_ok = True
    for key, val in required.items():
        status = "OK" if val else "MISSING"
        if not val:
            all_ok = False
        print(f"  {key}: {val or '(not set)'} [{status}]")

    creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if creds:
        exists = Path(creds).exists()
        print(f"  GOOGLE_APPLICATION_CREDENTIALS: {creds} [{'EXISTS' if exists else 'FILE NOT FOUND'}]")
        if not exists:
            all_ok = False
    else:
        print("  GOOGLE_APPLICATION_CREDENTIALS: (not set)")
        print("    -> Will use Application Default Credentials (gcloud auth)")

    if not all_ok:
        print("\n  RESULT: Configuration incomplete. Fix .env and retry.")
        return False

    print("\n  RESULT: Configuration OK")
    return True


def test_import():
    """Step 2: Verify google-cloud-documentai is installed."""
    print("\n" + "=" * 60)
    print("STEP 2: Checking google-cloud-documentai package")
    print("=" * 60)

    try:
        from google.cloud import documentai_v1 as documentai
        print(f"  Package version: {documentai.__version__ if hasattr(documentai, '__version__') else 'installed'}")
        print("  RESULT: Package OK")
        return True
    except ImportError as e:
        print(f"  ERROR: {e}")
        print("  FIX: Run:  pip install google-cloud-documentai>=2.20.0")
        return False


def test_auth():
    """Step 3: Verify authentication to Google Cloud."""
    print("\n" + "=" * 60)
    print("STEP 3: Testing authentication")
    print("=" * 60)

    try:
        from google.cloud import documentai_v1 as documentai
        from google.api_core.client_options import ClientOptions

        location = os.getenv("DOCUMENT_AI_LOCATION", "asia-southeast1")
        client_options = None
        if location not in ("us", "eu"):
            api_endpoint = f"{location}-documentai.googleapis.com"
            client_options = ClientOptions(api_endpoint=api_endpoint)

        client = documentai.DocumentProcessorServiceClient(
            client_options=client_options
        )

        # Try to list processors as a connectivity test
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        parent = f"projects/{project}/locations/{location}"

        print(f"  Connecting to: {api_endpoint if client_options else 'documentai.googleapis.com'}")
        print(f"  Resource: {parent}")

        # List processors to verify auth
        processors = list(client.list_processors(parent=parent))
        print(f"  Found {len(processors)} processor(s):")
        for p in processors:
            print(f"    - {p.display_name} ({p.type_}) [ID: {p.name.split('/')[-1]}]")

        print("\n  RESULT: Authentication OK")
        return True

    except Exception as e:
        error_msg = str(e)
        print(f"  ERROR: {e}")

        if "403" in error_msg or "PERMISSION_DENIED" in error_msg:
            print("\n  FIX: Your credentials don't have Document AI permissions.")
            print("  Either:")
            print("    a) Set GOOGLE_APPLICATION_CREDENTIALS to a service account JSON key")
            print("    b) Run: gcloud auth application-default login")
            print("    c) Grant 'Document AI Editor' role to your account")
        elif "404" in error_msg or "NOT_FOUND" in error_msg:
            print("\n  FIX: Project or location not found. Check:")
            print("    - GOOGLE_CLOUD_PROJECT in .env")
            print("    - DOCUMENT_AI_LOCATION in .env")
        elif "Could not automatically determine credentials" in error_msg:
            print("\n  FIX: No Google Cloud credentials found.")
            print("  Option A (recommended for development):")
            print("    gcloud auth application-default login")
            print("  Option B (production):")
            print("    Set GOOGLE_APPLICATION_CREDENTIALS=path/to/key.json in .env")
        else:
            print("\n  Check your network connection and credentials.")

        return False


def test_extract(file_path: str, doc_type: str = "generic"):
    """Step 4: Actually extract data from a document."""
    print("\n" + "=" * 60)
    print(f"STEP 4: Extracting '{Path(file_path).name}' (type={doc_type})")
    print("=" * 60)

    from services.extractors.documentai_extractor import DocumentAIExtractor

    extractor = DocumentAIExtractor()

    start = time.monotonic()
    result = extractor.extract(file_path, doc_type)
    elapsed = time.monotonic() - start

    if result.error:
        print(f"  ERROR: {result.error}")
        return None

    print(f"  Processing time: {result.processing_time_ms}ms")
    print(f"  Fields extracted: {result.field_count}")
    print(f"  Avg confidence: {result.avg_confidence:.2%}")
    print(f"  Tables found: {len(result.tables)}")
    print(f"  Pages: {result.page_count}")

    if result.fields:
        print(f"\n  {'Key':<40} {'Value':<35} {'Conf':>6}")
        print(f"  {'─' * 40} {'─' * 35} {'─' * 6}")
        for f in sorted(result.fields, key=lambda x: x.confidence, reverse=True):
            val = f.value[:33] + ".." if len(f.value) > 35 else f.value
            print(f"  {f.key:<40} {val:<35} {f.confidence:>5.1%}")

    if result.tables:
        for t in result.tables:
            print(f"\n  TABLE (page {t['page']}, {t['row_count']} rows):")
            if t.get("headers"):
                print(f"    Headers: {' | '.join(t['headers'])}")
            for i, row in enumerate(t["rows"][:5]):  # First 5 rows
                print(f"    Row {i+1}: {' | '.join(row)}")
            if t["row_count"] > 5:
                print(f"    ... and {t['row_count'] - 5} more rows")

    if result.low_confidence_fields:
        print(f"\n  LOW CONFIDENCE ({len(result.low_confidence_fields)} fields):")
        for f in result.low_confidence_fields:
            print(f"    {f.key}: '{f.value}' (confidence: {f.confidence:.1%})")

    # Save raw output
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / f"docai_test_{Path(file_path).stem}.json"
    with open(output_file, "w", encoding="utf-8") as fp:
        json.dump({
            "source_file": str(file_path),
            "document_type": doc_type,
            "extraction_method": result.extraction_method,
            "processing_time_ms": result.processing_time_ms,
            "page_count": result.page_count,
            "field_count": result.field_count,
            "avg_confidence": result.avg_confidence,
            "fields": result.to_dict_with_confidence(),
            "flat_dict": result.to_dict(),
            "tables": result.tables,
        }, fp, indent=2, ensure_ascii=False)
    print(f"\n  Full output saved to: {output_file}")

    return result


def test_compare(file_path: str, doc_type: str = "generic"):
    """Compare Gemini vs Document AI extraction side by side."""
    print("\n" + "=" * 60)
    print(f"COMPARE: Gemini vs Document AI on '{Path(file_path).name}'")
    print("=" * 60)

    from services.extractors.gemini_extractor import GeminiVisionExtractor
    from services.extractors.documentai_extractor import DocumentAIExtractor

    # Gemini extraction
    print("\n  Running Gemini Vision extraction...")
    gemini = GeminiVisionExtractor()
    g_result = gemini.extract(file_path, doc_type)

    # Document AI extraction
    print("  Running Document AI extraction...")
    docai = DocumentAIExtractor()
    d_result = docai.extract(file_path, doc_type)

    # Side-by-side comparison
    all_keys = set()
    g_dict = g_result.to_dict()
    d_dict = d_result.to_dict()
    d_conf = {f.key: f.confidence for f in d_result.fields}

    all_keys.update(g_dict.keys())
    all_keys.update(d_dict.keys())

    print(f"\n  {'Field':<35} {'Gemini':<30} {'Document AI':<30} {'Conf':>6}")
    print(f"  {'─' * 35} {'─' * 30} {'─' * 30} {'─' * 6}")

    for key in sorted(all_keys):
        g_val = g_dict.get(key, "—")[:28]
        d_val = d_dict.get(key, "—")[:28]
        conf = d_conf.get(key, 0)
        match = "=" if g_val == d_val else "~" if g_val.lower() == d_val.lower() else " "

        print(f"  {key:<35} {g_val:<30} {d_val:<30} {conf:>5.1%} {match}")

    print(f"\n  Summary:")
    print(f"    Gemini:      {g_result.field_count} fields, {g_result.processing_time_ms}ms")
    print(f"    Document AI: {d_result.field_count} fields, {d_result.processing_time_ms}ms, "
          f"avg conf: {d_result.avg_confidence:.1%}")
    print(f"    Tables (Doc AI only): {len(d_result.tables)}")

    # Save comparison
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    comparison_file = output_dir / f"compare_{Path(file_path).stem}.json"
    with open(comparison_file, "w", encoding="utf-8") as fp:
        json.dump({
            "source_file": str(file_path),
            "document_type": doc_type,
            "gemini": {"fields": g_dict, "field_count": g_result.field_count, "time_ms": g_result.processing_time_ms},
            "documentai": {"fields": d_dict, "field_count": d_result.field_count, "time_ms": d_result.processing_time_ms,
                           "avg_confidence": d_result.avg_confidence, "tables": d_result.tables},
        }, fp, indent=2, ensure_ascii=False)
    print(f"    Comparison saved to: {comparison_file}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Test Document AI integration")
    parser.add_argument("file", nargs="?", help="Path to document to extract")
    parser.add_argument("type", nargs="?", default="generic",
                        help="Document type: aadhaar, policy_card, estimate, clinical_notes, generic")
    parser.add_argument("--compare", action="store_true",
                        help="Compare Gemini vs Document AI side by side")
    parser.add_argument("--skip-auth", action="store_true",
                        help="Skip auth test (if you know it works)")

    args = parser.parse_args()

    print("=" * 60)
    print("  DOCUMENT AI INTEGRATION TEST")
    print("=" * 60)

    # Step 1: Config
    if not test_config():
        sys.exit(1)

    # Step 2: Package
    if not test_import():
        sys.exit(1)

    # Step 3: Auth
    if not args.skip_auth:
        if not test_auth():
            print("\n  Authentication failed. Fix credentials and retry.")
            print("  Quickest fix: gcloud auth application-default login")
            sys.exit(1)

    # Step 4: Extract (if file provided)
    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"\n  ERROR: File not found: {file_path}")
            sys.exit(1)

        if args.compare:
            test_compare(str(file_path), args.type)
        else:
            test_extract(str(file_path), args.type)
    else:
        print("\n  Config and auth verified! To test extraction, run:")
        print("    python scripts/test_documentai.py uploads/your_form.pdf estimate")
        print("    python scripts/test_documentai.py uploads/your_form.pdf estimate --compare")

    print("\n" + "=" * 60)
    print("  DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()
