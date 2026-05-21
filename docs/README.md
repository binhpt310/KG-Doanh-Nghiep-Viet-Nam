# Tài liệu dự án

Mục lục tài liệu Markdown trong thư mục này. Điểm vào chính (chạy stack, API): [README.md](../README.md).

**Snapshot 2026-05-21:** 10 413 node, 19 122 cạnh, 280 cạnh ẩn. Chi tiết: [entities_schema.md](entities_schema.md), [SLIDE_CONTENT.md §5.2](../SLIDE_CONTENT.md#52-số-liệu-graph).

| Tài liệu | Đối tượng | Nội dung |
|----------|-----------|----------|
| [../README.md](../README.md) | Phát triển / vận hành | Chạy stack, kiến trúc, API, cấu hình |
| [LLM_AND_QUERY.md](LLM_AND_QUERY.md) | Vận hành LLM | vLLM/Ollama, `/api/query`, lỗi HTTP 524 |
| [cypher_reference.md](cypher_reference.md) | Backend / agent | Mẫu Cypher, neo sinh truy vấn |
| [entities_schema.md](entities_schema.md) | Backend | Schema node/edge + quan hệ ẩn R01–R04 |
| [inference_rules.md](inference_rules.md) | Backend / pháp lý | Luật suy diễn R01–R04, Cypher mẫu |
| [FRONTEND.md](FRONTEND.md) | Frontend | React/Vite, cấu trúc UI |

## Sơ đồ runtime

- SVG: [frontend/public/runtime-architecture.svg](../frontend/public/runtime-architecture.svg)

## Bản đồ mã nguồn

| Chức năng | Vị trí |
|-----------|--------|
| API Flask | `backend/script.py` |
| Neo4j + LLM | `backend/app/runtime.py` |
| Catalog luật ẩn | `backend/app/rule_catalog.py` |
| Suy diễn cạnh | `backend/inference_rules.py` |
| Pipeline crawl | `backend/pipeline.py` |
| Preprocess | `backend/llm_preprocessor.py` |
| Giao diện | `frontend/src/` |

## Quan hệ ẩn (R01–R04)

Nguồn chuẩn: `rule_catalog.py`, `inference_rules.py`, `frontend/src/utils/lawLabels.ts`, `GET /api/rules`.

| `inferred_from` | Luật (UI) | `type(r)` Neo4j | Hiển thị UI |
|-----------------|-----------|-----------------|-------------|
| R01 | Luật 1 — Gộp sở hữu vợ chồng | `KIỂM_SOÁT_GIA_ĐÌNH` | Kiểm soát gia đình |
| R02 | Luật 2 — Sở hữu gián tiếp qua CT con | `SỞ_HỮU_GIÁN_TIẾP` | Sở hữu gián tiếp |
| R03 | Luật 3 — Ảnh hưởng gián tiếp 5/25/50 | `CÓ_LỢI_ÍCH_GIÁN_TIẾP` / `ẢNH_HƯỞNG_GIÁN_TIẾP_TỚI` / `KIỂM_SOÁT_GIÁN_TIẾP` | *Ảnh hưởng gián tiếp* + Thấp/Trung bình/Cao |
| R04 | Luật 4 — Cùng cổ đông lớn | `CÙNG_CỔ_ĐÔNG_LỚN` | Cùng cổ đông lớn |

**R02 và R03:** cùng đi qua chuỗi cổ đông → công ty con thực sự (chỉ `CÓ_CÔNG_TY_CON` type=0); R02 bắt buộc hop đầu `LÀ_CỔ_ĐÔNG_CỦA` và luôn tạo `SỞ_HỮU_GIÁN_TIẾP`; R03 linh hoạt hơn ở hop đầu và chọn một trong ba loại cạnh theo ngưỡng. Các quan hệ `CÓ_CÔNG_TY_LIÊN_KẾT`, `LIÊN_DOANH_VỚI`, `ĐẦU_TƯ_VÀO` (type=1,2,3) không tham gia vào R02/R03.

**Số liệu (snapshot 2026-05-21):** 10 413 node (2 711 công ty, 7 702 cá nhân), 19 122 cạnh (119 loại), 280 cạnh ẩn (R01=32, R02=16, R03=232, R04=0).

**Legacy:** `R07`→`R03`, `R12`→`R04` (migrate khi khởi động API / chạy inference).

Chi tiết: [inference_rules.md](inference_rules.md), [entities_schema.md](entities_schema.md).
