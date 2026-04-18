import os
import shutil
import json
import csv
from dotenv import load_dotenv

# 1. SETUP THƯ MỤC
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
INGEST_DIR = os.path.join(DATA_DIR, "ingest")
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")
PROCESSED_RAW_DIR = os.path.join(DATA_DIR, "processed_raw")

os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(INGEST_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)
os.makedirs(PROCESSED_RAW_DIR, exist_ok=True)

load_dotenv()

# Không tự động nạp LLM nếu không có file PDF/TXT
prompter = None

prompt_instruction = """
Bạn là một chuyên gia phân tích dữ liệu tài chính. Hãy đọc tài liệu đính kèm.
Trích xuất toàn bộ thông tin về các công ty/ngân hàng, nhân sự, cổ đông, và công ty con liên quan...

BẮT BUỘC ĐỊNH DẠNG đầu ra thành các dòng văn bản đơn giản theo CẤU TRÚC CHÍNH XÁC sau (để hệ thống Regex có thể tự động parse):
1. Nhân sự/Lãnh đạo: "{Tên người} là {Chức vụ} của {Mã công ty}." (Ví dụ: "Đào Mạnh Kháng là Chủ tịch của ABB.")
2. Cổ đông: "{Tên tổ chức/cá nhân} là cổ đông của {Mã công ty}."
3. Công ty con: "{Tên công ty con} là công ty con của {Mã công ty}."
4. Các thông tin tiểu sử khác cứ xuất ra thành đoạn văn bình thường.

Tuyệt đối không sử dụng bảng markdown. Chỉ xuất ra các câu văn tiếng Việt, mỗi câu 1 dòng.
"""

PLACEHOLDER_RAG_TEXT = "Dữ liệu JSON đã được parse trực tiếp vào Graph."


def _format_pct(value):
    try:
        return f"{float(value) * 100:.4f}%"
    except (TypeError, ValueError):
        return None


def _append_unique(lines, seen, text):
    text = (text or "").strip()
    if not text or text in seen:
        return
    seen.add(text)
    lines.append(text)


def _structured_json_to_text(filename, data):
    """
    Chuyển JSON cấu trúc thành văn bản phẳng có ý nghĩa để RAG / keyword retrieval dùng được.
    Không còn trả về placeholder vô nghĩa như trước.
    """
    name = os.path.basename(filename).lower()
    lines = []
    seen = set()

    if name == "crawler_state.json":
        return ""

    if name == "banks.json":
        for bank in data:
            symbol = bank.get("Symbol") or bank.get("symbol") or ""
            full_name = bank.get("FullName") or bank.get("companyName") or bank.get("name") or symbol
            exchange = bank.get("Exchange") or bank.get("exchange") or "không rõ sàn"
            industry = bank.get("Industry") or bank.get("industry")
            line = f"{full_name} ({symbol}) niêm yết trên {exchange}."
            if industry:
                line += f" Ngành: {industry}."
            _append_unique(lines, seen, line)

    elif name == "holders.json":
        for item in data:
            symbol = item.get("symbol") or ""
            company_name = item.get("companyName") or symbol
            for holder in item.get("holders", []):
                holder_name = holder.get("name") or "Cổ đông chưa rõ tên"
                shares = holder.get("shares")
                pct = _format_pct(holder.get("ownership"))
                parts = [f"{holder_name} là cổ đông của {company_name} ({symbol})."]
                if shares:
                    parts.append(f"Nắm {shares} cổ phiếu.")
                if pct:
                    parts.append(f"Tỷ lệ sở hữu {pct}.")
                _append_unique(lines, seen, " ".join(parts))

    elif name == "officers.json":
        for item in data:
            symbol = item.get("symbol") or ""
            company_name = item.get("companyName") or symbol
            for officer in item.get("officers", []):
                person_name = officer.get("name") or "Nhân sự chưa rõ tên"
                position = officer.get("position") or "Lãnh đạo"
                _append_unique(
                    lines,
                    seen,
                    f"{person_name} giữ chức vụ {position} tại {company_name} ({symbol}).",
                )

    elif name == "subsidiaries.json":
        for item in data:
            parent_symbol = item.get("symbol") or ""
            parent_name = item.get("companyName") or parent_symbol
            for sub in item.get("subsidiaries", []):
                sub_name = sub.get("companyName") or sub.get("name") or sub.get("symbol") or "Công ty con chưa rõ tên"
                sub_symbol = sub.get("symbol") or ""
                pct = _format_pct(sub.get("ownership"))
                line = f"{parent_name} ({parent_symbol}) có công ty con {sub_name}"
                if sub_symbol:
                    line += f" ({sub_symbol})"
                line += "."
                if pct:
                    line += f" Tỷ lệ sở hữu {pct}."
                _append_unique(lines, seen, line)

    elif name == "individuals.json":
        for item in data:
            profile = item.get("profile", {})
            person_name = profile.get("name") or "Cá nhân chưa rõ tên"
            dob = profile.get("dateOfBirth")
            home_town = profile.get("homeTown")
            place_of_birth = profile.get("placeOfBirth")
            bio_parts = [f"{person_name} là một cá nhân trong dữ liệu."]
            if dob:
                bio_parts.append(f"Ngày sinh: {dob}.")
            if home_town:
                bio_parts.append(f"Quê quán: {home_town}.")
            if place_of_birth:
                bio_parts.append(f"Nơi sinh: {place_of_birth}.")
            _append_unique(lines, seen, " ".join(bio_parts))

            for rel in item.get("relations", []):
                rel_person = rel.get("relatedIndividual", {})
                rel_name = rel_person.get("name") or "người thân chưa rõ tên"
                relation_name = rel.get("relationName") or "người thân"
                _append_unique(
                    lines,
                    seen,
                    f"{person_name} có quan hệ {relation_name} với {rel_name}.",
                )

            for job in item.get("jobs", []):
                company_name = job.get("institutionName") or job.get("institutionSymbol") or "đơn vị chưa rõ tên"
                symbol = job.get("institutionSymbol") or ""
                position = job.get("positionName") or "nhân sự"
                line = f"{person_name} là {position} của {company_name}"
                if symbol:
                    line += f" ({symbol})"
                line += "."
                _append_unique(lines, seen, line)

    if not lines:
        return f"{PLACEHOLDER_RAG_TEXT}\n"
    return "\n".join(lines) + "\n"

def get_prompter():
    global prompter
    if prompter is None:
        from llmware.prompts import Prompt
        # Sử dụng model Qwen của llmware để hỗ trợ tiếng Việt cực tốt
        MODEL_NAME = "llmware/deepseek-qwen-7b-gguf"
        print(f"⏳ Đang nạp Model LLM Generative: {MODEL_NAME} để phân tích file...")
        prompter = Prompt().load_model(MODEL_NAME)
    return prompter

def normalize_family_relation(source_id, target_id, relation_label):
    """
    Chuẩn hóa quan hệ gia đình: Luôn quay về hướng Người lớn -> Người nhỏ.
    Nếu nhãn là CON, CHÁU, EM -> Đảo ngược và đổi nhãn.
    """
    rel = relation_label.replace(" ", "_").upper()
    
    # Mapping các quan hệ "ngược" (từ dưới lên) sang "xuôi" (từ trên xuống)
    flippable = {
        "CON": ("CHA_MẸ", True),
        "CON_TRAI": ("CHA_MẸ", True),
        "CON_GÁI": ("CHA_MẸ", True),
        "CHÁU": ("ÔNG_BÀ_BÁC_CHÚ", True),
        "EM": ("ANH_CHỊ", True),
        "EM_TRAI": ("ANH_CHỊ", True),
        "EM_GÁI": ("ANH_CHỊ", True),
        "VỢ": ("VỢ_CHỒNG", False), # Vợ chồng có thể để ngang hàng, nhưng ta chuẩn hóa nhãn
        "CHỒNG": ("VỢ_CHỒNG", False),
    }
    
    if rel in flippable:
        new_rel, should_flip = flippable[rel]
        if should_flip:
            return target_id, source_id, new_rel
        return source_id, target_id, new_rel
        
    return source_id, target_id, rel

def process_structured_json(file_path):
    import json
    import os
    
    print(f"   -> [JSON Parser]: Xử lý trực tiếp file JSON {file_path} thành Nodes/Edges...")
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    kg_dir = os.path.join(DATA_DIR, "kg_data")
    os.makedirs(kg_dir, exist_ok=True)
    
    nodes_file = os.path.join(kg_dir, "kg_nodes.json")
    edges_file = os.path.join(kg_dir, "kg_edges.json")
    
    # Load existing nodes/edges to append
    nodes = []
    if os.path.exists(nodes_file):
        with open(nodes_file, 'r', encoding='utf-8') as f:
            try:
                nodes = json.load(f)
            except:
                pass
                
    edges = []
    if os.path.exists(edges_file):
        with open(edges_file, 'r', encoding='utf-8') as f:
            try:
                edges = json.load(f)
            except:
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
        if props is None: props = {}
        edge_key = f"{source}_{label}_{target}"
        if edge_key not in edges_set:
            edges.append({"source": source, "target": target, "label": label, "props": props})
            edges_set.add(edge_key)

    filename = os.path.basename(file_path).lower()
    
    if filename == "banks.json":
        for b in data:
            symbol = b.get("Symbol")
            if symbol:
                add_node(f"C_{symbol}", "Company", b.get("FullName", symbol), {"symbol": symbol, "price": b.get("Price")})
                
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
                
                # Relations
                for rel in item.get("relations", []):
                    rel_individual = rel.get("relatedIndividual", {})
                    rel_iid = rel_individual.get("individualID")
                    rel_name_vi = rel.get("relationName", "NGƯỜI_THÂN").replace(" ", "_").upper()
                    if rel_iid:
                        target_pid = f"P_{rel_iid}"
                        add_node(target_pid, "Person", rel_individual.get("name", ""), {})
                        
                        # Chuẩn hóa hướng quan hệ gia đình
                        src, tgt, final_rel = normalize_family_relation(target_pid, pid, rel_name_vi)
                        add_edge(src, tgt, final_rel)
                        
                # Jobs
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
                    if indiv_id is not None:
                        source_id = f"P_{indiv_id}"
                        add_node(source_id, "Person", h.get("name", ""), {})
                    elif inst_id is not None:
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
                        
    # Xuất thêm văn bản phẳng để tầng RAG/keyword retrieval có dữ liệu thật để tra cứu.
    output_text = _structured_json_to_text(filename, data)
    
    with open(nodes_file, 'w', encoding='utf-8') as f:
        json.dump(list(nodes_dict.values()), f, ensure_ascii=False, indent=2)
    with open(edges_file, 'w', encoding='utf-8') as f:
        json.dump(edges, f, ensure_ascii=False, indent=2)
        
    return output_text


def rebuild_rag_corpus_from_processed_raw(force=False):
    """
    Tự phục hồi corpus văn bản cho RAG từ processed_raw khi:
    - ingest đã trống sau khi pipeline chạy xong
    - processed đang chỉ chứa placeholder
    """
    rebuilt = 0
    if not os.path.exists(PROCESSED_RAW_DIR):
        return rebuilt

    for filename in os.listdir(PROCESSED_RAW_DIR):
        source_path = os.path.join(PROCESSED_RAW_DIR, filename)
        if not os.path.isfile(source_path) or not filename.lower().endswith(".json"):
            continue

        base_name = os.path.splitext(filename)[0]
        target_path = os.path.join(PROCESSED_DIR, f"{base_name}_normalized.txt")

        if not force and os.path.exists(target_path):
            try:
                with open(target_path, "r", encoding="utf-8") as existing:
                    current = existing.read().strip()
                if current and current != PLACEHOLDER_RAG_TEXT:
                    continue
            except Exception:
                pass

        try:
            with open(source_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            text = _structured_json_to_text(filename, data)
            if not text.strip():
                continue
            with open(target_path, "w", encoding="utf-8") as out:
                out.write(text.strip() + "\n")
            rebuilt += 1
        except Exception as e:
            print(f"⚠️ Không thể rebuild corpus từ {filename}: {e}")

    if rebuilt:
        print(f"✅ Đã rebuild {rebuilt} file corpus văn bản từ processed_raw.")
    return rebuilt

def process_raw_files():
    files = [f for f in os.listdir(RAW_DIR) if os.path.isfile(os.path.join(RAW_DIR, f))]
    if not files:
        print("✅ Không có file thô nào trong data/raw/ để xuất ra data/ingest/.")
        return

    print(f"🚀 Tìm thấy {len(files)} file thô. Bắt đầu tiền xử lý (LLM Preprocessor)...")
    
    # Xoá file kg cũ nếu chạy lại từ đầu với data raw
    kg_dir = os.path.join(DATA_DIR, "kg_data")
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
                final_text = process_structured_json(file_path)
            elif ext == ".csv":
                final_text = process_csv_file(file_path)
            else:
                final_text = None
                
            # Nếu final_text là None (do CSV không chuẩn hoặc là định dạng khác như PDF, TXT, DOCX...)
            if final_text is None:
                print(f"      [LLM Fallback]: Kích hoạt LLM để trích xuất file {filename}...")
                p = get_prompter()
                source = p.add_source_document(RAW_DIR, filename)
                responses = p.prompt_with_source(prompt_instruction, prompt_name="default_with_context")
                
                final_text = ""
                for i, response in enumerate(responses):
                    # check if response is dict or string
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
            if prompter:
                prompter.clear_source_materials()

if __name__ == "__main__":
    process_raw_files()
