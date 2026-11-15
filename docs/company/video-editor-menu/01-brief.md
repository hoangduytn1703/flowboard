# Brief — menu "🎞 Chỉnh sửa video" + tinh gọn các menu video

## Hiện trạng (quét nhanh 15/11)
- Trình chỉnh sửa kiểu CapCut (`quicktool/dub/editor/DubEditor.tsx`) chỉ mở được **từ bên trong** trang Lồng tiếng hoặc Cắt video; không có lối vào riêng.
- "⇪ Áp cho cả loạt" chỉ có khi video cùng một lượt dán link (Lồng tiếng) hoặc cùng một lượt cắt (Cắt video). Video lồng từ Cào video kênh là việc lẻ → phải mở từng cái.
- Video trên máy muốn chỉnh (khung 9:16, nền, chữ, sáng tối, tốc độ…) phải đi vòng qua Lồng tiếng hoặc Cắt video.
- Ba trang Lồng tiếng / Cắt video / Cào video kênh mỗi trang đều tự có: form nhiều tuỳ chọn + danh sách việc + trình chỉnh sửa nhúng → nhiều bước, nhiều nút trùng nhau.
- Phần đang dở, chưa commit (dùng lại được): API lấy nhiều dự án theo danh sách (`GET /api/dub/jobs?ids=`), trang Lồng tiếng mở nhóm video (`?jobs=`), nút "✏️ Chỉnh N video" ở Cào video kênh / Clip của tôi / Cắt video. `tsc` + 51 test đạt, chưa xem trên trình duyệt.

## Mục tiêu
Một chỗ duy nhất để chỉnh video, nhận nhiều video một lần, chỉnh một video rồi áp cho tất cả. Các menu còn lại ít bước hơn.

## Người dùng & thước đo
- Người làm affiliate xử lý 10–30 video một lượt.
- Đạt khi: 10 video (từ máy hoặc từ Clip của tôi) → cùng một kiểu → xuất xong, với ≤ 5 lần bấm và không phải rời trang.

## Ba hướng
**A. Chỉ thêm menu mới** — menu "Chỉnh sửa video" (import nhiều file / chọn từ Clip của tôi), các menu khác giữ nguyên. Nhanh nhất (~1 buổi), nhưng không giải quyết chuyện rối.

**B. Menu mới là nơi chỉnh duy nhất (đề xuất)** —
- "🎞 Chỉnh sửa video": thả nhiều file / chọn từ Clip của tôi → danh sách video → trình chỉnh sửa có ô "Video n/N" + "⇪ Áp cho cả loạt" + "Xuất cả N".
- Lồng tiếng, Cắt video, Cào video kênh **chỉ làm ra video**; xong thì nút "✏️ Chỉnh" đưa sang menu mới (bỏ trình chỉnh sửa nhúng ở từng trang).
- Form của ba trang đó rút gọn: chỉ còn nguồn + 1–2 lựa chọn chính, phần còn lại gập vào "Tuỳ chọn thêm" và nhớ lựa chọn lần trước.
- Khoảng 2–3 buổi; dùng lại gần hết code hiện có.

**C. Gộp tất cả thành một "Xưởng video"** — một trang theo bước: Nguồn → Xử lý (cắt / lồng tiếng / phụ đề) → Chỉnh → Xuất. Gọn nhất về lâu dài nhưng viết lại nhiều, rủi ro vỡ thứ đang chạy; nên để sau khi B ổn.

## Ngoài phạm vi (đợt này)
Sticker / chuyển cảnh / nhiều lớp video, Edit auto CapCut, wizard clip quảng cáo 5 bước.
