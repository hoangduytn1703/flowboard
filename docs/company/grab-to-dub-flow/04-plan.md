# Thiết kế + kế hoạch (gộp 03 / 04) — đã làm xong 15/11

Giám đốc duyệt "OK hết, làm luôn" ở G2 nên thiết kế và kế hoạch ghi gọn ở đây, không dừng ở G3.

## Thiết kế
- **Agent điều phối, không phải trang web:** `services/grab_dub.py` giữ từng video đang "trên đường" (tải → chờ chỗ → giao cho hàng đợi lồng tiếng). Rời trang vẫn chạy. Giao xong thì video là một job lồng tiếng bình thường.
- **Một nguồn trạng thái:** `GET /api/grab/work` trả cả video đang tải / chờ lẫn job lồng tiếng (thêm `ahead`, `media_id`, `name`, `mode`, trạng thái `downloading`, `nospeech`). Trang đọc 2,5 giây một lần khi có việc.
- **Không đổi kiến trúc lồng tiếng:** vẫn một video một lúc (Whisper dùng chung card).

## Việc đã làm
| # | Việc | Kiểm bằng |
|---|---|---|
| 1 | `POST /api/grab/dub`, `/api/grab/dub/stop`, `grab_dub.py` | `test_grab_dub.py` |
| 2 | Tải lỗi tạm thời tự thử lại 3 lần; lỗi vĩnh viễn (quá dài…) không thử lại | test |
| 3 | Hàng đợi lồng tiếng đầy → video chờ, không lỗi (gửi được 30 video một lượt) | test |
| 4 | Hộp "Lồng tiếng ngay" (`grab/DubNowDialog.tsx`), nhớ lựa chọn | chạy thật |
| 5 | Thẻ video: tiến độ từng bước, chờ lượt, xong có "Mở chỉnh" / "Xem", không lời (xám), lỗi + "Thử lại" | chạy thật |
| 6 | Thanh tổng: x/y xong, còn khoảng N phút, "Dừng tất cả" | chạy thật |
| 7 | Tên clip dịch từ đúng tiếng của caption | test + chạy thật |
| 8 | Rà tên riêng tối đa 20 giây | test + chạy thật |
| 9 | Trang Lồng tiếng: mở video đã xong khi loạt còn chạy | chạy thật |
| 10 | Kéo phụ đề: mặc định "Tất cả câu" | chạy thật |
