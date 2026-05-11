"""
Phase 0 - Data Quality Filter: Cleanup script for Neo4j.

Deletes:
1. Edges where ownership = 0 or ownership IS NULL
2. Orphan nodes (nodes with no edges after cleanup)

Usage: python scripts/cleanup_zero_ownership.py
"""

import os
from pathlib import Path
from neo4j import GraphDatabase

# Load project .env to get the correct local URI
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            # Override Neo4j connection vars from .env
            if _k.strip() in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE"):
                os.environ[_k.strip()] = _v.strip()

NEO4J_URI = os.environ.get("NEO4J_URI", "neo4j://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASSWORD", "password123")


def main():
    print(f"Kết nối Neo4j tại: {NEO4J_URI}")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

    try:
        with driver.session() as session:
            # Step 1: Delete edges with ownership = 0 or ownership IS NULL
            print("\n--- Xoá các cạnh có ownership = 0 hoặc NULL ---")

            result = session.run("""
                MATCH ()-[r]->()
                WHERE r.ownership = 0 OR r.ownership IS NULL
                RETURN count(r) AS cnt
            """)
            cnt = result.single()["cnt"]
            print(f"  Tìm thấy {cnt} cạnh cần xoá.")

            session.run("""
                MATCH ()-[r]->()
                WHERE r.ownership = 0 OR r.ownership IS NULL
                DELETE r
            """)
            print(f"  Đã xoá {cnt} cạnh.")

            # Step 2: Delete orphan nodes (nodes with no relationships)
            print("\n--- Xoá các node orphan (không còn cạnh nào) ---")

            result = session.run("""
                MATCH (n)
                WHERE NOT (n)--()
                RETURN count(n) AS cnt
            """)
            orphan_cnt = result.single()["cnt"]
            print(f"  Tìm thấy {orphan_cnt} node orphan.")

            session.run("""
                MATCH (n)
                WHERE NOT (n)--()
                DELETE n
            """)
            print(f"  Đã xoá {orphan_cnt} node orphan.")

            print("\n=== HOÀN TẤT ===")
            print(f"  Cạnh đã xoá: {cnt}")
            print(f"  Node orphan đã xoá: {orphan_cnt}")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
