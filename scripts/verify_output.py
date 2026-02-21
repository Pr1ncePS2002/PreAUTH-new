#!/usr/bin/env python3
"""Verify overlay text positions in the filled PDF"""
import pdfplumber
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

pdf = pdfplumber.open(PROJECT_ROOT / 'output' / 'Ericson TPA Preauth_filled.pdf')
orig = pdfplumber.open(PROJECT_ROOT / 'templates' / 'Ericson TPA Preauth.pdf')

with open(PROJECT_ROOT / 'analyzed' / 'Ericson TPA Preauth.json') as f:
    structure = json.load(f)

for page_num in range(len(pdf.pages)):
    filled_words = pdf.pages[page_num].extract_words()
    orig_words = orig.pages[page_num].extract_words()
    
    orig_set = set()
    for w in orig_words:
        orig_set.add((round(w['x0'], 1), round(w['top'], 1), w['text']))
    
    new_words = []
    for w in filled_words:
        key = (round(w['x0'], 1), round(w['top'], 1), w['text'])
        if key not in orig_set:
            new_words.append(w)
    
    if new_words:
        print(f'\nPage {page_num+1} - Overlay text ({len(new_words)} words):')
        for w in new_words:
            print(f'  "{w["text"]}" at x={w["x0"]:.1f}, y={w["top"]:.1f}')

pdf.close()
orig.close()
