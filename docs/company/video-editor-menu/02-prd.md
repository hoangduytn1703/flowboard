# PRD — menu "🎞 Chỉnh sửa video" (hướng B, đợt 1)

Đã chốt 15/11: hướng B; rút gọn form các menu cũ **để sau** (xem xong đợt này mới quyết); video từ máy không tự nghe lời lúc import.

## Phạm vi đợt 1
1. **Menu mới "🎞 Chỉnh sửa video"** (`/tools/edit`, nhóm Công cụ).
2. **Đưa video vào** bằng 3 cách:
   - thả / chọn nhiều file từ máy (một lượt tối đa 30 file);
   - "🎬 Chọn từ Clip của tôi" (mọi clip có video: clip quảng cáo đã ghép, clip lồng tiếng, clip cắt);
   - nút "✏️ Chỉnh" / "✏️ Chỉnh N video" ở Lồng tiếng, Cắt video, Cào video kênh, Clip của tôi → sang menu này.
3. **Danh sách video đang chỉnh**: ảnh, tên, độ dài, trạng thái (chưa chỉnh / đã chỉnh chưa xuất / đang xuất x% / ✓ đã xuất / lỗi); tick nhiều; "✏️ Chỉnh N video", "⬇ Tải N (.zip)", "🗑 Bỏ khỏi danh sách" (không xoá clip, không xoá file gốc).
4. **Trình chỉnh sửa** (cái đang có) mở với các video đã tick: ô "Video n/N", "⇪ Áp cho cả loạt", "✓ Xuất cả N đã sửa", ★ Mẫu. "← Danh sách" quay về menu này (hoặc trang đã gửi video sang).
5. **Phụ đề cho video từ máy**: mặc định không có. Bật phụ đề ở tab 💬 thì tool mới nghe lời video đó (có tiến độ, dừng được).
6. Mỗi video xuất ra thành một clip trong "Clip của tôi" (như phần cắt hiện nay) để tải / đăng / lồng tiếng tiếp.
7. Trang Lồng tiếng và Cắt video **không nhúng trình chỉnh sửa nữa**; link cũ (`/tools/dub?job=`, `/tools/cut?job=`) tự chuyển sang menu mới. Riêng việc sửa bản dịch / giọng của video lồng tiếng vẫn làm trong cùng trình chỉnh sửa đó.

## Không làm đợt này
Rút gọn form Lồng tiếng / Cắt / Cào kênh; sticker, chuyển cảnh, nhiều lớp video; trợ lý AI cho menu mới (thêm sau khi luồng ổn).

## Tiêu chí nghiệm thu
- A1. Thả 10 file mp4 → cả 10 hiện trong danh sách trong < 1 phút (không chờ nghe lời).
- A2. Tick 10 → Chỉnh → đổi khung 9:16 + nền + tiêu đề ở video 1 → "Áp cho cả loạt" → cả 10 xuất xong, mỗi video giữ tiêu đề riêng; tổng ≤ 5 lần bấm kể từ lúc thả file.
- A3. Chọn 5 clip từ Clip của tôi (lẫn clip lồng tiếng và clip ghép) → mở chung một trình chỉnh sửa.
- A4. Từ Cào video kênh tick 10 video đã lồng → "✏️ Chỉnh 10 video" → vào menu mới với đủ 10.
- A5. Bật phụ đề cho một video từ máy → nghe lời → phụ đề hiện, xuất được.
- A6. Link cũ `/tools/dub?job=…` và `/tools/cut?job=…` vẫn mở đúng video.
- A7. Gói: menu hiện khi tài khoản có `dub` hoặc `cut` (không thêm tính năng gói mới).
