import os
import shutil
import json
import csv
from dotenv import load_dotenv

# 1. SETUP THƯ MỤC
RAW_DIR = os.path.abspath("data/raw")
INGEST_DIR = os.path.abspath("data/ingest")
PROCESSED_RAW_DIR = os.path.abspath("data/processed_raw")

os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(INGEST_DIR, exist_ok=True)
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
        
    kg_dir = os.path.abspath("data/kg_data")
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
                        add_edge(parent_cid, sub_cid, "CÓ_CÔNG_TY_CON")
                        # FILTER: Bỏ qua công ty con có ownership = 0 hoặc None (thực thể ma, không sở hữu thực sự)
                        sub_ownership = sub.get("ownership")
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
                        
    # Convert old structured raw back to text for simple LLM text ingestion (so search works)
    output_text = "Dữ liệu JSON đã được parse trực tiếp vào Graph.\n"
    
    with open(nodes_file, 'w', encoding='utf-8') as f:
        json.dump(list(nodes_dict.values()), f, ensure_ascii=False, indent=2)
    with open(edges_file, 'w', encoding='utf-8') as f:
        json.dump(edges, f, ensure_ascii=False, indent=2)
        
    return output_text

def process_raw_files():
    files = [f for f in os.listdir(RAW_DIR) if os.path.isfile(os.path.join(RAW_DIR, f))]
    if not files:
        print("✅ Không có file thô nào trong data/raw/ để xuất ra data/ingest/.")
        return

    print(f"🚀 Tìm thấy {len(files)} file thô. Bắt đầu tiền xử lý (LLM Preprocessor)...")
    
    # Xoá file kg cũ nếu chạy lại từ đầu với data raw
    kg_dir = os.path.abspath("data/kg_data")
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
