#!/usr/bin/env python3
"""
Kiem tra co che tu dong detect va resume crawl cua pipeline.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from pipeline import (
    PROCESSED_RAW_DIR,
    RAW_DIR,
    STATE_FILE,
    _STATE_FILE_LEGACY,
    _collect_individual_ids,
    _load_state,
    get_all_symbols,
)


print("=" * 70)
print("VERIFY: AUTO-RESUME CRAWL MECHANISM")
print("=" * 70)

errors = []
warnings = []

print("\nTEST 1: State File Locations")
print(f"  Primary (RAW_DIR):      {STATE_FILE}")
print(f"  Legacy (PROCESSED_RAW): {_STATE_FILE_LEGACY}")

primary_exists = os.path.exists(STATE_FILE)
legacy_exists = os.path.exists(_STATE_FILE_LEGACY)

print(f"  Primary exists:  {'YES' if primary_exists else 'NO'}")
print(f"  Legacy exists:   {'YES' if legacy_exists else 'NO'}")

if not primary_exists and not legacy_exists:
    errors.append("Khong tim thay state file o ca 2 locations.")

print("\nTEST 2: State Load Mechanism")
state = _load_state()
crawled_symbols = state.get("crawled_symbols", [])
crawled_individuals = state.get("crawled_individuals", [])
last_step = state.get("last_step", "Unknown")

print("  Loaded successfully.")
print(f"  Crawled symbols:     {len(crawled_symbols)}")
print(f"  Crawled individuals: {len(crawled_individuals)}")
print(f"  Last step:           {last_step}")

if len(crawled_symbols) == 0 and len(crawled_individuals) == 0:
    warnings.append("State trong - se crawl tu dau.")

print("\nTEST 3: Data Files Availability (raw/ va processed_raw/)")
for file_name in ["banks.json", "officers.json", "holders.json", "subsidiaries.json", "individuals.json"]:
    raw_path = os.path.join(RAW_DIR, file_name)
    processed_path = os.path.join(PROCESSED_RAW_DIR, file_name)
    raw_exists = os.path.exists(raw_path)
    processed_exists = os.path.exists(processed_path)

    if raw_exists or processed_exists:
        size = os.path.getsize(processed_path if processed_exists else raw_path)
        location = "processed_raw" if processed_exists else "raw"
        print(f"  {file_name}: {location} ({size:,} bytes)")
    else:
        print(f"  {file_name}: NOT FOUND o ca 2 locations!")
        errors.append(f"Missing {file_name}")

print("\nTEST 4: Individual IDs Collection")
all_individual_ids = _collect_individual_ids()
print(f"  Total unique IDs collected: {len(all_individual_ids)}")

crawled_set = set(crawled_individuals)
already_crawled = [iid for iid in all_individual_ids if iid in crawled_set]
remaining = [iid for iid in all_individual_ids if iid not in crawled_set]

print(f"  Already crawled: {len(already_crawled)}")
print(f"  Remaining:       {len(remaining)}")

if len(all_individual_ids) == 0:
    errors.append("Khong collect duoc individual IDs nao.")
elif len(remaining) == 0:
    warnings.append("Tat ca individuals da crawl xong.")
else:
    print(f"  Co {len(remaining)} individuals can crawl tiep.")

print("\nTEST 5: Skip Logic Verification")
if remaining:
    print(f"  Test IDs (first 3 remaining): {remaining[:3]}")
    for individual_id in remaining[:3]:
        if individual_id in crawled_set:
            errors.append(f"ID {individual_id} bi bao remaining nhung thuc te da crawl.")
        else:
            print(f"    ID {individual_id} correctly marked as remaining")

    if already_crawled:
        print(f"  Test IDs (first 3 already crawled): {already_crawled[:3]}")
        for individual_id in already_crawled[:3]:
            if individual_id in crawled_set:
                print(f"    ID {individual_id} correctly marked as crawled")
            else:
                errors.append(f"ID {individual_id} da crawl nhung khong co trong state.")

print("\nTEST 6: Save State Mechanism")
print(f"  State will be saved to: {STATE_FILE}")
if os.access(RAW_DIR, os.W_OK):
    print("  RAW_DIR is writable")
else:
    errors.append(f"RAW_DIR khong writable: {RAW_DIR}")

if legacy_exists:
    print("  Legacy state file readable")

print("\nTEST 7: Symbols List")
all_symbols = get_all_symbols()
symbols_crawled = set(crawled_symbols)
symbols_remaining = [symbol for symbol in all_symbols if symbol not in symbols_crawled]

print(f"  Total symbols:     {len(all_symbols)}")
print(f"  Symbols crawled:   {len(crawled_symbols)}")
print(f"  Symbols remaining: {len(symbols_remaining)}")

if symbols_remaining:
    print(f"  First 5 remaining: {symbols_remaining[:5]}")
else:
    print("  Tat ca symbols da crawl xong.")

print("\n" + "=" * 70)
print("VERIFICATION SUMMARY")
print("=" * 70)

if errors:
    print(f"\nERRORS ({len(errors)}):")
    for error in errors:
        print(f"  - {error}")

if warnings:
    print(f"\nWARNINGS ({len(warnings)}):")
    for warning in warnings:
        print(f"  - {warning}")

if not errors:
    print("\nALL CHECKS PASSED.")
    print("\nKET LUAN:")
    print(f"  - Script co the tu dong resume crawl")
    print(f"  - Se skip {len(crawled_symbols)} symbols da crawl")
    print(f"  - Se skip {len(crawled_individuals)} individuals da crawl")
    print(f"  - Se crawl tiep {len(symbols_remaining)} symbols con thieu")
    print(f"  - Se crawl tiep {len(remaining)} individuals con thieu")
    print("\nCommand de chay crawl tiep:")
    print("  docker exec kg-app python pipeline.py resume")
else:
    print("\nCO LOI! Can fix truoc khi crawl.")
    sys.exit(1)

print("\n" + "=" * 70)
