# Kế hoạch (thiết kế + việc)

## Thiết kế ngắn
- Không thêm bảng mới. Một video trong menu = một `dub.Job` (như phần cắt hiện nay: `mode sub`, `sub_lang none`), lưu `job.json` + snapshot trên clip.
- Video từ máy / clip ghép: job mới `kind "edit"` (đi cùng nhánh code với `kind "cut"`), nguồn = file đã tải lên / video cuối của clip; chưa có câu nào. Clip lồng tiếng / clip cắt: dùng luôn job sẵn có của nó.
- Danh sách "đang chỉnh" theo tài khoản: AppSetting `edit_list` (id job, mới nhất trước, tối đa 300).
- Nghe lời khi cần: `POST /api/edit/jobs/{id}/hear` (dùng runner Whisper sẵn có, chạy nền, dừng được).
- Trang mới `pages/EditPage.tsx` giữ nhóm video + trình chỉnh sửa (chuyển phần nhóm vừa làm ở `DubPage` sang đây).

## Việc, theo thứ tự
1. Backend `services/video_edit.py` + `routes/edit.py`: thêm từ file / từ clip, danh sách, bỏ khỏi danh sách, nghe lời; luật gói; test. → A1, A3, A5, A7
2. `EditPage` + menu + route: thả file, chọn clip, danh sách, tick, mở trình chỉnh sửa nhóm, áp cả loạt, xuất cả N, tải zip. → A1–A3
3. Nối các trang khác: nút "Chỉnh" ở Cào kênh / Clip của tôi / Lồng tiếng / Cắt sang `/tools/edit`; bỏ trình chỉnh sửa nhúng; chuyển hướng link cũ. → A4, A6
4. Tab 💬 Phụ đề: nút "🎧 Nghe lời để có phụ đề" cho video chưa có câu. → A5
5. Kiểm: test backend, `tsc`, Playwright trên bản thử cổng 8534 theo A1–A7, rồi bàn giao bản chạy thử cho bạn.
6. Ghi CLAUDE.md.

## Rủi ro
- `kind "edit"` phải đi qua mọi chỗ đang xét `kind == "cut"` (≈ 20 chỗ) — sót một chỗ là video không xuất được khi không có câu; có test riêng cho việc này.
- Bỏ trình chỉnh sửa nhúng đụng 2 trang lớn; làm sau cùng, sau khi menu mới đã chạy.
