import os
import sys
import shutil
import json
from datetime import datetime, timezone
from dotenv import load_dotenv

# 1. SETUP - load_dotenv MUST be called FIRST before any env var usage
load_dotenv()

from llmware.configs import LLMWareConfig
from llmware.library import Library
from llmware.agents import LLMfx
from llmware.models import ModelCatalog
from llmware.gguf_configs import GGUFConfigs
from itertools import combinations
from neo4j import GraphDatabase
from flask import Flask, render_template, request, jsonify
from pipeline import crawl_and_update
import threading


def _detect_gpu() -> bool:
    has_driver = os.path.exists("/proc/driver/nvidia/version")
    has_device = os.path.exists("/dev/nvidia0")
    return has_driver and has_device


# Tự động phát hiện GPU
USE_GPU = _detect_gpu()
if USE_GPU:
    print("🚀 [GPU]: Phát hiện GPU qua filesystem. Kích hoạt GPU layers cho GGUF models.")
    try:
        GGUFConfigs().set_config("force_gpu", True)
        GGUFConfigs().set_config("n_gpu_layers", 100)  # offload 100 layers lên GPU
        print("   ✅ GGUFConfigs: force_gpu=True, n_gpu_layers=100")
    except Exception as _gpu_err:
        print(f"   ⚠️ GGUFConfigs set error (ignored): {_gpu_err}")
else:
    print("⚠️ [GPU]: Không tìm thấy GPU. Dùng CPU để inference.")


# Cấu hình Fast-Start (Local), Sử dụng SQLite + ChromaDB
LLMWareConfig().set_active_db("sqlite")
LLMWareConfig().set_vector_db("chromadb")

# Setup Neo4j Driver (safer to create after load_dotenv)
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")
neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

# Crawl progress tracker (shared between thread and API)
_crawl_progress = {
    "running": False,
    "step": "",
    "message": "",
    "total_nodes": 0,
    "total_edges": 0,
    "symbols_crawled": 0,
    "error": None
}

# MODEL_NAME, LLM_BACKEND, LLM_BASE_URL / VLLM_BASE_URL (một nguồn; ưu tiên LLM_BASE_URL)
MODEL_NAME = os.getenv("MODEL_NAME", "qwen3-14b").strip()
LLM_BACKEND = os.getenv("LLM_BACKEND", "openai").strip().lower()
_default_llm_base = (
    "http://localhost:9061"
    if LLM_BACKEND in ("openai", "vllm", "openai_compat")
    else "http://localhost:11434"
)
LLM_BASE_URL = (
    os.getenv("LLM_BASE_URL") or os.getenv("VLLM_BASE_URL") or _default_llm_base
).strip()
if not LLM_BASE_URL.startswith("http"):
    LLM_BASE_URL = f"http://{LLM_BASE_URL}"
LLM_BASE_URL = LLM_BASE_URL.rstrip("/")

_p = LLM_BASE_URL.replace("http://", "").replace("https://", "").rstrip("/").split(":")
LLM_HTTP_HOST = _p[0]
LLM_HTTP_PORT = int(_p[1]) if len(_p) > 1 else (9061 if LLM_BACKEND in ("openai", "vllm", "openai_compat") else 11434)
os.environ["LLM_BASE_URL"] = LLM_BASE_URL

import re as _re
import requests

LLM_INFERENCE_TIMEOUT = int(os.getenv("LLM_INFERENCE_TIMEOUT", "300"))
OLLAMA_NUM_CTX = 10000
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8192"))

_THINK_RE = _re.compile(r"<think>.*?</think>", _re.DOTALL)

def _strip_think_tags(text: str) -> str:
    """Loại bỏ toàn bộ block <think>...</think> khỏi output LLM."""
    return _THINK_RE.sub("", text).strip()

def ollama_inference(prompt: str, model: str = MODEL_NAME) -> dict:
    """Ollama POST /api/chat."""
    prompt = prompt.strip() + "/nothink"
    url = f"{LLM_BASE_URL}/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": -1,
        "options": {"temperature": 0.8, "num_ctx": OLLAMA_NUM_CTX},
    }
    r = requests.post(url, json=payload, timeout=LLM_INFERENCE_TIMEOUT)
    r.raise_for_status()
    out = r.json()
    text = out.get("message", {}).get("content", "")
    text = _strip_think_tags(text)
    return {"llm_response": text.strip(), "usage": {}}


def openai_compatible_inference(prompt: str, model: str = MODEL_NAME) -> dict:
    """vLLM: POST /v1/chat/completions (OpenAI-compatible)."""
    url = f"{LLM_BASE_URL}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt.strip()}],
        "temperature": 0.8,
        "max_tokens": LLM_MAX_TOKENS,
        "stream": False,
    }
    r = requests.post(url, json=payload, timeout=LLM_INFERENCE_TIMEOUT)
    r.raise_for_status()
    out = r.json()
    choices = out.get("choices") or []
    text = ""
    if choices and isinstance(choices[0], dict):
        msg = choices[0].get("message") or {}
        text = msg.get("content") or ""
    text = _strip_think_tags(text)
    return {"llm_response": text.strip(), "usage": out.get("usage") or {}}


def llm_inference(prompt: str, model: str = MODEL_NAME) -> dict:
    if LLM_BACKEND in ("openai", "vllm", "openai_compat"):
        return openai_compatible_inference(prompt, model=model)
    return ollama_inference(prompt, model=model)


def _keep_alive():
    if LLM_BACKEND != "ollama":
        return
    try:
        requests.post(
            f"{LLM_BASE_URL}/api/chat",
            json={
                "model": MODEL_NAME,
                "messages": [{"role": "user", "content": "ping"}],
                "stream": False,
                "keep_alive": -1,
                "options": {"num_ctx": OLLAMA_NUM_CTX},
            },
            timeout=120,
        )
        print(f"✅ [Ollama keep_alive]: Model '{MODEL_NAME}' đã được pin trong VRAM (num_ctx={OLLAMA_NUM_CTX}).")
    except Exception as e:
        print(f"⚠️ keep_alive Ollama (bỏ qua): {e}")


threading.Thread(target=_keep_alive, daemon=True).start()

if LLM_BACKEND == "ollama":
    ModelCatalog().register_ollama_model(
        model_name=MODEL_NAME,
        model_type="chat",
        host=LLM_HTTP_HOST,
        port=LLM_HTTP_PORT,
        temperature=0.8,
        context_window=10000,
    )
else:
    print(f"ℹ️ [LLM] backend={LLM_BACKEND} base={LLM_BASE_URL} model={MODEL_NAME}")

# --- Cấu trúc Graph để LLM hiểu và tự sinh Cypher ---
NEO4J_SCHEMA = """
Các Nodes (Thực thể):
- (Entity): Có các thuộc tính: name (tên), type (loại: BANK, PERSON, COMPANY), id (mã định danh). Labels bổ sung: Person, Company.
- Công ty luôn có id bắt đầu bằng 'C_' (ví dụ: 'C_VIC', 'C_TCB'). Người luôn có id bắt đầu bằng 'P_' (ví dụ: 'P_123').
Các Relationships (Trọng tâm truy vấn):
- [:LÃNH_ĐẠO_CAO_NHẤT]: Người đứng đầu/Chủ tịch HĐQT của công ty. Luôn ưu tiên dùng cạnh này khi hỏi "Ai là lãnh đạo/chủ tịch/đứng đầu". (VD: (p:Entity)-[:LÃNH_ĐẠO_CAO_NHẤT]->(c:Entity {symbol: 'VIC'}))
- [:LÀ_CỔ_ĐÔNG_CỦA]: Người/tổ chức sở hữu cổ phần công ty. Có thuộc tính: `shares` (số CP), `ownership` (tỷ lệ sở hữu).
- [:CÓ_CÔNG_TY_CON]: Khi hỏi công ty con. (VD: MATCH (p:Entity)-[:CÓ_CÔNG_TY_CON]->(c:Entity))
- [:CHA_MẸ], [:ANH_CHỊ], [:VỢ_CHỒNG]: Quan hệ gia đình.
- [:LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO]: Người thân của lãnh đạo công ty. Có các thuộc tính trên cạnh (relationship properties): `leaderName` (tên lãnh đạo), `position` (chức vụ lãnh đạo), `familyRelation` (quan hệ với lãnh đạo).

Luật viết Cypher (BẮT BUỘC):
1. Phải DÙNG MATCH (n:Entity) HẠN CHẾ SỬ DỤNG (n:Person) hay (n:Company) để tránh lỗi label. Thay vào đó dùng n.type = 'Person'.
2. Luôn dùng toLower(n.name) CONTAINS toLower('Từ khóa') thay vì so sánh bằng name = 'Từ khóa'. Nếu biết mã chứng khoán (symbol), TỐT NHẤT LÀ so sánh c.symbol = 'MÃ_CQ' thay vì name.
3. Khi trả kết quả (RETURN), bắt buộc phải có các trường: source_id, source_name, source_group, source_symbol, target_id, target_name, target_group, target_symbol, edge_label, inferred.
"""

def generate_cypher_with_llm(user_query, history_context, schema, steps_list, model=None):
    """Sử dụng LLM để sinh câu lệnh Cypher bằng kĩ thuật Grounded Reasoning."""
    use_model = model or MODEL_NAME
    steps_list.append("🧠 AI đang phân tích logic và quy tắc truy vấn (Grounded Reasoning)...")
    
    # Load grounding document
    grounding_doc = ""
    try:
        ref_path = os.path.join(os.path.dirname(__file__), "docs", "cypher_reference.md")
        if os.path.exists(ref_path):
            with open(ref_path, "r", encoding="utf-8") as f:
                grounding_doc = f.read()
    except Exception as e:
        print(f"Warning: Could not load cypher_reference.md: {e}")

    prompt = f"""
Bạn là chuyên gia thiết kế Cypher cho Neo4j. Hãy phân tích yêu cầu của người dùng dựa trên tài liệu tham khảo dưới đây.

TÀI LIỆU THAM KHẢO CYPHER:
{grounding_doc}

SƠ ĐỒ GRAPH (SCHEMA):
{schema}

YÊU CẦU:
- Thực hiện suy luận từng bước (THOUGHT) trước khi viết câu lệnh Cypher.
- Chú ý đặc biệt đến các quan hệ ẩn (inferred) và quy tắc sở hữu chéo.
- Câu trả lời của bạn phải tuân thủ định dạng sau:
# THOUGHT
[Phân tích logic của bạn ở đây, sử dụng các pattern từ tài liệu tham khảo]

# CYPHER
[Câu lệnh Cypher duy nhất, KHÔNG markdown]

Lịch sử phiên: {history_context}
Câu hỏi: {user_query}
"""
    try:
        print("[LLM] Đang thực hiện Grounded Reasoning...")
        response = llm_inference(prompt, model=use_model)
        full_res = response.get("llm_response", "").strip()
        
        thought = ""
        cypher = ""
        
        if "# CYPHER" in full_res:
            parts = full_res.split("# CYPHER")
            thought = parts[0].replace("# THOUGHT", "").strip()
            cypher = parts[1].strip().replace("```cypher", "").replace("```", "").strip()
        else:
            cypher = full_res.strip().replace("```cypher", "").replace("```", "").strip()
            
        if thought:
            steps_list.append(f"🔍 Suy luận: {thought[:300]}...")
            
        print(f"Generated Cypher: {cypher}")
        return cypher
    except Exception as e:
        print(f"Error generating Cypher: {e}")
        return None


# CÁC HÀM TƯƠNG TÁC VỚI NEO4J

def upsert_entity(tx, node_id, entity_name, entity_type, props=None):
    if props is None: props = {}
    query = """
    MERGE (n:Entity {id: $id})
    ON CREATE SET n.name = $name, n.type = $type
    ON MATCH SET n.name = $name, n.type = $type
    """
    if props:
        query += "\nSET n += $props"
    query += "\nRETURN n"
    tx.run(query, id=node_id, name=entity_name, type=entity_type, props=props)

def upsert_relation(tx, src_id, tgt_id, relation, props=None, is_inferred=False):
    import re
    if props is None: props = {}
    
    # Neo4j relationship types không chứa space và các ký tự đặc biệt, ta chuẩn hóa relation string
    rel_type = relation.replace(" ", "_").upper()
    rel_type = re.sub(r'[^A-Z0-9_ÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚĂĐĨŨƠàáâãèéêìíòóôõùúăđĩũơƯĂẠẢẤẦẨẪẬẮẰẲẴẶẸẺẼỀỀỂưăạảấầẩẫậắằẳẵặẹẻẽềềểỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪễệỉịọỏốồổỗộớờởỡợụủứừỬỮỰỲỴÝỶỸửữựỳỵỷỹ]', '', rel_type)
    
    query = f"""
    MATCH (a:Entity {{id: $src_id}})
    MATCH (b:Entity {{id: $tgt_id}})
    MERGE (a)-[r:`{rel_type}`]->(b)
    ON CREATE SET r.inferred = $is_inferred, r.label = $relation
    ON MATCH SET r.inferred = $is_inferred, r.label = $relation
    """
    if props:
        query += "\nSET r += $props"
    tx.run(query, src_id=src_id, tgt_id=tgt_id, is_inferred=is_inferred, relation=relation, props=props)


# 2. XỬ LÝ INGESTION (INCREMENTAL)

def process_new_files():
    # Bước 0: LLM Preprocessor - Đọc file thô và xuất file chuẩn vào data/ingest/
    import llm_preprocessor
    llm_preprocessor.process_raw_files()
    
    lib_name = "kg_demo_vn"
    lib = Library().create_new_library(lib_name)
    
    ingest_path = os.path.abspath("data/ingest")
    processed_path = os.path.abspath("data/processed")
    os.makedirs(ingest_path, exist_ok=True)
    os.makedirs(processed_path, exist_ok=True)
    
    new_files = os.listdir(ingest_path)
    if not new_files:
        print("✅ [Trạng thái]: Không có file mới trong thư mục ingest.")
        return False, lib
        
    print(f"🚀 [Bắt đầu]: Tìm thấy {len(new_files)} file mới. Bắt đầu xử lý...")
    
    print("⏳ [Ingestion]: Đang đọc và phân tích nội dung files...")
    lib.add_files(ingest_path)
    print("✅ [Ingestion]: Hoàn tất đọc files.")
    
    for i, fname in enumerate(new_files):
        print(f"   -> Đang chuyển đổi file ({i+1}/{len(new_files)}): {fname}")
        src = os.path.join(ingest_path, fname)
        dst = os.path.join(processed_path, fname)
        shutil.move(src, dst)
        
    print("⏳ [Embedding]: Đang khởi tạo bộ nhúng (embedding) và vector hóa dữ liệu...")
    ModelCatalog().register_sentence_transformer_model(
        model_name="vinai/phobert-large",
        embedding_dims=1024,
        context_window=256
    )
    lib.install_new_embedding(
        embedding_model_name="vinai/phobert-large",
        vector_db="chromadb",
        batch_size=50
    )
    
    lib.export_library_to_jsonl_file(lib.nlp_path, "kg_export")
    return True, lib


def run_ner_and_relation_extraction(lib):
    kg_dir = os.path.abspath("data/kg_data")
    nodes_file = os.path.join(kg_dir, "kg_nodes.json")
    edges_file = os.path.join(kg_dir, "kg_edges.json")
    
    if not os.path.exists(nodes_file) or not os.path.exists(edges_file):
        print("✅ [Neo4j Ingestion]: Không tìm thấy file JSON Graph. Bỏ qua bước đưa dữ liệu vào Neo4j.")
        return

    print(f"⏳ [Neo4j Ingestion]: Bắt đầu chèn nodes & edges đã parse trực tiếp vào Neo4j...")
    
    with open(nodes_file, 'r', encoding='utf-8') as f:
        nodes = json.load(f)
        
    with open(edges_file, 'r', encoding='utf-8') as f:
        edges = json.load(f)
        
    total_entities = 0
    total_relations = 0

    with neo4j_driver.session() as session:
        print(f"   -> Chèn {len(nodes)} Entities (Nodes)...")
        for node in nodes:
            n_id = node.get("id")
            n_name = node.get("name", "")
            n_type = node.get("label", "Entity")
            n_props = node.get("props", {})
            
            clean_props = {}
            for k, v in n_props.items():
                if v is not None:
                    if isinstance(v, str):
                        clean_props[k] = v.strip()
                    else:
                        clean_props[k] = v
            session.execute_write(upsert_entity, n_id, n_name, n_type, clean_props)
            total_entities += 1
            
        print(f"   -> Chèn {len(edges)} Quan hệ (Edges)...")
        for edge in edges:
            src = edge.get("source")
            tgt = edge.get("target")
            rel = edge.get("label")
            e_props = edge.get("props", {})
            session.execute_write(upsert_relation, src, tgt, rel, props=e_props, is_inferred=False)
            total_relations += 1
            
    print(f"✅ [Neo4j Ingestion]: Hoàn tất. Đã chèn {total_entities} entities và {total_relations} quan hệ trực tiếp.")

    # Tạo quan hệ LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO cho Neo4j biết người thân của lãnh đạo
    try:
        from scripts.add_leader_family_relations import run as add_leader_family
        add_leader_family(neo4j_driver)
        print("✅ [Neo4j]: Đã cập nhật quan hệ người thân của lãnh đạo.")
    except Exception as e:
        print(f"⚠️ [Neo4j] add_leader_family: {e}")


def run_hidden_relation_inference_loop():
    print("⏳ [Inference]: Bắt đầu vòng lặp suy luận quan hệ ẩn...")

    query_get_triplets = """
    MATCH (a:Entity)-[r1]->(b:Entity)-[r2]->(c:Entity)
    WHERE a <> c AND NOT EXISTS { (a)-->(c) }
    RETURN a.id AS A, b.id AS B, c.id AS C, r1.label as R1, r2.label as R2
    LIMIT 100
    """
    
    with neo4j_driver.session() as session:
        result = session.run(query_get_triplets)
        records = list(result)
        
        if not records:
             print("✅ [Inference]: Không có đồ thị con hở để suy luận (hoặc đã duyệt hết).")
             return
             
        print(f"   -> Đã trích xuất {len(records)} đồ thị con hở (triplets). Bắt đầu đánh giá...")
        new_relations_found = 0
        for i, rec in enumerate(records):
             if (i+1) % max(1, len(records) // 5) == 0:
                 print(f"   -> Đang đánh giá cặp {i+1}/{len(records)}...")
             A, B, C = rec["A"], rec["B"], rec["C"]
             
             inferred_relation = "NONE"
             r1_label = str(rec["R1"])
             r2_label = str(rec["R2"])
             
             if r2_label == "CÓ_CÔNG_TY_CON" and r1_label != "CÓ_CÔNG_TY_CON":
                 inferred_relation = "ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI"
                  
             if inferred_relation != "NONE":
                  new_relations_found += 1
                  session.execute_write(upsert_relation, A, C, inferred_relation, is_inferred=True)
                  
        print(f"✅ [Inference]: Đã suy luận và chèn {new_relations_found} quan hệ ẩn mới vào Neo4j.")


# 5. FLASK WEB UI & GRAPH API

def _load_entity_map():
    """Load từ data/config/entity_map.json (tạo bởi scripts/generate_entity_map.py)."""
    path = os.path.join(os.path.dirname(__file__), "data", "config", "entity_map.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Không đọc được entity_map.json: {e}")
    return {}

ENTITY_MAP = _load_entity_map()

LEADER_RELS = ["LÃNH_ĐẠO_CAO_NHẤT", "CHỦ_TỊCH_HĐQT", "TỔNG_GIÁM_ĐỐC"]

def get_leaders_of_company(company_id):
    """Trả về danh sách (leader_id, leader_name) của công ty."""
    with neo4j_driver.session() as session:
        r = session.run("""
            MATCH (leader:Entity)-[r]->(c:Entity {id: $cid})
            WHERE r.label IN $rels
            RETURN leader.id AS lid, leader.name AS lname
            LIMIT 5
        """, cid=company_id, rels=LEADER_RELS)
        return [(rec["lid"], rec["lname"]) for rec in r]

def _fetch_subgraph(center_id, limit=100):
    """Lấy subgraph xoay quanh 1 entity. Trả về (nodes_dict, edges_list)."""
    nodes_dict = {}
    edges = []
    q_out = """
        MATCH (n:Entity {id: $eid})-[r]->(m:Entity)
        WITH n, m, r ORDER BY r.label
        LIMIT $lim
        RETURN n.id AS sid, n.name AS sname, n.type AS sgrp, n.symbol AS ssym,
               m.id AS tid, m.name AS tname, m.type AS tgrp, m.symbol AS tsym,
               r.label AS elabel, r.inferred AS inf
    """
    q_in = """
        MATCH (n:Entity)-[r]->(m:Entity {id: $eid})
        WITH n, m, r ORDER BY r.label
        LIMIT $lim
        RETURN n.id AS sid, n.name AS sname, n.type AS sgrp, n.symbol AS ssym,
               m.id AS tid, m.name AS tname, m.type AS tgrp, m.symbol AS tsym,
               r.label AS elabel, r.inferred AS inf
    """
    def add_rec(rec):
        s_id = rec["sid"]
        t_id = rec["tid"]
        s_sym = rec.get("ssym")
        t_sym = rec.get("tsym")
        s_display = f"{rec['sname']} ({s_sym})" if s_sym else (rec["sname"] or s_id)
        t_display = f"{rec['tname']} ({t_sym})" if t_sym else (rec["tname"] or t_id)
        nodes_dict[s_id] = {"id": s_id, "label": s_display, "group": rec["sgrp"] or "DEFAULT"}
        nodes_dict[t_id] = {"id": t_id, "label": t_display, "group": rec["tgrp"] or "DEFAULT"}
        edges.append({"from": s_id, "to": t_id, "label": rec["elabel"] or "", "dashes": bool(rec.get("inf", False))})
    try:
        with neo4j_driver.session() as session:
            for rec in session.run(q_out, eid=center_id, lim=limit):
                add_rec(rec)
            for rec in session.run(q_in, eid=center_id, lim=limit):
                add_rec(rec)
    except Exception as e:
        print(f"[_fetch_subgraph] {e}")
    return nodes_dict, edges

def extract_main_entities(query_text, target_entity_id, target_display):
    """
    Trả về danh sách (entity_id, display_label) các thực thể chính trong câu hỏi.
    VD: "lãnh đạo ACB và người thân" -> [(C_ACB, "ACB"), (P_xxx, "Trần Hùng Huy")]
    """
    main = []
    q_lower = query_text.lower()
    has_leader = any(w in q_lower for w in ["lãnh đạo", "lanh dao", "chủ tịch", "chu tich", "tổng giám đốc", "tong giam doc"])
    has_family = any(w in q_lower for w in ["người thân", "nguoi than", "cha", "mẹ", "anh", "chị", "em"])
    if target_entity_id and (has_leader or has_family):
        main.append((target_entity_id, target_display or target_entity_id))
        leaders = get_leaders_of_company(target_entity_id)
        for lid, lname in leaders:
            main.append((lid, lname or lid))
    elif target_entity_id:
        main.append((target_entity_id, target_display or target_entity_id))
    return main

def extract_target_entity(query_text):
    q_lower = query_text.lower().strip()
    # 1. Ưu tiên khớp Bank từ ENTITY_MAP
    for key in sorted(ENTITY_MAP.keys(), key=len, reverse=True):
        if key in q_lower:
            return ENTITY_MAP[key], key.upper()
            
    # 2. Khớp tên người hoặc công ty từ Graph
    tokens = [w for w in query_text.split() if len(w) >= 3]
    if len(tokens) >= 1:
        # Thử ghép 2-4 từ
        for n in [4, 3, 2, 1]:
            for i in range(len(tokens) - n + 1):
                phrase = " ".join(tokens[i:i+n]).lower()
                if len(phrase) < 3: continue
                with neo4j_driver.session() as session:
                    # Tìm kiếm chính xác hoặc gần đúng trong Graph
                    res = session.run(
                        """
                        MATCH (ent:Entity) 
                        WHERE toLower(ent.name) = $phrase OR toLower(ent.id) = $phrase
                        RETURN ent.id as eid, ent.name as ename, ent.type as etype LIMIT 1
                        """, phrase=phrase
                    )
                    rec = res.single()
                    if rec:
                        return rec["eid"], rec["ename"]
    return None, None


app = Flask(__name__, static_folder='templates/assets', static_url_path='/assets')

@app.after_request
def add_ngrok_skip_header(response):
    # Add header to skip ngrok browser warning page for all responses
    # This header tells ngrok to skip the warning page for visitors
    response.headers['ngrok-skip-browser-warning'] = 'skip'
    return response

@app.route("/")
def index():
    return render_template(
        "index.html",
        neo4j_browser_url=os.getenv("NEO4J_BROWSER_URL", "http://localhost:7474").strip(),
    )

def _is_company(e):
    eid = e.get("id", "")
    etype = e.get("type", "")
    return (isinstance(eid, str) and eid.startswith("C_")) or etype == "Company"

def _is_person(e):
    eid = e.get("id", "")
    etype = e.get("type", "")
    return (isinstance(eid, str) and eid.startswith("P_")) or etype == "Person"


def _relationship_display_label(rel):
    """Neo4j Relationship: type + optional property `label`."""
    if rel is None:
        return ""
    try:
        props = dict(rel)
        return (props.get("label") or getattr(rel, "type", "") or "").strip()
    except Exception:
        return getattr(rel, "type", "") or ""


def _build_symbol_exchange_map():
    """HOSE/HNX/UPCOM từ pipeline — trùng logic api_stats_exchange."""
    from pipeline import HOSE, HNX, UPCOM

    m = {}
    for _s in HOSE:
        m.setdefault(_s, "HOSE")
    for _s in HNX:
        m.setdefault(_s, "HNX")
    for _s in UPCOM:
        m.setdefault(_s, "UPCOM")
    return m


def _resolve_vn_listing(exchange, symbol, nid):
    """
    Trả về 'HOSE' | 'HNX' | 'UPCOM' nếu niêm yết VN; None nếu bucket 'Khác'.
    Trùng quy tắc GET /api/stats/exchange.
    """
    _static_map = _build_symbol_exchange_map()
    ex = (exchange or "").strip().upper() if exchange else ""
    if not ex or ex in ("", "NONE"):
        sym = (symbol or "").strip()
        if not sym and isinstance(nid, str) and nid.startswith("C_"):
            sym = nid.replace("C_", "", 1)
        ex = _static_map.get(sym, "")
    if not ex:
        return None
    if ex in ("HOSE", "HNX", "UPCOM"):
        return ex
    return None


def _listed_company_ids(session):
    """Tập id Entity công ty (C_) đang niêm yết HOSE/HNX/UPCOM."""
    q = """
    MATCH (n:Entity) WHERE n.id STARTS WITH 'C_'
    RETURN n.id AS nid, n.symbol AS symbol, n.exchange AS exchange
    """
    out = set()
    for rec in session.run(q):
        if _resolve_vn_listing(rec.get("exchange"), rec.get("symbol"), rec.get("nid")):
            out.add(rec["nid"])
    return out


def _append_graph_edge(nodes, links, n, m, r, seen_pairs, mode_persons_dedupe):
    """Thêm một cạnh và hai node vào nodes/links."""
    n_props = dict(n)
    m_props = dict(m)
    n_id = n_props.get("id", str(getattr(n, "element_id", "")))
    m_id = m_props.get("id", str(getattr(m, "element_id", "")))
    if mode_persons_dedupe:
        pair = tuple(sorted([n_id, m_id]))
        if pair in seen_pairs:
            return
        seen_pairs.add(pair)
    n_sym = n_props.get("symbol", "")
    m_sym = m_props.get("symbol", "")
    n_label = f"{n_props.get('name', n_id)} ({n_sym})" if n_sym else (n_props.get("name") or n_id)
    m_label = f"{m_props.get('name', m_id)} ({m_sym})" if m_sym else (m_props.get("name") or m_id)
    nodes[n_id] = {"id": n_id, "label": n_label, "group": n_props.get("type", "DEFAULT")}
    nodes[m_id] = {"id": m_id, "label": m_label, "group": m_props.get("type", "DEFAULT")}
    rel_label = _relationship_display_label(r)
    try:
        inf = bool(dict(r).get("inferred", False))
    except Exception:
        inf = False
    links.append(
        {
            "from": n_id,
            "to": m_id,
            "label": rel_label,
            "dashes": inf,
            "inferred": inf,
        }
    )


# Một lần tải toàn bộ subgraph (không phân trang); giới hạn cạnh để tránh treo trình duyệt
GRAPH_MAX_EDGES = min(100000, max(500, int(os.getenv("GRAPH_MAX_EDGES", "25000"))))


@app.route("/api/graph", methods=["GET"])
def api_graph():
    mode = request.args.get("mode", "companies").lower()
    if mode not in ("companies", "persons"):
        mode = "companies"
    # persons: view=leaders (mặc định) = lãnh đạo cao nhất tại công ty listed; view=full = toàn bộ subgraph person
    view = (request.args.get("view") or "leaders").lower()
    if mode == "persons" and view not in ("leaders", "full"):
        view = "leaders"

    try:
        lim = min(GRAPH_MAX_EDGES, max(100, int(request.args.get("limit", GRAPH_MAX_EDGES))))
    except ValueError:
        lim = GRAPH_MAX_EDGES

    with neo4j_driver.session() as session:
        nodes = {}
        links = []
        seen_pairs = set()
        total_edges_db = 0

        if mode == "companies":
            listed = list(_listed_company_ids(session))
            if not listed:
                total_edges_db = 0
            else:
                count_q = """
                MATCH (n:Entity)-[r]->(m:Entity)
                WHERE n.id IN $listed AND m.id IN $listed
                RETURN count(r) AS ecnt
                """
                cr = session.run(count_q, listed=listed).single()
                total_edges_db = int(cr["ecnt"]) if cr and cr.get("ecnt") is not None else 0
                data_q = """
                MATCH (n:Entity)-[r]->(m:Entity)
                WHERE n.id IN $listed AND m.id IN $listed
                RETURN n, r, m
                LIMIT $lim
                """
                result = session.run(data_q, listed=listed, lim=lim)
                for record in result:
                    n, m, r = record["n"], record["m"], record["r"]
                    n_props, m_props = dict(n), dict(m)
                    if not _is_company(n_props) or not _is_company(m_props):
                        continue
                    _append_graph_edge(nodes, links, n, m, r, seen_pairs, False)
                # Hiển thị mọi mã listed dưới dạng node (kể cả chưa có cạnh C–C tới listed khác trong KG)
                missing_ids = [nid for nid in listed if nid not in nodes]
                if missing_ids:
                    _batch = 500
                    for _off in range(0, len(missing_ids), _batch):
                        sub = missing_ids[_off : _off + _batch]
                        q_iso = """
                        MATCH (n:Entity) WHERE n.id IN $ids
                        RETURN n
                        """
                        for rec in session.run(q_iso, ids=sub):
                            np = dict(rec["n"])
                            if not _is_company(np):
                                continue
                            nid = np.get("id")
                            if not nid or nid in nodes:
                                continue
                            sym = np.get("symbol", "")
                            lab = (
                                f"{np.get('name', nid)} ({sym})"
                                if sym
                                else (np.get("name") or nid)
                            )
                            nodes[nid] = {
                                "id": nid,
                                "label": lab,
                                "group": np.get("type", "DEFAULT"),
                            }

        elif mode == "persons" and view == "full":
            count_q = """
            MATCH (n:Entity)-[r]->(m:Entity)
            WHERE (n.id STARTS WITH 'P_' OR n.type = 'Person'
               OR m.id STARTS WITH 'P_' OR m.type = 'Person')
            RETURN count(r) AS ecnt
            """
            data_q = """
            MATCH (n:Entity)-[r]->(m:Entity)
            WHERE (n.id STARTS WITH 'P_' OR n.type = 'Person'
               OR m.id STARTS WITH 'P_' OR m.type = 'Person')
            RETURN n, r, m
            LIMIT $lim
            """
            cr = session.run(count_q).single()
            total_edges_db = int(cr["ecnt"]) if cr and cr.get("ecnt") is not None else 0
            result = session.run(data_q, lim=lim)
            for record in result:
                n, m, r = record["n"], record["m"], record["r"]
                _append_graph_edge(nodes, links, n, m, r, seen_pairs, True)

        else:
            # persons + leaders: một (ưu tiên) lãnh đạo / công ty listed
            listed = list(_listed_company_ids(session))
            rels = LEADER_RELS
            if not listed:
                total_edges_db = 0
            else:
                count_q = """
                MATCH (p:Entity)-[r]->(c:Entity)
                WHERE c.id IN $listed AND type(r) IN $rels
                RETURN count(r) AS ecnt
                """
                cr = session.run(count_q, listed=listed, rels=rels).single()
                total_edges_db = int(cr["ecnt"]) if cr and cr.get("ecnt") is not None else 0
                data_q = """
                MATCH (p:Entity)-[r]->(c:Entity)
                WHERE c.id IN $listed AND type(r) IN $rels
                RETURN p, r, c
                LIMIT $lim
                """
                raw_rows = list(
                    session.run(data_q, listed=listed, rels=rels, lim=min(lim, 500000))
                )
                best_by_company = {}
                for record in raw_rows:
                    p, r, c = record["p"], record["r"], record["c"]
                    c_props = dict(c)
                    cid = c_props.get("id")
                    if not cid:
                        continue
                    try:
                        rt = r.type
                    except Exception:
                        rt = ""
                    pri = rels.index(rt) if rt in rels else 99
                    cur = best_by_company.get(cid)
                    if cur is None or pri < cur[0]:
                        best_by_company[cid] = (pri, p, r, c)
                if not best_by_company:
                    # Neo4j có thể chưa có cạnh LÃNH_ĐẠO_* — fallback: cổ đông cá nhân có ownership cao nhất / công ty listed
                    count_fb = """
                    MATCH (p:Entity)-[r:LÀ_CỔ_ĐÔNG_CỦA]->(c:Entity)
                    WHERE c.id IN $listed AND (p.id STARTS WITH 'P_' OR p.type = 'Person')
                    RETURN count(r) AS ecnt
                    """
                    cr_fb = session.run(count_fb, listed=listed).single()
                    total_edges_db = int(cr_fb["ecnt"]) if cr_fb and cr_fb.get("ecnt") is not None else 0
                    fb_q = """
                    MATCH (p:Entity)-[r:LÀ_CỔ_ĐÔNG_CỦA]->(c:Entity)
                    WHERE c.id IN $listed AND (p.id STARTS WITH 'P_' OR p.type = 'Person')
                    RETURN p, r, c
                    LIMIT $lim
                    """
                    fb_rows = list(session.run(fb_q, listed=listed, lim=min(lim, 500000)))
                    best_sh = {}
                    for record in fb_rows:
                        p, r, c = record["p"], record["r"], record["c"]
                        cid = dict(c).get("id")
                        if not cid:
                            continue
                        try:
                            ow = float(dict(r).get("ownership") or 0)
                        except (TypeError, ValueError):
                            ow = 0.0
                        cur = best_sh.get(cid)
                        if cur is None or ow > cur[0]:
                            best_sh[cid] = (ow, p, r, c)
                    for _cid, tup in best_sh.items():
                        _ow, p, r, c = tup
                        _append_graph_edge(nodes, links, p, c, r, seen_pairs, False)
                else:
                    for _cid, tup in best_by_company.items():
                        _pri, p, r, c = tup
                        _append_graph_edge(nodes, links, p, c, r, seen_pairs, False)

        total_nodes = len(nodes)

    response = jsonify(
        {
            "nodes": list(nodes.values()),
            "edges": links,
            "total": total_nodes,
            "total_edges": total_edges_db,
            "pagination_row_count": total_edges_db,
            "current_page": 1,
            "page_size": lim,
            "loaded_edges": len(links),
            "truncated": total_edges_db > len(links),
            "view": view if mode == "persons" else None,
        }
    )
    response.headers["Cache-Control"] = "public, max-age=60"
    return response

# ==================== CRAWL API ENDPOINTS ====================

def _run_crawl(symbols=None, skip_individuals=False):
    """Chạy crawl pipeline trong background thread."""
    global _crawl_progress
    _crawl_progress = {
        "running": True,
        "step": "Khởi động pipeline...",
        "message": "Đang bắt đầu crawl dữ liệu mới",
        "total_nodes": 0,
        "total_edges": 0,
        "symbols_crawled": 0,
        "error": None
    }
    try:
        _crawl_progress["step"] = "Crawling Fireant API..."
        _crawl_progress["message"] = "Đang crawl dữ liệu từ Fireant API..."

        result = crawl_and_update(
            symbols=symbols,
            skip_individuals=skip_individuals,
            push_neo4j=True,
            neo4j_driver=neo4j_driver,
            run_inference=True
        )

        _crawl_progress["running"] = False
        _crawl_progress["step"] = "Hoàn tất!"
        msg = f"Crawl thành công: {result.get('nodes_count', 0)} nodes, {result.get('edges_count', 0)} edges"
        if not result.get("neo4j_pushed") and result.get("nodes_count", 0) == 0:
            msg += " — Không có dữ liệu preprocess mới (API có thể đã crawl hết; thử POST /api/crawl/start với {\"symbols\":[\"ACB\"]})"
        _crawl_progress["message"] = msg
        _crawl_progress["total_nodes"] = result.get('nodes_count', 0)
        _crawl_progress["total_edges"] = result.get('edges_count', 0)
        _crawl_progress["symbols_crawled"] = result.get('crawled_symbols', 0)
        try:
            _lc_path = os.path.join(os.path.dirname(__file__), "data", "last_crawl_success.json")
            os.makedirs(os.path.dirname(_lc_path), exist_ok=True)
            with open(_lc_path, "w", encoding="utf-8") as _lf:
                json.dump(
                    {
                        "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "nodes_count": result.get("nodes_count", 0),
                        "edges_count": result.get("edges_count", 0),
                        "neo4j_pushed": result.get("neo4j_pushed", False),
                        "message": msg,
                    },
                    _lf,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as _le:
            print(f"⚠️ Ghi last_crawl_success.json: {_le}")

    except Exception as e:
        _crawl_progress["running"] = False
        _crawl_progress["step"] = "Lỗi!"
        _crawl_progress["message"] = f"Lỗi crawl: {str(e)}"
        _crawl_progress["error"] = str(e)
        import traceback
        traceback.print_exc()

@app.route("/api/crawl/start", methods=["POST"])
def api_crawl_start():
    """Trigger crawl pipeline."""
    global _crawl_progress
    if _crawl_progress.get("running"):
        return jsonify({"error": "Crawl đang chạy, vui lòng đợi"}), 400

    data = request.json or {}
    symbols = data.get("symbols")  # None = crawl all
    skip_individuals = data.get("skip_individuals", False)

    thread = threading.Thread(
        target=_run_crawl,
        args=(symbols, skip_individuals),
        daemon=True
    )
    thread.start()

    return jsonify({"status": "started", "message": "Crawl pipeline đã khởi động"})

def _read_last_crawl_success():
    try:
        p = os.path.join(os.path.dirname(__file__), "data", "last_crawl_success.json")
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


@app.route("/api/crawl/progress", methods=["GET"])
def api_crawl_progress():
    """Lấy tiến trình crawl + lần thành công gần nhất (file)."""
    out = dict(_crawl_progress)
    ls = _read_last_crawl_success()
    if ls:
        out["last_success"] = ls
    return jsonify(out)

@app.route("/api/stats", methods=["GET"])
def api_stats():
    """Lấy thống kê hiện tại của KG.

    inferred_relationships: số *cạnh* có coalesce(r.inferred,false)=true (không phải số node).
    Nếu = 0: chưa chạy suy luận trên Neo4j hoặc không có pattern thỏa điều kiện (xem inference_rules.py).
    Để tạo quan hệ ẩn: POST /api/inference hoặc POST /api/inference/run, hoặc crawl với run_inference=True.
    """
    with neo4j_driver.session() as session:
        node_count = session.run("MATCH (n) RETURN count(n) as cnt").single()["cnt"]
        edge_count = session.run("MATCH ()-[r]->() RETURN count(r) as cnt").single()["cnt"]
        company_count = session.run("MATCH (n:Entity) WHERE n.id =~ 'C_.*' RETURN count(n) as cnt").single()["cnt"]
        person_count = session.run("MATCH (n:Entity) WHERE n.id =~ 'P_.*' OR n.type = 'Person' RETURN count(n) as cnt").single()["cnt"]
        inferred_rel_count = session.run(
            "MATCH ()-[r]->() WHERE coalesce(r.inferred, false) = true RETURN count(r) AS cnt"
        ).single()["cnt"]
        inferred_nodes_rec = session.run(
            """
            MATCH (a)-[r]->(b) WHERE coalesce(r.inferred, false) = true
            WITH collect(DISTINCT a) + collect(DISTINCT b) AS nodes
            UNWIND nodes AS n
            RETURN count(DISTINCT n) AS cnt
            """
        ).single()
        inferred_node_count = inferred_nodes_rec["cnt"] if inferred_nodes_rec else 0
    return jsonify({
        "total_nodes": node_count,
        "total_edges": edge_count,
        "companies": company_count,
        "persons": person_count,
        "inferred_relationships": inferred_rel_count,
        "inferred_nodes": inferred_node_count,
    })

@app.route("/api/search", methods=["GET"])
def api_search():
    """Search for entities by name."""
    query = request.args.get("q", "").strip()
    if not query or len(query) < 2:
        return jsonify({"results": []})
    
    limit = int(request.args.get("limit", 20))
    with neo4j_driver.session() as session:
        q = """
        MATCH (n:Entity)
        WHERE toLower(n.name) CONTAINS toLower($q)
           OR toLower(n.symbol) CONTAINS toLower($q)
           OR toLower(n.id) CONTAINS toLower($q)
        RETURN n.id AS id, n.name AS label, n.symbol AS symbol, n.type AS type
        ORDER BY 
            CASE 
                WHEN toLower(n.name) STARTS WITH toLower($q) THEN 1
                WHEN toLower(n.symbol) STARTS WITH toLower($q) THEN 2
                ELSE 3
            END,
            n.name
        LIMIT $limit
        """
        result = session.run(q, q=query, limit=limit)
        results = []
        for rec in result:
            label = rec["label"] or rec["id"]
            if rec.get("symbol"):
                label = f"{label} ({rec['symbol']})"
            results.append({
                "id": rec["id"],
                "label": label,
                "type": rec["type"] or "Entity"
            })
    
    return jsonify({"results": results})




@app.route("/api/inference/run", methods=["POST"])
def api_run_inference():
    """Trigger manual inference run."""
    from inference_rules import run_all_inference_rules
    results = run_all_inference_rules(neo4j_driver, batch_size=500)
    return jsonify({"status": "complete", **results})


@app.route("/api/inference", methods=["POST"])
def api_inference_alias():
    """Backward-compatible alias for inference endpoint."""
    return api_run_inference()


@app.route("/api/inferred-relations", methods=["GET"])
def api_inferred_relations():
    """Get all inferred relations with stats."""
    from flask import request
    level = request.args.get("level")  # optional filter: LOW/MEDIUM/HIGH
    with neo4j_driver.session() as session:
        if level:
            q = """
            MATCH (a)-[r]->(b)
            WHERE r.inferred = true AND r.influence_level = $level
            RETURN a.id AS source, a.name AS source_name,
                   b.id AS target, b.name AS target_name,
                   r.label AS relation, r.indirect_ownership_pct AS ownership,
                   r.influence_level AS level, r.inferred_from AS rule
            ORDER BY r.indirect_ownership_pct DESC LIMIT 200
            """
            result = session.run(q, level=level)
        else:
            q = """
            MATCH (a)-[r]->(b)
            WHERE r.inferred = true
            RETURN a.id AS source, a.name AS source_name,
                   b.id AS target, b.name AS target_name,
                   r.label AS relation, r.indirect_ownership_pct AS ownership,
                   r.influence_level AS level, r.inferred_from AS rule
            ORDER BY r.indirect_ownership_pct DESC LIMIT 200
            """
            result = session.run(q)
        relations = [dict(r) for r in result]

    # Stats
    with neo4j_driver.session() as session:
        q = """
        MATCH ()-[r]->() WHERE r.inferred = true
        RETURN count(r) AS total,
               count(CASE WHEN r.influence_level = 'LOW' THEN 1 END) AS low,
               count(CASE WHEN r.influence_level = 'MEDIUM' THEN 1 END) AS medium,
               count(CASE WHEN r.influence_level = 'HIGH' THEN 1 END) AS high
        """
        stats_rec = session.run(q).single()
        stats = dict(stats_rec) if stats_rec else {"total": 0, "low": 0, "medium": 0, "high": 0}

    return jsonify({"relations": relations, "stats": stats})

@app.route("/api/rules", methods=["GET"])
def api_rules():
    """Returns the logic rules of the system."""
    rules = [
        {
            "id": "R01",
            "name": "Gộp sở hữu vợ chồng",
            "logic": "A -[VỢ_CHỒNG]- B, A/B cùng -[LÀ_CỔ_ĐÔNG_CỦA]-> C",
            "inferred": "A -[KIỂM_SOÁT_GIA_ĐÌNH]-> C",
            "explanation": "Nếu hai vợ chồng cùng nắm cổ phần tại một doanh nghiệp, hệ thống cộng tỷ lệ sở hữu để nhận diện mức kiểm soát gia đình thay vì nhìn từng cá nhân riêng lẻ.",
            "example": "Ông A nắm 18% và bà B nắm 12% tại Công ty C. Hệ thống suy ra gia đình A-B có 30% ảnh hưởng tại C.",
            "legal_refs": [
                {
                    "title": "Thông tư 96/2020/TT-BTC - Hướng dẫn công bố thông tin trên thị trường chứng khoán",
                    "url": "https://vanban.chinhphu.vn/default.aspx?docid=201902&pageid=27160"
                },
                {
                    "title": "Nghị định 168/2025/NĐ-CP - Về đăng ký doanh nghiệp",
                    "url": "https://vanban.chinhphu.vn/?docid=214334&pageid=27160"
                },
                {
                    "title": "Luật số 76/2025/QH15 - Luật sửa đổi, bổ sung một số điều của Luật Doanh nghiệp",
                    "url": "https://vanban.chinhphu.vn/?classid=1&docid=214562&pageid=27160&typegroupid=3"
                }
            ]
        },
        {
            "id": "R02",
            "name": "Sở hữu gián tiếp qua công ty con",
            "logic": "A -[LÀ_CỔ_ĐÔNG_CỦA:x]-> B, B/C có quan hệ công ty con với tỷ lệ y",
            "inferred": "A -[SỞ_HỮU_GIÁN_TIẾP:(x*y)]-> C",
            "explanation": "Khi A sở hữu B và B kiểm soát hoặc sở hữu công ty con C, hệ thống nhân chuỗi tỷ lệ để tính phần sở hữu gián tiếp của A tại C.",
            "example": "A nắm 40% ở B, còn B nắm 60% ở C. Hệ thống suy ra A sở hữu gián tiếp 24% ở C.",
            "legal_refs": [
                {
                    "title": "Luật số 54/2019/QH14 - Luật Chứng khoán",
                    "url": "https://vanban.chinhphu.vn/default.aspx?docid=198541&pageid=27160"
                },
                {
                    "title": "Thông tư 96/2020/TT-BTC - Hướng dẫn công bố thông tin trên thị trường chứng khoán",
                    "url": "https://vanban.chinhphu.vn/default.aspx?docid=201902&pageid=27160"
                }
            ]
        },
        {
            "id": "R07",
            "name": "Ảnh hưởng gián tiếp theo ngưỡng 5/25/50",
            "logic": "A -[r1]-> B, B/C có quan hệ công ty con với tỷ lệ sở hữu; tính tỷ lệ gián tiếp rồi phân loại mức ảnh hưởng",
            "inferred": "A -[CÓ_LỢI_ÍCH_GIÁN_TIẾP | ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI | KIỂM_SOÁT_GIÁN_TIẾP]-> C",
            "explanation": "Sau khi tính được tỷ lệ sở hữu gián tiếp, hệ thống gán nhãn theo ngưỡng pháp lý: từ 5% là lợi ích gián tiếp, từ 25% là ảnh hưởng đáng kể, từ 50% là kiểm soát.",
            "example": "A nắm 30% ở B, B nắm 51% ở C. Tỷ lệ gián tiếp của A ở C là 15.3%, nên hệ thống gán nhãn CÓ_LỢI_ÍCH_GIÁN_TIẾP.",
            "legal_refs": [
                {
                    "title": "Thông tư 96/2020/TT-BTC - Hướng dẫn công bố thông tin trên thị trường chứng khoán",
                    "url": "https://vanban.chinhphu.vn/default.aspx?docid=201902&pageid=27160"
                },
                {
                    "title": "Nghị định 168/2025/NĐ-CP - Về đăng ký doanh nghiệp",
                    "url": "https://vanban.chinhphu.vn/?docid=214334&pageid=27160"
                },
                {
                    "title": "Luật số 54/2019/QH14 - Luật Chứng khoán",
                    "url": "https://vanban.chinhphu.vn/default.aspx?docid=198541&pageid=27160"
                }
            ]
        },
        {
            "id": "R12",
            "name": "Liên kết qua cùng cổ đông lớn",
            "logic": "Một cá nhân là cổ đông >= 5% tại hai doanh nghiệp niêm yết khác nhau",
            "inferred": "Công ty X -[CÙNG_CỔ_ĐÔNG_LỚN]-> Công ty Y",
            "explanation": "Nếu cùng một cá nhân là cổ đông lớn ở hai công ty, hệ thống tạo liên kết để giúp phát hiện mạng lưới ảnh hưởng chéo giữa các doanh nghiệp.",
            "example": "Ông A nắm 8% ở X và 6% ở Y. Hệ thống suy ra X và Y có liên hệ qua cùng cổ đông lớn là ông A.",
            "legal_refs": [
                {
                    "title": "Thông tư 96/2020/TT-BTC - Hướng dẫn công bố thông tin trên thị trường chứng khoán",
                    "url": "https://vanban.chinhphu.vn/default.aspx?docid=201902&pageid=27160"
                },
                {
                    "title": "Luật số 54/2019/QH14 - Luật Chứng khoán",
                    "url": "https://vanban.chinhphu.vn/default.aspx?docid=198541&pageid=27160"
                }
            ]
        }
    ]
    return jsonify(rules)

@app.route("/api/vllm/models", methods=["GET"])
@app.route("/api/ollama/models", methods=["GET"])
def api_llm_models():
    """Danh sách model: Ollama /api/tags hoặc OpenAI-compatible /v1/models (vLLM)."""
    models = []
    try:
        if LLM_BACKEND in ("openai", "vllm", "openai_compat"):
            r = requests.get(f"{LLM_BASE_URL}/v1/models", timeout=8)
            r.raise_for_status()
            models = [m["id"] for m in r.json().get("data", []) if m.get("id")]
        else:
            r = requests.get(f"{LLM_BASE_URL}/api/tags", timeout=8)
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", []) if m.get("name")]
    except Exception as ex:
        print(f"[LLM] models list error: {ex}")
        models = []
    if not models:
        models = [MODEL_NAME]
    return jsonify({"models": models, "current": MODEL_NAME, "backend": LLM_BACKEND})


@app.route('/api/query', methods=['POST'])
def api_query():
    print("\n--- Nhận Query Mới (Agentic Mode) ---")
    data = request.json
    query_text = data.get("query", "")
    history = data.get("history", [])
    if not query_text:
        return jsonify({"error": "Query rỗng"}), 400

    model = (data.get("model") or "").strip() or MODEL_NAME
    reasoning_enabled = data.get("reasoning", True)
    if reasoning_enabled:
        steps = ["Bắt đầu xử lý truy vấn (Reasoning: Bật)"]
    else:
        steps = ["Bắt đầu xử lý truy vấn (Reasoning: Tắt)"]

    # --- Bước 1: Phát hiện entity mục tiêu ---
    target_entity_id, target_display = extract_target_entity(query_text)
    if target_entity_id:
        steps.append(f"🔍 Phát hiện thực thể: {target_display} ({target_entity_id})")
    else:
        steps.append("🔍 Không phát hiện thực thể cụ thể, dùng tìm kiếm từ khóa.")

    # --- Bước 2: Semantic Search (RAG) ---
    steps.append("⏳ Đang tìm kiếm ngữ nghĩa trong Vector DB (RAG)...")
    from llmware.library import Library
    from llmware.retrieval import Query as LWQuery
    contexts = []
    try:
        retriever = Library().load_library("kg_demo_vn")
        search_results = LWQuery(retriever).semantic_query(query_text, result_count=5)
        for res in search_results:
            txt = res.get("text", "").strip()
            if txt: contexts.append(txt)
        steps.append(f"✅ Tìm thấy {len(contexts)} đoạn văn bản liên quan.")
    except Exception as e:
        steps.append(f"⚠️ Lỗi tìm kiếm semantic: {str(e)}")

    # --- Bước 3: Graph Search (Agentic Loop) ---
    steps.append("⏳ Đang truy vấn Knowledge Graph (Neo4j)...")
    nodes_dict = {}
    edges = []
    graph_context = []
    cypher_used = ""

    def execute_cypher(cypher_str, params=None):
        import traceback
        nonlocal cypher_used
        cypher_used += f"\n\n{cypher_str}"
        try:
            with neo4j_driver.session() as session:
                res = session.run(cypher_str, **(params or {}))
                recs = list(res)
                print(f"[Neo4j] Query trả về {len(recs)} rows")
                for rec in recs:
                    keys = list(rec.keys())
                    if "source_id" in keys and "target_id" in keys:
                        s_id, s_name = rec["source_id"], rec["source_name"]
                        t_id, t_name = rec["target_id"], rec["target_name"]
                        s_sym = rec.get("source_symbol")
                        t_sym = rec.get("target_symbol")
                        s_display = f"{s_name} ({s_sym})" if s_sym else (s_name or s_id)
                        t_display = f"{t_name} ({t_sym})" if t_sym else (t_name or t_id)
                        s_grp = rec["source_group"] if "source_group" in keys else "DEFAULT"
                        t_grp = rec["target_group"] if "target_group" in keys else "DEFAULT"
                        e_label = rec["edge_label"] if "edge_label" in keys else ""
                        inf = rec["inferred"] if "inferred" in keys else False
                        nodes_dict[s_id] = {"id": s_id, "label": s_display, "group": s_grp}
                        nodes_dict[t_id] = {"id": t_id, "label": t_display, "group": t_grp}
                        edges.append({"from": s_id, "to": t_id, "label": e_label, "dashes": bool(inf)})
                        ctx_line = f"{s_display} --[{e_label}]--> {t_display}"
                        if e_label == "LÀ_CỔ_ĐÔNG_CỦA" or (e_label and "CỔ_ĐÔNG" in e_label):
                            sh = rec.get("sh")
                            ow = rec.get("ow")
                            bits = []
                            if sh is not None:
                                try:
                                    bits.append(f"số_CP={int(float(sh))}")
                                except (TypeError, ValueError):
                                    bits.append(f"số_CP={sh}")
                            if ow is not None:
                                try:
                                    bits.append(f"tỷ_lệ={float(ow) * 100:.4f}%")
                                except (TypeError, ValueError):
                                    pass
                            if bits:
                                ctx_line = f"{s_display} --[{e_label}; {', '.join(bits)}]--> {t_display}"
                        graph_context.append(ctx_line)
                    elif "n" in keys:
                        n = rec["n"]
                        nid = n.get("id", str(n.element_id))
                        nodes_dict[nid] = {"id": nid, "label": n.get("name", nid), "group": n.get("type", "DEFAULT")}
                return len(recs)
        except Exception as e:
            print(f"[Neo4j] Cypher Error: {e}\n{traceback.format_exc()}")
            return 0

    # Lượt 1: Fast Path (WITH tách rõ để tránh lỗi "RETURN only at end" trên Neo4j 5)
    if target_entity_id:
        q_out = """
        MATCH (n:Entity {id: $eid})-[r]->(m:Entity)
        WITH n, m, r
        ORDER BY CASE r.label WHEN 'LÃNH_ĐẠO_CAO_NHẤT' THEN 1 WHEN 'CHỦ_TỊCH_HĐQT' THEN 2 WHEN 'TỔNG_GIÁM_ĐỐC' THEN 3 WHEN 'LÀ_CÔNG_TY_CON_CỦA' THEN 4 ELSE 5 END
        LIMIT 150
        RETURN n.id AS source_id, n.name AS source_name, n.type AS source_group, n.symbol AS source_symbol,
               m.id AS target_id, m.name AS target_name, m.type AS target_group, m.symbol AS target_symbol,
               r.label AS edge_label, r.inferred AS inferred, r.shares AS sh, r.ownership AS ow
        """
        q_in = """
        MATCH (n:Entity)-[r]->(m:Entity {id: $eid})
        WITH n, m, r
        ORDER BY CASE r.label WHEN 'LÃNH_ĐẠO_CAO_NHẤT' THEN 1 WHEN 'CHỦ_TỊCH_HĐQT' THEN 2 WHEN 'TỔNG_GIÁM_ĐỐC' THEN 3 WHEN 'CÓ_CÔNG_TY_CON' THEN 4 ELSE 5 END
        LIMIT 150
        RETURN n.id AS source_id, n.name AS source_name, n.type AS source_group, n.symbol AS source_symbol,
               m.id AS target_id, m.name AS target_name, m.type AS target_group, m.symbol AS target_symbol,
               r.label AS edge_label, r.inferred AS inferred, r.shares AS sh, r.ownership AS ow
        """
        print(f"[Neo4j] Chạy q_out cho entity: {target_entity_id}")
        execute_cypher(q_out.strip(), {"eid": target_entity_id})
        print(f"[Neo4j] Chạy q_in cho entity: {target_entity_id}")
        execute_cypher(q_in.strip(), {"eid": target_entity_id})
    else:
        tokens = [w for w in query_text.split() if len(w) > 3]
        for kw in tokens[:2]:
            q = "MATCH (n:Entity)-[r]->(m:Entity) WHERE toLower(n.name) CONTAINS toLower($kw) OR toLower(m.name) CONTAINS toLower($kw) RETURN n.id as source_id, n.name as source_name, n.type as source_group, n.symbol as source_symbol, m.id as target_id, m.name as target_name, m.type as target_group, m.symbol as target_symbol, r.label as edge_label, r.inferred as inferred, r.shares AS sh, r.ownership AS ow LIMIT 50"
            execute_cypher(q, {"kw": kw})

    # Bổ sung top cổ đông (số CP) cho công ty mục tiêu — LLM dùng để trả lời xếp hạng
    if target_entity_id and str(target_entity_id).startswith("C_"):
        try:
            with neo4j_driver.session() as session:
                sh_rows = list(
                    session.run(
                        """
                        MATCH (p:Entity)-[r:LÀ_CỔ_ĐÔNG_CỦA]->(c:Entity {id: $eid})
                        WHERE coalesce(toFloat(r.shares), 0) > 0
                        RETURN coalesce(p.name, p.id) AS pname, r.shares AS sh, r.ownership AS ow
                        ORDER BY toFloat(r.shares) DESC
                        LIMIT 20
                        """,
                        eid=target_entity_id,
                    )
                )
            if sh_rows:
                steps.append(f"📊 Đã nạp top {len(sh_rows)} cổ đông (số cổ phiếu) cho công ty mục tiêu.")
                graph_context.append(
                    "--- Top cổ đông theo số cổ phiếu (Neo4j; dùng để trả lời top N / xếp hạng) ---"
                )
                for i, rec in enumerate(sh_rows, 1):
                    pname = rec["pname"] or ""
                    sh = rec["sh"]
                    ow = rec.get("ow")
                    try:
                        sh_i = int(float(sh))
                    except (TypeError, ValueError):
                        sh_i = sh
                    line = f"{i}. {pname}: {sh_i} cổ phiếu"
                    if ow is not None:
                        try:
                            line += f" ({float(ow) * 100:.4f}% vốn)"
                        except (TypeError, ValueError):
                            pass
                    graph_context.append(line)
        except Exception as _ex:
            steps.append(f"⚠️ Không nạp bảng cổ đông: {_ex}")

    # Lượt 2: Agentic Mode (LLM sinh Cypher theo câu hỏi)
    if reasoning_enabled:
        steps.append("🧠 Agentic (Bật): Yêu cầu AI tự viết Cypher chuyên sâu hơn...")
        hist_ctx = "\n".join([f"{h['role']}: {h['content']}" for h in history[-2:]])
        gen_cypher = generate_cypher_with_llm(query_text, hist_ctx, NEO4J_SCHEMA, steps, model=model)
        if gen_cypher and all(x not in gen_cypher.upper() for x in ["DELETE", "DROP", "CREATE", "SET"]):
            count = execute_cypher(gen_cypher)
            steps.append(f"🔄 Đã chạy Agentic Cypher, gộp thêm {count} bản ghi.")

    steps.append(f"✅ Hoàn tất Graph search: {len(edges)} quan hệ.")
    print(f"[Graph] Đã thu thập {len(edges)} quan hệ, {len(graph_context)} dòng context.")

    # --- Xây graphs theo thực thể chính (multi-KG) ---
    main_entities = extract_main_entities(query_text, target_entity_id, target_display)
    seen = set()
    graphs = []
    for eid, elabel in main_entities:
        if eid in seen:
            continue
        seen.add(eid)
        nd, ed = _fetch_subgraph(eid)
        if nd:
            label = elabel
            if not label:
                label = nd.get(eid, {}).get("label", eid)
            graphs.append({"center": eid, "centerLabel": label, "nodes": list(nd.values()), "edges": ed})
    if not graphs:
        graphs = [{"center": None, "centerLabel": None, "nodes": list(nodes_dict.values()), "edges": edges}]

    # --- Bước 4: Tổng hợp LLM ---
    steps.append("🧠 Đang tổng hợp câu trả lời cuối cùng...")
    doc_text = "\n".join(contexts[:5])
    graph_text = "\n".join(list(set(graph_context))[:150])
    history_ctx = "\n".join([f"{h['role']}: {h['content']}" for h in history[-3:]])
    instruct = (
        "Bạn là trợ lý AI chuyên gia về các công ty đã niêm yết trên sàn chứng khoán Việt Nam. Trả lời bằng tiếng Việt, ngắn gọn, DỰA TRÊN DỮ LIỆU ĐƯỢC CUNG CẤP từ query của Neo4j.\n"
        "QUAN TRỌNG: Khi dữ liệu có mã chứng khoán trong ngoặc (VD: VCB, ACB, VIB), BẮT BUỘC dùng đúng mã đó. Ngân hàng TMCP Ngoại thương Việt Nam (VCB) KHÁC Ngân hàng TMCP Quốc tế Việt Nam (VIB). Không được nhầm lẫn.\n"
        "Nếu thấy nhiều người cùng tên, phân biệt qua công ty (VD: ông Nguyễn Văn A (VCB) vs ông Nguyễn Văn A (ACB)).\n"
        "Trong 1 công ty, người lãnh đạo cao nhất là Chủ tịch HĐQT (LÃNH_ĐẠO_CAO_NHẤT). Trích xuất đúng tên người tương ứng chức vụ.\n"
        "Khi hỏi về quan hệ của 1 người, trình bày người thân từ hướng người được hỏi.\n"
        "Khi hỏi top cổ đông / khối lượng cổ phiếu: bắt buộc dùng các dòng 'Top cổ đông' hoặc cạnh có số_CP trong Dữ liệu Graph. Không được nói không có dữ liệu nếu các dòng đó tồn tại.\n"
    )
    prompt = f"{instruct}\n\n=== Lịch sử ===\n{history_ctx}\n\n=== Dữ liệu Graph ===\n{graph_text}\n\n=== Tài liệu ===\n{doc_text}\n\nCâu hỏi: {query_text}"
    try:
        print("[LLM] Đang tổng hợp câu trả lời...")
        response = llm_inference(prompt, model=model)
    except Exception as e:
        print(f"[LLM] Lỗi tổng hợp: {e}")
        response = {"llm_response": f"[Lỗi: {e}]"}
    if isinstance(response, dict):
        ans = response.get("llm_response") or response.get("text") or str(response)
    elif isinstance(response, list) and response:
        ans = response[0].get("llm_response") or response[0].get("text") or str(response[0])
    else:
        ans = str(response)

    print("--- Trả kết quả ---")
    steps.append("🎉 Thành công.")
    payload = {
        "answer": ans.strip(),
        "nodes": list(nodes_dict.values()),
        "edges": edges,
        "graphs": graphs,
        "steps": steps,
        "cypher": cypher_used.strip()
    }
    return jsonify(payload)


@app.route("/api/node/<path:node_id>/neighbors", methods=["GET"])
def get_node_neighbors(node_id):
    """Get 1-hop neighbors of a node for lazy graph expansion."""
    limit = min(200, int(request.args.get("limit", 100)))
    nodes = {}
    edges = []
    try:
        with neo4j_driver.session() as session:
            # Outgoing edges
            q_out = """
            MATCH (n:Entity {id: $eid})-[r]->(m:Entity)
            WITH n, m, r LIMIT $lim
            RETURN n.id AS sid, n.name AS sname, n.type AS sgrp, n.symbol AS ssym,
                   m.id AS tid, m.name AS tname, m.type AS tgrp, m.symbol AS tsym,
                   r.label AS elabel, coalesce(r.inferred, false) AS inf
            """
            # Incoming edges
            q_in = """
            MATCH (n:Entity)-[r]->(m:Entity {id: $eid})
            WITH n, m, r LIMIT $lim
            RETURN n.id AS sid, n.name AS sname, n.type AS sgrp, n.symbol AS ssym,
                   m.id AS tid, m.name AS tname, m.type AS tgrp, m.symbol AS tsym,
                   r.label AS elabel, coalesce(r.inferred, false) AS inf
            """
            for rec in list(session.run(q_out, eid=node_id, lim=limit)) + list(session.run(q_in, eid=node_id, lim=limit)):
                s_sym = rec.get("ssym") or ""
                t_sym = rec.get("tsym") or ""
                s_label = f"{rec['sname']} ({s_sym})" if s_sym else (rec["sname"] or rec["sid"])
                t_label = f"{rec['tname']} ({t_sym})" if t_sym else (rec["tname"] or rec["tid"])
                nodes[rec["sid"]] = {"id": rec["sid"], "label": s_label, "group": rec["sgrp"] or "DEFAULT"}
                nodes[rec["tid"]] = {"id": rec["tid"], "label": t_label, "group": rec["tgrp"] or "DEFAULT"}
                edges.append({
                    "from": rec["sid"], "to": rec["tid"],
                    "label": rec["elabel"] or "",
                    "inferred": bool(rec["inf"]),
                    "dashes": bool(rec["inf"])
                })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"nodes": list(nodes.values()), "edges": edges})


@app.route("/api/stats/exchange", methods=["GET"])
def api_stats_exchange():
    """Exchange distribution of company nodes (by exchange property or static mapping)."""
    try:
        # Import static lists for fallback mapping
        from pipeline import HOSE, HNX, UPCOM
        _static_map = {}
        for _s in HOSE:
            _static_map.setdefault(_s, "HOSE")
        for _s in HNX:
            _static_map.setdefault(_s, "HNX")
        for _s in UPCOM:
            _static_map.setdefault(_s, "UPCOM")

        counts = {}
        with neo4j_driver.session() as session:
            q = """
            MATCH (n:Entity) WHERE n.id STARTS WITH 'C_'
            RETURN n.id AS nid, n.symbol AS symbol, n.exchange AS exchange
            """
            for rec in session.run(q):
                ex = (rec["exchange"] or "").strip().upper() if rec["exchange"] else ""
                if not ex or ex in ("", "NONE"):
                    sym = rec["symbol"] or ""
                    if not sym:
                        nid = rec["nid"] or ""
                        sym = nid.replace("C_", "", 1) if nid.startswith("C_") else ""
                    ex = _static_map.get(sym, "")
                if not ex:
                    ex = "Khác"
                counts[ex] = counts.get(ex, 0) + 1

        breakdown = sorted(
            [{"exchange": k, "count": v} for k, v in counts.items()],
            key=lambda x: -x["count"]
        )
        total = sum(r["count"] for r in breakdown)
        return jsonify({"breakdown": breakdown, "total": total})
    except Exception as e:
        return jsonify({"breakdown": [], "total": 0, "error": str(e)})


@app.route("/api/stats/top", methods=["GET"])
def api_stats_top():
    """Return top entities based on criteria."""
    criteria = request.args.get("criteria", "degree")
    try:
        with neo4j_driver.session() as session:
            if criteria == "shareholders":
                q = """
                MATCH (n)-[r:LÀ_CỔ_ĐÔNG_CỦA]->(c:Entity)
                RETURN c.id AS id, c.name AS name, count(r) AS value
                ORDER BY value DESC LIMIT 10
                """
                result = session.run(q)
            elif criteria == "subsidiaries":
                q_fwd = """
                MATCH (p:Entity)-[r:CÓ_CÔNG_TY_CON]->(c:Entity)
                WHERE p.id STARTS WITH 'C_' AND c.id STARTS WITH 'C_'
                RETURN p.id AS id, p.name AS name, count(r) AS value
                ORDER BY value DESC LIMIT 10
                """
                rows = list(session.run(q_fwd))
                if not rows:
                    q_rev = """
                    MATCH (c:Entity)-[r:LÀ_CÔNG_TY_CON_CỦA]->(p:Entity)
                    WHERE c.id STARTS WITH 'C_' AND p.id STARTS WITH 'C_'
                    RETURN p.id AS id, p.name AS name, count(r) AS value
                    ORDER BY value DESC LIMIT 10
                    """
                    result = session.run(q_rev)
                else:
                    result = iter(rows)
            elif criteria == "leadership":
                q = """
                MATCH (n:Entity)-[r]->(c:Entity)
                WHERE c.id STARTS WITH 'C_'
                  AND type(r) IN ['LÃNH_ĐẠO_CAO_NHẤT', 'CHỦ_TỊCH_HĐQT', 'TỔNG_GIÁM_ĐỐC']
                RETURN c.id AS id, c.name AS name, count(r) AS value
                ORDER BY value DESC LIMIT 10
                """
                result = session.run(q)
            elif criteria == "market_cap":
                # Proxy vốn hóa: tổng số cổ phiếu ghi nhận từ các cạnh cổ đông (khi chưa có marketCap trên node)
                q = """
                MATCH ()-[r:LÀ_CỔ_ĐÔNG_CỦA]->(c:Entity)
                WHERE c.id STARTS WITH 'C_' AND r.shares IS NOT NULL
                WITH c, sum(toFloat(r.shares)) AS total
                WHERE total > 0
                RETURN c.id AS id, c.name AS name, total AS value
                ORDER BY value DESC LIMIT 10
                """
                rows = list(session.run(q))
                if not rows:
                    q2 = """
                    MATCH ()-[r:LÀ_CỔ_ĐÔNG_CỦA]->(c:Entity)
                    WHERE c.id STARTS WITH 'C_' AND r.ownership IS NOT NULL
                    WITH c, sum(toFloat(r.ownership)) AS total
                    WHERE total > 0
                    RETURN c.id AS id, c.name AS name, total AS value
                    ORDER BY value DESC LIMIT 10
                    """
                    result = session.run(q2)
                else:
                    result = iter(rows)
            else:  # default: degree
                q = """
                MATCH (n:Entity)-[r]-()
                WHERE n.id STARTS WITH 'C_'
                RETURN n.id AS id, n.name AS name, count(r) AS value
                ORDER BY value DESC LIMIT 10
                """
                result = session.run(q)

            data = [
                {
                    "id": rec["id"],
                    "name": rec["name"],
                    "value": round(rec["value"], 4) if isinstance(rec["value"], float) else rec["value"],
                }
                for rec in result
            ]
            return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/node/<path:node_id>", methods=["GET"])

def get_node_details(node_id):
    with neo4j_driver.session() as session:
        props = {}
        target_name = None
        target_internal_id = None
        target_original_id = node_id
        
        def get_props_from_res(res):
            rec = res.single()
            if rec: return rec["props"], rec["node_id"], rec["n_name"]
            return None, None, None

        res = session.run("MATCH (n:Entity {id: $id}) RETURN properties(n) as props, elementId(n) as node_id, n.name as n_name", id=node_id)
        p, internal_id, name = get_props_from_res(res)
        
        if p is None:
            res = session.run("MATCH (n) WHERE elementId(n) = $eid RETURN properties(n) as props, elementId(n) as node_id, n.name as n_name", eid=node_id)
            p, internal_id, name = get_props_from_res(res)
            
        if p is None:
            try:
                int_id = int(node_id)
                res = session.run("MATCH (n) WHERE elementId(n) = $iid RETURN properties(n) as props, elementId(n) as node_id, n.name as n_name", iid=int_id)
                p, internal_id, name = get_props_from_res(res)
            except: pass

        if p is not None:
            props, target_name = p, name
            if "price" in props and props["price"] is not None:
                try: props["price"] = f"{float(props['price']):,.1f} K VNĐ"
                except: pass

            is_person = (props.get("type") == "Person" or
                         (isinstance(target_original_id, str) and target_original_id.startswith("P_")))
            is_company = (props.get("type") == "Company" or
                          (isinstance(target_original_id, str) and target_original_id.startswith("C_")))

            if is_company:
                has_relations = session.run(
                    """
                    MATCH (p:Entity {id: $nid})
                    OPTIONAL MATCH (p)-[r1:CÓ_CÔNG_TY_CON]->()
                    WITH p, count(r1) as sub_count
                    OPTIONAL MATCH ()-[r2:LÀ_CỔ_ĐÔNG_CỦA]->(p)
                    WHERE (r2.ownership IS NOT NULL AND toFloat(r2.ownership) > 0) OR (r2.shares IS NOT NULL AND toFloat(r2.shares) > 0)
                    RETURN sub_count, count(r2) as share_count
                    """, nid=target_original_id
                )
                rel_rec = has_relations.single()
                if rel_rec:
                    if rel_rec["sub_count"] and rel_rec["sub_count"] > 0:
                        props["Số công ty con"] = rel_rec["sub_count"]
                    if rel_rec["share_count"] and rel_rec["share_count"] > 0:
                        props["Số cổ đông"] = rel_rec["share_count"]

                # Fetch Chủ tịch HĐQT (LÃNH_ĐẠO_CAO_NHẤT)
                chairman_res = session.run(
                    """
                    MATCH (p:Entity)-[r:LÃNH_ĐẠO_CAO_NHẤT]->(c:Entity {id: $nid})
                    RETURN p.name as chairman_name LIMIT 1
                    """, nid=target_original_id
                )
                c_rec = chairman_res.single()
                if c_rec and c_rec["chairman_name"]:
                    props = {"Chủ tịch HĐQT": c_rec["chairman_name"], **props}

                top_sh = session.run(
                    """
                    MATCH (p:Entity)-[r:LÀ_CỔ_ĐÔNG_CỦA]->(c:Entity {id: $nid})
                    WHERE coalesce(toFloat(r.shares), 0) > 0
                    RETURN coalesce(p.name, p.id) AS pname, r.shares AS sh, r.ownership AS ow
                    ORDER BY toFloat(r.shares) DESC
                    LIMIT 40
                    """,
                    nid=target_original_id,
                )
                top_lines = []
                for trec in top_sh:
                    pname = trec["pname"] or ""
                    sh = trec["sh"]
                    ow = trec.get("ow")
                    try:
                        sh_i = int(float(sh))
                    except (TypeError, ValueError):
                        sh_i = sh
                    row = f"{pname}: {sh_i} cổ phiếu"
                    if ow is not None:
                        try:
                            row += f" ({float(ow) * 100:.4f}% vốn)"
                        except (TypeError, ValueError):
                            pass
                    top_lines.append(row)
                if top_lines:
                    props["Top cổ đông (số cổ phiếu)"] = "\n".join(top_lines)

            if is_person:
                company_relations = []
                OFFICER_RELS = ["CHỦ_TỊCH_HĐQT", "TỔNG_GIÁM_ĐỐC", "PHÓ_CHỦ_TỊCH_HĐQT", "PHÓ_TỔNG_GIÁM_ĐỐC",
                                "THÀNH_VIÊN_HĐQT", "TRƯỞNG_BAN_KIỂM_SOÁT", "THÀNH_VIÊN_BAN_KIỂM_SOÁT",
                                "K_TOÁN_TRƯỞNG", "LÃNH_ĐẠO_CAO_NHẤT", "CHỦ_TỊCH_HỘI_ĐỒNG_THÀNH_VIÊN",
                                "GIÁM_ĐỐC_ĐIỀU_HÀNH", "PHÓ_GIÁM_ĐỐC_ĐIỀU_HÀNH"]
                FAMILY_RELS = ["ANH", "ANH_CHỊ", "BỐ", "CHA_MẸ", "CHỊ", "MẸ", "VỢ_CHỒNG", "ÔNG_NỘI", "BÀ_NỘI",
                              "NGƯỜI_THÂN", "BỐ_CHỒNG", "MẸ_CHỒNG", "BỐ_VỢ", "MẸ_VỢ", "CÔ", "CHÚ", "CẬU", "DÌ",
                              "EM_GÁI_CÙNG_BỐ_KHÁC_MẸ", "EM_TRAI_CÙNG_BỐ_KHÁC_MẸ", "ANH_RỂ", "CHỊ_DÂU", "CON_RỂ", "CON_DÂU"]

                q_fam = """
                    MATCH (p:Entity {id: $nid})-[r:LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO]->(c:Entity)
                    RETURN r.leaderRelationship AS rel
                    LIMIT 5
                """
                for rec in session.run(q_fam, nid=target_original_id):
                    if rec["rel"]:
                        company_relations.append(rec["rel"])

                q_sh = """
                    MATCH (p:Entity {id: $nid})-[r:LÀ_CỔ_ĐÔNG_CỦA]->(c:Entity)
                    WHERE c.id STARTS WITH 'C_' AND coalesce(toFloat(r.shares), 0) > 0
                    RETURN c.name AS cname, c.symbol AS sym, r.ownership AS ow, r.shares AS sh
                    ORDER BY toFloat(r.shares) DESC
                    LIMIT 40
                """
                share_lines = []
                for rec in session.run(q_sh, nid=target_original_id):
                    cname = rec["cname"] or ""
                    sym = f" ({rec['sym']})" if rec.get("sym") else ""
                    ow = rec.get("ow")
                    sh = rec.get("sh")
                    try:
                        sh_i = int(float(sh)) if sh is not None else None
                    except (TypeError, ValueError):
                        sh_i = None
                    part = f"{cname}{sym}: {sh_i if sh_i is not None else sh} cổ phiếu"
                    if ow is not None:
                        try:
                            part += f" ({float(ow)*100:.4f}% vốn)"
                        except (TypeError, ValueError):
                            pass
                    share_lines.append(part)
                    company_relations.append(f"Cổ đông: {part}")
                if share_lines:
                    props["Số cổ phiếu nắm giữ (theo công ty)"] = "\n".join(share_lines)

                q_pos = """
                    MATCH (p:Entity {id: $nid})-[r]->(c:Entity)
                    WHERE c.id =~ 'C_.*' AND type(r) IN $rels
                    RETURN type(r) AS pos, c.name AS cname, c.symbol AS sym
                    LIMIT 5
                """
                for rec in session.run(q_pos, nid=target_original_id, rels=OFFICER_RELS):
                    pos = (rec["pos"] or "").replace("_", " ")
                    cname = rec["cname"] or ""
                    sym = f" ({rec['sym']})" if rec.get("sym") else ""
                    company_relations.append(f"{pos}: {cname}{sym}")

                # Quan hệ gián tiếp: người thân của người có liên quan công ty
                if not company_relations:
                    q_indirect = """
                        MATCH (p:Entity {id: $nid})-[rf]-(q:Entity)
                        WHERE type(rf) IN $frels AND q <> p
                        MATCH (q)-[rc]->(c:Entity)
                        WHERE c.id =~ 'C_.*'
                        AND (type(rc) IN $orels OR type(rc) = 'LÀ_CỔ_ĐÔNG_CỦA' OR type(rc) = 'LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO')
                        RETURN q.name AS qname, type(rc) AS rtype, c.name AS cname, c.symbol AS sym,
                               rc.leaderRelationship AS lr, rc.ownership AS ow
                        LIMIT 5
                    """
                    for rec in session.run(q_indirect, nid=target_original_id, frels=FAMILY_RELS, orels=OFFICER_RELS):
                        qname = rec["qname"] or "?"
                        cname = rec["cname"] or ""
                        sym = f" ({rec['sym']})" if rec.get("sym") else ""
                        lr = rec.get("lr")
                        rtype = rec["rtype"] or ""
                        ow = rec.get("ow")
                        if lr:
                            company_relations.append(f"Người thân của [{qname}]: {lr}")
                        elif rtype == "LÀ_CỔ_ĐÔNG_CỦA":
                            part = f"Người thân của [{qname}] - cổ đông {cname}{sym}"
                            if ow is not None:
                                part += f" ({float(ow)*100:.2f}%)"
                            company_relations.append(part)
                        else:
                            pos = rtype.replace("_", " ")
                            company_relations.append(f"Người thân của [{qname}] - {pos} tại {cname}{sym}")

                if company_relations:
                    props["Liên quan công ty"] = "; ".join(company_relations)

        return jsonify({"props": props})


if __name__ == "__main__":
    print("=== PIPELINE KNOWLEDGE GRAPH ===")
    # Cập nhật entity_map từ dữ liệu (chạy khi có kg_nodes.json)
    _kg_path = os.path.join(os.path.dirname(__file__), "data", "kg_data", "kg_nodes.json")
    if os.path.exists(_kg_path):
        try:
            import subprocess
            subprocess.run(
                [sys.executable, os.path.join(os.path.dirname(__file__), "scripts", "generate_entity_map.py")],
                cwd=os.path.dirname(__file__),
                check=False,
                capture_output=True,
                timeout=30
            )
        except Exception as e:
            print(f"⚠️ generate_entity_map (bỏ qua): {e}")
    has_new_files, library = process_new_files()
    if has_new_files:
        run_ner_and_relation_extraction(library)
        run_hidden_relation_inference_loop()
        print("Cập nhật KG hoàn tất!")
        
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)  # Ẩn "Running on" mặc định
    print("Khởi động Web UI tại http://localhost:5001")
    app.run(host="0.0.0.0", port=5001)