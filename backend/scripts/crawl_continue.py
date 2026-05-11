#!/usr/bin/env python3
"""
Tương thích ngược: gọi cùng logic với `python pipeline.py resume` hoặc
`python pipeline.py crawl`.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from pipeline import crawl_fireant_data


if __name__ == "__main__":
    print("=" * 60)
    print("CONTINUE CRAWL (resume) - khuyen nghi: python pipeline.py resume")
    print("=" * 60)
    crawl_fireant_data(symbols=None, skip_individuals=False, reset=False, banks_only=False)
