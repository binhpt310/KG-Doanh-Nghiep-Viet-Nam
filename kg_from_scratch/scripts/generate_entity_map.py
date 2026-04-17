#!/usr/bin/env python3
"""
Tự động trích xuất entity_map từ dữ liệu tiền xử lý.
Chạy sau bước llm_preprocessor (đã có kg_nodes.json) hoặc khi có raw JSON.
Output: data/config/entity_map.json
"""
import os
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KG_NODES = PROJECT_ROOT / "data" / "kg_data" / "kg_nodes.json"
PROCESSED_RAW = PROJECT_ROOT / "data" / "processed_raw"
CONFIG_DIR = PROJECT_ROOT / "data" / "config"
ENTITY_MAP_OUT = CONFIG_DIR / "entity_map.json"
OVERRIDES_FILE = CONFIG_DIR / "entity_map_overrides.json"

# Từ bỏ qua khi tách phần tên riêng
STOPWORDS = [
    "ngân hàng", "thương mại", "cổ phần", "tmcp", "việt nam", "công ty",
    "tổng", "công ty tnhh", "ctcp", "chi nhánh", " tại "
]


def _normalize(s: str) -> str:
    """Chuẩn hóa cho key: lowercase, bỏ khoảng thừa."""
    if not s or not isinstance(s, str):
        return ""
    return " ".join(s.lower().strip().split())


def _extract_short_name(full_name: str) -> list[str]:
    """Trích các alias từ tên đầy đủ tiếng Việt."""
    if not full_name:
        return []
    n = _normalize(full_name)
    aliases = [n]
    # Bỏ từng stopword
    remain = n
    for w in STOPWORDS:
        remain = remain.replace(w, " ").strip()
    remain = re.sub(r"\s+", " ", remain).strip()
    if len(remain) >= 2:
        aliases.append(remain)
        # Nếu còn dài, thêm "ngân hàng X" cho phần đặc trưng
        parts = [p for p in remain.split() if len(p) >= 2]
        if len(parts) >= 2:
            key_part = " ".join(parts[-2:])  # 2 từ cuối thường là đặc trưng
            if key_part != remain:
                aliases.append(f"ngân hàng {key_part}")
    return aliases


def _is_listed_symbol(s: str) -> bool:
    """Chỉ coi là mã CK niêm yết nếu 2-5 chữ cái/số, không có INST/UNL."""
    if not s or len(s) > 5:
        return False
    if s.startswith("INST") or s.startswith("UNL"):
        return False
    return s.isalnum()


def _from_kg_nodes() -> dict[str, str]:
    """Đọc từ kg_nodes.json."""
    out = {}
    if not KG_NODES.exists():
        return out
    with open(KG_NODES, encoding="utf-8") as f:
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
        out[_normalize(symbol)] = cid
        if name:
            for a in _extract_short_name(name):
                if a and len(a) >= 2:
                    out[a] = cid
            out[_normalize(name)] = cid
    return out


def _from_banks_json() -> dict[str, str]:
    """Đọc từ banks.json (processed_raw) - có FullName chuẩn."""
    out = {}
    path = PROCESSED_RAW / "banks.json"
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for item in data:
        sym = item.get("Symbol") or item.get("symbol")
        full = item.get("FullName") or item.get("fullName") or ""
        if not sym:
            continue
        cid = f"C_{sym}"
        out[_normalize(sym)] = cid
        if full:
            out[_normalize(full)] = cid
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


def _from_overrides() -> dict[str, str]:
    """Đọc overrides do user tự thêm."""
    if not OVERRIDES_FILE.exists():
        return {}
    with open(OVERRIDES_FILE, encoding="utf-8") as f:
        return json.load(f)


def _is_valid_entity_id(eid: str) -> bool:
    """Chỉ giữ id dạng C_SYMBOL (mã CK 2-6 ký tự), loại C_INST_*, C_UNL_*."""
    if not eid or not eid.startswith("C_"):
        return False
    suf = eid[2:]
    if "_" in suf or len(suf) < 2 or len(suf) > 6:
        return False
    if suf.startswith("INST") or suf.startswith("UNL"):
        return False
    return suf.isalnum()


def run():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    merged: dict[str, str] = {}
    merged.update(_from_kg_nodes())
    merged.update(_from_banks_json())
    merged.update(_from_overrides())
    # Chỉ giữ mapping tới entity id hợp lệ (công ty niêm yết)
    merged = {k: v for k, v in merged.items() if _is_valid_entity_id(v)}
    # Sắp xếp key theo độ dài giảm dần để match dài trước
    sorted_items = sorted(merged.items(), key=lambda x: (-len(x[0]), x[0]))
    result = dict(sorted_items)
    with open(ENTITY_MAP_OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Đã ghi {len(result)} mapping vào {ENTITY_MAP_OUT}")
    return result


if __name__ == "__main__":
    run()
