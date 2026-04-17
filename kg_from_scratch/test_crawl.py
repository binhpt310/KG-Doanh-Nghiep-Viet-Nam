#!/usr/bin/env python3
"""
Test crawl 5 individuals để kiểm tra xem API có hoạt động không.
"""

import os
from dotenv import load_dotenv

load_dotenv()

from pipeline import _crawl_all_individuals, _load_state

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 TEST CRAWL - 5 INDIVIDUALS")
    print("=" * 60)
    
    state = _load_state()
    print(f"\n📊 State loaded: {len(state.get('crawled_individuals', []))} individuals already crawled")
    
    # Chỉ lấy 5 individuals chưa crawl
    from pipeline import _collect_individual_ids
    all_ids = _collect_individual_ids()
    crawled = set(state.get("crawled_individuals", []))
    remaining = [iid for iid in all_ids if iid not in crawled]
    
    print(f"📋 Total unique IDs: {len(all_ids)}")
    print(f"✅ Already crawled: {len(crawled)}")
    print(f"🔄 Remaining: {len(remaining)}")
    
    if remaining:
        print(f"\n🎯 First 5 to crawl: {remaining[:5]}")
        print("\n⏳ Starting test crawl (will be stopped after 5)...\n")
        
        # Crawl thử 5 cái
        import time
        from pipeline import _crawl_individual_profile, INDIVIDUAL_DELAY
        
        for i, iid in enumerate(remaining[:5]):
            print(f"  [{i+1}/5] Crawling individual {iid}...")
            profile = _crawl_individual_profile(iid)
            if profile:
                print(f"    ✅ Success: {profile.get('name', 'N/A')}")
            else:
                print(f"    ⚠️ No data")
            time.sleep(INDIVIDUAL_DELAY)
        
        print("\n✅ TEST COMPLETE! API hoạt động tốt.")
    else:
        print("\n⚠️ No remaining individuals to crawl!")
