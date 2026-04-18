# Vietnam Listed Companies Knowledge Graph

Knowledge Graph cho doanh nghiệp niêm yết Việt Nam, tập trung vào dữ liệu từ FireAnt và các quan hệ giữa công ty, lãnh đạo, cổ đông, người thân và công ty con.

## Hệ thống hiện làm được gì

- Crawl dữ liệu từ FireAnt API: `banks`, `officers`, `holders`, `subsidiaries`, `individuals`
- Chuẩn hóa dữ liệu JSON thành `nodes` / `edges` cho KG
- Push dữ liệu vào Neo4j
- Chạy suy diễn quan hệ ẩn bằng rule-based inference trong Neo4j
- Cung cấp Web UI + REST API qua Flask
- Hỗ trợ hỏi đáp với LLM backend (`ollama` hoặc OpenAI-compatible / vLLM)

## Entry points chính

### `kg_from_scratch/pipeline.py`

Đây là entry point đúng cho pipeline dữ liệu FireAnt.

Luồng thực tế:

1. Crawl từ FireAnt vào `data/raw/`
2. Preprocess qua `llm_preprocessor.py`
3. Sinh `data/kg_data/kg_nodes.json` và `data/kg_data/kg_edges.json`
4. Push toàn bộ graph lên Neo4j
5. Làm giàu quan hệ người thân của lãnh đạo
6. Chạy hidden relation inference
7. Sinh lại `data/config/entity_map.json`

CLI hiện có:

```bash
cd kg_from_scratch
python pipeline.py crawl [--symbols ...] [--banks-only] [--skip-individuals] [--reset]
python pipeline.py resume
python pipeline.py update [--symbols ...] [--banks-only] [--skip-individuals] [--no-push] [--no-inference]
python pipeline.py preprocess
python pipeline.py push
python pipeline.py entity-map
```

### `kg_from_scratch/script.py`

Đây là Flask app phục vụ Web UI và API tại cổng `5001`.

Chức năng chính:

- Dashboard graph
- Search entity
- Crawl API (`/api/crawl/start`)
- Stats API (`/api/stats`, `/api/stats/exchange`, `/api/stats/top`)
- Hidden inference API (`/api/inference`, `/api/inference/run`, `/api/inferred-relations`)
- Chat / query API (`/api/query`)
- Node detail API (`/api/node/<id>` và `/api/node/<id>/neighbors`)

Lưu ý: `script.py` có flow startup cũ cho `data/ingest/`, nhưng với dữ liệu FireAnt thì nên dùng `pipeline.py update` để cập nhật KG cho đúng logic hiện tại.

## Kiến trúc hiện tại

```text
FireAnt API
   -> data/raw/*.json
   -> llm_preprocessor.py
   -> data/kg_data/kg_nodes.json + kg_edges.json
   -> Neo4j
   -> inference_rules.py
   -> Flask UI / API (script.py)
```

## Cài đặt nhanh với Docker

### 1. Chuẩn bị biến môi trường

Repo đang dùng `kg_from_scratch/.env.docker` làm file env chính cho app.

Ví dụ:

```env
NEO4J_URI=neo4j://neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password123
NEO4J_DATABASE=neo4j

LLM_BACKEND=openai
LLM_BASE_URL=http://host.docker.internal:9061
VLLM_BASE_URL=http://host.docker.internal:9061
MODEL_NAME=qwen3-14b
```

Nếu dùng Ollama trên host:

```env
LLM_BACKEND=ollama
LLM_BASE_URL=http://host.docker.internal:11434
MODEL_NAME=qwen3:8b
```

### 2. Khởi động hệ thống

```bash
cd kg_from_scratch_docker
docker compose up -d --build
```

`docker-compose.yml` hiện khởi động 2 service:

- `neo4j` tại `7474` / `7687`
- `kg-app` tại `5001`

Mount quan trọng:

- `./kg_from_scratch/data:/app/kg_from_scratch/data`
- `./kg_from_scratch:/app/kg_from_scratch`

Điều này giúp dữ liệu và source code được đồng bộ giữa host và container.

### 3. Truy cập

- Web UI: `http://localhost:5001`
- Neo4j Browser: `http://localhost:7474`

## Chạy local dev

Theo rule của project, nên dùng conda env `kg`.

```bash
cd kg_from_scratch
conda create -n kg python=3.12 -y
conda activate kg
pip install -r requirements-docker.txt
```

Tạo file `.env` hoặc export env tương đương:

```env
NEO4J_URI=neo4j://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password123
NEO4J_DATABASE=neo4j
LLM_BACKEND=ollama
LLM_BASE_URL=http://localhost:11434
MODEL_NAME=qwen3:8b
```

Chạy Web UI:

```bash
cd kg_from_scratch
python script.py
```

Cập nhật dữ liệu FireAnt:

```bash
cd kg_from_scratch
python pipeline.py update
```

## Quy trình cập nhật dữ liệu khuyến nghị

### Cập nhật toàn bộ

```bash
python pipeline.py update
```

Các biến thể hữu ích:

```bash
python pipeline.py update --banks-only
python pipeline.py update --symbols VCB ACB FPT
python pipeline.py update --skip-individuals
python pipeline.py update --no-push
python pipeline.py update --no-inference
```

### Crawl tiếp từ trạng thái trước đó

```bash
python pipeline.py resume
```

### Chạy từng bước riêng

```bash
python pipeline.py crawl
python pipeline.py preprocess
python pipeline.py push
python pipeline.py entity-map
```

## Hidden relation inference

Hidden relation hiện được triển khai ở `kg_from_scratch/inference_rules.py` bằng Cypher rule-based inference, không dùng LLM.

Các rule hiện có:

- `R01`: gộp sở hữu vợ chồng (`KIỂM_SOÁT_GIA_ĐÌNH`)
- `R02`: sở hữu gián tiếp (`SỞ_HỮU_GIÁN_TIẾP`)
- `R07`: ảnh hưởng gián tiếp theo ngưỡng (`CÓ_LỢI_ÍCH_GIÁN_TIẾP`, `ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI`, `KIỂM_SOÁT_GIÁN_TIẾP`)
- `R12`: cùng cổ đông lớn (`CÙNG_CỔ_ĐÔNG_LỚN`)

Quan trọng:

- Dữ liệu công ty con hiện giữ cả 2 chiều:
  - `CÓ_CÔNG_TY_CON` từ công ty mẹ sang công ty con
  - `LÀ_CÔNG_TY_CON_CỦA` từ công ty con về công ty mẹ
- Logic inference hiện hỗ trợ cả dữ liệu mới và dữ liệu cũ tương thích ngược
- UI thống kê `Quan hệ ẩn` dựa trên số cạnh có `r.inferred = true`

Chạy inference thủ công:

```bash
curl -X POST http://localhost:5001/api/inference/run
```

Hoặc:

```bash
curl -X POST http://localhost:5001/api/inference
```

## Dữ liệu đầu ra quan trọng

### Raw data

- `data/raw/banks.json`
- `data/raw/officers.json`
- `data/raw/holders.json`
- `data/raw/subsidiaries.json`
- `data/raw/individuals.json`
- `data/raw/crawler_state.json`

### Processed graph

- `data/kg_data/kg_nodes.json`
- `data/kg_data/kg_edges.json`

### Metadata

- `data/config/entity_map.json`
- `data/last_crawl_success.json`

## Schema hiện tại

### Nodes

- `Person` với prefix id `P_...`
- `Company` với prefix id `C_...`, `C_INST_...`, hoặc `C_UNL_...`

### Quan hệ trực tiếp thường gặp

- `LÀ_CỔ_ĐÔNG_CỦA`
- `CÓ_CÔNG_TY_CON`
- `LÀ_CÔNG_TY_CON_CỦA`
- `CHỦ_TỊCH_HĐQT`
- `TỔNG_GIÁM_ĐỐC`
- `LÃNH_ĐẠO_CAO_NHẤT`
- `CHA_MẸ`
- `VỢ_CHỒNG`
- `ANH_CHỊ`
- `LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO`

### Quan hệ ẩn thường gặp

- `SỞ_HỮU_GIÁN_TIẾP`
- `CÓ_LỢI_ÍCH_GIÁN_TIẾP`
- `ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI`
- `KIỂM_SOÁT_GIÁN_TIẾP`
- `KIỂM_SOÁT_GIA_ĐÌNH`
- `CÙNG_CỔ_ĐÔNG_LỚN`

## API hiện có

### Web UI

- `GET /`

### Graph / stats

- `GET /api/graph`
- `GET /api/stats`
- `GET /api/stats/exchange`
- `GET /api/stats/top`
- `GET /api/search?q=...`
- `GET /api/node/<node_id>`
- `GET /api/node/<node_id>/neighbors`

### Crawl / inference

- `POST /api/crawl/start`
- `GET /api/crawl/progress`
- `POST /api/inference`
- `POST /api/inference/run`
- `GET /api/inferred-relations`
- `GET /api/rules`

### LLM / query

- `POST /api/query`
- `GET /api/vllm/models`
- `GET /api/ollama/models`

## Một số lệnh kiểm tra nhanh

### Kiểm tra stats

```bash
curl http://localhost:5001/api/stats
```

### Kiểm tra inferred relations

```bash
curl http://localhost:5001/api/inferred-relations
curl http://localhost:5001/api/inferred-relations?level=HIGH
```

### Kiểm tra top relationship types trong Neo4j

```bash
docker compose exec neo4j cypher-shell -u neo4j -p password123   "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count ORDER BY count DESC LIMIT 20"
```

## Cấu trúc repo

```text
kg_from_scratch_docker/
├── docker-compose.yml
└── kg_from_scratch/
    ├── script.py
    ├── pipeline.py
    ├── llm_preprocessor.py
    ├── inference_rules.py
    ├── reset_db.py
    ├── crawl_continue.py
    ├── verify_resume.py
    ├── requirements-docker.txt
    ├── templates/
    ├── scripts/
    └── data/
```

## Troubleshooting ngắn

### `Quan hệ ẩn = 0`

Kiểm tra theo thứ tự:

1. Đã chạy `python pipeline.py update` hoặc `POST /api/inference/run` chưa
2. `GET /api/stats` có `inferred_relationships = 0` thật hay chỉ UI chưa refresh
3. Trong Neo4j có dữ liệu `holders` và `subsidiaries` chưa
4. `data/last_crawl_success.json` có báo `neo4j_pushed = true` không

### Không có dữ liệu mới sau `update`

Nếu FireAnt đã crawl hết và không có file mới cần preprocess, `crawl_and_update()` sẽ trả về `nodes_count = 0`, `edges_count = 0`, `neo4j_pushed = false`.

### FireAnt token lỗi

Có thể override bằng env:

```bash
export FIREANT_TOKEN="your_new_token"
```

## Ghi chú

- README này phản ánh logic code hiện tại của repo, không cố giữ các số liệu snapshot dễ stale
- Với dữ liệu FireAnt, hãy ưu tiên `pipeline.py update` thay vì kỳ vọng `script.py` tự refresh toàn bộ graph
