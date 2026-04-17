# Vietnam Listed Companies Knowledge Graph

Hệ thống **Knowledge Graph** (đồ thị tri thức) cho các công ty niêm yết trên sàn chứng khoán Việt Nam (HOSE, HNX, UPCOM), với khả năng:

- **Crawl dữ liệu tự động** từ Fireant API
- **Phân tích quan hệ** giữa công ty, lãnh đạo, cổ đông, người thân
- **Tương tác qua giao diện Web** tích hợp RAG + Agentic Cypher generation
- **Deploy dễ dàng** qua Docker — bất kỳ đâu, bất kỳ máy nào

---

## Mục lục

1. [Kiến trúc hệ thống](#kiến-trúc-hệ-thống)
2. [Yêu cầu hệ thống](#yêu-cầu-hệ-thống)
3. [Cài đặt nhanh với Docker](#cài-đặt-nhanh-với-docker)
4. [Cài đặt thủ công (Local Dev)](#cài-đặt-thủ-công-local-dev)
5. [Cập nhật dữ liệu tự động](#cập-nhật-dữ-liệu-tự-động)
6. [Truy cập giao diện Web](#truy-cập-giao-diện-web)
7. [Cấu hình LLM (Ollama hoặc vLLM)](#cấu-hình-llm-ollama-hoặc-vllm)
8. [Cấu trúc dự án & các file Python](#cấu-trúc-dự-án--các-file-python)
9. [Schema dữ liệu](#schema-dữ-liệu)
10. [API endpoints](#api-endpoints)
11. [Reset database](#reset-database)
12. [Troubleshooting](#troubleshooting)

---

## Kiến trúc hệ thống

```
┌──────────────┐     ┌───────────────┐     ┌───────────────┐     ┌──────────────┐
│  1. CRAWL    │ --> │  2. PREPROCESS│ --> │  3. INGEST    │ --> │  4. WEB UI   │
│  Fireant API │     │  JSON + LLM   │     │  Neo4j + RAG  │     │  Flask + UI  │
└──────────────┘     └───────────────┘     └───────────────┘     └──────────────┘
 │                     │                     │                     │
 │ • Officers          │ • Parse JSON        │ • Nodes             │ • Semantic
 │ • Holders           │ • Extract text      │   (Person/Company)  │   search
 │ • Subsidiaries      │ • Gen nodes/edges   │ • Edges            │ • Agentic
 │ • Individuals       │                     │ • Inference        │   Cypher
 │                     │                     │                     │ • Graph viz
```

**Chi tiết từng bước:**

1. **Crawl** — Thu thập dữ liệu từ Fireant API: thông tin công ty, lãnh đạo, cổ đông, công ty con, hồ sơ cá nhân và quan hệ gia đình.
2. **Preprocess** — Xử lý file JSON trực tiếp thành nodes/edges, hoặc dùng LLM để trích xuất thông tin từ file PDF/TXT/CSV.
3. **Ingest** — Đưa dữ liệu vào Neo4j (graph database) và ChromaDB (vector database cho semantic search).
4. **Web UI** — Giao diện Flask cho phép hỏi đáp tự nhiên, kết hợp RAG + Agentic Cypher để trả lời câu hỏi về doanh nghiệp.

---

## Yêu cầu hệ thống

### Tùy chọn 1: Docker (khuyến nghị)

| Thành phần | Yêu cầu |
|---|---|
| Docker | 24.0+ |
| Docker Compose | 2.20+ |
| RAM | Tối thiểu 8GB (khuyến nghị 16GB+) |
| LLM (Ollama hoặc vLLM OpenAI-compatible) | Trên host — xem [Cấu hình LLM](#cấu-hình-llm-ollama-hoặc-vllm) |

### Tùy chọn 2: Local Development

| Thành phần | Yêu cầu |
|---|---|
| Python | 3.12+ |
| Neo4j | 5.x (community edition) |
| GPU (tùy chọn) | NVIDIA CUDA 12.6+ (để tăng tốc inference) |
| Ollama | 0.1.30+ |
| RAM | Tối thiểu 16GB (nếu dùng CPU inference) |

---

## Cài đặt nhanh với Docker

### Bước 1: Chuẩn bị

```bash
cd kg_from_scratch_docker
```

### Bước 2: Cấu hình biến môi trường

Một file cấu hình duy nhất: `kg_from_scratch/.env.docker` (được `docker-compose` dùng qua `env_file`, image copy thành `.env` trong container; ở thư mục gốc có symlink `.env` → file này để Compose interpolate `${NEO4J_*}` cho Neo4j).

```env
# Neo4j connection (nội bộ Docker)
NEO4J_URI=neo4j://neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password123
NEO4J_DATABASE=neo4j

# vLLM (OpenAI-compatible) trên host
LLM_BACKEND=openai
LLM_BASE_URL=http://host.docker.internal:9061
VLLM_BASE_URL=http://host.docker.internal:9061
MODEL_NAME=qwen3-14b
```

> **Chú ý**: `host.docker.internal` trỏ về máy host. Đổi `LLM_BASE_URL` / cổng theo chỗ bạn chạy Ollama (`11434`) hoặc vLLM (`9061`, …). `LLM_BACKEND=ollama` dùng `/api/chat`; `openai` dùng `/v1/chat/completions`.

### Bước 3: Chuẩn bị LLM trên host (Ollama **hoặc** vLLM)

**Ollama** (ví dụ cổng 11434):

```bash
ollama pull qwen3:8b
ollama serve
```

**vLLM** (OpenAI-compatible server): khởi chạy theo hướng dẫn vLLM; backend đặt `LLM_BACKEND=openai` và `LLM_BASE_URL` trỏ tới base URL (không gồm `/v1`).

### Bước 4: Khởi động toàn bộ hệ thống

```bash
docker compose up -d --build
```

Lệnh này sẽ:
- Khởi tạo container **Neo4j** (graph database) với plugin APOC
- Build và khởi tạo container **kg-app** (Flask application)
- Tự động kết nối 2 service, chờ Neo4j healthy trước khi khởi app

### Bước 5: Kiểm tra trạng thái

```bash
# Xem logs
docker compose logs -f kg-app

# Kiểm tra container đang chạy
docker compose ps

# Kiểm tra Neo4j đã sẵn sàng
docker compose exec neo4j cypher-shell -u neo4j -p password123 "RETURN 1 AS test"
```

### Bước 6: Truy cập giao diện

Mở trình duyệt và truy cập:

- **Web UI**: http://localhost:5001
- **Neo4j Browser**: http://localhost:7474 (đăng nhập: `neo4j` / `password123`)

### Cơ chế lưu trữ dữ liệu (Data Persistence)

**Quan trọng**: Container kg-app được cấu hình **volume mount** để dữ liệu crawl được sync 2 chiều giữa container và host:

```yaml
# docker-compose.yml
volumes:
  - ./kg_from_scratch/data:/app/kg_from_scratch/data
```

**Điều này có nghĩa:**

| Hành động | Kết quả |
|-----------|---------|
| Crawl dữ liệu trong container | ✅ Data được lưu ngay vào host (`./kg_from_scratch/data/`) |
| Rebuild Docker image | ✅ Image mới nhất luôn có data mới từ host |
| Stop/Start container | ✅ Data không bị mất (đã lưu trên host) |
| Chạy `docker compose up -d --build` | ✅ Container mới lấy data từ host qua volume mount |

**Kiểm tra data trên host:**

```bash
# Xem dữ liệu đã crawl
ls -lh kg_from_scratch/data/processed_raw/
# Kết quả: banks.json, officers.json, holders.json, subsidiaries.json, individuals.json

# Kiểm tra crawler state
cat kg_from_scratch/data/processed_raw/crawler_state.json | jq '.crawled_symbols | length'
# Kết quả: 147 (số symbols đã crawl)
```

**Crawl tiếp dữ liệu thiếu:**

```bash
# Tạo tmux session để crawl background
tmux new-session -d -s kg-crawl "docker exec kg-app python pipeline.py resume"

# Xem progress
tmux attach -t kg-crawl
# Hoặc: tmux capture-pane -t kg-crawl -p | tail -30

# Dừng crawl (nếu cần)
tmux kill-session -t kg-crawl
```

Sau khi crawl xong, data sẽ **tự động update** vào thư mục `data/` trên host và sẽ có trong lần build image tiếp theo.

---

## Xem dữ liệu Neo4j trực quan

Có nhiều cách để xem và khám phá dữ liệu Knowledge Graph trong Neo4j:

### 1. Neo4j Browser (có sẵn)

Truy cập http://localhost:7474, đăng nhập và chạy Cypher queries:

```cypher
// Xem toàn bộ graph (giới hạn 100 nodes)
MATCH (n) RETURN n LIMIT 100

// Xem công ty và lãnh đạo
MATCH (p:Entity)-[r]->(c:Entity)
WHERE c.type = 'Company' AND c.id =~ 'C_[A-Z]+'
RETURN p, r, c LIMIT 50

// Xem quan hệ gia đình
MATCH (a:Person)-[r]->(b:Person)
WHERE r.label IN ['CHA_MẸ', 'VỢ_CHỒNG', 'ANH_CHỊ', 'ÔNG_BÀ_BÁC_CHÚ']
RETURN a, r, b LIMIT 50

// Top 10 công ty có nhiều quan hệ nhất
MATCH (c:Entity)
WHERE c.type = 'Company'
WITH c, count{(c)--()} AS rels
ORDER BY rels DESC LIMIT 10
RETURN c.id, c.name, rels
```

### 2. Neo4j Bloom (visualization đẹp nhất)

Neo4j Bloom là công cụ trực quan graph kéo-thả, có sẵn trong Neo4j Desktop và Neo4j Browser phiên bản mới:

```bash
# Trong Neo4j Browser, bật Bloom:
:server bloom
```

Hoặc truy cập trực tiếp: http://localhost:7474/browser/bloom

**Ưu điểm:**
- Giao diện kéo-thả, không cần viết Cypher
- Tự động phát hiện patterns và relationships
- Zoom, pan, filter trực quan
- Tìm kiếm theo tên entity

### 3. Neo4j Graph Data Science (GDS) Library

Nếu cần phân tích graph nâng cao (centrality, community detection):

```cypher
// Cài GDS plugin (nếu chưa có)
// https://neo4j.com/docs/graph-data-science/current/installation/

// Chạy PageRank để tìm entity quan trọng nhất
CALL gds.pageRank.stream('my-graph')
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).name AS name, score
ORDER BY score DESC LIMIT 10
```

### 4. Công cụ bên thứ ba

| Công cụ | Loại | Mô tả |
|---|---|---|
| **[Neovis.js](https://github.com/neo4j-contrib/neovis.js)** | Web library | Nhúng graph visualization vào web app |
| **[yFiles for Neo4j](https://www.yworks.com/products/yfiles-for-neo4j)** | Commercial | Visualization chuyên nghiệp, layout đẹp |
| **[GraphXR](https://www.kineviz.com/graphxr/)** | Desktop app | Phân tích graph nâng cao, export báo cáo |
| **[Linkurious](https://linkurious.com/)** | Enterprise | Platform phát hiện gian lận qua graph |
| **[Neo4j ECharts](https://github.com/neo4j-contrib/neo4j-echarts)** | Open source | Visualization với Apache ECharts |

### 5. Xem nhanh qua CLI

```bash
# Docker: Chạy cypher-shell
docker compose exec neo4j cypher-shell -u neo4j -p password123

# Xem thống kê nhanh
docker compose exec neo4j cypher-shell -u neo4j -p password123 \
  "MATCH (n) RETURN labels(n) AS label, count(*) AS count ORDER BY count DESC"

# Xem relationships
docker compose exec neo4j cypher-shell -u neo4j -p password123 \
  "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count ORDER BY count DESC LIMIT 15"
```

---

## Cài đặt thủ công (Local Dev)

### Bước 1: Cài đặt Neo4j

```bash
# Option A: Docker (đơn giản nhất)
docker run -d --name neo4j-local \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password123 \
  -e NEO4J_PLUGINS='["apoc"]' \
  neo4j:5-community

# Option B: Cài đặt trực tiếp https://neo4j.com/download/
```

### Bước 2: Tạo môi trường Python

```bash
cd kg_from_scratch

# Sử dụng conda (khuyến nghị)
conda create -n kg python=3.12 -y
conda activate kg

# HOẶC sử dụng venv
python3.12 -m venv venv
source venv/bin/activate  # Linux/macOS
# hoặc: venv\Scripts\activate  # Windows
```

### Bước 3: Cài đặt dependencies

```bash
pip install -r requirements-docker.txt
```

Gói chính:
- `Flask>=3.1.0` — Web framework
- `neo4j>=6.0.0` — Neo4j driver
- `llmware>=0.4.0` — LLM agent framework
- `chromadb>=0.4.0` — Vector database
- `sentence-transformers>=2.0.0` — Embedding model (PhoBERT)
- `python-dotenv>=1.0.0` — Quản lý biến môi trường
- `requests>=2.28.0` — HTTP client
- `Jinja2>=3.1.0` — Template engine

### Bước 4: Cấu hình `.env`

Tạo file `kg_from_scratch/.env`:

```env
NEO4J_URI=neo4j://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password123
NEO4J_DATABASE=neo4j
LLM_BACKEND=ollama
LLM_BASE_URL=http://localhost:11434
MODEL_NAME=qwen3:14b
```

### Bước 5: Chạy LLM trên máy (Ollama hoặc vLLM)

Ví dụ Ollama: `ollama pull` model rồi `ollama serve`. Xem [Cấu hình LLM](#cấu-hình-llm-ollama-hoặc-vllm).

### Bước 6: Chạy pipeline

```bash
cd kg_from_scratch
python script.py
```

Ứng dụng sẽ tự động:
1. Xử lý file mới trong `data/ingest/`
2. Chèn nodes/edges vào Neo4j
3. Chạy vòng lặp suy diễn quan hệ ẩn
4. Khởi động Flask server tại http://localhost:5001

---

## Cập nhật dữ liệu tự động

### Giới thiệu

Hệ thống dùng **Fireant API** để thu thập dữ liệu về các công ty niêm yết trên 3 sàn:
- **HOSE** — Sàn giao dịch chứng khoán TP.HCM (~100+ mã)
- **HNX** — Sàn giao dịch chứng khoán Hà Nội (~60+ mã)
- **UPCOM** — Sàn giao dịch công ty đại chúng (~30+ mã)

Tổng cộng **~150+ mã chứng khoán** thuộc các ngành: Ngân hàng, Bất động sản, Thép, Dầu khí, Điện, Công nghệ, Bán lẻ, Thực phẩm, Logistics, Chứng khoán, Bảo hiểm.

### Cách 1: Cập nhật toàn bộ pipeline (khuyến nghị)

Hàm `crawl_and_update()` trong `pipeline.py` là entry-point duy nhất để cập nhật toàn bộ:

```bash
cd kg_from_scratch

# Cập nhật toàn bộ: Crawl → Preprocess → Push Neo4j → Inference → Entity Map
python pipeline.py update

# Chỉ crawl nhóm ngân hàng
python pipeline.py update --banks-only

# Crawl một số symbols cụ thể
python pipeline.py update --symbols VCB ACB FPT

# Bỏ qua phần individual profiles (nhanh hơn)
python pipeline.py update --skip-individuals

# Không push lên Neo4j (chỉ crawl + preprocess)
python pipeline.py update --no-push
```

### Cách 2: Chạy từng bước riêng lẻ

```bash
# Chỉ crawl dữ liệu từ Fireant API
python pipeline.py crawl

# Chỉ chạy preprocessor
python pipeline.py preprocess

# Chỉ push lên Neo4j (cần có kg_nodes.json + kg_edges.json)
python pipeline.py push

# Sinh lại entity_map.json
python pipeline.py entity-map
```

### Cách 3: Chỉ chạy Web UI (`script.py`)

```bash
python script.py
```

`script.py` là **entry chính**: khởi động Flask (port 5001), tùy dữ liệu có thể xử lý ingest/Neo4j/inference khi start; **crawl Fireant** nên dùng `pipeline.py` hoặc nút **Crawl Data** trên UI (gọi `/api/crawl/start`).

### Dữ liệu thu thập

| Endpoint | Dữ liệu | File đầu ra |
|---|---|---|
| `GET /symbols/{SYMBOL}` | Thông tin cơ bản công ty | `data/raw/banks.json` |
| `GET /symbols/{SYMBOL}/officers` | Danh sách lãnh đạo | `data/raw/officers.json` |
| `GET /symbols/{SYMBOL}/holders` | Danh sách cổ đông | `data/raw/holders.json` |
| `GET /symbols/{SYMBOL}/subsidiaries` | Công ty con | `data/raw/subsidiaries.json` |
| `GET /individuals/{ID}/profile` | Hồ sơ cá nhân | `data/raw/individuals.json` |
| `GET /individuals/{ID}/jobs` | Quá trình công tác | (trong `individuals.json`) |
| `GET /individuals/{ID}/assets` | Tài sản / sở hữu cổ phần | (trong `individuals.json`) |
| `GET /individuals/{ID}/relations` | Quan hệ gia đình | (trong `individuals.json`) |

### Cơ chế resume

Crawler lưu trạng thái vào `data/processed_raw/crawler_state.json`. Khi chạy lại, sẽ tự động:

1. **Detect state file**: Tìm ở `data/raw/crawler_state.json` trước, fallback sang `data/processed_raw/crawler_state.json`
2. **Skip đã crawled**: Tự động bỏ qua symbols và individuals đã crawl xong
3. **Resume từ vị trí dừng**: Tiếp tục crawl các entities còn thiếu
4. **Save sau mỗi entity**: State được update sau mỗi lần crawl thành công (an toàn nếu bị gián đoạn)

**Data flow trong Docker:**

```
Fireant API
    ↓ (crawl trong container)
container:data/raw/*.json  ←→  host:kg_from_scratch/data/raw/*.json (volume mount)
    ↓ (preprocess)
container:data/processed_raw/*.json  ←→  host:kg_from_scratch/data/processed_raw/*.json
    ↓ (push to Neo4j)
Neo4j Database (7284 nodes, 11430 edges hiện tại)
```

**Lưu ý quan trọng:**
- ✅ Data crawl được **sync tự động** giữa container và host qua volume mount
- ✅ Rebuild image sẽ **luôn có data mới nhất** từ host
- ✅ Có thể crawl trong container, stop container, rebuild → data vẫn còn

### Fireant API Token

Token được cấu hình sẵn trong code. Nếu token hết hạn, cập nhật lại qua biến môi trường:

```bash
export FIREANT_TOKEN="your_new_token_here"
```

---

## Truy cập giao diện Web

### Địa chỉ

Cách 1:

- Chạy ngrok ```ngrok config add-authtoken [token]```
- Chạy ở tmux ```ngrok http 5001``` để lấy URL ví dụ như ```https://alfredo-machinable-chante.ngrok-free.dev/```

Sau khi khởi động, mở trình duyệt:

```
http://localhost:5001
http://localhost:5001/debug_graph.html
```

### Tính năng giao diện

| Tính năng | Mô tả |
|---|---|
| **Một trang (dashboard)** | Graph, Chat RAG, luật suy diễn, thống kê trên cùng trang; từng khối thu gọn/mở rộng |
| **Chat RAG** | Câu hỏi tiếng Việt; chọn model; phiên hội thoại lưu `localStorage` |
| **Đồ thị (Vis.js)** | Chế độ **Companies** (cạnh C–C) / **Persons** (mọi cạnh có ít nhất một Person); tải một lần (giới hạn `GRAPH_MAX_EDGES`) |
| **Sau khi chat** | Đồ thị cập nhật theo `nodes`/`edges` (hoặc `graphs[0]`) từ câu trả lời |
| **Chi tiết entity** | Panel node: cổ phiếu `shares` / tỷ lệ khi có cạnh `LÀ_CỔ_ĐÔNG_CỦA` |
| **Process monitor** | Các bước xử lý + Cypher (Agentic / fast path) |
| **Crawl** | Nút crawl + badge **Crawl OK** (thời điểm file `data/last_crawl_success.json`) |
| **Tìm kiếm** | Tìm thực thể (Ctrl+K) |

### Ví dụ câu hỏi

- "Chủ tịch HĐQT của ACB là ai?"
- "Cổ đông lớn nhất của VCB là ai?"
- "ACB có những công ty con nào?"
- "Người thân của ông Trần Hùng Huy có liên quan đến công ty nào?"
- "Lãnh đạo của VIB và MBB có mối quan hệ gì không?"

---

## Cấu hình LLM (Ollama hoặc vLLM)

### LLM dùng cho việc gì?

1. **Preprocessor (llmware)**: Trích xuất từ văn bản khi có file ingest (PDF/TXT/…)
2. **Chat RAG (`/api/query`)**: Tổng hợp câu trả lời + (tùy chọn) **Agentic Cypher** — **không** dùng LLM cho suy diễn quan hệ ẩn trong Neo4j (luật đó chạy bằng Cypher trong `inference_rules.py`)

### Biến môi trường (backend)

| Biến | Ý nghĩa |
|------|---------|
| `LLM_BACKEND` | `ollama` → `/api/chat` + `/api/tags`; `openai` / `vllm` / `openai_compat` → `/v1/chat/completions` + `/v1/models` |
| `LLM_BASE_URL` | URL gốc server (vd `http://host.docker.internal:9061`), **không** kèm `/v1` |
| `VLLM_BASE_URL` | Fallback nếu không set `LLM_BASE_URL` (cùng giá trị với base vLLM) |
| `MODEL_NAME` | Tên model trên server (vd `qwen3-14b`, `qwen3:8b`) |
| `LLM_INFERENCE_TIMEOUT` | Timeout giây (mặc định 300) |
| `LLM_MAX_TOKENS` | Giới hạn token (OpenAI-compatible, mặc định 8192) |

### Ollama (ví dụ)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:8b
ollama serve
```

```env
LLM_BACKEND=ollama
LLM_BASE_URL=http://localhost:11434
MODEL_NAME=qwen3:8b
```

```bash
curl http://localhost:11434/api/tags
ollama list
```

### vLLM (OpenAI-compatible)

Khởi chạy vLLM theo tài liệu; cấu hình:

```env
LLM_BACKEND=openai
LLM_BASE_URL=http://localhost:9061
VLLM_BASE_URL=http://localhost:9061
MODEL_NAME=qwen3-14b
```

Kiểm tra: `curl http://localhost:9061/v1/models`

### GPU Acceleration

Nếu có NVIDIA GPU, hệ thống tự động phát hiện và kích hoạt GPU layers. Kiểm tra:

```bash
# Xác minh GPU được phát hiện
ls /dev/nvidia0  # Nếu có output -> GPU đã được nhận diện
nvidia-smi       # Kiểm tra trạng thái GPU
```

---

## Cấu trúc dự án & các file Python

```
kg_from_scratch_docker/
├── docker-compose.yml          # Neo4j + kg-app
├── Dockerfile                  # Image kg-app (PyTorch CUDA base)
├── .env                        # Biến môi trường khi chạy compose
├── fireant_api_list.txt        # Ghi chú endpoint Fireant
│
└── kg_from_scratch/
    ├── script.py               # Flask Web UI + API; khởi động ingest/inference tùy dữ liệu
    ├── pipeline.py             # Crawl Fireant, preprocess, push Neo4j, CLI (`crawl`, `resume`, `update`, …)
    ├── inference_rules.py      # Suy diễn quan hệ ẩn (Cypher; không LLM)
    ├── llm_preprocessor.py     # Preprocess file vào ingest / embedding
    ├── reset_db.py             # Xóa Neo4j + vector DB + reset ingest (thao tác nguy hiểm)
    ├── crawl_continue.py       # Tương thích cũ — gọi `crawl_fireant_data`; dùng `python pipeline.py resume`
    ├── verify_resume.py        # Kiểm tra state crawler / resume (QA)
    ├── test_crawl.py           # Thử crawl vài individual (dev)
    ├── check_nlp.py            # In vài block NLP từ library llmware (debug)
    ├── requirements-docker.txt
    ├── .env.docker             # Mặc định trong image
    ├── templates/              # index.html + assets (CSS, …)
    ├── scripts/
    │   ├── generate_entity_map.py
    │   ├── add_leader_family_relations.py
    │   └── cleanup_zero_ownership.py
    └── data/
        ├── raw/ , processed_raw/ , ingest/ , processed/ , kg_data/ , config/
        └── last_crawl_success.json   # Ghi sau crawl Web thành công (UTC)
```

### Vai trò từng module Python

| Module | Vai trò |
|--------|---------|
| `script.py` | Ứng dụng Flask: graph, chat, crawl API, stats, search, inference API, node detail |
| `pipeline.py` | Toàn bộ đường ống dữ liệu + **CLI** (`crawl`, `resume`, `update`, `preprocess`, `push`, `entity-map`) |
| `inference_rules.py` | Luật R01/R02/R07 (suy diễn trên Neo4j) |
| `llm_preprocessor.py` | Đọc raw → chuẩn hóa / LLM cho file văn bản |
| `reset_db.py` | Dọn Neo4j + Chroma + đưa processed → ingest |

### Có nên gộp thêm file không?

| Gợi ý | Lý do |
|-------|--------|
| **`crawl_continue.py`** | Đã **trùng** `python pipeline.py resume` (và `pipeline.py crawl`). File giữ lại cho lệnh cũ / Docker; logic nằm ở `pipeline.py`. |
| **`verify_resume.py`**, **`test_crawl.py`** | Nên **giữ riêng**: script chẩn đoán / thử API, không nhét vào `pipeline.py` để tránh phình module. |
| **`check_nlp.py`** | Script debug nhỏ; có thể chuyển vào `scripts/` sau nếu muốn gọn thư mục gốc. |
| **`inference_rules.py`** | **Giữ tách** — tách khỏi `script.py` để test và đọc luật rõ ràng. |
| **`scripts/*.py`** | Tiện ích một lần / bảo trì DB; gọi từ pipeline hoặc tay. |

### Mô tả file phụ trợ (cũ)

| File | Chức năng |
|---|---|
| `scripts/generate_entity_map.py` | Sinh `entity_map.json` (alias → id) |
| `scripts/add_leader_family_relations.py` | Bổ sung quan hệ gia đình lãnh đạo (nếu chạy tay) |
| `scripts/cleanup_zero_ownership.py` | Dọn cạnh ownership = 0 |

---

## Schema dữ liệu

### Node Types

#### Person (Cá nhân) — ID prefix: `P_xxxxx`

| Field | Kiểu | Ví dụ |
|---|---|---|
| `id` | string | `P_8587` |
| `name` | string | `Trần Hùng Huy` |
| `type` | string | `Person` |
| `dateOfBirth` | string/null | `25/10/1971` |
| `homeTown` | string/null | `Phú Yên` |
| `placeOfBirth` | string/null | `TP. Hồ Chí Minh` |
| `isForeign` | boolean/null | `false` |

#### Company (Công ty) — ID prefix: `C_xxx` hoặc `C_INST_xxxxx`

| Field | Kiểu | Ví dụ |
|---|---|---|
| `id` | string | `C_ACB`, `C_INST_7127` |
| `name` | string | `Ngân hàng TMCP Á Châu` |
| `type` | string | `Company` |
| `symbol` | string | `ACB` |
| `props` | object | `{}` (thường rỗng) |

### Relationship Types

| Quan hệ | Hướng | Properties | Ví dụ |
|---|---|---|---|
| `LÀ_CỔ_ĐÔNG_CỦA` | Person/Company → Company | `shares`, `ownership` | Ông A →[LÀ_CỔ_ĐÔNG_CỬA {shares: 1000000, ownership: 0.05}]→ ACB |
| `CHỦ_TỊCH_HĐQT` | Person → Company | — | Ông A →[CHỦ_TỊCH_HĐQT]→ ACB |
| `TỔNG_GIÁM_ĐỐC` | Person → Company | — | Ông B →[TỔNG_GIÁM_ĐỐC]→ VCB |
| `LÃNH_ĐẠO_CAO_NHẤT` | Person → Company | — | (alias cho chủ tịch) |
| `CÓ_CÔNG_TY_CON` | Company → Company | — | ACB →[CÓ_CÔNG_TY_CON]→ ACB Securities |
| `LÀ_CÔNG_TY_CON_CỦA` | Company → Company | `ownership` | ACB Securities →[LÀ_CÔNG_TY_CON_CỦA]→ ACB |
| `CHA_MẸ` | Person → Person | — | Ông A →[CHA_MẸ]→ Ông B |
| `VỢ_CHỒNG` | Person → Person | — | Ông A →[VỢ_CHỒNG]→ Bà B |
| `ANH_CHỊ` | Person → Person | — | Ông A →[ANH_CHỊ]→ Ông B |
| `ÔNG_BÀ_BÁC_CHÚ` | Person → Person | — | Ông A →[ÔNG_BÀ_BÁC_CHÚ]→ Ông B |
| `LÀ_NGƯỜI_THÂN_CỦA_LÃNH_ĐẠO` | Person → Company | `leaderRelationship`, `leaderName`, `position` | |
| `ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI` | Entity → Entity | `inferred: true` | (quan hệ suy diễn) |

> **Lưu ý**: Các quan hệ gia đình được chuẩn hóa theo hướng **Người lớn → Người nhỏ** (cha→con, ông→cháu, anh→em).

---

## API endpoints

### Web UI

| Method | Endpoint | Mô tả |
|---|---|---|
| `GET` | `/` | Trang chủ (dashboard một trang) |

### REST API (Flask — `script.py`)

| Method | Endpoint | Ghi chú |
|---|---|---|
| `GET` | `/api/graph` | `mode=companies\|persons`, `limit` (mặc định theo `GRAPH_MAX_EDGES`); trả `nodes`, `edges`, `total_edges`, `truncated` |
| `GET` | `/api/stats` | Thống kê nodes/edges, company/person, inferred |
| `GET` | `/api/search?q=` | Gợi ý entity theo tên |
| `GET` | `/api/node/<node_id>` | Thuộc tính node + bổ sung cổ đông / quan hệ |
| `GET` | `/api/vllm/models` | Danh sách model (Ollama `/api/tags` hoặc OpenAI `/v1/models`) + `backend` |
| `GET` | `/api/ollama/models` | Alias của `/api/vllm/models` |
| `POST` | `/api/query` | Body: `query`, `history`, `reasoning`, `model` — RAG + Neo4j + LLM tổng hợp |
| `POST` | `/api/crawl/start` | Body tùy chọn: `symbols`, `skip_individuals` |
| `GET` | `/api/crawl/progress` | Tiến trình crawl + `last_success` (từ `last_crawl_success.json`) |
| `POST` | `/api/inference` | Chạy toàn bộ luật suy diễn (`inference_rules`) |
| `POST` | `/api/inference/run` | (alias inference) |
| `GET` | `/api/inferred-relations` | Quan hệ suy diễn + thống kê |

### Ví dụ `/api/query`

**Request:**
```json
{
  "query": "Chủ tịch HĐQT của ACB là ai?",
  "history": [],
  "reasoning": true,
  "model": "qwen3-14b"
}
```

**Response:**
```json
{
  "answer": "Chủ tịch HĐQT của Ngân hàng TMCP Á Châu (ACB) là Trần Hùng Huy...",
  "nodes": [
    {"id": "C_ACB", "label": "Ngân hàng TMCP Á Châu (ACB)", "group": "Company"},
    {"id": "P_8587", "label": "Trần Hùng Huy", "group": "Person"}
  ],
  "edges": [
    {"from": "P_8587", "to": "C_ACB", "label": "CHỦ_TỊCH_HĐQT", "dashes": false}
  ],
  "steps": [
    "Bắt đầu xử lý truy vấn (Reasoning: Bật)",
    "Phát hiện thực thể: ACB (C_ACB)",
    "Tìm thấy 5 đoạn văn bản liên quan.",
    "Hoàn tất Graph search: 1 quan hệ."
  ],
  "cypher": "MATCH (p:Entity)-[r]->(c:Entity {id: 'C_ACB'}) WHERE r.label = 'CHỦ_TỊCH_HĐQT' RETURN p.name LIMIT 50"
}
```

---

## Reset database

Khi cần xóa toàn bộ dữ liệu cũ và chạy lại từ đầu:

### Docker mode

```bash
# Xóa Neo4j data volume
docker compose down -v

# Khởi động lại
docker compose up -d --build
```

### Local mode

```bash
cd kg_from_scratch
python reset_db.py
```

Script `reset_db.py` sẽ:
1. Xóa ChromaDB collection `kg_demo_vn`
2. Xóa Library trong LLMWare (SQLite blocks)
3. Xóa toàn bộ nodes và relationships trong Neo4j (`MATCH (n) DETACH DELETE n`)
4. Di chuyển file từ `data/processed/` về `data/ingest/` để có thể xử lý lại

Sau khi reset, chạy lại pipeline:

```bash
python script.py
```

---

## Troubleshooting

### 1. Ollama không phản hồi

**Triệu chứng**: Log báo lỗi kết nối Ollama hoặc timeout.

**Giải pháp**:
```bash
# Kiểm tra Ollama đang chạy
ollama list
curl http://localhost:11434/api/tags

# Kiểm tra URL trong .env có đúng
grep -E 'LLM_BASE_URL|VLLM_BASE_URL' .env

# Trong Docker, đảm bảo host.docker.internal hoạt động
# Thử nghiệm: ping host.docker.internal

# Restart Ollama
systemctl restart ollama  # Linux
# hoặc kill và chạy lại: ollama serve
```

### 2. Neo4j không kết nối được

**Triệu chứng**: Lỗi `Connection refused` hoặc `Authentication failed`.

**Giải pháp**:
```bash
# Docker: Kiểm tra container
docker compose ps neo4j
docker compose logs neo4j

# Chờ Neo4j khởi động hoàn tất (có thể mất 30-60s)
docker compose exec neo4j cypher-shell -u neo4j -p password123 "RETURN 1"

# Local: Kiểm tra Neo4j đang chạy
neo4j status
# Hoặc:
curl http://localhost:7474
```

### 3. Hết bộ nhớ (OOM)

**Triệu chứng**: Process bị kill, log báo `Out of memory`.

**Giải pháp**:
- Dùng model nhẹ hơn: `qwen3:8b` thay vì `qwen3:14b`
- Tăng memory trong `docker-compose.yml`:
  ```yaml
  NEO4J_dbms_memory_pagecache_size=1G
  NEO4J_dbms_memory_heap_max__size=2G
  ```
- Nếu dùng CPU inference, xem xét thêm swap:
  ```bash
  sudo fallocate -l 8G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  ```

### 4. Lỗi embedding / ChromaDB

**Triệu chứng**: Lỗi khi gọi `lib.install_new_embedding()`.

**Giải pháp**:
```bash
# Kiểm tra sentence-transformers
python -c "from sentence_transformers import SentenceTransformer; m = SentenceTransformer('vinai/phobert-large'); print('OK')"

# Nếu lỗi, cài lại:
pip install --upgrade sentence-transformers chromadb
```

### 5. Crawler bị rate limit (429)

**Triệu chứng**: Log báo `Rate limited (429)`.

**Giải pháp**:
- Crawler đã có cơ chế tự động retry với backoff
- Có thể tăng `REQUEST_DELAY` trong `pipeline.py` từ 0.5s lên 1.0s
- Dùng cơ chế `--banks-only` để crawl ít hơn

### 6. Fireant token hết hạn

**Triệu chứng**: Lỗi `401 Unauthorized`.

**Giải pháp**:
```bash
# Lấy token mới từ Fireant
export FIREANT_TOKEN="your_new_token"

# HOẶC chỉnh sửa trực tiếp trong pipeline.py (biến FIREANT_TOKEN)
```

### 7. Lỗi GPU không được phát hiện

**Triệu chứng**: Log báo `Không tìm thấy GPU. Dùng CPU để inference.`

**Giải pháp**:
```bash
# Kiểm tra NVIDIA driver
nvidia-smi

# Kiểm tra CUDA
python -c "import torch; print(torch.cuda.is_available())"

# Nếu dùng Docker, đảm bảo dùng NVIDIA Container Toolkit
# https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html
```

### 8. Docker không truy cập được Ollama trên host

**Triệu chứng**: `Connection refused` từ trong container.

**Giải pháp**:
- Đảm bảo `extra_hosts` đã được cấu hình trong `docker-compose.yml`:
  ```yaml
  extra_hosts:
    - "host.docker.internal:host-gateway"
  ```
- Trên Linux, có thể cần thêm route:
  ```bash
  # Thử dùng IP thật của host thay vì host.docker.internal
  ip route | grep default  # Lấy IP gateway
  # Sau đó đổi LLM_BASE_URL / VLLM_BASE_URL thành http://<host-ip>:9061 (hoặc cổng vLLM của bạn)
  ```

---

## Build và Push Docker Image lên Docker Hub

Image Docker hiện tại: **https://hub.docker.com/repository/docker/ptbinh310/vn-company-kg**

### Build image mới

```bash
cd kg_from_scratch_docker

# Build image local
docker build -t vn-company-kg:latest .

# Test chạy thử
docker run --rm -p 5001:5001 vn-company-kg:latest
```

### Push lên Docker Hub

```bash
cd kg_from_scratch_docker

# 1. Đăng nhập Docker Hub
docker login -u ptbinh310

# 2. Tag image
docker tag vn-company-kg:latest ptbinh310/vn-company-kg:latest

# 3. Push lên Docker Hub
docker push ptbinh310/vn-company-kg:latest
```

### Push với version tag (khuyến nghị)

```bash
# Tag với version
docker tag vn-company-kg:latest ptbinh310/vn-company-kg:v1.0.0

# Push version
docker push ptbinh310/vn-company-kg:v1.0.0

# Push latest (luôn giữ tag latest đồng bộ với version mới nhất)
docker push ptbinh310/vn-company-kg:latest
```

### Build + Push bằng docker compose

```bash
cd kg_from_scratch_docker

# Build image mới nhất
docker compose build kg-app

# Tag và push
docker tag kg_from_scratch_docker-kg-app:latest ptbinh310/vn-company-kg:latest
docker push ptbinh310/vn-company-kg:latest
```

### One-liner: Build → Tag → Push

```bash
docker build -t vn-company-kg:latest . \
  && docker tag vn-company-kg:latest ptbinh310/vn-company-kg:latest \
  && docker push ptbinh310/vn-company-kg:latest
```

### Kiểm tra image trên Docker Hub

Sau khi push, kiểm tra tại:
- https://hub.docker.com/repository/docker/ptbinh310/vn-company-kg
- Hoặc CLI:
  ```bash
  docker pull ptbinh310/vn-company-kg:latest
  docker images | grep vn-company-kg
  ```

### Cập nhật docker-compose.yml để dùng image mới

Sau khi push image mới, cập nhật `docker-compose.yml`:

```yaml
services:
  kg-app:
    image: ptbinh310/vn-company-kg:latest   # <-- Đổi version nếu cần
    # hoặc: image: ptbinh310/vn-company-kg:v1.0.0
```

Sau đó pull và restart:

```bash
docker compose pull kg-app
docker compose up -d kg-app
```

### Tự động build trên Docker Hub (Docker Hub Build)

Nếu muốn Docker Hub tự động build mỗi khi push code lên GitHub:

1. Vào **Docker Hub** → **Repositories** → **Create Repository**
2. Chọn **Builds** → **Link to GitHub**
3. Chọn repository và branch (ví dụ: `main`)
4. Cấu hình `Dockerfile location`: `Dockerfile`
5. Cấu hình `Build Rules`:
   - `latest` ← `main`
   - `v*` ← `tags`
6. Bấm **Save and Build**

Mỗi khi push code lên GitHub, Docker Hub sẽ tự động build và push image mới.

---

## Tác giả & Giấy phép

Dự án được phát triển cho mục đích nghiên cứu Knowledge Graph trong lĩnh vực tài chính — chứng khoán Việt Nam.

## Liên hệ

Nếu có vấn đề hoặc góp ý, vui lòng mở issue hoặc liên hệ với nhóm phát triển.
