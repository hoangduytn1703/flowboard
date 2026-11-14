# Brief — luồng "Cào video kênh → Lồng tiếng" mượt và chuyên nghiệp

Ngày 15/11/2026 · trạng thái: chờ duyệt G1

## Hiện trạng (đọc code, chưa chạy lại với Douyin thật)

- Stack: agent FastAPI (`services/channel_grab.py`, `services/dub.py`), giao diện React (`pages/GrabPage.tsx`, `pages/DubPage.tsx`, `dub/editor/*`).
- Douyin đọc qua Chrome của người dùng (extension 0.7.2, cần đăng nhập douyin.com); tải video qua trang chia sẻ mobile (chập chờn).
- Luồng hiện tại, đếm theo số lần người dùng phải làm gì:
  1. Trang Cào kênh: tick video → bấm "🎙 Lồng tiếng N video".
  2. Tool tải video chưa có (2 cái một lúc), chỉ báo bằng toast; xong tự chuyển trang.
  3. Trang Lồng tiếng: video nằm trong form, người dùng phải **cuộn xuống, chọn lại giọng / mẫu, bấm "Lồng tiếng" lần nữa**.
  4. Bảng loạt hiện %, **chờ cả loạt xong mới mở trình chỉnh sửa**; video chạy lần lượt.
  5. Quay lại Cào kênh: trạng thái từng video cập nhật chậm (30 giây một lần).

## Chỗ chưa mượt (giả thuyết, cần chạy thật để xác nhận)

1. Hai lần bấm cho một việc (bước 1 và 3), cài đặt giọng / mẫu nằm ở trang khác với nơi chọn video.
2. Lúc tải video không có màn tiến độ rõ (chỉ toast), một video lỗi là cả lượt đứng lại, phải bỏ chọn tay rồi bấm lại.
3. Douyin tải lúc được lúc không, không tự thử lại.
4. Không biết còn bao lâu; không mở được video đã xong khi các video khác còn chạy.
5. Trên danh sách Cào kênh không thấy tiến độ sống của video đang lồng tiếng.
6. Lỗi giữa chừng (tải, nghe, dịch, giọng) hiện ở nhiều nơi khác nhau, câu chữ không thống nhất.

## Mục tiêu

Chọn video ở Cào kênh → **một lần bấm** → theo dõi ở một chỗ → video nào xong mở chỉnh được ngay. Không có bước nào người dùng phải đoán "nó đang làm gì".

Đo thành công: (a) số lần bấm từ lúc tick video tới lúc có video lồng tiếng: từ ~4 xuống 1–2; (b) chạy thật 10 video Douyin liên tiếp, không lần nào phải làm lại tay vì lỗi tạm thời; (c) mọi trạng thái (tải, chờ, nghe, dịch, đọc giọng, xuất, lỗi) hiện trên cùng một thẻ của video.

## Ba hướng

- **A. Vá từng chỗ (nhỏ, ~1 buổi):** tự thử lại khi Douyin lỗi, video lỗi thì bỏ qua và làm tiếp các video còn lại, trạng thái ở Cào kênh cập nhật nhanh, mở được video đã xong giữa loạt.
- **B. "Lồng tiếng ngay" từ Cào kênh (vừa, ~1–2 buổi) — đề xuất:** gồm cả A, thêm hộp nhỏ ngay tại Cào kênh (giọng, mẫu chỉnh sửa, lồng tiếng / chỉ phụ đề — nhớ lựa chọn lần trước) → bấm một lần là tải + lồng tiếng chạy nền; thẻ video trên danh sách hiện tiến độ từng bước; xong thì nút "✏️ Mở chỉnh". Trang Lồng tiếng giữ nguyên cho ai dán link.
- **C. Trang "Hàng đợi" chung (lớn, vài buổi):** một màn theo dõi mọi việc nền (tải, cắt, lồng tiếng, xuất) thay cho nút "việc đang chạy". Đẹp nhất nhưng đụng nhiều chỗ.

## Cách kiểm thử

Agent thử riêng (cổng 8534, dữ liệu tạm) + Chromium có extension và đăng nhập Douyin (hồ sơ `D:\dflow-qc\chrome-profile`, nếu phiên đăng nhập còn). Trước khi sửa: chạy luồng hiện tại với 5–10 video của một kênh Douyin, ghi lại từng chỗ vấp kèm ảnh chụp, để danh sách ở trên thành sự thật đo được.
