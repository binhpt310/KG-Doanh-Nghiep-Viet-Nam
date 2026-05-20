# Giao diện web (frontend)

Ứng dụng React + TypeScript + Vite cho đồ thị tri thức doanh nghiệp niêm yết Việt Nam. Mục lục tài liệu: [docs/README.md](README.md) · Tổng quan dự án: [README.md](../README.md).

## Chạy phát triển

```bash
npm install
npm run dev
```

Mặc định: `http://localhost:5173`. Proxy `/api` → `http://127.0.0.1:5001` (timeout 600s cho truy vấn chat chậm). Cần backend Flask đang chạy (`backend/script.py`).

## Build production

```bash
npm run build
```

Artifact trong `dist/`. Image Docker `kg-ui` dùng build này + Nginx (xem `Dockerfile.frontend`, `docker/nginx.conf`).

## Cấu trúc chính

| Thư mục / file | Vai trò |
|----------------|---------|
| `src/components/` | `TopBar`, `LeftRail`, `AssistantPanel`, `NodeDetailPanel`, … |
| `src/graph/useKgGraph.ts` | Tải graph vis-network, láng giềng |
| `src/api/client.ts` | Gọi `/api/*` |
| `src/content/copy/vi.ts` | Chuỗi giao diện tiếng Việt |
| `src/utils/lawLabels.ts` | Nhãn Luật 1–4 / quan hệ ẩn |
| `public/runtime-architecture.svg` | Sơ đồ kiến trúc runtime |

## Ghi chú

- Modal **Kết nối LLM** và chat: `AssistantPanel.tsx` — thanh kéo giữa ô nhập và lưới gợi ý (`kg_prompt_grid_height` trong `localStorage`).
- Copy tiếng Việt tập trung tại `content/copy/vi.ts`; không chỉnh trực tiếp chuỗi rải rác trong component nếu có thể thêm vào file copy.
