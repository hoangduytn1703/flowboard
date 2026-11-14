# Kiểm thử — 15/11/2026

Môi trường: agent thử cổng 8534, dữ liệu tạm `D:\dflow-qc`, kênh Douyin thật 82 video, Chromium của Playwright.

## Chạy thật: 5 video Douyin, giọng nhân bản (VieNeu), giữ nhạc nền
- Tick 5 video → "🎙 Lồng tiếng 5 video" → "▶ Bắt đầu": **2 lần bấm**, không chuyển trang. Hộp ghi đúng "tải 1 video còn thiếu".
- Thẻ video hiện từng bước (tải → chờ lượt "còn N video trước" → Whisper → dịch → rà tên → đọc giọng → xuất) kèm %.
- Video đầu xong ở giây 71: có "✏️ Mở chỉnh" / "▶ Xem" trong lúc 3 video sau còn chạy.
- Video chỉ có nhạc: thẻ xám "Không có lời để lồng tiếng", các video khác chạy tiếp.
- Tên clip đã ra tiếng Việt ("Núi tuyết lạnh giá, bữa cơm nóng hổi!…") — trước là chữ Trung.
- Rà tên riêng: 10–20 giây mỗi video (trước 41 giây).
- Cả lượt: 7 phút 16 giây, 4 xong + 1 không lời, 0 lỗi. Ước lượng ban đầu "còn khoảng 7 phút".
- Phần lớn thời gian là giọng VieNeu đọc trên máy (38 câu = 110 giây); giọng Edge nhanh hơn nhiều.

## Kiểm thêm
- Trình chỉnh sửa mở từ thẻ: ô "Chỉnh cho" mặc định **Tất cả câu**.
- Trang Lồng tiếng, loạt 2 video: bấm "✏️ Mở" ở video đã xong khi video kia đang chạy → vào trình chỉnh sửa, 4 giây sau vẫn ở đó; "← Danh sách" quay lại bảng loạt.
- Không có lỗi JavaScript trong cả hai lượt.

## Test tự động
- `test_grab_dub.py` (4): tải rồi lồng tiếng, video lỗi không chặn video khác, tự thử lại, hàng đợi đầy thì chờ, dừng tất cả, luật gói, tên clip, giới hạn rà tên.
- Cả bộ test backend: xem kết quả ở `STATUS.md`.

## Chưa kiểm
- Tự thử lại khi Douyin từ chối **thật** (lần này Douyin không lỗi; mới có test giả lập).
- 10 video trở lên một lượt, và lượt 30 video.
- "Dừng tất cả" và "↻ Thử lại" bấm trên giao diện (mới qua test API).
- Kéo phụ đề bằng chuột sau khi đổi mặc định (mới xem ô chọn đúng).
- Trên app cài (WebView2) và trong Chrome thật của giám đốc.
