#!/usr/bin/env python3
"""
Tương thích ngược: gọi cùng logic với `python pipeline.py resume` hoặc `python pipeline.py crawl`.
"""
from dotenv import load_dotenv

load_dotenv()

from pipeline import crawl_fireant_data

if __name__ == "__main__":
    print("=" * 60)
    print("🔄 CONTINUE CRAWL (resume) — khuyến nghị: python pipeline.py resume")
    print("=" * 60)
    crawl_fireant_data(symbols=None, skip_individuals=False, reset=False, banks_only=False)
