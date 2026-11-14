# PRD — "Lồng tiếng ngay" từ Cào video kênh (hướng B)

Ngày 15/11/2026 · trạng thái: chờ duyệt G2

## Kết quả chạy thử luồng hiện tại (Douyin thật, agent thử, 15/11)

Kênh Douyin 82 video: quét 28 giây; tải 6 video ngắn 20 giây, 6/6 được. Lồng tiếng 3 video một loạt: 121 giây. Thấy thật:

| # | Vấn đề | Bằng chứng |
|---|---|---|
| 1 | Video chỉ có nhạc, không lời → báo **lỗi đỏ** "Whisper không nghe ra câu nào" | video 73 |
| 2 | **Tên clip vẫn là chữ Trung** khi video ít lời | video 74: tên "冷冰冰的雪山…" |
| 3 | Bước "AI rà tên riêng" chiếm **41 / 75 giây** của một video 45 giây | video 75: 63 s → 104 s |
| 4 | Video chạy lần lượt, video sau chỉ ghi "Chờ đến lượt", không biết còn bao lâu | cả loạt |
| 5 | Phải bấm ở 2 trang, chờ cả loạt xong mới mở chỉnh được (đọc code) | — |

Lần này Douyin tải không lỗi; lỗi "Douyin không trả dữ liệu" các hôm trước là chập chờn nên vẫn cần tự thử lại.

## Phạm vi làm (MVP)

**P1. Hộp "🎙 Lồng tiếng ngay" tại Cào video kênh**
- Chọn video → bấm "🎙 Lồng tiếng N video" → hộp nhỏ: Lồng tiếng Việt / Chỉ phụ đề, giọng (có giọng nhân bản), mẫu chỉnh sửa, giữ nhạc nền. Nhớ lựa chọn lần trước.
- Bấm "Bắt đầu" một lần: tool tải video còn thiếu rồi tự lồng tiếng, không chuyển trang.
- Đạt khi: từ lúc tick video tới lúc việc chạy chỉ cần 2 lần bấm; lần sau mở hộp đã chọn sẵn như lần trước.

**P2. Tiến độ ngay trên thẻ video**
- Thẻ video hiện từng bước: đang tải → chờ lượt (thứ mấy) → đang nghe → dịch → đọc giọng → xuất → xong, kèm %.
- Xong: nút "✏️ Mở chỉnh" và "▶ Xem" ngay trên thẻ, không chờ các video khác.
- Thanh tổng phía trên danh sách: "Đang lồng tiếng 2/6 · còn khoảng 4 phút" + "Dừng tất cả".
- Đạt khi: không cần rời trang Cào kênh để biết video nào tới đâu; trạng thái cập nhật trong 3 giây.

**P3. Lỗi không làm đứng cả lượt**
- Tải lỗi (Douyin chập chờn): tự thử lại 2 lần, cách nhau vài giây; vẫn lỗi thì bỏ qua video đó, các video khác chạy tiếp.
- Video không có lời: ghi "Không có lời để lồng tiếng" (màu xám, không phải lỗi đỏ), gợi ý dùng nguyên video.
- Thẻ lỗi có nút "↻ Thử lại" cho đúng video đó.
- Đạt khi: 10 video một lượt, 1 video hỏng không chặn 9 video kia.

**P4. Sửa 2 lỗi tìm thấy**
- Tên clip luôn được dịch sang tiếng Việt (kể cả video ít lời).
- Bước rà tên riêng: giới hạn thời gian (đề xuất 20 giây); quá hạn thì giữ bản dịch Google và ghi chú, không để người dùng chờ.

## Không làm đợt này
- Trang "Hàng đợi" chung (hướng C).
- Chạy nhiều video lồng tiếng song song (Whisper dùng chung card).
- Đổi luồng "Cắt video" từ Cào kênh (giữ như hiện tại).
- Trang Lồng tiếng: giữ nguyên, chỉ thêm việc mở được video đã xong giữa loạt.

## Kiểm thử chấp nhận
Agent thử + Douyin thật: chọn 10 video (có 1 video không lời), bấm 2 lần, xem tiến độ trên thẻ, mở video đầu khi các video sau còn chạy, ngắt mạng giả một lượt tải để thấy tự thử lại. Kèm test tự động cho phần agent.
