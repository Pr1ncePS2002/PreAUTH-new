import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

with open(PROJECT_ROOT / 'analyzed' / 'Ericson TPA Preauth.json') as f:
    schema = json.load(f)
pages = {}
for x in schema['fields']:
    pages.setdefault(x['page'], []).append(x)
for p in sorted(pages.keys()):
    print(f"--- Page {p} ({len(pages[p])} fields) ---")
    for x in pages[p]:
        print(f"  {x['field_id']} ({x['type']})")
