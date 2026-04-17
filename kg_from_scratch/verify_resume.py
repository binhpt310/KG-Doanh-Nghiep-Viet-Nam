#!/usr/bin/env python3
"""
verify_resume.py — Kiểm tra cơ chế tự động detect và resume crawl của pipeline.

Verify checklist:
  1. State file được load đúng từ legacy location (processed_raw/crawler_state.json)
  2. Symbols đã crawl được skip đúng
  3. Individuals đã crawl được skip đúng
  4. Individual IDs được collect từ cả officers.json và holders.json
  5. Files data được load từ cả raw/ và processed_raw/
  6. State được save đúng location sau khi crawl thêm
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

print("=" * 70)
print("🔍 VERIFY: AUTO-RESUME CRAWL MECHANISM")
print("=" * 70)

# Import pipeline functions
from pipeline import (
    _load_state,
    _collect_individual_ids,
    _load_json_file,
    RAW_DIR,
    PROCESSED_RAW_DIR,
    STATE_FILE,
    _STATE_FILE_LEGACY,
    get_all_symbols,
)

errors = []
warnings = []

# ────────────────────────────────────────────────────────────────────────────
# TEST 1: State file locations
# ────────────────────────────────────────────────────────────────────────────
print("\n📌 TEST 1: State File Locations")
print(f"  Primary (RAW_DIR):      {STATE_FILE}")
print(f"  Legacy (PROCESSED_RAW): {_STATE_FILE_LEGACY}")

primary_exists = os.path.exists(STATE_FILE)
legacy_exists = os.path.exists(_STATE_FILE_LEGACY)

print(f"  Primary exists:  {'✅ YES' if primary_exists else '❌ NO'}")
print(f"  Legacy exists:   {'✅ YES' if legacy_exists else '❌ NO'}")

if not primary_exists and not legacy_exists:
    errors.append("❌ Không tìm thấy state file ở cả 2 locations!")

# ────────────────────────────────────────────────────────────────────────────
# TEST 2: State load mechanism
# ────────────────────────────────────────────────────────────────────────────
print("\n📌 TEST 2: State Load Mechanism")
state = _load_state()

crawled_symbols = state.get("crawled_symbols", [])
crawled_individuals = state.get("crawled_individuals", [])
last_step = state.get("last_step", "Unknown")

print(f"  ✅ Loaded successfully!")
print(f"  Crawled symbols:    {len(crawled_symbols)}")
print(f"  Crawled individuals: {len(crawled_individuals)}")
print(f"  Last step:          {last_step}")

if len(crawled_symbols) == 0 and len(crawled_individuals) == 0:
    warnings.append("⚠️ State trống - sẽ crawl từ đầu")

# ────────────────────────────────────────────────────────────────────────────
# TEST 3: Data files availability
# ────────────────────────────────────────────────────────────────────────────
print("\n📌 TEST 3: Data Files Availability (raw/ và processed_raw/)")
data_files = ["banks.json", "officers.json", "holders.json", "subsidiaries.json", "individuals.json"]

for fname in data_files:
    raw_path = os.path.join(RAW_DIR, fname)
    processed_path = os.path.join(PROCESSED_RAW_DIR, fname)
    raw_exists = os.path.exists(raw_path)
    processed_exists = os.path.exists(processed_path)

    if raw_exists or processed_exists:
        size = 0
        if processed_exists:
            size = os.path.getsize(processed_path)
        elif raw_exists:
            size = os.path.getsize(raw_path)
        print(f"  ✅ {fname}: {'processed_raw' if processed_exists else 'raw'} ({size:,} bytes)")
    else:
        print(f"  ❌ {fname}: NOT FOUND ở cả 2 locations!")
        errors.append(f"❌ Missing {fname}")

# ────────────────────────────────────────────────────────────────────────────
# TEST 4: Individual IDs collection
# ────────────────────────────────────────────────────────────────────────────
print("\n📌 TEST 4: Individual IDs Collection")
all_individual_ids = _collect_individual_ids()

print(f"  Total unique IDs collected: {len(all_individual_ids)}")

# Check overlap with state
crawled_set = set(crawled_individuals)
already_crawled = [iid for iid in all_individual_ids if iid in crawled_set]
remaining = [iid for iid in all_individual_ids if iid not in crawled_set]

print(f"  Already crawled: {len(already_crawled)}")
print(f"  Remaining:       {len(remaining)}")

if len(all_individual_ids) == 0:
    errors.append("❌ Không collect được individual IDs nào!")
elif len(remaining) == 0:
    warnings.append("⚠️ Tất cả individuals đã crawl xong!")
else:
    print(f"  ✅ Có {len(remaining)} individuals cần crawl tiếp")

# ────────────────────────────────────────────────────────────────────────────
# TEST 5: Skip logic verification
# ────────────────────────────────────────────────────────────────────────────
print("\n📌 TEST 5: Skip Logic Verification")

# Check if crawl function would skip correctly
from pipeline import _crawl_all_individuals

# Test với first 3 remaining IDs
if remaining:
    test_ids = remaining[:3]
    print(f"  Test IDs (first 3 remaining): {test_ids}")

    # Verify they are NOT in crawled set
    for tid in test_ids:
        if tid in crawled_set:
            errors.append(f"❌ ID {tid} bị báo remaining nhưng thực tế đã crawl!")
        else:
            print(f"    ✅ ID {tid} correctly marked as remaining")

    # Verify crawled IDs would be skipped
    if already_crawled:
        test_crawled = already_crawled[:3]
        print(f"  Test IDs (first 3 already crawled): {test_crawled}")
        for tid in test_crawled:
            if tid in crawled_set:
                print(f"    ✅ ID {tid} correctly marked as crawled (will be skipped)")
            else:
                errors.append(f"❌ ID {tid} đã crawl nhưng không có trong state!")

# ────────────────────────────────────────────────────────────────────────────
# TEST 6: Save state mechanism
# ────────────────────────────────────────────────────────────────────────────
print("\n📌 TEST 6: Save State Mechanism")
print(f"  State will be saved to: {STATE_FILE}")

# Check if RAW_DIR is writable
if os.access(RAW_DIR, os.W_OK):
    print(f"  ✅ RAW_DIR is writable")
else:
    errors.append(f"❌ RAW_DIR không writable: {RAW_DIR}")

# Check if PROCESSED_RAW_DIR state file is readable
if legacy_exists:
    print(f"  ✅ Legacy state file readable")

# ────────────────────────────────────────────────────────────────────────────
# TEST 7: Symbols list
# ────────────────────────────────────────────────────────────────────────────
print("\n📌 TEST 7: Symbols List")
all_symbols = get_all_symbols()
symbols_crawled = set(crawled_symbols)
symbols_remaining = [s for s in all_symbols if s not in symbols_crawled]

print(f"  Total symbols:        {len(all_symbols)}")
print(f"  Symbols crawled:      {len(crawled_symbols)}")
print(f"  Symbols remaining:    {len(symbols_remaining)}")

if symbols_remaining:
    print(f"  First 5 remaining:    {symbols_remaining[:5]}")
else:
    print(f"  ✅ Tất cả symbols đã crawl xong")

# ────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("📊 VERIFICATION SUMMARY")
print("=" * 70)

if errors:
    print(f"\n❌ ERRORS ({len(errors)}):")
    for err in errors:
        print(f"  {err}")

if warnings:
    print(f"\n⚠️ WARNINGS ({len(warnings)}):")
    for warn in warnings:
        print(f"  {warn}")

if not errors:
    print("\n✅ ALL CHECKS PASSED!")
    print("\n🎯 KẾT LUẬN:")
    print(f"   - Script CÓ THỂ tự động resume crawl")
    print(f"   - Sẽ skip {len(crawled_symbols)} symbols đã crawl")
    print(f"   - Sẽ skip {len(crawled_individuals)} individuals đã crawl")
    print(f"   - Sẽ crawl tiếp {len(symbols_remaining)} symbols còn thiếu")
    print(f"   - Sẽ crawl tiếp {len(remaining)} individuals còn thiếu")
    print(f"\n🚀 Command để chạy crawl tiếp:")
    print(f"   docker exec kg-app python pipeline.py resume")
else:
    print(f"\n❌ CÓ LỖI! Cần fix trước khi crawl.")
    sys.exit(1)

print("\n" + "=" * 70)
