---
trigger: 
description: Các nguyên tắc thiết kế web (Web Design Skills) dựa trên xu hướng 2026 và top 10 website công nghệ hàng đầu, đảm bảo tính thẩm mỹ, hiệu năng và trải nghiệm người dùng tối ưu.
---

# Web Design Skills & Guidelines cho Antigravity

Khi nhận được yêu cầu thiết kế giao diện hoặc viết mã frontend (HTML/CSS/JS/Components), bắt buộc phải áp dụng các kỹ năng và tiêu chuẩn sau để tạo ra giao diện đẳng cấp, hiện đại và tập trung vào trải nghiệm người dùng.

## 1. Top 10 Nguồn Cảm Hứng (Tham khảo từ awesome-design-md)
Học hỏi và áp dụng phong cách từ top 10 website có UI/UX được đánh giá cao nhất trong giới developer/tech:
1. **Stripe**: Đẳng cấp với các mảng gradient đẹp mắt, typography tinh tế, độ chính xác cao.
2. **Linear**: Tối giản tuyệt đối (ultra-minimalism), dark mode chuẩn mực, viền mỏng, nhấn mạnh màu tím.
3. **Vercel**: Chính xác với tông màu Đen & Trắng, tận dụng khoảng trắng (whitespace) và font chữ Geist.
4. **Apple**: Khoảng trắng cực lớn, typography cao cấp (SF Pro), ưu tiên hình ảnh/video điện ảnh.
5. **Raycast**: Thiết kế cho dev với giao diện mượt mà, chrome tối màu, điểm nhấn gradient sáng.
6. **Supabase**: Chủ đề ngọc lục bảo (emerald) tối, hướng tới lập trình viên (code-first).
7. **Framer**: Độ tương phản cao, tập trung mạnh vào chuyển động (motion-first) và thiết kế.
8. **Claude (Anthropic)**: Bố cục mang tính biên tập (editorial layout), màu đất (terracotta), gọn gàng.
9. **Notion**: Chủ nghĩa tối giản ấm áp (warm minimalism), viền bo tròn mềm mại, tạo cảm giác thân thiện.
10. **Airbnb**: Thân thiện, các nút/thẻ bo góc tròn lớn, màu nhấn coral nổi bật, tập trung vào thị giác.

## 2. Các Xu Hướng Thiết Kế Chủ Đạo 2026 (Trends & Best Practices)
*   **The "Human" Correction & Tactile Maximalism**: Sau thời gian dài phụ thuộc vào AI sinh ra các thiết kế quá hoàn hảo và phẳng, giao diện 2026 hướng tới sự "con người" hơn. Sử dụng các yếu tố có tính vật lý (tactile), hiệu ứng chiều sâu nhẹ (light skeuomorphism), hoặc nút bấm có cảm giác "jelly".
*   **Cognitive Clarity (Sạch, Yên tĩnh)**: Ưu tiên "calm interfaces", giảm tải nhận thức. Bố cục không quá nhiều chi tiết rườm rà, tập trung vào không gian thở (whitespace) và tính khả dụng để giúp người dùng thấy thư giãn khi trải nghiệm.
*   **Adaptive & Living Systems / Functional Motion**: Giao diện không còn tĩnh mà "sống động" (alive), phản ứng linh hoạt với ngữ cảnh của người dùng thông qua các chuyển động mang tính chức năng (functional motion) thay vì chỉ để trang trí.
*   **Anti-Grid & Organic Layouts**: Vượt rào cản của lưới (grid) cứng nhắc, kết hợp những đường cong tự nhiên, bố cục bất đối xứng để tạo sự phá cách (tuy nhiên với các công cụ tool/SaaS thì vẫn ưu tiên sự chính xác, có thể mix nhẹ để tạo điểm nhấn).
*   **Dark Mode & Theme Switching**: Mặc định hướng đến giao diện Dark Mode (như Linear, Raycast) cho các ứng dụng tech/tooling, vì nó giảm mỏi mắt và trông chuyên nghiệp. Cung cấp độ tương phản tối ưu.

## 3. Quy Nhược Bắt Buộc Khi Viết Code Giao Diện
*   **Semantic HTML**: Luôn ưu tiên dùng các thẻ có ý nghĩa (header, nav, main, article, section) thay vì chỉ dùng `div`.
*   **Performance (Hiệu năng)**: Code CSS gọn gàng, tránh lạm dụng thư viện nếu có thể tự viết bằng CSS thuần một cách hiệu quả.
*   **Accessibility (A11y)**: Đảm bảo độ tương phản màu sắc đáp ứng WCAG, thêm thẻ `aria-` và `alt` cho hình ảnh/icon, hỗ trợ điều hướng bằng bàn phím.
*   **Mobile-first**: Thiết kế từ màn hình nhỏ trước, sau đó dùng media queries scale up cho tablet/desktop.

> **Mục tiêu cuối cùng:** Giao diện cho dự án Knowledge Graph (KG) phải trông như một công cụ SaaS chuyên nghiệp, đẳng cấp, nhanh và cực kỳ tinh tế giống như các sản phẩm thuộc [Top 10](#1-top-10-nguồn-cảm-hứng).


# Anti-Slop Skill

Phát hiện và loại bỏ dấu hiệu nội dung AI rập khuôn ("slop"), giúp sản phẩm cuối xác thực, rõ ràng và chất lượng cao.

## AI Slop là gì?
Dấu hiệu nhận biết nội dung AI chất lượng thấp:
- **Văn bản**: Cụm sáo rỗng ("delve into", "navigate the complexities", "in today's fast-paced world"), buzzword quá tải, meta-commentary thừa.
- **Code**: Tên biến chung (`data`, `temp`, `item`), comment hiển nhiên, trừu tượng hóa vô cớ.
- **Design**: Gradient/glassmorphism lạm dụng, layout theo khuôn mẫu, copy marketing sáo rỗng ("Empower your business").

## Khi nào sử dụng
- Review nội dung AI trước bàn giao.
- Sáng tạo nội dung gốc, tránh lối mòn AI.
- Dọn dẹp dự án/nội dung cảm thấy "công nghiệp".
- Thiết lập tiêu chuẩn chất lượng cho nhóm.
- Người dùng yêu cầu phát hiện/xử lý slop.

## Quy trình 5 bước
1. **Detect**: Chạy script hoặc rà soát thủ công theo tài liệu tham chiếu.
2. **Analyze**: Xác định mẫu gây hại, đánh giá ngữ cảnh chấp nhận được.
3. **Clean**: Dùng script cho mẫu rõ ràng, can thiệp thủ công cho phần phức tạp.
4. **Review**: Đảm bảo ý nghĩa/giá trị cốt lõi không đổi.
5. **Refine**: Tối ưu giọng văn, cấu trúc, logic.

## Hướng dẫn xử lý nhanh
**📝 Văn bản**:
- *Xóa ngay*: Mở bài rườm rà, "it's important to note that", các từ đệm vô nghĩa.
- *Rút gọn*: "in order to" → "to", "due to the fact that" → "because".
- *Thay thế*: "leverage" → "use", "synergistic" → "cooperative".
- *Nguyên tắc*: Đi thẳng vào vấn đề, dùng ví dụ cụ thể, ưu đãi câu chủ động, đa dạng cấu trúc, giữ giọng văn phù hợp ngữ cảnh.

**💻 Mã nguồn**:
- *Đổi tên*: `data`/`result`/`item` → mô tả chính xác nội dung.
- *Xóa comment*: Bỏ comment mô tả việc code đã tự nói rõ.
- *Giản lược*: Xóa lớp trừu tượng thừa, thay tên hàm chung chung (`handleData()`) bằng hành động cụ thể.
- *Nguyên tắc*: Rõ ràng > "thông minh", tài liệu hóa "tại sao" chứ không phải "làm gì", đặt tên theo chức năng/trách nhiệm.

**🎨 Thiết kế**:
- *Visual*: Giảm gradient mặc định, hạn chế hiệu ứng trend vô cớ, tránh element trang trí không mục đích.
- *Layout*: Thiết kế theo nội dung thực tế, cân bằng whitespace có chủ đích, không ép mọi thứ vào card.
- *Copy*: Thay headline/CTA chung chung bằng giá trị cụ thể, giọng văn phản ánh đúng thương hiệu.
- *Nguyên tắc*: Content-first, mọi quyết định phải có lý do, ưu tiên nhu cầu user thay vì trend.

## Công cụ & Script
- `python scripts/detect_slop.py <file> [--verbose]`
  Quét văn bản, trả điểm slop (0-100), liệt kê mẫu & gợi ý sửa.
  *Thang điểm*: ≤20 (Tốt) | 20-40 (Trung bình) | 40-60 (Cao) | >60 (Nghiêm trọng).
- `python scripts/clean_slop.py <file> [--save] [--aggressive] [--output <file>]`
  Xem trước → Lưu (tự backup) → Chế độ mạnh (có thể đổi sắc thái). Chỉ xử lý văn bản. Luôn review kỹ output.

## Tài liệu tham chiếu (`references/`)
- `text-patterns.md`: Mẫu văn bản, quy tắc phát hiện, chiến lược sửa.
- `code-patterns.md`: Anti-pattern lập trình, hướng dẫn refactor đa ngôn ngữ.
- `design-patterns.md`: Mẫu thiết kế/UX, chiến lược cải thiện trực quan.
*Mỗi file chứa*: Định nghĩa, ví dụ, độ tin cậy, ngữ cảnh chấp nhận, hướng dẫn chi tiết.

## Thực hành tốt nhất
- **Phòng bệnh hơn chữa bệnh**: Viết cho đối tượng cụ thể, dùng ví dụ thực tế, bỏ mở bài rườm rà, chọn từ chính xác, tự rà soát trước khi hoàn tất.
- **Linh hoạt ngữ cảnh**: Văn học thuật/pháp lý cần hedging/cụm từ chuẩn. Luôn hỏi: "Ai đọc? Mục đích gì? Mẫu này có phục vụ mục đích không? Có cách tốt hơn không?"
- **Công cụ hỗ trợ tư duy**: Script chỉ gợi ý. Review thủ công bắt buộc với nội dung quan trọng. Ưu tiên: Chất lượng > đồng nhất, Ngữ cảnh > quy tắc, Rõ ràng > phức tạp, Cụ thể > chung chung.

## Kịch bản áp dụng
- **Review bài viết AI**: Đọc `text-patterns.md` → `detect_slop.py` → review → `clean_slop.py --save` → rà soát cuối.
- **Dọn codebase**: Đọc `code-patterns.md` → quét thủ công → lập danh sách đổi tên/refactor → test kỹ sau mỗi bước.
- **Audit thiết kế**: Đối chiếu `design-patterns.md` → chỉ ra lỗi visual/layout/copy → đề xuất giải pháp, ưu tiên cấu trúc trước thẩm mỹ.
- **Chuẩn nhóm**: Chốt điểm tối đa (VD: 30), yêu cầu review nếu >20, từ chối auto nếu >50. Tích hợp script vào pipeline.

## Giới hạn & Mẹo nhanh
- *Giới hạn*: Script chỉ xử lý văn bản. Code & Design cần đánh giá thủ công. Tối ưu tiếng Anh, code tập trung Python/JS/Java. Ngữ cảnh quyết định việc giữ/bỏ mẫu.
- *Text*: Detect trước → dùng non-aggressive cho nội dung quan trọng → ưu tiên xóa cụm rủi ro cao → luôn review.
- *Code*: Đổi tên biến → xóa comment thừa → refactor over-engineered → test.
- *Design*: Audit element → xử lý lỗi cấu trúc trước → đảm bảo phục vụ user → giữ nhất quán brand.