import os
import shutil
from dotenv import load_dotenv
from neo4j import GraphDatabase
from llmware.configs import LLMWareConfig
from llmware.library import Library

# 1. Setup Neo4j Driver
load_dotenv()
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")
neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

# 2. Xóa Library DB trong LLMWare (SQLite + ChromaDB)
print("⏳ Đang xóa DB cục bộ (SQLite + ChromaDB) của dự án llmware...")
LLMWareConfig().set_active_db("sqlite")
LLMWareConfig().set_vector_db("chromadb")

lib_name = "kg_demo_vn"

# 2a. Xóa ChromaDB collection (lưu riêng, delete_library không xóa)
try:
    import chromadb
    from llmware.configs import ChromaDBConfig
    persist_path = ChromaDBConfig.get_config("persistent_path")
    if persist_path:
        client = chromadb.PersistentClient(path=persist_path)
        try:
            client.delete_collection(lib_name)
            print("✅ Đã xóa ChromaDB collection.")
        except Exception as ce:
            if "does not exist" in str(ce).lower() or "not found" in str(ce).lower():
                print("ℹ️ ChromaDB collection chưa tồn tại.")
            else:
                print(f"⚠️ ChromaDB: {ce}")
    else:
        print("ℹ️ ChromaDB dùng EphemeralClient, không cần xóa.")
except Exception as e:
    print(f"⚠️ ChromaDB cleanup: {e}")

# 2b. Xóa Library (SQLite blocks + thư mục)
try:
    Library().delete_library(lib_name, confirm_delete=True)
    print("✅ Đã xóa Library (SQLite + thư mục).")
except Exception as e:
    print(f"ℹ️ Library: {e}")

# 3. Xóa Dữ liệu Neo4j
print("⏳ Đang dọn dẹp dữ liệu cũ trên Neo4j DB...")
try:
    # Test connectivity first
    with neo4j_driver.session() as session:
        session.run("RETURN 1")
    with neo4j_driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n;")
    print("✅ Đã xóa toàn bộ Node & Relationship trên Neo4j.")
except Exception as e:
    print(f"⚠️ Không thể kết nối/xóa Neo4j (bỏ qua): {e}")
    print("   Neo4j có thể chưa chạy hoặc thông tin kết nối chưa đúng.")

# 4. Di chuyển file từ processed -> ingest
processed_path = os.path.abspath("data/processed")
ingest_path = os.path.abspath("data/ingest")
os.makedirs(ingest_path, exist_ok=True)
os.makedirs(processed_path, exist_ok=True)

moved_files = 0
for fname in os.listdir(processed_path):
    src = os.path.join(processed_path, fname)
    dst = os.path.join(ingest_path, fname)
    shutil.move(src, dst)
    moved_files += 1

print(f"✅ Đã di chuyển (reset) {moved_files} file từ processed về lại ingest.")
print("\n🎉 RESET THÀNH CÔNG! BẠN CÓ THỂ CHẠY LẠI SCRIPT CHÍNH (python script.py).")
