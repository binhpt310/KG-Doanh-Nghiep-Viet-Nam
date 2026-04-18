"""
pipeline.py — Consolidated KG pipeline module.

Combines:
  - fireant_crawler.py      (crawl_fireant_data)
  - llm_preprocessor.py     (process_raw_files)
  - push_to_neo4j.py        (push_to_neo4j)
  - vietnam_symbols.py      (BANKS, get_all_symbols, etc.)
  - add_leader_family_relations.py  (add_leader_family_relations)
"""

import os
import re
import sys
import json
import csv
import time
import shutil
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from neo4j import GraphDatabase

# ============================================================================
# SECTION 1 — Vietnam Symbols (from vietnam_symbols.py)
# ============================================================================

BANKS = [
    "VCB", "BID", "CTG", "MBB",
    "ACB", "VPB", "TCB", "STB", "EIB", "HDB", "VPB", "TPB",
    "VIB", "OCB", "MSB", "SHB", "NVB", "LPB", "BVB", "NAB",
    "SCB", "SGB", "ABB", "VAB", "BAC", "KLB",
]

HOSE = [
    "VCB", "BID", "CTG", "MBB", "ACB", "VPB", "TCB", "STB", "EIB", "HDB",
    "VPB", "TPB", "VIB", "OCB", "MSB", "ABB",
    "VHM", "VIC", "VRE", "NVL", "KDH", "HDG", "SCR", "DXG", "NLG", "PDR",
    "BCF", "BCM", "TCH", "DIG", "ITC", "QCG", "LDG", "AHM",
    "VCB", "CTG", "HAG", "HNG", "VCG", "FCN", "CII", "CVC",
    "HPG", "HSG", "NKG", "SMC",
    "GAS", "PVS", "PVD", "BSR", "PVB", "PVP",
    "REE", "GVR", "PC1", "NT2", "PTB",
    "FPT", "CMG", "VGI", "CTR",
    "MWG", "FRT", "PNJ", "DCM",
    "VNM", "MSN", "SAB", "KDC", "VHC", "MPC", "TCT", "NSC",
    "GMD", "NVL", "PHP", "VTP",
    "SSI", "VND", "HCM", "VCI", "MBS", "CTS", "BSI", "FTS", "ORS", "AAS",
    "BMI", "BVH", "PVI", "QBI",
    "SVC", "SAM", "GIL", "TDC", "DTD", "HBC", "DPM", "DGC",
]

HNX = [
    "SHB", "NVB", "LPB", "BVB", "NAB", "SGB",
    "SHS", "VIX", "NDN",
    "PVC", "PVT", "PVP", "PIC",
    "TCD", "VCS", "NTP", "TVC",
    "NET", "TNG",
    "D2D", "VGC", "S99", "TIG", "VFS", "HUT", "CEO", "RCL", "VCC", "TDW",
    "TDT", "DDV", "KTS", "MHL", "L14", "DNT", "DTA", "PBT", "T10", "EVF",
]

UPCOM = [
    "VCB", "SAB", "ACV", "GVR", "QNS", "BWE", "NBC", "VGC", "PHC", "TCD",
    "CJC", "TST", "HUT", "VE1", "VE2", "CCV", "T10",
]


def get_all_symbols(include_banks_first=True):
    """Trả về danh sách tất cả symbols (không trùng)."""
    all_symbols = set()
    ordered = []
    if include_banks_first:
        for s in BANKS:
            if s not in all_symbols:
                all_symbols.add(s)
                ordered.append(s)
    for s in HOSE + HNX + UPCOM:
        if s not in all_symbols:
            all_symbols.add(s)
            ordered.append(s)
    return ordered


# ============================================================================
# SECTION 2 — Fireant Crawler (from fireant_crawler.py)
# ============================================================================

FIREANT_TOKEN = os.getenv("FIREANT_TOKEN", "").strip()
CRAWLER_BASE_URL = os.getenv("FIREANT_BASE_URL", "https://restv2.fireant.vn").rstrip("/")

CRAWLER_HEADERS = {
    "Content-Type": "application/json",
}
if FIREANT_TOKEN:
    CRAWLER_HEADERS["Authorization"] = f"Bearer {FIREANT_TOKEN}"

# Use the same RAW_DIR as the preprocessor so files are shared
RAW_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "raw"))
INGEST_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "ingest"))
PROCESSED_RAW_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "processed_raw"))

os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(INGEST_DIR, exist_ok=True)
os.makedirs(PROCESSED_RAW_DIR, exist_ok=True)

REQUEST_DELAY = 0.5
MAX_RETRIES = 5
RETRY_DELAY = 10
INDIVIDUAL_DELAY = 1.0

STATE_FILE = os.path.join(RAW_DIR, "crawler_state.json")
# Also check processed_raw for backward compatibility
_STATE_FILE_LEGACY = os.path.join(PROCESSED_RAW_DIR, "crawler_state.json")


def _save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _load_state():
    # Check primary location first
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    # Fallback to legacy location
    if os.path.exists(_STATE_FILE_LEGACY):
        print(f"⚠️  Loading state from legacy location: {_STATE_FILE_LEGACY}")
        with open(_STATE_FILE_LEGACY, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "crawled_symbols": [],
        "crawled_individuals": [],
        "last_step": None,
    }


def _load_json_file(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_json_file(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _api_get(endpoint, params=None):
    if not FIREANT_TOKEN:
        raise RuntimeError("Missing FIREANT_TOKEN. Set it in your local .env before crawling.")
    url = f"{CRAWLER_BASE_URL}/{endpoint}"
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=CRAWLER_HEADERS, params=params, timeout=60)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                wait_time = RETRY_DELAY * (attempt + 1)
                print(f"      ⏳ Rate limited (429). Waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            elif resp.status_code == 401:
                print(f"      ❌ Unauthorized (401). Token may be expired.")
                return None
            elif resp.status_code == 404:
                return None
            else:
                print(f"      ⚠️ HTTP {resp.status_code} for {endpoint}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                continue
        except requests.exceptions.Timeout:
            print(f"      ⏱️  Timeout (attempt {attempt + 1}/{MAX_RETRIES})")
            time.sleep(RETRY_DELAY)
        except requests.exceptions.RequestException as e:
            print(f"      ⚠️ Request error (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            time.sleep(RETRY_DELAY)
    print(f"      ❌ Failed after {MAX_RETRIES} retries: {endpoint}")
    return None


def _safe_get_list(data, key=None):
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if key and key in data:
            result = data[key]
            return result if isinstance(result, list) else []
        for k in ["data", "results", "items", "list"]:
            if k in data and isinstance(data[k], list):
                return data[k]
    return []


def _crawl_company_info(symbol):
    data = _api_get(f"symbols/{symbol}")
    if data and isinstance(data, dict):
        return {
            "Symbol": data.get("symbol", symbol),
            "FullName": data.get("companyName", data.get("name", "")),
            "Price": data.get("currentPrice", data.get("price", None)),
            "Exchange": data.get("exchange", ""),
            "Industry": data.get("industry", ""),
        }
    return {"Symbol": symbol, "FullName": "", "Price": None, "Exchange": "", "Industry": ""}


def _crawl_officers(symbol):
    data = _api_get(f"symbols/{symbol}/officers")
    officers = _safe_get_list(data)
    if officers:
        return {"symbol": symbol, "officers": officers}
    return None


def _crawl_holders(symbol):
    data = _api_get(f"symbols/{symbol}/holders")
    holders = _safe_get_list(data)
    if holders:
        return {"symbol": symbol, "holders": holders}
    return None


def _crawl_subsidiaries(symbol):
    data = _api_get(f"symbols/{symbol}/subsidiaries")
    subsidiaries = _safe_get_list(data)
    if subsidiaries:
        return {"symbol": symbol, "subsidiaries": subsidiaries}
    return None


def _crawl_individual_profile(individual_id):
    return _api_get(f"individuals/{individual_id}/profile")


def _crawl_individual_jobs(individual_id):
    data = _api_get(f"individuals/{individual_id}/jobs")
    return _safe_get_list(data)


def _crawl_individual_assets(individual_id):
    data = _api_get(f"individuals/{individual_id}/assets")
    return _safe_get_list(data)


def _crawl_individual_relations(individual_id):
    data = _api_get(f"individuals/{individual_id}/relations")
    return _safe_get_list(data)


def _crawl_all_company_data(symbols, state):
    crawled = set(state.get("crawled_symbols", []))

    # Check both raw and processed_raw locations
    officers_data = _load_json_file(os.path.join(RAW_DIR, "officers.json")) or \
                    _load_json_file(os.path.join(PROCESSED_RAW_DIR, "officers.json")) or []
    holders_data = _load_json_file(os.path.join(RAW_DIR, "holders.json")) or \
                   _load_json_file(os.path.join(PROCESSED_RAW_DIR, "holders.json")) or []
    subsidiaries_data = _load_json_file(os.path.join(RAW_DIR, "subsidiaries.json")) or \
                        _load_json_file(os.path.join(PROCESSED_RAW_DIR, "subsidiaries.json")) or []
    banks_data = _load_json_file(os.path.join(RAW_DIR, "banks.json")) or \
                 _load_json_file(os.path.join(PROCESSED_RAW_DIR, "banks.json")) or []

    banks_symbols = {b.get("Symbol") for b in banks_data if b.get("Symbol")}
    officers_symbols = {o.get("symbol") for o in officers_data}
    holders_symbols = {h.get("symbol") for h in holders_data}
    subsidiaries_symbols = {s.get("symbol") for s in subsidiaries_data}

    total = len(symbols)
    for i, symbol in enumerate(symbols):
        if symbol in crawled:
            print(f"  [{i + 1}/{total}] Skipping {symbol} (already crawled)")
            continue

        print(f"  [{i + 1}/{total}] Crawling {symbol}...")

        if symbol not in banks_symbols:
            info = _crawl_company_info(symbol)
            if info and info not in banks_data:
                banks_data.append(info)

        if symbol not in officers_symbols:
            officers = _crawl_officers(symbol)
            if officers:
                officers_data.append(officers)
                print(f"    ✅ {len(officers.get('officers', []))} officers")

        if symbol not in holders_symbols:
            holders = _crawl_holders(symbol)
            if holders:
                holders_data.append(holders)
                print(f"    ✅ {len(holders.get('holders', []))} holders")

        if symbol not in subsidiaries_symbols:
            subs = _crawl_subsidiaries(symbol)
            if subs:
                subsidiaries_data.append(subs)
                print(f"    ✅ {len(subs.get('subsidiaries', []))} subsidiaries")

        crawled.add(symbol)
        state["crawled_symbols"] = list(crawled)
        state["last_step"] = "company_data"
        _save_state(state)

        _save_json_file(os.path.join(RAW_DIR, "banks.json"), banks_data)
        _save_json_file(os.path.join(RAW_DIR, "officers.json"), officers_data)
        _save_json_file(os.path.join(RAW_DIR, "holders.json"), holders_data)
        _save_json_file(os.path.join(RAW_DIR, "subsidiaries.json"), subsidiaries_data)

        time.sleep(REQUEST_DELAY)

    print(f"\n✅ Completed company data crawl.")
    print(f"   Banks: {len(banks_data)}, Officers: {len(officers_data)}, "
          f"Holders: {len(holders_data)}, Subsidiaries: {len(subsidiaries_data)}")


def _collect_individual_ids():
    individual_ids = set()
    # Check both locations
    officers = _load_json_file(os.path.join(RAW_DIR, "officers.json")) or \
               _load_json_file(os.path.join(PROCESSED_RAW_DIR, "officers.json")) or []
    for item in officers:
        for off in item.get("officers", []):
            iid = off.get("individualID")
            if iid:
                individual_ids.add(int(iid))
    holders = _load_json_file(os.path.join(RAW_DIR, "holders.json")) or \
              _load_json_file(os.path.join(PROCESSED_RAW_DIR, "holders.json")) or []
    for item in holders:
        for h in item.get("holders", []):
            iid = h.get("individualHolderID")
            if iid:
                individual_ids.add(int(iid))
    print(f"📋 Found {len(individual_ids)} unique individual IDs")
    return sorted(individual_ids)


def _crawl_all_individuals(state):
    crawled = set(state.get("crawled_individuals", []))
    individual_ids = _collect_individual_ids()

    individuals_data = _load_json_file(os.path.join(RAW_DIR, "individuals.json")) or \
                       _load_json_file(os.path.join(PROCESSED_RAW_DIR, "individuals.json")) or []
    crawled_ids = {
        int(item.get("profile", {}).get("individualID", 0))
        for item in individuals_data
        if item.get("profile", {}).get("individualID")
    }

    total = len(individual_ids)
    success_count = 0
    error_count = 0

    for i, iid in enumerate(individual_ids):
        if iid in crawled or iid in crawled_ids:
            print(f"  [{i + 1}/{total}] Skipping individual {iid} (already crawled)")
            continue

        print(f"  [{i + 1}/{total}] Crawling individual {iid}...")

        profile = _crawl_individual_profile(iid)
        jobs = _crawl_individual_jobs(iid)
        assets = _crawl_individual_assets(iid)
        relations = _crawl_individual_relations(iid)

        if profile and isinstance(profile, dict):
            record = {
                "profile": profile,
                "jobs": jobs,
                "assets": assets,
                "relations": relations,
            }
            individuals_data.append(record)
            success_count += 1
        else:
            error_count += 1
            print(f"    ⚠️ No profile data for {iid}")

        crawled.add(iid)
        state["crawled_individuals"] = list(crawled)
        state["last_step"] = "individuals"
        _save_state(state)

        _save_json_file(os.path.join(RAW_DIR, "individuals.json"), individuals_data)
        time.sleep(INDIVIDUAL_DELAY)

        if (i + 1) % 50 == 0:
            print(f"  📊 Progress: {i + 1}/{total} ({(i + 1) / total * 100:.1f}%), Success: {success_count}")

    print(f"\n✅ Completed individual crawl.")
    print(f"   Success: {success_count}, Errors: {error_count}, Total: {len(individuals_data)}")


def crawl_fireant_data(symbols=None, skip_individuals=False, reset=False, banks_only=False):
    """
    Main crawl function — callable entry point.

    Args:
        symbols: list of stock symbols to crawl (default: all)
        skip_individuals: if True, skip individual profile crawl
        reset: if True, reset crawl state and start fresh
        banks_only: if True, only crawl bank symbols
    """
    print("=" * 60)
    print("🚀 FIREANT API CRAWLER")
    print("=" * 60)

    if reset and os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
        print("🗑️  Reset crawler state")

    if symbols is None:
        symbols = get_all_symbols()

    if banks_only:
        symbols = list(set(BANKS))
        print(f"🏦 Bank-only mode: {len(symbols)} symbols")

    state = _load_state()
    print(f"\n📊 Resume state: {len(state.get('crawled_symbols', []))} symbols, "
          f"{len(state.get('crawled_individuals', []))} individuals crawled")

    print("\n📌 STEP 1: Crawling company data (officers, holders, subsidiaries)...")
    _crawl_all_company_data(symbols, state)

    if not skip_individuals:
        print("\n📌 STEP 2: Crawling individual data (profiles, jobs, assets, relations)...")
        _crawl_all_individuals(state)

    print("\n" + "=" * 60)
    print("✅ CRAWL COMPLETE!")
    print(f"Output files in {RAW_DIR}:")
    for fname in ["banks.json", "officers.json", "holders.json", "subsidiaries.json", "individuals.json"]:
        fpath = os.path.join(RAW_DIR, fname)
        if os.path.exists(fpath):
            size = os.path.getsize(fpath)
            print(f"  {fname}: {size:,} bytes")
    print("=" * 60)


# ============================================================================
# SECTION 3 — LLM Preprocessor (from llm_preprocessor.py)
# ============================================================================

# Note: prompter is lazily initialized
_prompter = None
_prompt_instruction = """
Bạn là một chuyên gia phân tích dữ liệu tài chính. Hãy đọc tài liệu đính kèm.
Trích xuất toàn bộ thông tin về các công ty/ngân hàng, nhân sự, cổ đông, và công ty con liên quan...

BẮT BUỘC ĐỊNH DẠNG đầu ra thành các dòng văn bản đơn giản theo CẤU TRÚC CHÍNH XÁC sau (để hệ thống Regex có thể tự động parse):
1. Nhân sự/Lãnh đạo: "{Tên người} là {Chức vụ} của {Mã công ty}." (Ví dụ: "Đào Mạnh Kháng là Chủ tịch của ABB.")
2. Cổ đông: "{Tên tổ chức/cá nhân} là cổ đông của {Mã công ty}."
3. Công ty con: "{Tên công ty con} là công ty con của {Mã công ty}."
4. Các thông tin tiểu sử khác cứ xuất ra thành đoạn văn bình thường.

Tuyệt đối không sử dụng bảng markdown. Chỉ xuất ra các câu văn tiếng Việt, mỗi câu 1 dòng.
"""


def _normalize_family_relation(source_id, target_id, relation_label):
    """
    Chuẩn hóa quan hệ gia đình: Luôn quay về hướng Người lớn -> Người nhỏ.
    Nếu nhãn là CON, CHÁU, EM -> Đảo ngược và đổi nhãn.
    """
    rel = relation_label.replace(" ", "_").upper()
    flippable = {
        "CON": ("CHA_MẸ", True),
        "CON_TRAI": ("CHA_MẸ", True),
        "CON_GÁI": ("CHA_MẸ", True),
        "CHÁU": ("ÔNG_BÀ_BÁC_CHÚ", True),
        "EM": ("ANH_CHỊ", True),
        "EM_TRAI": ("ANH_CHỊ", True),
        "EM_GÁI": ("ANH_CHỊ", True),
        "VỢ": ("VỢ_CHỒNG", False),
        "CHỒNG": ("VỢ_CHỒNG", False),
    }
    if rel in flippable:
        new_rel, should_flip = flippable[rel]
        if should_flip:
            return target_id, source_id, new_rel
        return source_id, target_id, new_rel
    return source_id, target_id, rel


def _get_prompter():
    global _prompter
    if _prompter is None:
        from llmware.prompts import Prompt
        MODEL_NAME = "llmware/deepseek-qwen-7b-gguf"
        print(f"⏳ Đang nạp Model LLM Generative: {MODEL_NAME} để phân tích file...")
        _prompter = Prompt().load_model(MODEL_NAME)
    return _prompter


def _process_structured_json(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    kg_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "kg_data"))
    os.makedirs(kg_dir, exist_ok=True)

    nodes_file = os.path.join(kg_dir, "kg_nodes.json")
    edges_file = os.path.join(kg_dir, "kg_edges.json")

    nodes = []
    if os.path.exists(nodes_file):
        with open(nodes_file, 'r', encoding='utf-8') as f:
            try:
                nodes = json.load(f)
            except Exception:
                pass

    edges = []
    if os.path.exists(edges_file):
        with open(edges_file, 'r', encoding='utf-8') as f:
            try:
                edges = json.load(f)
            except Exception:
                pass

    nodes_dict = {n["id"]: n for n in nodes}
    edges_set = set(f"{e['source']}_{e['label']}_{e['target']}" for e in edges)

    def add_node(node_id, label, name, props):
        if node_id not in nodes_dict:
            n = {"id": node_id, "label": label, "name": name, "props": props}
            nodes_dict[node_id] = n
        else:
            nodes_dict[node_id]["props"].update(props)
            if name:
                nodes_dict[node_id]["name"] = name

    def add_edge(source, target, label, props=None):
        if props is None:
            props = {}
        edge_key = f"{source}_{label}_{target}"
        if edge_key not in edges_set:
            edges.append({"source": source, "target": target, "label": label, "props": props})
            edges_set.add(edge_key)

    filename = os.path.basename(file_path).lower()

    # Build static exchange map from HOSE/HNX/UPCOM lists as fallback
    _exchange_map = {}
    for _s in HOSE:
        _exchange_map.setdefault(_s, "HOSE")
    for _s in HNX:
        _exchange_map.setdefault(_s, "HNX")
    for _s in UPCOM:
        _exchange_map.setdefault(_s, "UPCOM")

    if filename == "banks.json":
        for b in data:
            symbol = b.get("Symbol")
            if symbol:
                exchange = (b.get("Exchange") or "").strip().upper()
                if not exchange or exchange in ("", "NONE"):
                    exchange = _exchange_map.get(symbol, "")
                add_node(f"C_{symbol}", "Company", b.get("FullName", symbol), {
                    "symbol": symbol,
                    "price": b.get("Price"),
                    "exchange": exchange,
                    "industry": b.get("Industry", ""),
                })

    elif filename == "individuals.json":
        for item in data:
            profile = item.get("profile", {})
            iid = profile.get("individualID")
            if iid:
                pid = f"P_{iid}"
                name = profile.get("name", "")
                add_node(pid, "Person", name, {
                    "dateOfBirth": profile.get("dateOfBirth"),
                    "homeTown": profile.get("homeTown"),
                    "placeOfBirth": profile.get("placeOfBirth"),
                    "isForeign": profile.get("isForeign")
                })
                for rel in item.get("relations", []):
                    rel_individual = rel.get("relatedIndividual", {})
                    rel_iid = rel_individual.get("individualID")
                    rel_name_vi = rel.get("relationName", "NGƯỜI_THÂN").replace(" ", "_").upper()
                    if rel_iid:
                        target_pid = f"P_{rel_iid}"
                        add_node(target_pid, "Person", rel_individual.get("name", ""), {})
                        src, tgt, final_rel = _normalize_family_relation(target_pid, pid, rel_name_vi)
                        add_edge(src, tgt, final_rel)
                for job in item.get("jobs", []):
                    comp_symbol = job.get("institutionSymbol")
                    job_title = job.get("positionName", "LÀM_VIỆC_TẠI").replace(" ", "_").upper()
                    if comp_symbol:
                        cid = f"C_{comp_symbol}"
                        add_node(cid, "Company", job.get("institutionName", comp_symbol), {"symbol": comp_symbol})
                        add_edge(pid, cid, job_title)
                        if job_title == "CHỦ_TỊCH_HĐQT":
                            add_edge(pid, cid, "LÃNH_ĐẠO_CAO_NHẤT")

    elif filename == "officers.json":
        for item in data:
            symbol = item.get("symbol")
            if symbol:
                cid = f"C_{symbol}"
                for off in item.get("officers", []):
                    iid = off.get("individualID")
                    if iid:
                        pid = f"P_{iid}"
                        pos_name = off.get("position", "LÃNH_ĐẠO").replace(" ", "_").upper()
                        add_node(pid, "Person", off.get("name", ""), {})
                        add_edge(pid, cid, pos_name)
                        if pos_name == "CHỦ_TỊCH_HĐQT":
                            add_edge(pid, cid, "LÃNH_ĐẠO_CAO_NHẤT")

    elif filename == "subsidiaries.json":
        for item in data:
            parent_symbol = item.get("symbol")
            if parent_symbol:
                parent_cid = f"C_{parent_symbol}"
                for sub in item.get("subsidiaries", []):
                    sub_symbol = sub.get("symbol")
                    if sub_symbol:
                        sub_cid = f"C_{sub_symbol}"
                        add_node(sub_cid, "Company", sub.get("companyName", sub_symbol), {"symbol": sub_symbol})
                        sub_ownership = sub.get("ownership")
                        parent_props = {}
                        if sub_ownership and sub_ownership != 0:
                            parent_props["ownership"] = sub_ownership
                        add_edge(parent_cid, sub_cid, "CÓ_CÔNG_TY_CON", parent_props)
                        # Giữ thêm cạnh ngược để tương thích dữ liệu cũ và các truy vấn hiện có.
                        if sub_ownership and sub_ownership != 0:
                            add_edge(sub_cid, parent_cid, "LÀ_CÔNG_TY_CON_CỦA", {"ownership": sub_ownership})
                    else:
                        sub_id = f"C_UNL_{sub.get('institutionID')}"
                        add_node(sub_id, "Company", sub.get("companyName", ""), {})
                        add_edge(parent_cid, sub_id, "CÓ_CÔNG_TY_CON")

    elif filename == "holders.json":
        for item in data:
            comp_symbol = item.get("symbol")
            if comp_symbol:
                cid = f"C_{comp_symbol}"
                for h in item.get("holders", []):
                    indiv_id = h.get("individualHolderID")
                    inst_id = h.get("institutionHolderID")
                    source_id = None
                    if indiv_id:
                        source_id = f"P_{indiv_id}"
                        add_node(source_id, "Person", h.get("name", ""), {})
                    elif inst_id:
                        source_id = f"C_INST_{inst_id}"
                        add_node(source_id, "Company", h.get("name", ""), {})
                    if source_id:
                        # FILTER: Bỏ qua cổ đông có ownership = 0/None hoặc shares = 0 (thực thể ma, không nắm giữ cổ phần thực sự)
                        h_ownership = h.get("ownership")
                        h_shares = h.get("shares")
                        if h_ownership and h_ownership != 0 and h_shares and h_shares != 0:
                            add_edge(source_id, cid, "LÀ_CỔ_ĐÔNG_CỦA", {
                                "shares": h_shares,
                                "ownership": h_ownership
                            })

    output_text = "Dữ liệu JSON đã được parse trực tiếp vào Graph.\n"

    with open(nodes_file, 'w', encoding='utf-8') as f:
        json.dump(list(nodes_dict.values()), f, ensure_ascii=False, indent=2)
    with open(edges_file, 'w', encoding='utf-8') as f:
        json.dump(edges, f, ensure_ascii=False, indent=2)

    return output_text


def _process_csv_file(file_path):
    """Process CSV files (kept as placeholder from original)."""
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        rows = list(reader)
    lines = []
    for row in rows:
        lines.append(", ".join(row))
    return "\n".join(lines)


def process_raw_files():
    """
    Main preprocessor entry point.
    Reads files from data/raw/, processes them, and outputs to data/ingest/.
    """
    files = [f for f in os.listdir(RAW_DIR) if os.path.isfile(os.path.join(RAW_DIR, f))]
    if not files:
        print("✅ Không có file thô nào trong data/raw/ để xuất ra data/ingest/.")
        return

    print(f"🚀 Tìm thấy {len(files)} file thô. Bắt đầu tiền xử lý (LLM Preprocessor)...")

    kg_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "kg_data"))
    if os.path.exists(kg_dir):
        shutil.rmtree(kg_dir)

    for filename in files:
        file_path = os.path.join(RAW_DIR, filename)
        print(f"\n-> Đang phân tích file: {filename}")

        try:
            base_name = os.path.splitext(filename)[0]
            ext = os.path.splitext(filename)[1].lower()

            final_text = ""

            if ext == ".json":
                final_text = _process_structured_json(file_path)
            elif ext == ".csv":
                final_text = _process_csv_file(file_path)
            else:
                final_text = None

            if final_text is None:
                print(f"      [LLM Fallback]: Kích hoạt LLM để trích xuất file {filename}...")
                p = _get_prompter()
                source = p.add_source_document(RAW_DIR, filename)
                responses = p.prompt_with_source(_prompt_instruction, prompt_name="default_with_context")

                final_text = ""
                for i, response in enumerate(responses):
                    if isinstance(response, dict):
                        final_text += response.get("llm_response", "") + "\n\n"
                    elif isinstance(response, str):
                        final_text += response + "\n\n"
                p.clear_source_materials()

            if final_text.strip():
                ingest_file = os.path.join(INGEST_DIR, f"{base_name}_normalized.txt")
                with open(ingest_file, "w", encoding="utf-8") as f:
                    f.write(final_text.strip())
                print(f"   [Thành công] Đã trích xuất & lưu chuẩn hóa vào: {ingest_file}")
            else:
                print(f"   [Cảnh báo] File {filename} không trích xuất được text.")

            shutil.move(file_path, os.path.join(PROCESSED_RAW_DIR, filename))

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"   [Lỗi] Không thể xử lý file {filename}: {str(e)}")
            if _prompter:
                _prompter.clear_source_materials()


# ============================================================================
# SECTION 4 — Neo4j Push (from push_to_neo4j.py)
# ============================================================================

KG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "kg_data"))
KG_NODES_FILE = os.path.join(KG_DIR, "kg_nodes.json")
KG_EDGES_FILE = os.path.join(KG_DIR, "kg_edges.json")

# Default Neo4j connection — can be overridden by env vars
_DEFAULT_NEO4J_URI = "neo4j://localhost:7687"
_DEFAULT_NEO4J_USER = "neo4j"
_DEFAULT_NEO4J_PASS = "password123"


def _sanitize_rel_type(label: str) -> str:
    if not label:
        return "RELATED_TO"
    rel = label.strip().replace(" ", "_").replace("-", "_").replace("/", "_")
    if rel and not rel[0].isalpha():
        rel = "R_" + rel
    if not rel or rel == "_":
        return "RELATED_TO"
    return rel


def push_to_neo4j(neo4j_uri=None, neo4j_user=None, neo4j_pass=None, driver=None):
    """
    Push kg_nodes.json and kg_edges.json to Neo4j.

    If `driver` is provided, uses it directly (ignoring uri/user/pass).
    Otherwise creates a new driver from env vars or defaults.
    """
    if driver is None:
        uri = neo4j_uri or os.getenv("NEO4J_URI", _DEFAULT_NEO4J_URI)
        user = neo4j_user or os.getenv("NEO4J_USERNAME", _DEFAULT_NEO4J_USER)
        password = neo4j_pass or os.getenv("NEO4J_PASSWORD", _DEFAULT_NEO4J_PASS)
        driver = GraphDatabase.driver(uri, auth=(user, password))
        own_driver = True
    else:
        own_driver = False

    nodes = json.load(open(KG_NODES_FILE, "r", encoding="utf-8"))
    edges = json.load(open(KG_EDGES_FILE, "r", encoding="utf-8"))

    print(f"Loading {len(nodes)} nodes and {len(edges)} edges...")

    with driver.session() as session:
        print("Clearing existing data...")
        session.run("MATCH (n) DETACH DELETE n")

        print("Pushing nodes...")
        batch_size = 500
        for i in range(0, len(nodes), batch_size):
            batch = nodes[i: i + batch_size]
            session.run(
                """
                UNWIND $batch AS item
                MERGE (n:Entity {id: item.id})
                SET n.name = item.name, n.type = item.label
                SET n += item.props
                """,
                batch=batch,
            )
            print(f"  Nodes: {min(i + batch_size, len(nodes))}/{len(nodes)}")

        print("Pushing edges...")
        success_count = 0
        error_count = 0
        for i, edge in enumerate(edges):
            src = edge.get("source")
            tgt = edge.get("target")
            label = edge.get("label", "RELATED_TO")
            props = edge.get("props", {})
            rel_type = _sanitize_rel_type(label)

            query = f"""
            MATCH (a:Entity {{id: $src}})
            MATCH (b:Entity {{id: $tgt}})
            MERGE (a)-[r:`{rel_type}`]->(b)
            SET r.label = $label, r.inferred = false
            """
            if props:
                query += ", r += $props"

            try:
                session.run(query, src=src, tgt=tgt, label=label, props=props)
                success_count += 1
            except Exception as e:
                error_count += 1
                if error_count <= 5:
                    print(f"  Edge error [{rel_type}]: {e}")

            if (i + 1) % 1000 == 0:
                print(f"  Edges: {i + 1}/{len(edges)} (OK: {success_count}, Err: {error_count})")

        print(f"\nDone! Nodes: {len(nodes)}, Edges: {success_count}/{len(edges)} (Errors: {error_count})")

    with driver.session() as session:
        n_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        e_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        print(f"Neo4j: {n_count} nodes, {e_count} edges")

        print("\n--- Sample companies ---")
        for rec in session.run(
            "MATCH (n:Entity) WHERE n.type = 'Company' AND n.id STARTS WITH 'C_' AND NOT n.id STARTS WITH 'C_UNL' AND NOT n.id STARTS WITH 'C_INST' RETURN n.id, n.name LIMIT 10"
        ):
            print(f"  {rec['n.id']}: {rec['n.name']}")

        print("\n--- Sample persons ---")
        for rec in session.run(
            "MATCH (n:Entity) WHERE n.type = 'Person' RETURN n.id, n.name LIMIT 5"
        ):
            print(f"  {rec['n.id']}: {rec['n.name']}")

        print("\n--- Sample relationships ---")
        for rec in session.run(
            "MATCH (a)-[r]->(b) RETURN a.name, type(r), b.name LIMIT 10"
        ):
            print(f"  {rec['a.name']} --[{rec['type(r)']}]--> {rec['b.name']}")

    if own_driver:
        driver.close()


# ============================================================================
# SECTION 5 — Leader Family Relations (from scripts/add_leader_family_relations.py)
# ============================================================================

FAMILY_RELS_WHITELIST = [
    "ANH", "ANHEM_TRAI", "ANH_CHỊ", "ANH_CHỒNG", "ANH_CÙNG_BỐ_KHÁC_MẸ",
    "ANH_RỂ", "ANH_VỢ", "BÀ_NGOẠI", "BÀ_NỘI", "BÁC_ANH_CỦA_BỐ", "BÁC_ANH_CỦA_MẸ",
    "BÁC_CHỊ_CỦA_BỐ", "BÁC_CHỊ_CỦA_MẸ", "BỐ", "BỐ_CHỒNG", "BỐ_VỢ", "CHA_MẸ",
    "CHÁU_GÁI_CON_CỦA_ANH", "CHÁU_GÁI_CON_CỦA_CHỊ", "CHÁU_GÁI_CON_CỦA_EM_GÁI",
    "CHÁU_GÁI_CON_CỦA_EM_TRAI", "CHÁU_NGOẠI_GÁI", "CHÁU_NGOẠI_TRAI", "CHÁU_NỘI_GÁI",
    "CHÁU_NỘI_TRAI", "CHÁU_TRAI_CON_CỦA_ANH", "CHÁU_TRAI_CON_CỦA_CHỊ",
    "CHÁU_TRAI_CON_CỦA_EM_GÁI", "CHÁU_TRAI_CON_CỦA_EM_TRAI", "CHÚ",
    "CHỊ", "CHỊEM_GÁI", "CHỊ_CHỒNG", "CHỊ_DÂU", "CHỊ_DÂU_CỦA_CHỒNG", "CHỊ_VỢ",
    "CON_DÂU", "CON_RỂ", "CÔ", "CẬU", "DÌ",
    "EM_DÂU", "EM_DÂU_CỦA_CHỒNG", "EM_GÁI_CHỒNG", "EM_GÁI_CÙNG_BỐ_KHÁC_MẸ",
    "EM_GÁI_VỢ", "EM_RỂ", "EM_TRAI_CHỒNG", "EM_TRAI_CÙNG_BỐ_KHÁC_MẸ", "EM_TRAI_VỢ",
    "MẸ", "MẸ_CHỒNG", "MẸ_VỢ", "NGƯỜI_THÂN", "NGƯỜI_THÂN_QUA_HÔN_NHÂN",
    "VỢ_CHỒNG", "ÔNG_NGOẠI", "ÔNG_NỘI"
]

LEADER_RELS = ["LÃNH_ĐẠO_CAO_NHẤT", "CHỦ_TỊCH_HĐQT", "TỔNG_GIÁM_ĐỐC"]

FAM_DISPLAY = {
    "CHA_MẸ": "cha/mẹ", "MẸ": "mẹ", "BỐ": "bố", "ANH_CHỊ": "anh/chị", "VỢ_CHỒNG": "vợ/chồng",
    "CHỊ": "chị", "ANH": "anh", "NGƯỜI_THÂN": "người thân", "ÔNG_NỘI": "ông nội",
    "ÔNG_NGOẠI": "ông ngoại", "BÀ_NỘI": "bà nội", "BÀ_NGOẠI": "bà ngoại",
    "BỐ_VỢ": "bố vợ", "MẸ_VỢ": "mẹ vợ", "BỐ_CHỒNG": "bố chồng", "MẸ_CHỒNG": "mẹ chồng",
}


def add_leader_family_relations(driver):
    """
    Add LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO relations to Neo4j.

    For each (family)-[fam_rel]->(leader) and (leader)-[lead_rel]->(company),
    creates (family)-[:LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO]->(company).

    Args:
        driver: Neo4j GraphDatabase driver instance.

    Returns:
        Number of relations created/updated.
    """
    def create_relation(tx, family_id, company_id, company_name, leader_id, leader_name, position, fam_rel):
        display_fam = FAM_DISPLAY.get(fam_rel, fam_rel.replace("_", " ").lower())
        comp = company_name or company_id
        leader_rel = f"[{display_fam}] của [{leader_name}] có chức vụ là [{position}] [{comp}]"
        q = """
        MATCH (a:Entity {id: $fam_id})
        MATCH (b:Entity {id: $comp_id})
        MERGE (a)-[r:LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO]->(b)
        ON CREATE SET r.leaderRelationship = $lr, r.leaderName = $ln, r.leaderId = $lid,
                      r.position = $pos, r.familyRelation = $frel, r.label = 'LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO'
        ON MATCH SET r.leaderRelationship = $lr, r.leaderName = $ln, r.leaderId = $lid,
                     r.position = $pos, r.familyRelation = $frel
        """
        tx.run(q, fam_id=family_id, comp_id=company_id, lr=leader_rel, ln=leader_name,
               lid=leader_id, pos=position, frel=fam_rel)

    with driver.session() as session:
        session.run("MATCH ()-[r:LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO]->() DELETE r")
        q = """
        MATCH (leader:Entity)-[r1]->(company:Entity)
        WHERE company.id =~ 'C_[A-Z0-9]{2,6}'
        AND type(r1) IN $lead_rels
        MATCH (family:Entity)-[r2]->(leader)
        WHERE type(r2) IN $fam_rels
        RETURN DISTINCT family.id AS fam_id, company.id AS comp_id, company.name AS comp_name,
               leader.id AS leader_id, leader.name AS leader_name,
               r1.label AS position, type(r2) AS fam_rel
        """
        result = session.run(q, lead_rels=LEADER_RELS, fam_rels=FAMILY_RELS_WHITELIST)
        rows = list(result)
        created = 0
        for rec in rows:
            session.execute_write(
                create_relation,
                rec["fam_id"], rec["comp_id"], rec["comp_name"], rec["leader_id"],
                rec["leader_name"], rec["position"], rec["fam_rel"]
            )
            created += 1
        return created


# ============================================================================
# SECTION 6 — Entity Map Generator (from scripts/generate_entity_map.py)
# Kept for convenience; also callable from script.py
# ============================================================================

_STOPWORDS = [
    "ngân hàng", "thương mại", "cổ phần", "tmcp", "việt nam", "công ty",
    "tổng", "công ty tnhh", "ctcp", "chi nhánh", " tại "
]

_KG_NODES_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "kg_data", "kg_nodes.json"))
_PROCESSED_RAW_PATH = PROCESSED_RAW_DIR
_CONFIG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "config"))
_ENTITY_MAP_OUT = os.path.join(_CONFIG_DIR, "entity_map.json")
_OVERRIDES_FILE = os.path.join(_CONFIG_DIR, "entity_map_overrides.json")


def _normalize_str(s: str) -> str:
    if not s or not isinstance(s, str):
        return ""
    return " ".join(s.lower().strip().split())


def _extract_short_name(full_name: str) -> list:
    if not full_name:
        return []
    n = _normalize_str(full_name)
    aliases = [n]
    remain = n
    for w in _STOPWORDS:
        remain = remain.replace(w, " ").strip()
    remain = re.sub(r"\s+", " ", remain).strip()
    if len(remain) >= 2:
        aliases.append(remain)
        parts = [p for p in remain.split() if len(p) >= 2]
        if len(parts) >= 2:
            key_part = " ".join(parts[-2:])
            if key_part != remain:
                aliases.append(f"ngân hàng {key_part}")
    return aliases


def _is_listed_symbol(s: str) -> bool:
    if not s or len(s) > 5:
        return False
    if s.startswith("INST") or s.startswith("UNL"):
        return False
    return s.isalnum()


def _from_kg_nodes() -> dict:
    out = {}
    if not os.path.exists(_KG_NODES_PATH):
        return out
    with open(_KG_NODES_PATH, encoding="utf-8") as f:
        nodes = json.load(f)
    for node in nodes:
        nid = node.get("id", "")
        name = node.get("name", "")
        label = node.get("label", "")
        props = node.get("props") or {}
        if label != "Company":
            continue
        symbol = props.get("symbol")
        if not symbol and nid.startswith("C_") and len(nid) <= 8 and "_" not in nid[2:]:
            candidate = nid[2:]
            if _is_listed_symbol(candidate):
                symbol = candidate
        if not symbol:
            continue
        cid = f"C_{symbol}"
        out[_normalize_str(symbol)] = cid
        if name:
            for a in _extract_short_name(name):
                if a and len(a) >= 2:
                    out[a] = cid
            out[_normalize_str(name)] = cid
    return out


def _from_banks_json() -> dict:
    out = {}
    path = os.path.join(_PROCESSED_RAW_PATH, "banks.json")
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for item in data:
        sym = item.get("Symbol") or item.get("symbol")
        full = item.get("FullName") or item.get("fullName") or ""
        if not sym:
            continue
        cid = f"C_{sym}"
        out[_normalize_str(sym)] = cid
        if full:
            out[_normalize_str(full)] = cid
            for a in _extract_short_name(full):
                if a and len(a) >= 2:
                    out[a] = cid
        if "techcombank" in full.lower() or "kỹ thương" in full.lower():
            out["techcombank"] = cid
            out["tcb"] = cid
        if "ngoại thương" in full.lower():
            out["ngoại thương"] = cid
            out["vietcombank"] = cid
            out["vcb"] = cid
        if "đầu tư" in full.lower() and "phát triển" in full.lower():
            out["bidv"] = cid
            out["đầu tư và phát triển"] = cid
        if "công thương" in full.lower():
            out["vietinbank"] = cid
            out["công thương"] = cid
        if "eximbank" in full.lower() or "xuất nhập khẩu" in full.lower():
            out["eximbank"] = cid
        if "sài gòn" in full.lower() and "thương tín" in full.lower():
            out["sacombank"] = cid
        if "quân đội" in full.lower():
            out["mbbank"] = cid
            out["mb bank"] = cid
        if "việt nam thịnh vượng" in full.lower():
            out["vpbank"] = cid
        if "quốc tế" in full.lower() and "việt nam" in full.lower():
            out["vib"] = cid
    return out


def _from_overrides() -> dict:
    if not os.path.exists(_OVERRIDES_FILE):
        return {}
    with open(_OVERRIDES_FILE, encoding="utf-8") as f:
        return json.load(f)


def _is_valid_entity_id(eid: str) -> bool:
    if not eid or not eid.startswith("C_"):
        return False
    suf = eid[2:]
    if "_" in suf or len(suf) < 2 or len(suf) > 6:
        return False
    if suf.startswith("INST") or suf.startswith("UNL"):
        return False
    return suf.isalnum()


def generate_entity_map():
    """
    Generate entity_map.json from kg_nodes.json and banks.json.
    Output: data/config/entity_map.json
    """
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    merged: dict = {}
    merged.update(_from_kg_nodes())
    merged.update(_from_banks_json())
    merged.update(_from_overrides())
    merged = {k: v for k, v in merged.items() if _is_valid_entity_id(v)}
    sorted_items = sorted(merged.items(), key=lambda x: (-len(x[0]), x[0]))
    result = dict(sorted_items)
    with open(_ENTITY_MAP_OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Đã ghi {len(result)} mapping vào {_ENTITY_MAP_OUT}")
    return result


# ============================================================================
# SECTION 8 — AUTO CRAWL (Cập nhật dữ liệu mới nhất)
# ============================================================================

def crawl_and_update(symbols=None, skip_individuals=False, push_neo4j=True,
                     neo4j_driver=None, run_inference=True):
    """
    Crawl dữ liệu mới nhất từ Fireant API → Preprocess → Push lên Neo4j.

    Đây là hàm entry-point duy nhất để cập nhật toàn bộ pipeline.

    Args:
        symbols: Danh sách symbols cần crawl. None = crawl tất cả.
        skip_individuals: Bỏ qua crawl thông tin cá nhân (nhanh hơn).
        push_neo4j: Tự động push dữ liệu lên Neo4j sau khi crawl.
        neo4j_driver: Neo4j driver instance. Nếu None, sẽ tự tạo từ env vars.
        run_inference: Chạy hidden relation inference sau khi push.

    Returns:
        dict: {
            'crawled_symbols': int,
            'crawled_individuals': int,
            'nodes_count': int,
            'edges_count': int,
            'neo4j_pushed': bool
        }
    """
    from pathlib import Path

    raw_dir = Path(RAW_DIR)
    processed_raw_dir = Path(PROCESSED_RAW_DIR)

    # Step 1: Crawl
    print("\n" + "=" * 60)
    print("🔄 BƯỚC 1: CRAWL DỮ LIỆU TỪ FIREANT API")
    print("=" * 60)
    crawl_fireant_data(symbols=symbols, skip_individuals=skip_individuals)

    # Step 2: Preprocess
    print("\n" + "=" * 60)
    print("🔄 BƯỚC 2: PREPROCESS DỮ LIỆU")
    print("=" * 60)
    result = _process_raw_files_wrapper()

    # Handle None return when no data files exist
    if result is None:
        has_new, lib = False, None
    else:
        has_new, lib = result

    if not has_new:
        print("⚠️ Không có dữ liệu mới để xử lý.")
        return {
            'crawled_symbols': 0,
            'crawled_individuals': 0,
            'nodes_count': 0,
            'edges_count': 0,
            'neo4j_pushed': False
        }

    # Step 3: Push to Neo4j
    neo4j_pushed = False
    nodes_count = 0
    edges_count = 0

    if push_neo4j:
        print("\n" + "=" * 60)
        print("🔄 BƯỚC 3: PUSH DỮ LIỆU LÊN NEO4J")
        print("=" * 60)

        try:
            if neo4j_driver is None:
                neo4j_driver = GraphDatabase.driver(
                    os.getenv("NEO4J_URI", "neo4j://localhost:7687"),
                    auth=(os.getenv("NEO4J_USERNAME", "neo4j"),
                          os.getenv("NEO4J_PASSWORD", "password123"))
                )
                should_close = True
            else:
                should_close = False

            nodes_count, edges_count = push_to_neo4j(driver=neo4j_driver)

            # Step 4: Family relations enrichment
            print("\n" + "=" * 60)
            print("🔄 BƯỚC 4: LÀM GIÀU QUAN HỆ GIA ĐÌNH")
            print("=" * 60)
            add_leader_family_relations(neo4j_driver)

            # Step 5: Hidden relation inference
            if run_inference:
                print("\n" + "=" * 60)
                print("🔄 BƯỚC 5: SUY DIỄN QUAN HỆ ẨN")
                print("=" * 60)
                _run_hidden_relation_inference(neo4j_driver)

            if should_close:
                neo4j_driver.close()

            neo4j_pushed = True
        except Exception as e:
            print(f"⚠️ Lỗi khi push lên Neo4j: {e}")

    # Step 6: Generate entity map
    print("\n" + "=" * 60)
    print("🔄 BƯỚC 6: CẬP NHẬT ENTITY MAP")
    print("=" * 60)
    generate_entity_map()

    print("\n" + "=" * 60)
    print("✅ HOÀN TẤT CẬP NHẬT!")
    print(f"   Nodes: {nodes_count}")
    print(f"   Edges: {edges_count}")
    print(f"   Neo4j: {'✅' if neo4j_pushed else '❌'}")
    print("=" * 60)

    return {
        'nodes_count': nodes_count,
        'edges_count': edges_count,
        'neo4j_pushed': neo4j_pushed
    }


def _process_raw_files_wrapper():
    """Wrapper cho process_raw_files để trả về (has_new, lib)."""
    import llm_preprocessor
    return llm_preprocessor.process_raw_files()


def _run_hidden_relation_inference(driver):
    """Chạy suy diễn quan hệ ẩn trong Neo4j — sử dụng inference_rules module."""
    print("🔍 Bắt đầu suy diễn quan hệ ẩn (tất cả rules)...")
    from inference_rules import run_all_inference_rules
    results = run_all_inference_rules(driver, batch_size=500)
    print(f"✅ Kết quả inference: {results}")


# ============================================================================
# CLI Entry Point
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="KG Pipeline — Crawl, Process, Update Neo4j")
    subparsers = parser.add_subparsers(dest="command")

    # crawl
    p_crawl = subparsers.add_parser("crawl", help="Crawl dữ liệu từ Fireant API")
    p_crawl.add_argument("--symbols", nargs="*", help="Symbols cụ thể")
    p_crawl.add_argument("--banks-only", action="store_true", help="Chỉ crawl ngân hàng")
    p_crawl.add_argument("--skip-individuals", action="store_true", help="Bỏ qua individuals")
    p_crawl.add_argument("--reset", action="store_true", help="Reset state và crawl lại")

    # resume — alias crawl tiếp (không reset); thay thế script crawl_continue.py
    subparsers.add_parser("resume", help="Crawl tiếp từ crawler_state (giống: crawl không --reset)")

    # update
    p_update = subparsers.add_parser("update", help="Crawl → Preprocess → Push Neo4j (full pipeline)")
    p_update.add_argument("--symbols", nargs="*", help="Symbols cụ thể")
    p_update.add_argument("--banks-only", action="store_true", help="Chỉ crawl ngân hàng")
    p_update.add_argument("--skip-individuals", action="store_true", help="Bỏ qua individuals")
    p_update.add_argument("--no-push", action="store_true", help="Không push lên Neo4j")
    p_update.add_argument("--no-inference", action="store_true", help="Không chạy inference")

    # preprocess
    subparsers.add_parser("preprocess", help="Chỉ chạy preprocessor")

    # push
    subparsers.add_parser("push", help="Chỉ push lên Neo4j")

    # entity-map
    subparsers.add_parser("entity-map", help="Sinh lại entity_map.json")

    args = parser.parse_args()

    if args.command == "crawl":
        symbols = None
        if args.banks_only:
            symbols = list(set(BANKS))
        elif args.symbols:
            symbols = args.symbols
        crawl_fireant_data(symbols=symbols, skip_individuals=args.skip_individuals, reset=args.reset)

    elif args.command == "resume":
        crawl_fireant_data(symbols=None, skip_individuals=False, reset=False, banks_only=False)

    elif args.command == "update":
        symbols = None
        if args.banks_only:
            symbols = list(set(BANKS))
        elif args.symbols:
            symbols = args.symbols
        crawl_and_update(
            symbols=symbols,
            skip_individuals=args.skip_individuals,
            push_neo4j=not args.no_push,
            run_inference=not args.no_inference
        )

    elif args.command == "preprocess":
        _process_raw_files_wrapper()

    elif args.command == "push":
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "neo4j://localhost:7687"),
            auth=(os.getenv("NEO4J_USERNAME", "neo4j"),
                  os.getenv("NEO4J_PASSWORD", "password123"))
        )
        push_to_neo4j(driver=driver)
        driver.close()

    elif args.command == "entity-map":
        generate_entity_map()

    else:
        parser.print_help()
