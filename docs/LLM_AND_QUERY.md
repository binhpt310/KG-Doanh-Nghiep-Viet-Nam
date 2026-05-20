# LLM và truy vấn chat (`/api/query`)

Hướng dẫn cấu hình LLM và xử lý lỗi chat. Bám `backend/app/runtime.py` và `frontend/src/components/AssistantPanel.tsx`.

## Backend hỗ trợ

| `LLM_BACKEND` | Endpoint | Ghi chú |
|---------------|----------|---------|
| `vllm` | `{LLM_BASE_URL}/v1/chat/completions` | Mặc định Docker; tương thích OpenAI |
| `openai` | Cùng trên | OpenAI hoặc gateway tương thích |
| `openai_compat` | Cùng trên | Hành vi giống `openai` |
| `ollama` | `{LLM_BASE_URL}/api/chat` | Tự thêm hậu tố `/nothink` trên prompt |

`LLM_BASE_URL` **không** chứa `/v1` — code tự nối đường dẫn.

Danh sách model: `GET /v1/models` (kiểu OpenAI) hoặc `GET /api/tags` (Ollama). Trên UI: modal **Kết nối LLM** → `GET|POST /api/llm/settings`, `POST /api/llm/fetch-models`.

## Biến môi trường (backend)

| Biến | Mặc định | Ý nghĩa |
|------|----------|---------|
| `LLM_BACKEND` | `openai` (code); Docker thường `vllm` | Loại backend |
| `LLM_BASE_URL` / `VLLM_BASE_URL` | `http://localhost:9061` hoặc Ollama `11434` | URL gốc LLM (container phải truy cập được máy host) |
| `MODEL_NAME` | `qwen3-14b` | Model mặc định |
| `OPENAI_API_KEY` / `LLM_API_KEY` | rỗng | Bearer nếu API yêu cầu |
| `LLM_INFERENCE_TIMEOUT` | `300` | Timeout mỗi lần gọi LLM (giây) |
| `LLM_MAX_TOKENS` | `4096` | `max_tokens` cho câu trả lời tổng hợp |
| `LLM_CYPHER_MAX_TOKENS` | `2048` | `max_tokens` khi sinh Cypher (agentic) |
| `LLM_DISABLE_THINKING` | `true` | Qwen/vLLM: tắt thinking + `/nothink` |
| `LIVE_NEWS_TIMEOUT` | `4.0` | Timeout lấy tin trong `/api/query` |
| `LIVE_NEWS_MAX_ITEMS` | `5` | Số tin tối đa đính kèm |

Docker: `backend/.env.docker` (service `kg-app`). `POST /api/llm/settings` **ghi đè** file này — **không có xác thực**.

## Luồng `POST /api/query`

1. Kiểm tra phạm vi câu hỏi (domain KG Việt Nam).
2. Trích thực thể, RAG (`llmware` / fallback từ khóa), truy vấn Neo4j.
3. Nếu **Reasoning bật** (checkbox UI): thêm một lần LLM sinh Cypher (`generate_cypher_with_llm`), chỉ chạy Cypher an toàn (không `DELETE`/`DROP`/…).
4. Thu thập tin tức web ngắn (`LIVE_NEWS_*`).
5. LLM tổng hợp câu trả lời từ graph + tài liệu + tin.

**Lưu ý:** Reasoning trên UI = sinh Cypher agentic, **không** bật chain-of-thought của model. Chain-of-thought do `LLM_DISABLE_THINKING` điều khiển ở tầng HTTP.

Lỗi LLM: HTTP **502** + trường `error` (không ghi vào `answer`).

## Qwen 3.x trên vLLM

Khi bật `enable_thinking`, API có thể trả `content: null` và nội dung nằm trong `reasoning` — chậm, dễ timeout.

Repo mặc định **tắt thinking** (`LLM_DISABLE_THINKING=true`). Kiểm tra:

```bash
curl -sS -X POST "$LLM_BASE_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen36-35b-a3b-fp8",
    "messages": [{"role": "user", "content": "Xin chào/nothink"}],
    "max_tokens": 64,
    "chat_template_kwargs": {"enable_thinking": false}
  }'
```

`choices[0].message.content` phải có nội dung.

## HTTP 524 và timeout

| Triệu chứng | Nguyên nhân | Cách xử lý |
|-------------|-------------|------------|
| `Lỗi: HTTP 524` trên UI | Proxy (Cloudflare ~100s) cắt trước khi Flask xong | Tắt Reasoning; `LLM_DISABLE_THINKING=true`; tăng timeout tunnel; hoặc truy cập LAN |
| Chậm >2 phút | Hai lần gọi LLM + prompt lớn | Tắt Reasoning; giảm `LLM_MAX_TOKENS` |
| Connection refused | Sai `LLM_BASE_URL`/cổng từ container | Sửa modal LLM → **Lưu**; dùng IP host hoặc `host.docker.internal` |

Timeout trong repo:

- **Nginx** (`docker/nginx.conf`): `proxy_read_timeout` / `proxy_send_timeout` **600s** cho `/api/`.
- **Vite dev** (`frontend/vite.config.ts`): `proxyTimeout` **600000** ms.

## Panel trợ lý (UI)

`AssistantPanel`: lịch sử chat, ô nhập, gợi ý prompt, modal LLM, tìm kiếm thực thể.

- Thanh kéo (`panel-splitter`) giữa ô nhập và `prompt-grid`.
- Chiều cao gợi ý: `localStorage` key `kg_prompt_grid_height` (mặc định 200px; double-click thanh kéo để reset).

## API tham chiếu

- `GET /api/vllm/models` — danh sách model (theo backend đang chọn)
- `GET /api/ollama/models` — alias tương tự
- `GET|POST /api/llm/settings`
- `POST /api/llm/fetch-models`
- `POST /api/query` — body: `{ "query", "history", "reasoning", "model" }`
