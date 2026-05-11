#!/usr/bin/env python3

import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from llmware.configs import LLMWareConfig
from llmware.library import Library
from neo4j import GraphDatabase


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")


NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")
neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

print("Dang xoa DB cuc bo (SQLite + ChromaDB) cua du an llmware...")
LLMWareConfig().set_active_db("sqlite")
LLMWareConfig().set_vector_db("chromadb")

lib_name = "kg_demo_vn"

try:
    import chromadb
    from llmware.configs import ChromaDBConfig

    persist_path = ChromaDBConfig.get_config("persistent_path")
    if persist_path:
        client = chromadb.PersistentClient(path=persist_path)
        try:
            client.delete_collection(lib_name)
            print("Da xoa ChromaDB collection.")
        except Exception as chroma_error:
            msg = str(chroma_error).lower()
            if "does not exist" in msg or "not found" in msg:
                print("ChromaDB collection chua ton tai.")
            else:
                print(f"ChromaDB: {chroma_error}")
    else:
        print("ChromaDB dang dung EphemeralClient, khong can xoa.")
except Exception as chroma_bootstrap_error:
    print(f"ChromaDB cleanup: {chroma_bootstrap_error}")

try:
    Library().delete_library(lib_name, confirm_delete=True)
    print("Da xoa Library (SQLite + thu muc).")
except Exception as library_error:
    print(f"Library cleanup: {library_error}")

print("Dang don dep du lieu cu tren Neo4j DB...")
try:
    with neo4j_driver.session() as session:
        session.run("RETURN 1")
    with neo4j_driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n;")
    print("Da xoa toan bo Node va Relationship tren Neo4j.")
except Exception as neo4j_error:
    print(f"Khong the ket noi/xoa Neo4j (bo qua): {neo4j_error}")
    print("Neo4j co the chua chay hoac thong tin ket noi chua dung.")

processed_path = PROJECT_ROOT / "data" / "processed"
ingest_path = PROJECT_ROOT / "data" / "ingest"
ingest_path.mkdir(parents=True, exist_ok=True)
processed_path.mkdir(parents=True, exist_ok=True)

moved_files = 0
for file_path in processed_path.iterdir():
    shutil.move(str(file_path), str(ingest_path / file_path.name))
    moved_files += 1

print(f"Da di chuyen (reset) {moved_files} file tu processed ve ingest.")
print("\nRESET thanh cong. Ban co the chay lai `python script.py`.")
