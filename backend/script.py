import os
import sys
import shutil
import json
import html
from datetime import datetime, timezone

from llmware.library import Library
from llmware.agents import LLMfx
from itertools import combinations
from flask import request, jsonify
from pipeline import crawl_and_update, FAMILY_RELS_WHITELIST
import threading

from app import runtime
from app.fireant_market import collect_fireant_market_data
from app.rule_catalog import (
    HIDDEN_RULE_QUERIES,
    RULES_API_PAYLOAD,
    hidden_relation_priority,
    influence_level_display_vi,
    inferred_edge_label_display_vi,
    law_display,
    normalize_vn_text,
)
from app.web import app

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

import re as _re
import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

BASE_DIR = runtime.BASE_DIR
DATA_DIR = runtime.DATA_DIR
DOCS_DIR = runtime.DOCS_DIR
RAG_LIBRARY_NAME = runtime.RAG_LIBRARY_NAME
neo4j_driver = runtime.neo4j_driver
_LEGACY_INFERRED_RULE_IDS_DONE = False


def _ensure_inferred_rule_ids_migrated():
    """Rewrite persisted inferred_from R07→R03, R12→R04 once per process."""
    global _LEGACY_INFERRED_RULE_IDS_DONE
    if _LEGACY_INFERRED_RULE_IDS_DONE:
        return
    from inference_rules import migrate_legacy_inferred_rule_ids

    migrate_legacy_inferred_rule_ids(neo4j_driver)
    _LEGACY_INFERRED_RULE_IDS_DONE = True


MODEL_NAME = runtime.MODEL_NAME
LLM_BACKEND = runtime.LLM_BACKEND
LLM_BASE_URL = runtime.LLM_BASE_URL
LLM_API_KEY = runtime.LLM_API_KEY
LLM_INFERENCE_TIMEOUT = runtime.LLM_INFERENCE_TIMEOUT
LIVE_NEWS_TIMEOUT = runtime.LIVE_NEWS_TIMEOUT
LIVE_NEWS_MAX_ITEMS = runtime.LIVE_NEWS_MAX_ITEMS
_ALLOWED_LLM_BACKENDS = runtime.ALLOWED_LLM_BACKENDS


def _sync_runtime_aliases():
    """Keep local compatibility aliases in sync after runtime settings change."""
    global MODEL_NAME, LLM_BACKEND, LLM_BASE_URL, LLM_API_KEY
    MODEL_NAME = runtime.MODEL_NAME
    LLM_BACKEND = runtime.LLM_BACKEND
    LLM_BASE_URL = runtime.LLM_BASE_URL
    LLM_API_KEY = runtime.LLM_API_KEY


def _mask_api_key(key: str) -> str:
    return runtime.mask_api_key(key)


def _fetch_remote_models():
    return runtime.fetch_remote_models()


def _write_env_docker_kv(updates: dict[str, str], remove_keys: set | None = None) -> None:
    runtime.write_env_docker_kv(updates, remove_keys=remove_keys)


def llm_inference(prompt: str, model: str | None = None) -> dict:
    return runtime.llm_inference(prompt, model=model)


def _normalize_vn_text(text):
    return normalize_vn_text(text)


def _law_display(rule_id):
    return law_display(rule_id)


def _hidden_relation_priority(relation):
    return hidden_relation_priority(relation)

# --- Cấu trúc Graph để LLM hiểu và tự sinh Cypher ---
NEO4J_SCHEMA = """
Các Nodes (Thực thể):
- (Entity): Có các thuộc tính: name (tên), type (loại: BANK, PERSON, COMPANY), id (mã định danh). Labels bổ sung: Person, Company.
- Công ty luôn có id bắt đầu bằng 'C_' (ví dụ: 'C_VIC', 'C_TCB'). Người luôn có id bắt đầu bằng 'P_' (ví dụ: 'P_123').
Các Relationships (Trọng tâm truy vấn):
- [:LÃNH_ĐẠO_CAO_NHẤT]: Người đứng đầu/Chủ tịch HĐQT của công ty. Luôn ưu tiên dùng cạnh này khi hỏi "Ai là lãnh đạo/chủ tịch/đứng đầu". (VD: (p:Entity)-[:LÃNH_ĐẠO_CAO_NHẤT]->(c:Entity {symbol: 'VIC'}))
- [:LÀ_CỔ_ĐÔNG_CỦA]: Người/tổ chức sở hữu cổ phần công ty. Có thuộc tính: `shares` (số CP), `ownership` (tỷ lệ sở hữu).
- [:CÓ_CÔNG_TY_CON]: Công ty con thực sự (type=0, sở hữu >50%). Khi hỏi về công ty con.
- [:CÓ_CÔNG_TY_LIÊN_KẾT]: Công ty liên kết (type=1, sở hữu 20-50%).
- [:LIÊN_DOANH_VỚI]: Liên doanh (type=2).
- [:ĐẦU_TƯ_VÀO]: Khoản đầu tư góp vốn (type=3).
- [:LÀ_CÔNG_TY_CON_CỦA]: Cạnh ngược của CÓ_CÔNG_TY_CON.
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
        ref_path = os.path.join(DOCS_DIR, "cypher_reference.md")
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
        response = llm_inference(
            prompt,
            model=use_model,
            max_tokens=runtime.LLM_CYPHER_MAX_TOKENS,
        )
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

    ingest_path = os.path.join(DATA_DIR, "ingest")
    processed_path = os.path.join(DATA_DIR, "processed")
    os.makedirs(ingest_path, exist_ok=True)
    os.makedirs(processed_path, exist_ok=True)

    new_files = os.listdir(ingest_path)
    if not new_files:
        print("✅ [Trạng thái]: Không có file mới trong thư mục ingest.")
        try:
            return False, Library().load_library(RAG_LIBRARY_NAME)
        except Exception:
            return False, None

    try:
        lib = Library().load_library(RAG_LIBRARY_NAME)
    except Exception:
        lib = Library().create_new_library(RAG_LIBRARY_NAME)
        
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
    q_norm = _normalize_vn_text(query_text)
    # Ngân hàng Quân Đội = MBB (không phải MIG bảo hiểm) — tránh alias entity_map cũ.
    if "ngan hang" in q_norm and "quan doi" in q_norm:
        if "bao hiem" not in q_norm and "mig" not in q_norm.split():
            mbb_id = ENTITY_MAP.get("mbb") or ENTITY_MAP.get("ngân hàng tmcp quân đội") or "C_MBB"
            return mbb_id, "Ngân hàng TMCP Quân Đội (MBB)"
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
                        WHERE toLower(ent.name) = $phrase
                           OR toLower(ent.id) = $phrase
                           OR toLower(ent.name) CONTAINS $phrase
                        RETURN ent.id as eid, ent.name as ename, ent.type as etype
                        ORDER BY
                            CASE
                                WHEN toLower(ent.name) = $phrase THEN 0
                                WHEN toLower(ent.id) = $phrase THEN 1
                                WHEN toLower(ent.name) STARTS WITH $phrase THEN 2
                                ELSE 3
                            END,
                            size(coalesce(ent.name, ent.id))
                        LIMIT 1
                        """, phrase=phrase
                    )
                    rec = res.single()
                    if rec:
                        return rec["eid"], rec["ename"]
    return None, None


@app.route("/")
def index():
    """HTML shell is served by the SPA (Nginx `kg-ui`); keep `/` for health checks."""
    return jsonify(
        service="kg-api",
        neo4j_browser_url=os.getenv(
            "NEO4J_BROWSER_URL", "http://localhost:7474"
        ).strip(),
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


def _dedupe_inferred_relation_rows(rows):
    """Mỗi cặp (source, target) chỉ giữ một quan hệ ẩn: ưu tiên nhãn mạnh hơn, rồi tỷ lệ."""
    best = {}
    for row in rows:
        s, t = row.get("source"), row.get("target")
        if not s or not t:
            continue
        rel = (row.get("relation") or "").strip()
        pri = _hidden_relation_priority(rel)
        own = row.get("ownership")
        try:
            own_f = float(own) if own is not None and own != "" else -1.0
        except (TypeError, ValueError):
            own_f = -1.0
        key = (s, t)
        prev = best.get(key)
        if prev is None:
            best[key] = (pri, own_f, row)
            continue
        p_pri, p_own, _ = prev
        if pri > p_pri or (pri == p_pri and own_f > p_own):
            best[key] = (pri, own_f, row)

    def _own_sort(r):
        try:
            return float(r.get("ownership") or 0)
        except (TypeError, ValueError):
            return 0.0

    out = [v[2] for v in best.values()]
    out.sort(
        key=lambda x: (
            -_hidden_relation_priority((x.get("relation") or "").strip()),
            -_own_sort(x),
        )
    )
    return out


def _dedupe_hidden_rule_records(records):
    """Cùng logic ưu tiên nhãn cho kết quả truy vấn theo tên luật (hidden rule)."""
    best = {}
    for rec in records:
        s_id = rec["source_id"]
        t_id = rec["target_id"]
        lbl = (rec.get("edge_label") or "").strip()
        pri = _hidden_relation_priority(lbl)
        pct = rec.get("indirect_pct")
        if pct is None:
            pct = rec.get("combined_pct")
        try:
            pf = float(pct) if pct is not None else -1.0
        except (TypeError, ValueError):
            pf = -1.0
        key = (s_id, t_id)
        prev = best.get(key)
        if prev is None:
            best[key] = (pri, pf, rec)
            continue
        p_pri, p_pf, _ = prev
        if pri > p_pri or (pri == p_pri and pf > p_pf):
            best[key] = (pri, pf, rec)
    return [v[2] for v in best.values()]


_RAG_STOPWORDS = {
    "co", "có", "nhung", "những", "nao", "nào", "la", "là", "cua", "của", "trong",
    "the", "thể", "thuc", "thực", "quan", "hệ", "quan hệ", "an", "ẩn", "gioi", "giới",
    "hay", "đây", "day", "theo", "cho", "biet", "biết", "ve", "về", "mot", "một",
    "tai", "tại", "giua", "giữa", "khong", "không", "coi", "hoi", "hỏi", "duoc", "được",
}

_LIVE_NEWS_SOURCES = [
    {"name": "Google News", "kind": "google", "site": None},
    {"name": "CafeF", "kind": "google", "site": "cafef.vn"},
    {"name": "Vietstock", "kind": "google", "site": "vietstock.vn"},
    {"name": "VnBusiness", "kind": "google", "site": "vnbusiness.vn"},
    {"name": "VnExpress Kinh doanh", "kind": "google", "site": "vnexpress.net"},
]

_PROJECT_DOMAIN_PHRASES = {
    "co dong",
    "lanh dao",
    "chu tich",
    "tong giam doc",
    "nguoi than",
    "cong ty con",
    "quan he an",
    "quan he huu",
    "so huu",
    "so huu gian tiep",
    "thi truong chung khoan",
    "chung khoan",
    "co phieu",
    "ma chung khoan",
    "niem yet",
    "khoi luong",
    "giao dich",
    "thanh khoan",
    "von hoa",
    "gia co phieu",
    "tang truong",
    "giam diem",
    "phien giao dich",
    "top tang",
    "mua ban",
    "hose",
    "hnx",
    "upcom",
    "vn-index",
    "vn index",
    "fireant",
    "neo4j",
    "rag",
    "kg",
}

# Câu hỏi thị trường / giao dịch — KG không có KLGD theo ngày; cần tin web.
_MARKET_LIVE_PHRASES = {
    "khoi luong",
    "giao dich",
    "thanh khoan",
    "von hoa",
    "gia co phieu",
    "tang truong",
    "giam diem",
    "phien giao dich",
    "top tang",
    "mua ban",
    "dat lenh",
    "vn-index",
    "vn index",
    "chi so",
    "thanh khoan cao",
    "thanh khoan thap",
}

_LIVE_NEWS_NOISE_TOKENS = _RAG_STOPWORDS | {
    "tin",
    "tuc",
    "news",
    "thi",
    "truong",
    "chung",
    "khoan",
    "viet",
    "nam",
    "hom",
    "nay",
    "moi",
    "nhat",
    "cho",
    "biet",
    "bao",
    "nhieu",
    "gi",
    "nao",
}

_ENTITY_NEWS_STOPWORDS = {
    "anh",
    "ba",
    "bank",
    "chi",
    "co",
    "company",
    "cong",
    "cp",
    "ctcp",
    "doan",
    "fund",
    "group",
    "hang",
    "holdings",
    "jsc",
    "nam",
    "ngan",
    "ong",
    "securities",
    "tap",
    "thi",
    "tmcp",
    "tong",
    "ty",
    "van",
    "viet",
}

_OUT_OF_SCOPE_REPLY = (
    "Mình chỉ hỗ trợ câu hỏi về công ty niêm yết, cổ đông, lãnh đạo, quan hệ sở hữu và tin chứng khoán Việt Nam."
)


def _is_live_market_query(query_text):
    """Câu hỏi cần dữ liệu thị trường/giao dịch thời gian thực (ngoài KG)."""
    q = _normalize_vn_text(query_text)
    if not q:
        return False
    if any(p in q for p in _MARKET_LIVE_PHRASES):
        return True
    if "hom nay" in q or "ngay hom nay" in q or _re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", q):
        if "chung khoan" in q or "co phieu" in q or "niem yet" in q:
            return True
    return False

for _rule in HIDDEN_RULE_QUERIES:
    _rule["name_norm"] = _normalize_vn_text(_rule["name"])


_LEADER_REL_TYPES = ["LÃNH_ĐẠO_CAO_NHẤT", "CHỦ_TỊCH_HĐQT", "TỔNG_GIÁM_ĐỐC", "PHÓ_TỔNG_GIÁM_ĐỐC"]

_STD_GRAPH_RETURN = """
       n.id AS source_id, n.name AS source_name, n.type AS source_group, n.symbol AS source_symbol,
       m.id AS target_id, m.name AS target_name, m.type AS target_group, m.symbol AS target_symbol,
       coalesce(r.label, type(r)) AS edge_label, coalesce(r.inferred, false) AS inferred,
       r.shares AS sh, r.ownership AS ow
"""


def _resolve_symbol_entity_id(symbol):
    """Map ticker (VIC) to C_VIC if present in Neo4j."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    cid = f"C_{sym}"
    try:
        with neo4j_driver.session() as session:
            rec = session.run(
                "MATCH (n:Entity {id: $id}) RETURN n.id AS id LIMIT 1", id=cid
            ).single()
            if rec:
                return rec["id"]
    except Exception:
        pass
    return cid


def _detect_suggested_query_intent(query_text):
    """Fast-path intent for UI suggested prompts (normalized Vietnamese keywords)."""
    q = _normalize_vn_text(query_text)
    if not q:
        return None

    if ("nguoi than" in q or "than nhan" in q) and (
        "vingroup" in q or " vic" in f" {q} " or q.startswith("vic ")
    ) and "co dong" in q:
        return "vic_family_shareholder_other"
    if "chu tich" in q and "co dong" in q and ("cong ty khac" in q or "khac" in q):
        return "chairman_and_shareholder_other"
    if "mbb" in q and ("cong ty con" in q or "2 cap" in q or "hai cap" in q):
        return "subsidiary_chain_2"
    if "vnm" in q and "cong ty con" in q and ("to chuc" in q or "co dong" in q):
        return "vnm_subsidiary_institutional_holder"
    if "fpt" in q and ("co dong" in q or "ngan hang" in q):
        return "fpt_leader_bank_shareholder"
    if "ho hung anh" in q and ("nguoi than" in q or "gia dinh" in q):
        return "ho_hung_anh_family_holdings"
    if ("vingroup" in q or "vic" in q) and ("vinhomes" in q or "vhm" in q) and (
        "gian tiep" in q or "lien ket" in q or "soi day" in q
    ):
        return "vic_vhm_indirect_links"
    if "masan" in q or "msn" in q:
        if "cong ty con" in q or "pha loang" in q or "100" in q:
            return "msn_subsidiary_diluted"
    return None


def _intent_cypher(intent_id, query_text):
    """Return (cypher_string, params_dict) for a detected suggested-prompt intent."""
    params = {"leaderTypes": _LEADER_REL_TYPES}

    if intent_id == "chairman_and_shareholder_other":
        cypher = f"""
        MATCH (p:Entity)-[r1]->(c1:Entity)
        WHERE p.id STARTS WITH 'P_'
          AND c1.id STARTS WITH 'C_'
          AND type(r1) IN $leaderTypes
        MATCH (p)-[r2:LÀ_CỔ_ĐÔNG_CỦA]->(c2:Entity)
        WHERE c2.id STARTS WITH 'C_' AND c1.id <> c2.id
        RETURN p.id AS source_id, p.name AS source_name, p.type AS source_group, p.symbol AS source_symbol,
               c2.id AS target_id, c2.name AS target_name, c2.type AS target_group, c2.symbol AS target_symbol,
               type(r2) AS edge_label, coalesce(r2.inferred, false) AS inferred, r2.shares AS sh, r2.ownership AS ow
        LIMIT 80
        """
        return cypher.strip(), params

    if intent_id == "vic_family_shareholder_other":
        vic_id = _resolve_symbol_entity_id("VIC")
        params["vicId"] = vic_id
        cypher = f"""
        MATCH (leader:Entity)-[lr]->(vic:Entity {{id: $vicId}})
        WHERE leader.id STARTS WITH 'P_'
          AND type(lr) IN $leaderTypes
        MATCH (fam:Entity)-[rf:LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO]->(vic)
        WHERE fam.id STARTS WITH 'P_'
        MATCH (fam)-[rh:LÀ_CỔ_ĐÔNG_CỦA]->(other:Entity)
        WHERE other.id STARTS WITH 'C_' AND other.id <> $vicId
        RETURN fam.id AS source_id, fam.name AS source_name, fam.type AS source_group, fam.symbol AS source_symbol,
               other.id AS target_id, other.name AS target_name, other.type AS target_group, other.symbol AS target_symbol,
               type(rh) AS edge_label, coalesce(rh.inferred, false) AS inferred, rh.shares AS sh, rh.ownership AS ow
        LIMIT 80
        """
        return cypher.strip(), params

    if intent_id == "subsidiary_chain_2":
        mbb_id = _resolve_symbol_entity_id("MBB")
        params["parentId"] = mbb_id
        cypher = """
        MATCH (parent:Entity {id: $parentId})-[:CÓ_CÔNG_TY_CON]->(child:Entity)-[:CÓ_CÔNG_TY_CON]->(grand:Entity)
        RETURN parent.id AS source_id, parent.name AS source_name, parent.type AS source_group, parent.symbol AS source_symbol,
               grand.id AS target_id, grand.name AS target_name, grand.type AS target_group, grand.symbol AS target_symbol,
               'CÓ_CÔNG_TY_CON' AS edge_label, false AS inferred, null AS sh, null AS ow
        LIMIT 50
        """
        return cypher.strip(), params

    if intent_id == "vnm_subsidiary_institutional_holder":
        vnm_id = _resolve_symbol_entity_id("VNM")
        params["parentId"] = vnm_id
        cypher = """
        MATCH (vnm:Entity {id: $parentId})-[:CÓ_CÔNG_TY_CON]->(sub:Entity)
        MATCH (inst:Entity)-[r:LÀ_CỔ_ĐÔNG_CỦA]->(sub)
        WHERE inst.id STARTS WITH 'C_INST_'
        RETURN inst.id AS source_id, inst.name AS source_name, inst.type AS source_group, inst.symbol AS source_symbol,
               sub.id AS target_id, sub.name AS target_name, sub.type AS target_group, sub.symbol AS target_symbol,
               type(r) AS edge_label, coalesce(r.inferred, false) AS inferred, r.shares AS sh, r.ownership AS ow
        LIMIT 80
        """
        return cypher.strip(), params

    if intent_id == "fpt_leader_bank_shareholder":
        fpt_id = _resolve_symbol_entity_id("FPT")
        params["fptId"] = fpt_id
        cypher = """
        MATCH (p:Entity)-[r1]->(fpt:Entity {id: $fptId})
        WHERE p.id STARTS WITH 'P_'
          AND type(r1) IN $leaderTypes
        MATCH (p)-[r2:LÀ_CỔ_ĐÔNG_CỦA]->(bank:Entity)
        WHERE bank.id STARTS WITH 'C_'
          AND bank.id <> $fptId
          AND (
            toLower(coalesce(bank.name, '')) CONTAINS 'ngan hang'
            OR toLower(coalesce(bank.name, '')) CONTAINS 'bank'
          )
        RETURN p.id AS source_id, p.name AS source_name, p.type AS source_group, p.symbol AS source_symbol,
               bank.id AS target_id, bank.name AS target_name, bank.type AS target_group, bank.symbol AS target_symbol,
               type(r2) AS edge_label, coalesce(r2.inferred, false) AS inferred, r2.shares AS sh, r2.ownership AS ow
        LIMIT 80
        """
        return cypher.strip(), params

    if intent_id == "ho_hung_anh_family_holdings":
        cypher = """
        MATCH (p:Entity)
        WHERE toLower(p.name) CONTAINS 'hồ hùng anh' OR toLower(p.name) CONTAINS 'ho hung anh'
        MATCH (p)-[rf]-(fam:Entity)
        WHERE fam.id STARTS WITH 'P_' AND fam.id <> p.id
          AND (
            type(rf) IN $familyTypes
            OR type(rf) = 'LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO'
            OR type(rf) CONTAINS 'VỢ_CHỒNG'
            OR type(rf) CONTAINS 'CHA_MẸ'
          )
        MATCH (holder:Entity)-[rh:LÀ_CỔ_ĐÔNG_CỦA]->(c:Entity)
        WHERE holder.id IN [p.id, fam.id] AND c.id STARTS WITH 'C_'
        RETURN holder.id AS source_id, holder.name AS source_name, holder.type AS source_group, holder.symbol AS source_symbol,
               c.id AS target_id, c.name AS target_name, c.type AS target_group, c.symbol AS target_symbol,
               type(rh) AS edge_label, coalesce(rh.inferred, false) AS inferred, rh.shares AS sh, rh.ownership AS ow
        LIMIT 120
        """
        params["familyTypes"] = [
            "VỢ_CHỒNG", "CHA_MẸ", "ANH_CHỊ", "NGƯỜI_THÂN", "MẸ", "BỐ", "ANH", "CHỊ",
            "LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO",
        ]
        return cypher.strip(), params

    if intent_id == "vic_vhm_indirect_links":
        params["vicId"] = _resolve_symbol_entity_id("VIC")
        params["vhmId"] = _resolve_symbol_entity_id("VHM")
        cypher = """
        MATCH path = (a:Entity {id: $vicId})-[*1..4]-(b:Entity {id: $vhmId})
        WHERE ALL(rel IN relationships(path) WHERE type(rel) IN [
          'CÓ_CÔNG_TY_CON', 'LÀ_CÔNG_TY_CON_CỦA', 'LÀ_CỔ_ĐÔNG_CỦA',
          'SỞ_HỮU_GIÁN_TIẾP', 'CÓ_LỢI_ÍCH_GIÁN_TIẾP', 'ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI', 'KIỂM_SOÁT_GIÁN_TIẾP'
        ])
        WITH path LIMIT 40
        UNWIND relationships(path) AS r
        WITH startNode(r) AS s, endNode(r) AS t, r
        RETURN s.id AS source_id, s.name AS source_name, s.type AS source_group, s.symbol AS source_symbol,
               t.id AS target_id, t.name AS target_name, t.type AS target_group, t.symbol AS target_symbol,
               coalesce(r.label, type(r)) AS edge_label, coalesce(r.inferred, false) AS inferred,
               r.shares AS sh, r.ownership AS ow
        LIMIT 120
        """
        return cypher.strip(), params

    if intent_id == "msn_subsidiary_diluted":
        params["msnId"] = _resolve_symbol_entity_id("MSN")
        cypher = """
        MATCH (msn:Entity {id: $msnId})-[rp:CÓ_CÔNG_TY_CON]->(sub:Entity)
        MATCH (p:Entity)-[r:LÀ_CỔ_ĐÔNG_CỦA]->(sub)
        WHERE p.id STARTS WITH 'P_'
          AND coalesce(toFloat(r.ownership), 0) > 0
          AND coalesce(toFloat(rp.ownership), 1) < 0.999
        RETURN p.id AS source_id, p.name AS source_name, p.type AS source_group, p.symbol AS source_symbol,
               sub.id AS target_id, sub.name AS target_name, sub.type AS target_group, sub.symbol AS target_symbol,
               type(r) AS edge_label, coalesce(r.inferred, false) AS inferred, r.shares AS sh, r.ownership AS ow
        LIMIT 80
        """
        return cypher.strip(), params

    return None, {}


def _detect_hidden_rule_query(query_text):
    """
    Nhận diện câu hỏi đang hỏi trực tiếp theo tên rule quan hệ ẩn.
    Đây là fast-path để tránh fallback sang tìm kiếm tên thực thể rồi bỏ sót cạnh inferred.
    """
    q_norm = _normalize_vn_text(query_text)
    if not q_norm:
        return None

    for rule in HIDDEN_RULE_QUERIES:
        if rule["name_norm"] in q_norm:
            return rule
    return None


def _tokenize_normalized_words(text):
    norm = _normalize_vn_text(text)
    norm = _re.sub(r"[^a-z0-9\s]+", " ", norm)
    return [tok for tok in norm.split() if tok]


def _news_query_terms(text):
    return {
        tok
        for tok in _tokenize_normalized_words(text)
        if len(tok) >= 2 and tok not in _LIVE_NEWS_NOISE_TOKENS
    }


def _extract_symbol_tokens(text):
    raw = str(text or "")
    symbols = set()
    for part in _re.findall(r"\(([A-Z0-9]{2,8})\)", raw):
        symbols.add(part.lower())
    for token in raw.split():
        clean = token.strip(" ,.?;:()[]{}\"'")
        if 2 <= len(clean) <= 8 and clean.isupper() and any(ch.isalpha() for ch in clean):
            symbols.add(clean.lower())
    return symbols


def _entity_focus_terms(text):
    return {
        tok
        for tok in _tokenize_normalized_words(text)
        if len(tok) >= 2 and tok not in _ENTITY_NEWS_STOPWORDS
    }


def _is_project_domain_query(query_text, target_entity_id=None, hidden_rule_query=None):
    if target_entity_id or hidden_rule_query:
        return True

    q_norm = _normalize_vn_text(query_text)
    if not q_norm:
        return False

    if _is_live_market_query(query_text):
        return True

    if any(phrase in q_norm for phrase in _PROJECT_DOMAIN_PHRASES):
        return True

    raw_lower = str(query_text or "").lower()
    for key in sorted(ENTITY_MAP.keys(), key=len, reverse=True):
        if len(key) >= 3 and key in raw_lower:
            return True

    return False


def _looks_like_named_entity_query(query_text):
    raw = str(query_text or "").strip()
    if not raw:
        return False

    if _is_live_market_query(query_text):
        return True

    if _re.search(r"\b[A-Z]{2,5}\b", raw):
        return True

    titled_words = 0
    for token in raw.split():
        clean = token.strip(" ,.?;:()[]{}\"'")
        if len(clean) < 2:
            continue
        if clean[:1].isupper():
            titled_words += 1
    return titled_words >= 2


def _is_relevant_news_item(title, query_text, target_display=None):
    title_norm = _normalize_vn_text(title)
    if not title_norm:
        return False

    title_terms = set(_tokenize_normalized_words(title_norm))
    if not title_terms:
        return False

    target_raw = str(target_display or "").strip()
    target_norm = _normalize_vn_text(target_raw) if target_raw else ""
    target_terms = _entity_focus_terms(target_raw)
    target_symbols = _extract_symbol_tokens(target_raw)
    if target_norm:
        if target_norm in title_norm:
            return True
        if target_symbols and (title_terms & target_symbols):
            return True
        overlap = title_terms & target_terms
        if len(target_terms) >= 2 and len(overlap) >= 2:
            return True
        if len(target_terms) == 1 and len(overlap) >= 1:
            return True

        return False

    query_terms = _news_query_terms(query_text)
    overlap = title_terms & query_terms
    if len(overlap) >= (1 if len(query_terms) <= 2 else 2):
        return True

    if _is_live_market_query(query_text):
        market_terms = {
            "giao", "dich", "khoi", "luong", "thanh", "khoan", "tang", "truong",
            "chung", "khoan", "vn", "index", "hose", "hnx", "niem", "yet", "co", "phieu",
        }
        if title_terms & market_terms:
            return True

    return False


def _library_has_searchable_content(lib):
    """
    Library llmware hợp lệ tối thiểu phải có block NLP để tra cứu.
    Embedding có thể chưa sẵn sàng; khi đó sẽ fallback sang keyword search.
    """
    if lib is None:
        return False
    nlp_path = getattr(lib, "nlp_path", "") or ""
    if not nlp_path or not os.path.isdir(nlp_path):
        return False
    return any(name.endswith((".json", ".jsonl")) for name in os.listdir(nlp_path))


def _library_has_embedding_index(lib):
    embedding_path = getattr(lib, "embedding_path", "") or ""
    embedding_model = getattr(lib, "embedding_model_name", None)
    if not embedding_model or not embedding_path or not os.path.isdir(embedding_path):
        return False
    return any(os.scandir(embedding_path))


def _ensure_rag_text_corpus():
    """
    Tự phục hồi corpus text từ processed_raw khi các file processed hiện chỉ là placeholder.
    Việc này giúp lớp RAG vẫn hoạt động được cả khi vector library bị rỗng.
    """
    try:
        import llm_preprocessor
        llm_preprocessor.rebuild_rag_corpus_from_processed_raw(force=False)
    except Exception as e:
        print(f"⚠️ [RAG] rebuild corpus failed: {e}")


def _bootstrap_rag_library_documents():
    """
    Nếu library llmware đang rỗng, nạp lại block NLP từ data/processed.
    Bước này nhẹ hơn nhiều so với build embedding, nhưng đủ để giữ library không còn ở trạng thái trống.
    """
    _ensure_rag_text_corpus()
    processed_dir = os.path.join(DATA_DIR, "processed")
    if not os.path.isdir(processed_dir):
        return None

    txt_files = [name for name in os.listdir(processed_dir) if name.endswith(".txt")]
    if not txt_files:
        return None

    try:
        lib = Library().load_library(RAG_LIBRARY_NAME)
    except Exception:
        lib = Library().create_new_library(RAG_LIBRARY_NAME)

    if _library_has_searchable_content(lib):
        return lib

    try:
        lib.add_files(processed_dir)
    except Exception as e:
        print(f"⚠️ [RAG] bootstrap library documents failed: {e}")
    return lib


def _fallback_rag_documents():
    """
    Gom tài liệu text cục bộ để dùng cho keyword retrieval khi semantic vector search không sẵn sàng.
    Ưu tiên docs/ và các file normalized đã rebuild từ processed_raw.
    """
    _ensure_rag_text_corpus()
    docs = []
    candidates = [
        os.path.join(DOCS_DIR, "inference_rules.md"),
        os.path.join(DOCS_DIR, "cypher_reference.md"),
        os.path.join(DOCS_DIR, "entities_schema.md"),
    ]

    processed_dir = os.path.join(DATA_DIR, "processed")
    if os.path.isdir(processed_dir):
        for name in sorted(os.listdir(processed_dir)):
            if name.endswith(".txt"):
                candidates.append(os.path.join(processed_dir, name))

    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            if text and text != "Dữ liệu JSON đã được parse trực tiếp vào Graph.":
                docs.append({"path": path, "text": text})
        except Exception:
            continue
    return docs


def _keyword_rag_search(query_text, result_count=5):
    """
    Fallback retrieval đơn giản nhưng ổn định:
    - chuẩn hóa tiếng Việt
    - chấm điểm theo overlap token
    - trả về top đoạn text phù hợp nhất
    """
    q_norm = _normalize_vn_text(query_text)
    q_tokens = {tok for tok in q_norm.split() if len(tok) >= 2 and tok not in _RAG_STOPWORDS}
    if not q_tokens:
        return []

    scored = []
    for doc in _fallback_rag_documents():
        text = doc["text"]
        chunks = [part.strip() for part in text.split("\n\n") if part.strip()]
        if len(chunks) <= 1:
            line_chunks = [line.strip() for line in text.splitlines() if line.strip()]
            chunks = line_chunks or [text]
        for chunk in chunks:
            chunk_norm = _normalize_vn_text(chunk)
            chunk_tokens = {tok for tok in chunk_norm.split() if len(tok) >= 2 and tok not in _RAG_STOPWORDS}
            if not chunk_tokens:
                continue
            overlap = q_tokens & chunk_tokens
            if not overlap:
                continue

            # Điểm ưu tiên chunk có nhiều token trùng hơn và chứa nguyên cụm query nếu có.
            score = len(overlap)
            if q_norm in chunk_norm:
                score += max(3, len(q_tokens))
            scored.append((score, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    results = []
    seen = set()
    for _, chunk in scored:
        if chunk in seen:
            continue
        seen.add(chunk)
        results.append(chunk)
        if len(results) >= result_count:
            break
    return results


def _build_live_news_query(query_text, target_display=None):
    """
    Tạo cụm tìm kiếm gọn để lấy tin nóng theo truy vấn hiện tại.
    Nếu nhận diện được thực thể đích thì ưu tiên thực thể đó.
    """
    q_norm = _normalize_vn_text(query_text)
    if _is_live_market_query(query_text):
        date_hint = ""
        m = _re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", str(query_text or ""))
        if m:
            date_hint = f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
        if "khoi luong" in q_norm or "thanh khoan" in q_norm:
            base = "khối lượng giao dịch cao nhất"
            if date_hint:
                return f"{base} {date_hint} HOSE HNX UPCOM Việt Nam"
            if "hom nay" in q_norm:
                return f"{base} hôm nay chứng khoán Việt Nam"
            return f"{base} chứng khoán Việt Nam"
        if "gia" in q_norm:
            return f"giá cổ phiếu chứng khoán Việt Nam {date_hint}".strip()

    if target_display:
        raw = str(target_display).strip()
        base_name = _re.sub(r"\s*\([^)]+\)\s*$", "", raw).strip()
        symbols = sorted(_extract_symbol_tokens(raw))
        if symbols:
            return f'"{base_name}" OR "{symbols[0].upper()}"'
        return f'"{base_name}"'

    q_norm = " ".join(str(query_text or "").strip().split())
    if not q_norm:
        return "chứng khoán Việt Nam"

    tokens = [tok for tok in q_norm.split() if len(tok) > 2]
    short = " ".join(tokens[:8]).strip()
    if not short:
        short = q_norm
    return f"{short} chứng khoán Việt Nam"


def _google_news_rss_url(search_query, site=None):
    query = search_query.strip()
    if site:
        query = f"{query} site:{site}"
    return (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + "&hl=vi&gl=VN&ceid=VN:vi"
    )


def _parse_rss_datetime(value):
    if not value:
        return None
    value = value.strip()
    fmts = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _fetch_rss_items(feed_url, source_name, max_items=2):
    try:
        resp = requests.get(
            feed_url,
            timeout=LIVE_NEWS_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 KG-News-Augment/1.0"},
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        return [], f"{source_name}: {e}"

    items = []
    seen = set()
    for item in root.findall(".//item"):
        title = html.unescape((item.findtext("title") or "").strip())
        link = (item.findtext("link") or "").strip()
        pub_date = item.findtext("pubDate") or item.findtext("published") or ""
        if not title or not link:
            continue
        dedupe_key = (title, link)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        dt = _parse_rss_datetime(pub_date)
        items.append(
            {
                "source": source_name,
                "title": title,
                "link": link,
                "published_at": dt.isoformat() if dt else "",
                "published_label": dt.strftime("%d/%m %H:%M") if dt else "",
            }
        )
        if len(items) >= max_items:
            break
    return items, None


def _collect_live_news(query_text, target_display, graph_context, steps):
    """
    Lấy tin thời gian thực từ 5 nguồn tin uy tín/ổn định.
    Dùng RSS/Google News RSS để tránh HTML scraping dễ vỡ.
    """
    search_query = _build_live_news_query(query_text, target_display=target_display)
    steps.append("📰 Đang lấy tin tức chứng khoán thời gian thực từ 5 nguồn web...")

    news_items = []
    errors = []
    for spec in _LIVE_NEWS_SOURCES:
        if spec["kind"] == "rss":
            feed_url = spec["url"]
        else:
            feed_url = _google_news_rss_url(search_query, site=spec.get("site"))

        items, err = _fetch_rss_items(feed_url, spec["name"], max_items=2)
        if err:
            errors.append(err)
            continue
        relevant_items = [
            item
            for item in items
            if _is_relevant_news_item(item["title"], query_text, target_display=target_display)
        ]
        if relevant_items:
            news_items.extend(relevant_items[:1])

    # Ưu tiên tin mới hơn nếu có timestamp, sau đó cắt còn tối đa 5 nguồn / tin.
    news_items.sort(key=lambda item: item.get("published_at") or "", reverse=True)
    news_items = news_items[:LIVE_NEWS_MAX_ITEMS]

    if news_items:
        steps.append(f"✅ Tìm thấy {len(news_items)} nguồn tin thời gian thực liên quan.")
    else:
        steps.append("ℹ️ Chưa lấy được tin tức thời gian thực phù hợp cho truy vấn này.")
        if errors:
            print("[LIVE_NEWS] errors:", errors)

    graph_text_norm = _normalize_vn_text("\n".join(graph_context[:80]))
    unseen_titles = 0
    for item in news_items:
        title_norm = _normalize_vn_text(item["title"])
        if title_norm and title_norm not in graph_text_norm:
            unseen_titles += 1

    diff_lines = []
    if graph_context:
        diff_lines.append(
            "- Dữ liệu KG/FireAnt hiện thiên về cấu trúc quan hệ, sở hữu và hồ sơ doanh nghiệp; phần tin tức dưới đây phản ánh diễn biến thời gian thực."
        )
    else:
        diff_lines.append(
            "- KG/FireAnt chưa trả về nhiều dữ liệu cấu trúc cho truy vấn này; các tin dưới đây bổ sung bối cảnh thời gian thực từ báo chí."
        )
    if unseen_titles:
        diff_lines.append(
            f"- Có khoảng {unseen_titles} tiêu đề tin mới chưa xuất hiện trực tiếp trong phần dữ liệu Graph/Cypher vừa truy vấn."
        )
    else:
        diff_lines.append(
            "- Các tin mới chủ yếu bổ sung diễn giải thị trường/sự kiện, không thay thế dữ liệu quan hệ đang có trong KG."
        )

    return news_items, diff_lines


def _format_live_news_markdown(news_items, diff_lines):
    if not news_items:
        return ""

    lines = ["", "## Tin Tức Thị Trường Mới Nhất"]
    for item in news_items:
        label = f" [{item['published_label']}]" if item.get("published_label") else ""
        lines.append(f"- **{item['source']}**{label}: [{item['title']}]({item['link']})")

    if diff_lines:
        lines.extend(["", "## Khác Biệt So Với FireAnt/KG"])
        lines.extend(diff_lines)
    return "\n".join(lines)


def _format_live_news_context(news_items):
    if not news_items:
        return "Không lấy được tin thời gian thực phù hợp."

    lines = []
    for item in news_items[:5]:
        label = f" | {item['published_label']}" if item.get("published_label") else ""
        lines.append(f"- [{item['source']}{label}] {item['title']}")
    return "\n".join(lines)


def _collect_rag_contexts(query_text, steps):
    """
    Ưu tiên semantic search của llmware nếu library còn tốt.
    Nếu vector layer rỗng/hỏng thì fallback sang keyword retrieval cục bộ thay vì đẩy lỗi ra UI.
    """
    contexts = []
    try:
        retriever = _bootstrap_rag_library_documents() or Library().load_library(RAG_LIBRARY_NAME)
        if _library_has_searchable_content(retriever) and _library_has_embedding_index(retriever):
            from llmware.retrieval import Query as LWQuery
            search_results = LWQuery(retriever).semantic_query(query_text, result_count=5)
            for res in search_results:
                txt = (res.get("text") or "").strip()
                if txt:
                    contexts.append(txt)
        elif _library_has_searchable_content(retriever):
            steps.append("ℹ️ Semantic index chưa được build, chuyển sang keyword retrieval cục bộ.")
        else:
            steps.append("ℹ️ Semantic library đang rỗng, chuyển sang keyword retrieval cục bộ.")
    except Exception as e:
        print(f"⚠️ [RAG] semantic search fallback: {e}")
        steps.append("ℹ️ Semantic search chưa sẵn sàng, chuyển sang keyword retrieval cục bộ.")

    if contexts:
        steps.append(f"✅ Tìm thấy {len(contexts)} đoạn liên quan từ vector/semantic search.")
        return contexts

    fallback_contexts = _keyword_rag_search(query_text, result_count=5)
    if fallback_contexts:
        steps.append(f"✅ Tìm thấy {len(fallback_contexts)} đoạn liên quan từ corpus cục bộ.")
    else:
        steps.append("ℹ️ Không tìm thấy tài liệu bổ trợ phù hợp trong corpus cục bộ.")
    return fallback_contexts


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
    RETURN n.id AS nid, n.symbol AS symbol
    """
    out = set()
    for rec in session.run(q):
        if _resolve_vn_listing(None, rec.get("symbol"), rec.get("nid")):
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

    inferred_relationships: tổng số cạnh inferred trong Neo4j (cùng giá trị với inferred_hidden_edges_raw).
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
        "inferred_hidden_edges_raw": inferred_rel_count,
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
    """Get inferred (hidden) relations with stats and a vis-ready graph payload."""
    from flask import request

    _ensure_inferred_rule_ids_migrated()

    level = request.args.get("level")
    try:
        lim = int(request.args.get("limit", "500"))
    except ValueError:
        lim = 500
    lim = max(50, min(lim, 5000))

    def _entity_group(ent_type, eid):
        t = (ent_type or "").strip() if ent_type else ""
        if t in ("Company", "Person", "Institution"):
            return t
        if isinstance(eid, str):
            if eid.startswith("P_"):
                return "Person"
            if eid.startswith("C_"):
                return "Company"
        return "DEFAULT"

    with neo4j_driver.session() as session:
        if level:
            q = """
            MATCH (a:Entity)-[r]->(b:Entity)
            WHERE coalesce(r.inferred, false) = true AND r.influence_level = $level
            RETURN a.id AS source, a.name AS source_name, a.type AS source_type,
                   b.id AS target, b.name AS target_name, b.type AS target_type,
                   r.label AS relation,
                   coalesce(toFloat(r.indirect_ownership_pct), toFloat(r.combined_ownership_pct), -1.0) AS ownership,
                   r.influence_level AS level, r.inferred_from AS rule
            ORDER BY coalesce(toFloat(r.indirect_ownership_pct), toFloat(r.combined_ownership_pct), 0) DESC
            """
            result = session.run(q, level=level)
        else:
            q = """
            MATCH (a:Entity)-[r]->(b:Entity)
            WHERE coalesce(r.inferred, false) = true
            RETURN a.id AS source, a.name AS source_name, a.type AS source_type,
                   b.id AS target, b.name AS target_name, b.type AS target_type,
                   r.label AS relation,
                   coalesce(toFloat(r.indirect_ownership_pct), toFloat(r.combined_ownership_pct), -1.0) AS ownership,
                   r.influence_level AS level, r.inferred_from AS rule
            ORDER BY coalesce(toFloat(r.indirect_ownership_pct), toFloat(r.combined_ownership_pct), 0) DESC
            """
            result = session.run(q)
        relations = _dedupe_inferred_relation_rows([dict(r) for r in result])[:lim]

    nodes_map = {}
    edges_out = []
    for row in relations:
        sid = row.get("source")
        tid = row.get("target")
        if not sid or not tid:
            continue
        sg = _entity_group(row.get("source_type"), sid)
        tg = _entity_group(row.get("target_type"), tid)
        sn = row.get("source_name") or sid
        tn = row.get("target_name") or tid
        nodes_map[sid] = {"id": sid, "label": sn, "name": sn, "group": sg}
        nodes_map[tid] = {"id": tid, "label": tn, "name": tn, "group": tg}
        _raw_rel = row.get("relation") or ""
        _rule = row.get("rule") or ""
        _edge_label = inferred_edge_label_display_vi(_raw_rel, _rule)
        edges_out.append(
            {
                "from": sid,
                "to": tid,
                "label": _edge_label,
                "inferred": True,
                "dashes": True,
                "inferred_from": _rule,
                "influence_level": row.get("level"),
            }
        )

    graph_payload = {"nodes": list(nodes_map.values()), "edges": edges_out}

    with neo4j_driver.session() as session:
        q = """
        MATCH ()-[r]->() WHERE coalesce(r.inferred, false) = true
        RETURN count(r) AS total,
               count(CASE WHEN r.influence_level = 'LOW' THEN 1 END) AS low,
               count(CASE WHEN r.influence_level = 'MEDIUM' THEN 1 END) AS medium,
               count(CASE WHEN r.influence_level = 'HIGH' THEN 1 END) AS high
        """
        stats_rec = session.run(q).single()
        stats = dict(stats_rec) if stats_rec else {"total": 0, "low": 0, "medium": 0, "high": 0}

    return jsonify({"relations": relations, "stats": stats, "graph": graph_payload})


def _entity_group_from_payload(ent_type, eid):
    t = (ent_type or "").strip() if ent_type else ""
    if t in ("Company", "Person", "Institution"):
        return t
    if isinstance(eid, str):
        if eid.startswith("P_"):
            return "Person"
        if eid.startswith("C_"):
            return "Company"
    return "DEFAULT"


def _entity_label(name, eid, symbol=""):
    base = (name or eid or "").strip() or str(eid or "")
    sym = (symbol or "").strip()
    return f"{base} ({sym})" if sym else base


def _coerce_pct(value, fraction_hint=False):
    if value is None or value == "":
        return None
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return None
    if fraction_hint and abs(pct) <= 1:
        pct *= 100.0
    return round(pct, 4)


def _fmt_pct(value, fraction_hint=False):
    pct = _coerce_pct(value, fraction_hint=fraction_hint)
    if pct is None:
        return None
    if float(int(pct)) == pct:
        return f"{int(pct)}%"
    return f"{pct:.2f}%"


def _edge_label_with_pct(label, pct=None, fraction_hint=False):
    pct_text = _fmt_pct(pct, fraction_hint=fraction_hint)
    if pct_text:
        return f"{label} ({pct_text})"
    return label or ""


def _add_focus_node(nodes_map, entity_id, name=None, ent_type=None, symbol=""):
    if not entity_id:
        return
    nodes_map[entity_id] = {
        "id": entity_id,
        "label": _entity_label(name, entity_id, symbol),
        "name": _entity_label(name, entity_id, symbol),
        "group": _entity_group_from_payload(ent_type, entity_id),
    }


def _add_focus_edge(
    edges_out,
    edge_seen,
    source_id,
    target_id,
    label,
    inferred=False,
    inferred_from=None,
    influence_level=None,
):
    if not source_id or not target_id:
        return
    edge_key = f"{source_id}→{target_id}:{label or ''}"
    if edge_key in edge_seen:
        return
    edge_seen.add(edge_key)
    obj = {
        "from": source_id,
        "to": target_id,
        "label": label or "",
        "inferred": bool(inferred),
        "dashes": bool(inferred),
        "inferred_from": inferred_from or "",
    }
    if influence_level:
        obj["influence_level"] = influence_level
    edges_out.append(obj)


@app.route("/api/inferred-relations/context", methods=["GET"])
def api_inferred_relation_context():
    """Return the supporting direct graph + explanation for one inferred relation."""
    source_id = (request.args.get("source") or "").strip()
    target_id = (request.args.get("target") or "").strip()
    rule_id = (request.args.get("rule") or "").strip()
    relation = (request.args.get("relation") or "").strip()

    _ensure_inferred_rule_ids_migrated()

    if not source_id or not target_id:
        return jsonify({"error": "source and target are required"}), 400

    with neo4j_driver.session() as session:
        rec = session.run(
            """
            MATCH (a:Entity {id: $source_id})-[r]->(c:Entity {id: $target_id})
            WHERE coalesce(r.inferred, false) = true
              AND ($rule_id = '' OR r.inferred_from = $rule_id)
              AND ($relation = '' OR coalesce(r.label, type(r), '') = $relation)
            RETURN a.id AS source_id, a.name AS source_name, a.type AS source_type, a.symbol AS source_symbol,
                   c.id AS target_id, c.name AS target_name, c.type AS target_type, c.symbol AS target_symbol,
                   type(r) AS rel_type, properties(r) AS rel_props
            ORDER BY coalesce(r.indirect_ownership_pct, r.combined_ownership_pct, 0) DESC
            LIMIT 1
            """,
            source_id=source_id,
            target_id=target_id,
            rule_id=rule_id,
            relation=relation,
        ).single()

        if not rec:
            return jsonify({"error": "inferred relation could not be found"}), 404

        rel_props = dict(rec.get("rel_props") or {})
        rel_label = rel_props.get("label") or rec.get("rel_type") or relation or ""
        resolved_rule_id = rel_props.get("inferred_from") or rule_id or ""
        rel_label_ui = inferred_edge_label_display_vi(rel_label, resolved_rule_id)
        inf_lvl = (rel_props.get("influence_level") or "").strip() or None
        source_label = _entity_label(rec.get("source_name"), source_id, rec.get("source_symbol") or "")
        target_label = _entity_label(rec.get("target_name"), target_id, rec.get("target_symbol") or "")

        nodes_map = {}
        edges_out = []
        edge_seen = set()

        _add_focus_node(
            nodes_map,
            source_id,
            rec.get("source_name"),
            rec.get("source_type"),
            rec.get("source_symbol") or "",
        )
        _add_focus_node(
            nodes_map,
            target_id,
            rec.get("target_name"),
            rec.get("target_type"),
            rec.get("target_symbol") or "",
        )
        _add_focus_edge(
            edges_out,
            edge_seen,
            source_id,
            target_id,
            rel_label_ui,
            inferred=True,
            inferred_from=resolved_rule_id,
            influence_level=inf_lvl,
        )

        explanation_lines = []
        law_txt = _law_display(resolved_rule_id)
        summary = (
            f"{source_label} được nối với {target_label} bằng cạnh suy luận "
            f"«{rel_label_ui}» theo {law_txt}."
        )

        if resolved_rule_id == "R01":
            spouse_id = rel_props.get("spouse_id")
            support = session.run(
                """
                MATCH (a:Entity {id: $source_id})
                MATCH (c:Entity {id: $target_id})
                OPTIONAL MATCH (sp:Entity {id: $spouse_id})
                OPTIONAL MATCH (a)-[sp_rel:VỢ_CHỒNG]-(sp)
                OPTIONAL MATCH (a)-[r1:LÀ_CỔ_ĐÔNG_CỦA]->(c)
                OPTIONAL MATCH (sp)-[r2:LÀ_CỔ_ĐÔNG_CỦA]->(c)
                RETURN sp.id AS spouse_id, sp.name AS spouse_name, sp.type AS spouse_type, sp.symbol AS spouse_symbol,
                       type(sp_rel) AS spouse_rel,
                       r1.ownership AS own_a,
                       r2.ownership AS own_b
                LIMIT 1
                """,
                source_id=source_id,
                target_id=target_id,
                spouse_id=spouse_id,
            ).single()

            spouse_label = rel_props.get("spouse_name") or spouse_id or "người phối ngẫu"
            own_a_pct = _fmt_pct(rel_props.get("ownership_a"))
            own_b_pct = _fmt_pct(rel_props.get("ownership_b"))
            combined_pct = _fmt_pct(rel_props.get("combined_ownership_pct"))

            if support and support.get("spouse_id"):
                spouse_id = support.get("spouse_id")
                spouse_label = _entity_label(
                    support.get("spouse_name"),
                    spouse_id,
                    support.get("spouse_symbol") or "",
                )
                _add_focus_node(
                    nodes_map,
                    spouse_id,
                    support.get("spouse_name"),
                    support.get("spouse_type"),
                    support.get("spouse_symbol") or "",
                )
                if support.get("spouse_rel"):
                    _add_focus_edge(
                        edges_out,
                        edge_seen,
                        source_id,
                        spouse_id,
                        support.get("spouse_rel"),
                    )
                _add_focus_edge(
                    edges_out,
                    edge_seen,
                    source_id,
                    target_id,
                    _edge_label_with_pct("LÀ_CỔ_ĐÔNG_CỦA", support.get("own_a"), fraction_hint=True),
                )
                _add_focus_edge(
                    edges_out,
                    edge_seen,
                    spouse_id,
                    target_id,
                    _edge_label_with_pct("LÀ_CỔ_ĐÔNG_CỦA", support.get("own_b"), fraction_hint=True),
                )
                if not own_a_pct:
                    own_a_pct = _fmt_pct(support.get("own_a"), fraction_hint=True)
                if not own_b_pct:
                    own_b_pct = _fmt_pct(support.get("own_b"), fraction_hint=True)

            summary = (
                f"{source_label} và {spouse_label} cùng có sở hữu trực tiếp tại {target_label}; "
                f"hệ thống gộp phần sở hữu gia đình để suy ra «{rel_label_ui}»."
            )
            explanation_lines.append(
                f"{source_label} có quan hệ VỢ_CHỒNG với {spouse_label}, nên đây là một cặp gia đình được xét gộp quyền sở hữu."
            )
            if own_a_pct or own_b_pct:
                explanation_lines.append(
                    f"Hai cạnh trực tiếp hỗ trợ suy luận là {source_label} -> {target_label}"
                    f"{f' ({own_a_pct})' if own_a_pct else ''} và {spouse_label} -> {target_label}"
                    f"{f' ({own_b_pct})' if own_b_pct else ''}."
                )
            if combined_pct:
                explanation_lines.append(
                    f"Tổng tỷ lệ sở hữu gộp của cặp gia đình tại {target_label} là khoảng {combined_pct}, "
                    f"vì vậy hệ thống ghi nhận cạnh suy luận «{rel_label_ui}» thay vì chỉ nhìn từng cá nhân riêng lẻ."
                )

        elif resolved_rule_id in ("R02", "R03"):
            path_tokens = [p.strip() for p in str(rel_props.get("path") or "").replace("⇔", "→").split("→") if p.strip()]
            bridge_id = path_tokens[1] if len(path_tokens) >= 3 else None
            support = None
            if bridge_id:
                support = session.run(
                    """
                    MATCH (a:Entity {id: $source_id})
                    MATCH (b:Entity {id: $bridge_id})
                    MATCH (c:Entity {id: $target_id})
                    OPTIONAL MATCH (a)-[r1]->(b)
                    OPTIONAL MATCH (b)-[r2:CÓ_CÔNG_TY_CON]->(c)
                    OPTIONAL MATCH (c)-[r2_rev:LÀ_CÔNG_TY_CON_CỦA]->(b)
                    RETURN b.id AS bridge_id, b.name AS bridge_name, b.type AS bridge_type, b.symbol AS bridge_symbol,
                           coalesce(r1.label, type(r1), '') AS r1_label,
                           r1.ownership AS own_ab,
                           coalesce(r2.label, r2_rev.label, type(r2), type(r2_rev), '') AS r2_label,
                           coalesce(r2.ownership, r2_rev.ownership) AS own_bc,
                           CASE WHEN r2 IS NOT NULL THEN 'out' WHEN r2_rev IS NOT NULL THEN 'in' ELSE '' END AS bridge_dir
                    LIMIT 1
                    """,
                    source_id=source_id,
                    bridge_id=bridge_id,
                    target_id=target_id,
                ).single()

            indirect_pct = _fmt_pct(rel_props.get("indirect_ownership_pct"))
            r1_pct = _fmt_pct(rel_props.get("r1_ownership"))
            r2_pct = _fmt_pct(rel_props.get("r2_ownership"))
            bridge_label = bridge_id or "thực thể trung gian"

            if support and support.get("bridge_id"):
                bridge_id = support.get("bridge_id")
                bridge_label = _entity_label(
                    support.get("bridge_name"),
                    bridge_id,
                    support.get("bridge_symbol") or "",
                )
                _add_focus_node(
                    nodes_map,
                    bridge_id,
                    support.get("bridge_name"),
                    support.get("bridge_type"),
                    support.get("bridge_symbol") or "",
                )
                if support.get("r1_label"):
                    _add_focus_edge(
                        edges_out,
                        edge_seen,
                        source_id,
                        bridge_id,
                        _edge_label_with_pct(
                            support.get("r1_label"),
                            support.get("own_ab"),
                            fraction_hint=True,
                        ),
                    )
                if support.get("r2_label"):
                    if support.get("bridge_dir") == "in":
                        _add_focus_edge(
                            edges_out,
                            edge_seen,
                            target_id,
                            bridge_id,
                            _edge_label_with_pct(
                                support.get("r2_label"),
                                support.get("own_bc"),
                                fraction_hint=True,
                            ),
                        )
                    else:
                        _add_focus_edge(
                            edges_out,
                            edge_seen,
                            bridge_id,
                            target_id,
                            _edge_label_with_pct(
                                support.get("r2_label"),
                                support.get("own_bc"),
                                fraction_hint=True,
                            ),
                        )
                if not r1_pct:
                    r1_pct = _fmt_pct(support.get("own_ab"), fraction_hint=True)
                if not r2_pct:
                    r2_pct = _fmt_pct(support.get("own_bc"), fraction_hint=True)

            summary = (
                f"{source_label} không nối trực tiếp tới {target_label}; cạnh «{rel_label_ui}» được suy ra "
                f"qua thực thể trung gian {bridge_label}."
            )
            explanation_lines.append(
                f"Chuỗi quan hệ gốc là {source_label} -> {bridge_label} -> {target_label}; đây là các cạnh trực tiếp được dùng để suy ra cạnh ẩn."
            )
            if r1_pct or r2_pct:
                explanation_lines.append(
                    f"Tỷ lệ ở chặng 1 là {r1_pct or 'không có'} và ở chặng 2 là {r2_pct or 'không có'}."
                )
            if indirect_pct:
                explanation_lines.append(
                    f"Sau khi nhân chuỗi tỷ lệ sở hữu/kiểm soát, hệ thống ra mức gián tiếp khoảng {indirect_pct} tại {target_label}."
                )
            if resolved_rule_id == "R03":
                level_raw = rel_props.get("influence_level") or ""
                level_vi = influence_level_display_vi(level_raw)
                explanation_lines.append(
                    f"{_law_display('R03')} sau đó ánh xạ {indirect_pct or 'mức gián tiếp này'} "
                    f"sang mức ảnh hưởng {level_vi} và ghi nhận loại cạnh suy luận «{rel_label_ui}»."
                )

        elif resolved_rule_id == "R04":
            holder_id = rel_props.get("shared_holder_id")
            support = session.run(
                """
                MATCH (n:Entity {id: $holder_id})
                MATCH (c:Entity {id: $source_id})
                MATCH (d:Entity {id: $target_id})
                OPTIONAL MATCH (n)-[r1:LÀ_CỔ_ĐÔNG_CỦA]->(c)
                OPTIONAL MATCH (n)-[r2:LÀ_CỔ_ĐÔNG_CỦA]->(d)
                RETURN n.id AS holder_id, n.name AS holder_name, n.type AS holder_type, n.symbol AS holder_symbol,
                       r1.ownership AS own_c,
                       r2.ownership AS own_d
                LIMIT 1
                """,
                holder_id=holder_id,
                source_id=source_id,
                target_id=target_id,
            ).single() if holder_id else None

            holder_label = rel_props.get("shared_holder_name") or holder_id or "cổ đông chung"
            own_c_pct = _fmt_pct(rel_props.get("ownership_c"), fraction_hint=True)
            own_d_pct = _fmt_pct(rel_props.get("ownership_d"), fraction_hint=True)

            if support and support.get("holder_id"):
                holder_id = support.get("holder_id")
                holder_label = _entity_label(
                    support.get("holder_name"),
                    holder_id,
                    support.get("holder_symbol") or "",
                )
                _add_focus_node(
                    nodes_map,
                    holder_id,
                    support.get("holder_name"),
                    support.get("holder_type"),
                    support.get("holder_symbol") or "",
                )
                _add_focus_edge(
                    edges_out,
                    edge_seen,
                    holder_id,
                    source_id,
                    _edge_label_with_pct("LÀ_CỔ_ĐÔNG_CỦA", support.get("own_c"), fraction_hint=True),
                )
                _add_focus_edge(
                    edges_out,
                    edge_seen,
                    holder_id,
                    target_id,
                    _edge_label_with_pct("LÀ_CỔ_ĐÔNG_CỦA", support.get("own_d"), fraction_hint=True),
                )
                if not own_c_pct:
                    own_c_pct = _fmt_pct(support.get("own_c"), fraction_hint=True)
                if not own_d_pct:
                    own_d_pct = _fmt_pct(support.get("own_d"), fraction_hint=True)

            summary = (
                f"{source_label} và {target_label} cùng liên kết với cổ đông lớn chung {holder_label}; "
                f"đó là cơ sở để sinh cạnh «{rel_label_ui}»."
            )
            explanation_lines.append(
                f"{holder_label} là thực thể trực tiếp kết nối cả hai doanh nghiệp trong subgraph này."
            )
            explanation_lines.append(
                f"Hai cạnh gốc là {holder_label} -> {source_label}{f' ({own_c_pct})' if own_c_pct else ''} "
                f"và {holder_label} -> {target_label}{f' ({own_d_pct})' if own_d_pct else ''}."
            )
            explanation_lines.append(
                "Vì cùng một cổ đông vượt ngưỡng công bố tại cả hai bên, hệ thống đánh dấu đây là liên kết doanh nghiệp qua cùng cổ đông lớn."
            )

        if not explanation_lines:
            explanation_lines.append(
                f"Đồ thị tập trung này chỉ giữ lại hai đầu mối {source_label}, {target_label} "
                "và các cạnh trực tiếp hỗ trợ tốt nhất cho quan hệ suy luận."
            )

        return jsonify({
            "summary": summary,
            "explanation_lines": explanation_lines,
            "graph": {
                "nodes": list(nodes_map.values()),
                "edges": edges_out,
            },
        })

@app.route("/api/rules", methods=["GET"])
def api_rules():
    """Returns the logic rules of the system."""
    return jsonify(RULES_API_PAYLOAD)

@app.route("/api/vllm/models", methods=["GET"])
@app.route("/api/ollama/models", methods=["GET"])
def api_llm_models():
    """Danh sách model: Ollama /api/tags hoặc OpenAI-compatible /v1/models (vLLM)."""
    models = _fetch_remote_models()
    return jsonify({"models": models, "current": MODEL_NAME, "backend": LLM_BACKEND})


@app.route("/api/llm/settings", methods=["GET", "POST"])
def api_llm_settings():
    """
    GET: cấu hình LLM hiện tại + models (masked API key).
    POST: cập nhật runtime và ghi .env.docker — chỉ dùng trong mạng tin cậy (không có auth).
    """
    if request.method == "GET":
        return jsonify({
            "backend": runtime.LLM_BACKEND,
            "base_url": runtime.LLM_BASE_URL,
            "model": runtime.MODEL_NAME,
            "models": _fetch_remote_models(),
            "api_key_masked": _mask_api_key(runtime.LLM_API_KEY),
        })
    data = request.get_json(force=True, silent=True) or {}
    backend = str(data.get("backend") or runtime.LLM_BACKEND).strip().lower()
    if backend not in _ALLOWED_LLM_BACKENDS:
        return jsonify({"error": f"LLM_BACKEND không hợp lệ: {backend}"}), 400
    base_url = str(data.get("base_url") or runtime.LLM_BASE_URL).strip()
    model = str(data.get("model") or runtime.MODEL_NAME).strip()
    try:
        payload = runtime.update_llm_runtime(
            backend=backend,
            base_url=base_url,
            model=model,
            api_key=str(data.get("api_key") or "").strip() or None,
            clear_api_key=bool(data.get("clear_api_key")),
        )
    except OSError as ex:
        print(f"[LLM] không ghi được .env.docker: {ex}")
        return jsonify({"error": str(ex), "applied_runtime": True}), 500
    except ValueError as ex:
        return jsonify({"error": str(ex)}), 400

    _sync_runtime_aliases()
    return jsonify({"ok": True, **payload})


@app.route('/api/llm/fetch-models', methods=['POST'])
def api_llm_fetch_models():
    """Lấy danh sách model từ base_url, backend và api_key được cung cấp."""
    data = request.get_json(force=True, silent=True) or {}
    base_url = str(data.get('base_url') or '').strip().rstrip('/')
    backend = str(data.get('backend') or 'openai').strip().lower()
    api_key = str(data.get('api_key') or '').strip()

    if not base_url:
        return jsonify({"error": "base_url rỗng"}), 400
    if backend not in _ALLOWED_LLM_BACKENDS:
        return jsonify({"error": f"backend không hợp lệ: {backend}"}), 400

    try:
        models = runtime.fetch_remote_models(
            base_url=base_url,
            backend=backend,
            api_key=api_key,
            fallback_model="",
        )
    except Exception as ex:
        print(f'[LLM] fetch models error: {ex}')
        return jsonify({'error': str(ex)}), 500

    return jsonify({'models': models})


@app.route('/api/query', methods=['POST'])
def api_query():
    print("\n--- Nhận Query Mới (Agentic Mode) ---")
    data = request.json
    query_text = data.get("query", "")
    history = data.get("history", [])
    if not query_text:
        return jsonify({"error": "Query rỗng"}), 400

    hidden_rule_query = _detect_hidden_rule_query(query_text)
    live_market_mode = _is_live_market_query(query_text)
    model = (data.get("model") or "").strip() or MODEL_NAME
    reasoning_enabled = data.get("reasoning", True)
    if reasoning_enabled:
        steps = ["Bắt đầu xử lý truy vấn (Reasoning: Bật)"]
    else:
        steps = ["Bắt đầu xử lý truy vấn (Reasoning: Tắt)"]

    quick_scope_match = _is_project_domain_query(
        query_text,
        hidden_rule_query=hidden_rule_query,
    )
    if not quick_scope_match and not _looks_like_named_entity_query(query_text):
        return jsonify({
            "answer": _OUT_OF_SCOPE_REPLY,
            "nodes": [],
            "edges": [],
            "graphs": [],
            "steps": [],
            "cypher": "",
        })

    # --- Bước 1: Phát hiện entity mục tiêu ---
    target_entity_id, target_display = extract_target_entity(query_text)
    if live_market_mode and target_entity_id and not _extract_symbol_tokens(query_text):
        q_norm = _normalize_vn_text(query_text)
        generic_market_q = any(
            p in q_norm
            for p in (
                "cong ty chung khoan nao",
                "cong ty nao",
                "ma nao",
                "chung khoan nao",
                "khoi luong giao dich cao nhat",
                "thanh khoan cao nhat",
            )
        )
        if generic_market_q:
            target_entity_id, target_display = None, None
    if not _is_project_domain_query(
        query_text,
        target_entity_id=target_entity_id,
        hidden_rule_query=hidden_rule_query,
    ):
        return jsonify({
            "answer": _OUT_OF_SCOPE_REPLY,
            "nodes": [],
            "edges": [],
            "graphs": [],
            "steps": [],
            "cypher": "",
        })
    if live_market_mode:
        steps.append(
            "📈 Câu hỏi thị trường/giao dịch: KG không có KLGD theo ngày — ưu tiên FireAnt API, sau đó tin web (RSS)."
        )
    if target_entity_id:
        steps.append(f"🔍 Phát hiện thực thể: {target_display} ({target_entity_id})")
    else:
        steps.append("🔍 Không phát hiện thực thể cụ thể, dùng tìm kiếm từ khóa.")

    # --- Bước 2: Semantic Search (RAG) ---
    steps.append("⏳ Đang tìm kiếm ngữ nghĩa trong Vector DB (RAG)...")
    contexts = _collect_rag_contexts(query_text, steps)

    # --- Bước 3: Graph Search (Agentic Loop) ---
    steps.append("⏳ Đang truy vấn Knowledge Graph (Neo4j)...")
    nodes_dict = {}
    edges = []
    graph_context = []
    cypher_used = ""
    hidden_rule_answer_lines = []
    hidden_rule_match_count = 0

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
                        edge_obj = {"from": s_id, "to": t_id, "label": e_label, "dashes": bool(inf)}
                        if "inferred_from" in keys:
                            edge_obj["inferred_from"] = rec["inferred_from"]
                        if "influence_level" in keys:
                            edge_obj["influence_level"] = rec["influence_level"]
                        edges.append(edge_obj)
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
                        elif inf:
                            bits = []
                            if rec.get("inferred_from"):
                                bits.append(f"luật={_law_display(rec['inferred_from'])}")
                            if rec.get("influence_level"):
                                bits.append(f"level={rec['influence_level']}")
                            if rec.get("indirect_pct") is not None:
                                try:
                                    bits.append(f"tỷ_lệ_gián_tiếp={float(rec['indirect_pct']):.4f}%")
                                except (TypeError, ValueError):
                                    pass
                            if rec.get("combined_pct") is not None:
                                try:
                                    bits.append(f"tỷ_lệ_gộp={float(rec['combined_pct']):.4f}%")
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
    if hidden_rule_query:
        steps.append(
            f"🎯 Nhận diện truy vấn theo quan hệ ẩn: {hidden_rule_query['name']} ({_law_display(hidden_rule_query['rule_id'])})"
        )
        if hidden_rule_query["rule_id"] == "R01":
            extra_return = "r.combined_ownership_pct AS combined_pct, NULL AS indirect_pct"
        elif hidden_rule_query["rule_id"] in ("R02", "R03"):
            extra_return = "NULL AS combined_pct, r.indirect_ownership_pct AS indirect_pct"
        else:
            extra_return = "NULL AS combined_pct, NULL AS indirect_pct"

        hidden_q = f"""
        MATCH (n:Entity)-[r]->(m:Entity)
        WHERE coalesce(r.inferred, false) = true
          AND (
            r.inferred_from = $rule_id
            OR coalesce(r.label, type(r)) IN $labels
            OR type(r) IN $labels
          )
        RETURN n.id AS source_id, n.name AS source_name, n.type AS source_group, n.symbol AS source_symbol,
               m.id AS target_id, m.name AS target_name, m.type AS target_group, m.symbol AS target_symbol,
               coalesce(r.label, type(r)) AS edge_label,
               coalesce(r.inferred, false) AS inferred,
               r.inferred_from AS inferred_from,
               r.influence_level AS influence_level,
               {extra_return}
        ORDER BY source_name, target_name
        LIMIT 100
        """
        cypher_used += f"\n\n{hidden_q.strip()}"
        with neo4j_driver.session() as session:
            hidden_records = list(
                session.run(
                    hidden_q,
                    rule_id=hidden_rule_query["rule_id"],
                    labels=hidden_rule_query["labels"],
                )
            )
            hidden_records = _dedupe_hidden_rule_records(hidden_records)

        hidden_rule_match_count = len(hidden_records)
        for rec in hidden_records:
            s_id, s_name = rec["source_id"], rec["source_name"]
            t_id, t_name = rec["target_id"], rec["target_name"]
            s_sym = rec.get("source_symbol")
            t_sym = rec.get("target_symbol")
            s_display = f"{s_name} ({s_sym})" if s_sym else (s_name or s_id)
            t_display = f"{t_name} ({t_sym})" if t_sym else (t_name or t_id)

            edge_raw = rec.get("edge_label") or ""
            edge_ui = inferred_edge_label_display_vi(
                edge_raw, rec.get("inferred_from") or ""
            )
            nodes_dict[s_id] = {"id": s_id, "label": s_display, "group": rec.get("source_group") or "DEFAULT"}
            nodes_dict[t_id] = {"id": t_id, "label": t_display, "group": rec.get("target_group") or "DEFAULT"}
            edges.append(
                {
                    "from": s_id,
                    "to": t_id,
                    "label": edge_ui,
                    "dashes": True,
                    "inferred_from": rec.get("inferred_from"),
                    "influence_level": rec.get("influence_level"),
                }
            )

            details = []
            if rec.get("combined_pct") is not None:
                try:
                    details.append(f"tỷ lệ gộp {float(rec['combined_pct']):.4f}%")
                except (TypeError, ValueError):
                    pass
            if rec.get("indirect_pct") is not None:
                try:
                    details.append(f"tỷ lệ gián tiếp {float(rec['indirect_pct']):.4f}%")
                except (TypeError, ValueError):
                    pass
            if rec.get("influence_level"):
                details.append(
                    f"mức {influence_level_display_vi(rec['influence_level'])}"
                )

            ctx_line = f"{s_display} --[{edge_ui}]--> {t_display}"
            if details:
                ctx_line = f"{ctx_line} ({'; '.join(details)})"
            graph_context.append(ctx_line)
            hidden_rule_answer_lines.append(ctx_line)

        steps.append(f"🕵️ Tìm thấy {hidden_rule_match_count} quan hệ ẩn khớp rule được hỏi.")

    suggested_intent = _detect_suggested_query_intent(query_text)
    intent_row_count = 0
    if suggested_intent and not hidden_rule_query:
        steps.append(f"🎯 Nhận diện intent gợi ý: {suggested_intent}")
        icypher, iparams = _intent_cypher(suggested_intent, query_text)
        if icypher:
            intent_row_count = execute_cypher(icypher, iparams)
            steps.append(
                f"📎 Intent Cypher ({suggested_intent}): {intent_row_count} bản ghi."
            )

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
    elif not hidden_rule_query and not suggested_intent and not live_market_mode:
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

    fireant_lines, fireant_md = [], ""
    if live_market_mode:
        fireant_lines, fireant_md = collect_fireant_market_data(query_text, steps)
        if fireant_lines:
            graph_context.extend(fireant_lines)

    live_news_items, live_news_diff_lines = _collect_live_news(
        query_text,
        target_display,
        graph_context,
        steps,
    )
    live_news_md = _format_live_news_markdown(live_news_items, live_news_diff_lines)

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

    if hidden_rule_query:
        if hidden_rule_match_count == 0:
            ans = f'Không có thực thể nào trong dữ liệu hiện tại có quan hệ ẩn "{hidden_rule_query["name"]}".'
        else:
            answer_lines = [
                f'Các thực thể có quan hệ ẩn "{hidden_rule_query["name"]}":'
            ]
            answer_lines.extend(f"- {line}" for line in hidden_rule_answer_lines[:30])
            if hidden_rule_match_count > 30:
                answer_lines.append(f"- ... và còn {hidden_rule_match_count - 30} quan hệ khác.")
            ans = "\n".join(answer_lines)

        if fireant_md:
            ans = f"{ans}\n{fireant_md}"
        if live_news_md:
            ans = f"{ans}\n{live_news_md}"

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

    # --- Bước 4: Tổng hợp LLM ---
    steps.append("🧠 Đang tổng hợp câu trả lời cuối cùng...")
    doc_text = "\n".join(contexts[:5])
    graph_text = "\n".join(list(set(graph_context))[:150])
    live_news_text = _format_live_news_context(live_news_items)
    fireant_text = "\n".join(fireant_lines) if fireant_lines else "(Không có dữ liệu FireAnt cho truy vấn này.)"
    history_ctx = "\n".join([f"{h['role']}: {h['content']}" for h in history[-3:]])
    instruct = (
        "Bạn là trợ lý AI chuyên gia về các công ty đã niêm yết trên sàn chứng khoán Việt Nam. Trả lời bằng tiếng Việt, ngắn gọn, DỰA TRÊN DỮ LIỆU ĐƯỢC CUNG CẤP từ query của Neo4j.\n"
        "QUAN TRỌNG: Khi dữ liệu có mã chứng khoán trong ngoặc (VD: VCB, ACB, VIB), BẮT BUỘC dùng đúng mã đó. Ngân hàng TMCP Ngoại thương Việt Nam (VCB) KHÁC Ngân hàng TMCP Quốc tế Việt Nam (VIB). Không được nhầm lẫn.\n"
        "Nếu thấy nhiều người cùng tên, phân biệt qua công ty (VD: ông Nguyễn Văn A (VCB) vs ông Nguyễn Văn A (ACB)).\n"
        "Trong 1 công ty, người lãnh đạo cao nhất là Chủ tịch HĐQT (LÃNH_ĐẠO_CAO_NHẤT). Trích xuất đúng tên người tương ứng chức vụ.\n"
        "Khi hỏi về quan hệ của 1 người, trình bày người thân từ hướng người được hỏi.\n"
        "Khi hỏi top cổ đông / khối lượng cổ phiếu: bắt buộc dùng các dòng 'Top cổ đông' hoặc cạnh có số_CP trong Dữ liệu Graph. Không được nói không có dữ liệu nếu các dòng đó tồn tại.\n"
        "Khi người dùng hỏi theo tên rule quan hệ ẩn, bắt buộc ưu tiên các cạnh inferred trong Dữ liệu Graph. Nếu đã có dòng inferred khớp rule thì phải liệt kê thực thể/quan hệ tương ứng, không được trả lời là không có.\n"
        "Nếu Dữ liệu Graph có ít nhất một dòng quan hệ trực tiếp liên quan câu hỏi (vd. LÃNH_ĐẠO_CAO_NHẤT + LÀ_CỔ_ĐÔNG_CỦA), bắt buộc trả lời CÓ và nêu ví dụ cụ thể (tên, mã). Không được nói 'không tìm thấy' hoặc 'không có dữ liệu Graph' khi các dòng đó đã có trong context.\n"
        "Nếu câu hỏi nhắc tới tin mới, diễn biến hiện tại, sự kiện gần đây, hãy dùng mục 'Tin tức thời gian thực' để trả lời ngắn gọn. Không được tự bịa tin, và không được nói là không có tin nếu mục đó đang có dữ liệu.\n"
        "Nếu mục 'Tin tức thời gian thực' ghi rõ là không lấy được tin phù hợp, chỉ khi đó mới nói là chưa có/không lấy được tin mới.\n"
        "Sau câu trả lời chính về KG/Cypher, có thể có thêm phần tin tức thời gian thực. Phần đó chỉ dùng để bổ sung bối cảnh mới, không được mâu thuẫn với dữ liệu Graph.\n"
    )
    if live_market_mode:
        instruct += (
            "\nĐÂY LÀ CÂU HỎI THỊ TRƯỜNG (khối lượng/giá/thanh khoản theo phiên hoặc ngày). "
            "Knowledge Graph KHÔNG chứa KLGD/giá theo ngày — KHÔNG được nói 'không có dữ liệu Graph' để từ chối. "
            "Ưu tiên mục 'Dữ liệu FireAnt (giá/KLGD)' nếu có bảng top KLGD hoặc giá — đây là số liệu API chính thức. "
            "Sau đó dùng 'Tin tức thời gian thực' để bổ sung bối cảnh (CafeF, Vietstock, VnExpress, …). "
            "Nếu FireAnt đã liệt kê top mã theo totalVolume, trả lời đúng thứ tự và ghi rõ mã + KLGD. "
            "Nếu cả FireAnt và tin đều không có bảng xếp hạng, nói rõ hạn chế.\n"
        )
    prompt = (
        f"{instruct}\n\n=== Lịch sử ===\n{history_ctx}"
        f"\n\n=== Dữ liệu Graph ===\n{graph_text}"
        f"\n\n=== Tài liệu ===\n{doc_text}"
        f"\n\n=== Dữ liệu FireAnt (giá/KLGD) ===\n{fireant_text}"
        f"\n\n=== Tin tức thời gian thực ===\n{live_news_text}"
        f"\n\nCâu hỏi: {query_text}"
    )
    try:
        print("[LLM] Đang tổng hợp câu trả lời...")
        response = llm_inference(prompt, model=model)
    except Exception as e:
        print(f"[LLM] Lỗi tổng hợp: {e}")
        return jsonify({
            "error": str(e),
            "answer": "",
            "nodes": list(nodes_dict.values()),
            "edges": edges,
            "graphs": graphs,
            "steps": steps + [f"❌ LLM: {e}"],
            "cypher": cypher_used.strip(),
        }), 502
    if isinstance(response, dict):
        ans = response.get("llm_response") or response.get("text") or str(response)
    elif isinstance(response, list) and response:
        ans = response[0].get("llm_response") or response[0].get("text") or str(response[0])
    else:
        ans = str(response)

    print("--- Trả kết quả ---")
    if fireant_md:
        ans = f"{ans.strip()}\n{fireant_md}"
    if live_news_md:
        ans = f"{ans.strip()}\n{live_news_md}"
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


# Types excluded when expanding family neighbors for a person node.
_FAMILY_EXPAND_EXCLUDE = [
    "LÀ_CỔ_ĐÔNG_CỦA",
    "LÀ_CÔNG_TY_CON_CỦA",
    "CÓ_CÔNG_TY_CON",
    "LÃNH_ĐẠO_CAO_NHẤT",
    "SỞ_HỮU_GIÁN_TIẾP",
    "CÓ_LỢI_ÍCH_GIÁN_TIẾP",
    "ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI",
    "KIỂM_SOÁT_GIÁN_TIẾP",
    "KIỂM_SOÁT_GIA_ĐÌNH",
]

_FAMILY_EXPAND_TYPES = list(
    dict.fromkeys(
        list(FAMILY_RELS_WHITELIST)
        + [
            "LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO",
            "VỢ_CHỒNG",
            "CHA_MẸ",
            "ANH_CHỊ",
            "NGƯỜI_THÂN",
            "MẸ",
            "BỐ",
            "ANH",
            "CHỊ",
            "CHỊ_DÂU",
            "CHỊ_EM_GÁI",
            "CHỊ_EM_TRAI",
            "ANH_EM_TRAI",
            "ANH_RỂ",
            "EM_RỂ",
            "CON_RỂ",
            "CON_DÂU",
            "ÔNG_NỘI",
            "BÀ_NỘI",
            "ÔNG_NGOẠI",
            "BÀ_NGOẠI",
        ]
    )
)


_COMPANY_EXPAND_TYPES = [
    "LÀ_CỔ_ĐÔNG_CỦA",
    "CÓ_CÔNG_TY_CON",
    "LÀ_CÔNG_TY_CON_CỦA",
    "LÃNH_ĐẠO_CAO_NHẤT",
    "CHỦ_TỊCH_HĐQT",
    "TỔNG_GIÁM_ĐỐC",
    "PHÓ_TỔNG_GIÁM_ĐỐC",
    "THÀNH_VIÊN_HĐQT",
    "THÀNH_VIÊN_BAN_KIỂM_SOÁT",
    "LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO",
    "SỞ_HỮU_GIÁN_TIẾP",
    "CÓ_LỢI_ÍCH_GIÁN_TIẾP",
    "ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI",
    "KIỂM_SOÁT_GIÁN_TIẾP",
]


def _neighbor_records(session, node_id, limit, scope):
    """Fetch neighbor rows for graph expand; scope=family | company filters rel types."""
    nid = str(node_id)
    if scope == "company" and (nid.startswith("C_") or nid.startswith("C_INST_")):
        q = """
        MATCH (n:Entity {id: $eid})-[r]-(m:Entity)
        WHERE type(r) IN $companyTypes
           OR type(r) STARTS WITH 'THÀNH_VIÊN'
           OR type(r) STARTS WITH 'PHÓ_'
           OR type(r) STARTS WITH 'CHỦ_TỊCH'
           OR type(r) STARTS WITH 'TỔNG_GIÁM'
           OR type(r) STARTS WITH 'KẾ_TOÁN'
           OR type(r) STARTS WITH 'ĐẠI_DIỆN'
        WITH n, m, r,
             CASE WHEN startNode(r) = n THEN n ELSE m END AS src,
             CASE WHEN startNode(r) = n THEN m ELSE n END AS tgt
        RETURN src.id AS sid, src.name AS sname, src.type AS sgrp, src.symbol AS ssym,
               tgt.id AS tid, tgt.name AS tname, tgt.type AS tgrp, tgt.symbol AS tsym,
               coalesce(r.label, type(r)) AS elabel, coalesce(r.inferred, false) AS inf,
               startNode(r).id AS edge_from, endNode(r).id AS edge_to
        LIMIT $lim
        """
        return session.run(q, eid=node_id, lim=limit, companyTypes=_COMPANY_EXPAND_TYPES)
    if scope == "company" and nid.startswith("P_"):
        q = """
        MATCH (n:Entity {id: $eid})-[r]-(m:Entity)
        WHERE type(r) IN $companyTypes
           OR type(r) STARTS WITH 'THÀNH_VIÊN'
           OR type(r) STARTS WITH 'PHÓ_'
           OR type(r) STARTS WITH 'CHỦ_TỊCH'
           OR type(r) STARTS WITH 'TỔNG_GIÁM'
           OR type(r) STARTS WITH 'KẾ_TOÁN'
           OR type(r) STARTS WITH 'ĐẠI_DIỆN'
        WITH n, m, r,
             CASE WHEN startNode(r) = n THEN n ELSE m END AS src,
             CASE WHEN startNode(r) = n THEN m ELSE n END AS tgt
        RETURN src.id AS sid, src.name AS sname, src.type AS sgrp, src.symbol AS ssym,
               tgt.id AS tid, tgt.name AS tname, tgt.type AS tgrp, tgt.symbol AS tsym,
               coalesce(r.label, type(r)) AS elabel, coalesce(r.inferred, false) AS inf,
               startNode(r).id AS edge_from, endNode(r).id AS edge_to
        LIMIT $lim
        """
        return session.run(q, eid=node_id, lim=limit, companyTypes=_COMPANY_EXPAND_TYPES)
    if scope == "family" and nid.startswith("P_"):
        q = """
        MATCH (n:Entity {id: $eid})-[r]-(m:Entity)
        WHERE type(r) IN $familyTypes
           OR type(r) = 'LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO'
           OR (
             n.id STARTS WITH 'P_' AND m.id STARTS WITH 'P_'
             AND NOT type(r) IN $excludeTypes
             AND (
               type(r) CONTAINS 'CHÁU'
               OR type(r) CONTAINS 'EM_'
               OR type(r) CONTAINS 'ANH_'
               OR type(r) CONTAINS 'CHỊ_'
               OR type(r) CONTAINS 'CON_'
               OR type(r) CONTAINS 'VỢ'
               OR type(r) CONTAINS 'CHỒNG'
               OR type(r) IN ['CHA_MẸ', 'NGƯỜI_THÂN', 'MẸ', 'BỐ', 'ANH', 'CHỊ', 'CÔ', 'CHÚ', 'CẬU', 'DÌ']
             )
           )
        WITH n, m, r,
             CASE WHEN startNode(r) = n THEN n ELSE m END AS src,
             CASE WHEN startNode(r) = n THEN m ELSE n END AS tgt
        RETURN src.id AS sid, src.name AS sname, src.type AS sgrp, src.symbol AS ssym,
               tgt.id AS tid, tgt.name AS tname, tgt.type AS tgrp, tgt.symbol AS tsym,
               coalesce(r.label, type(r)) AS elabel, coalesce(r.inferred, false) AS inf,
               startNode(r).id AS edge_from, endNode(r).id AS edge_to
        LIMIT $lim
        """
        return session.run(
            q,
            eid=node_id,
            lim=limit,
            familyTypes=_FAMILY_EXPAND_TYPES,
            excludeTypes=_FAMILY_EXPAND_EXCLUDE,
        )
    q_out = """
    MATCH (n:Entity {id: $eid})-[r]->(m:Entity)
    WITH n, m, r LIMIT $lim
    RETURN n.id AS sid, n.name AS sname, n.type AS sgrp, n.symbol AS ssym,
           m.id AS tid, m.name AS tname, m.type AS tgrp, m.symbol AS tsym,
           coalesce(r.label, type(r)) AS elabel, coalesce(r.inferred, false) AS inf,
           n.id AS edge_from, m.id AS edge_to
    """
    q_in = """
    MATCH (n:Entity)-[r]->(m:Entity {id: $eid})
    WITH n, m, r LIMIT $lim
    RETURN n.id AS sid, n.name AS sname, n.type AS sgrp, n.symbol AS ssym,
           m.id AS tid, m.name AS tname, m.type AS tgrp, m.symbol AS tsym,
           coalesce(r.label, type(r)) AS elabel, coalesce(r.inferred, false) AS inf,
           n.id AS edge_from, m.id AS edge_to
    """
    return list(session.run(q_out, eid=node_id, lim=limit)) + list(
        session.run(q_in, eid=node_id, lim=limit)
    )


@app.route("/api/node/<path:node_id>/neighbors", methods=["GET"])
def get_node_neighbors(node_id):
    """Get 1-hop neighbors of a node for lazy graph expansion."""
    limit = min(200, int(request.args.get("limit", 100)))
    scope = (request.args.get("scope") or "").strip().lower()
    if scope == "family" and not str(node_id).startswith("P_"):
        return jsonify({"nodes": [], "edges": []})
    if scope == "company" and not (
        str(node_id).startswith("C_") or str(node_id).startswith("P_")
    ):
        return jsonify({"nodes": [], "edges": []})
    nodes = {}
    edges = []
    try:
        with neo4j_driver.session() as session:
            rows = _neighbor_records(session, node_id, limit, scope)
            for rec in rows:
                s_sym = rec.get("ssym") or ""
                t_sym = rec.get("tsym") or ""
                s_label = f"{rec['sname']} ({s_sym})" if s_sym else (rec["sname"] or rec["sid"])
                t_label = f"{rec['tname']} ({t_sym})" if t_sym else (rec["tname"] or rec["tid"])
                nodes[rec["sid"]] = {"id": rec["sid"], "label": s_label, "group": rec["sgrp"] or "DEFAULT"}
                nodes[rec["tid"]] = {"id": rec["tid"], "label": t_label, "group": rec["tgrp"] or "DEFAULT"}
                edges.append({
                    "from": rec.get("edge_from") or rec["sid"],
                    "to": rec.get("edge_to") or rec["tid"],
                    "label": rec["elabel"] or "",
                    "inferred": bool(rec["inf"]),
                    "dashes": bool(rec["inf"])
                })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"nodes": list(nodes.values()), "edges": edges})


@app.route("/api/stats/edge-types", methods=["GET"])
def api_stats_edge_types():
    """Count edges per Neo4j relationship type for the relation-type browser."""
    try:
        with neo4j_driver.session() as session:
            rows = session.run(
                """
                MATCH ()-[r]->()
                RETURN type(r) AS type,
                       coalesce(r.inferred, false) AS inferred,
                       count(*) AS count
                ORDER BY count DESC
                """
            )
            types = [
                {
                    "type": rec["type"],
                    "count": rec["count"],
                    "inferred": bool(rec["inferred"]),
                }
                for rec in rows
            ]
            total = sum(t["count"] for t in types)
        return jsonify({"total_edges": total, "types": types})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
    try:
        import llm_preprocessor
        llm_preprocessor.rebuild_rag_corpus_from_processed_raw(force=False)
    except Exception as e:
        print(f"⚠️ rebuild_rag_corpus_from_processed_raw (bỏ qua): {e}")
    has_new_files, library = process_new_files()
    if has_new_files:
        run_ner_and_relation_extraction(library)
        run_hidden_relation_inference_loop()
        print("Cập nhật KG hoàn tất!")
        
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)  # Ẩn "Running on" mặc định
    print("Khởi động Web UI tại http://localhost:5001")
    app.run(host="0.0.0.0", port=5001)