import requests
import json
import time

URL = "http://localhost:5001/api/query"

test_queries = [
    "Có bất kỳ cá nhân nào đồng thời là Chủ tịch HĐQT của một công ty nhưng lại là cổ đông của công ty khác không?",
    "Những người thân của Chủ tịch tập đoàn Vingroup (VIC) có làm cổ đông của một công ty nào khác không?",
    "Có công ty con nào của ngân hàng MBB lại tiếp tục có công ty con của riêng nó tạo thành chuỗi 2 cấp bậc không?",
    "Cho biết những công ty nào là công ty con của VNM nhưng lại bị sở hữu bởi một cổ đông Tổ chức (không phải cá nhân)?",
    "Ai là cá nhân vừa nắm giữ chức vụ lãnh đạo tại FPT, vừa là cổ đông của một tổ chức khác?",
    "Hồ Hùng Anh và những người thân trong gia đình ông đang sở hữu tổng cộng những công ty nào?",
    "Có cá nhân nào giữ vai trò Chủ tịch HĐQT của từ 2 công ty trở lên (đa nhiệm) không?",
    "Tìm các công ty con do Masan (MSN) sở hữu nhưng MSN không nắm 100% cổ phần mà bị pha loãng bởi cá nhân khác?",
    "Phạm Thu Hương có mối quan hệ trực tiếp hay gián tiếp gì với tập đoàn Vingroup và người đứng đầu Vingroup?",
    "Mô tả tất cả các sợi dây liên kết gián tiếp giữa Vingroup (VIC) và Vinhomes (VHM) qua các công ty con và cổ đông."
]

print("=== STARTING THE ADVANCED MULTI-HOP RAG STRESS TEST ===")
success_count = 0

for i, query in enumerate(test_queries, 1):
    print(f"\n--- Test {i}/{len(test_queries)} ---")
    print(f"Query: {query}")
    
    payload = {
        "query": query,
        "history": [],
        "model": "qwen3-14b",
        "reasoning": True
    }
    
    try:
        start_time = time.time()
        response = requests.post(URL, json=payload, timeout=90) # Hard queries take longer
        dur = time.time() - start_time
        if response.status_code == 200:
            data = response.json()
            answer = data.get("answer", "")
            cypher = data.get("cypher", "")
            
            print(f"Generated Cypher:\n{cypher.strip()}")
            # Determine success simply by checking if RAG didn't crash and answered something.
            # Real validation will be done via manual inspection as instructed by user.
            if len(cypher) > 5 and len(answer) > 20:
                print(f"✅ PASSED (Successfully emitted GraphRAG output)")
                success_count += 1
            else:
                print(f"❌ FAILED (Empty cypher or very short answer)")
            
            print(f"Answer:\n{answer}\n(Thời gian xử lý: {dur:.2f}s)")
        else:
            print(f"HTTP ERROR {response.status_code}")
            
    except Exception as e:
        print(f"FAIL Exception: {str(e)}")

print(f"\n=== FINISHED RAG STRESS TEST ({success_count}/{len(test_queries)} successful queries) ===")
