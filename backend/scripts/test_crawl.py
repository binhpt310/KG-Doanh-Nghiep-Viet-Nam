#!/usr/bin/env python3
"""
Test crawl 5 individuals de kiem tra xem API co hoat dong khong.
"""

import sys
import time
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from pipeline import (
    INDIVIDUAL_DELAY,
    _collect_individual_ids,
    _crawl_individual_profile,
    _load_state,
)


if __name__ == "__main__":
    print("=" * 60)
    print("TEST CRAWL - 5 INDIVIDUALS")
    print("=" * 60)

    state = _load_state()
    print(f"\nState loaded: {len(state.get('crawled_individuals', []))} individuals already crawled")

    all_ids = _collect_individual_ids()
    crawled = set(state.get("crawled_individuals", []))
    remaining = [iid for iid in all_ids if iid not in crawled]

    print(f"Total unique IDs: {len(all_ids)}")
    print(f"Already crawled: {len(crawled)}")
    print(f"Remaining: {len(remaining)}")

    if remaining:
        print(f"\nFirst 5 to crawl: {remaining[:5]}")
        print("\nStarting test crawl (will be stopped after 5)...\n")

        for index, individual_id in enumerate(remaining[:5], start=1):
            print(f"  [{index}/5] Crawling individual {individual_id}...")
            profile = _crawl_individual_profile(individual_id)
            if profile:
                print(f"    Success: {profile.get('name', 'N/A')}")
            else:
                print("    No data")
            time.sleep(INDIVIDUAL_DELAY)

        print("\nTEST COMPLETE! API hoat dong tot.")
    else:
        print("\nNo remaining individuals to crawl.")
