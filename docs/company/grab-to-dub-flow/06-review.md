# Rà soát code + bảo mật — 15/11/2026

Tự rà trên diff (chưa có người thứ hai xem).

## Đã sửa trong lúc rà
- Người dùng bấm dừng một lượt tải → video rời lượt lồng tiếng, không hiện thành lỗi đỏ.
- % tiến độ có số lẻ ("30.400000%") → làm tròn ở cả agent lẫn thẻ.
- Video đã có trên máy hiện nhầm "Đang tải video về" trong 1 giây đầu → "Đang chuẩn bị".

## Để ý, chưa đổi
- "Dừng tất cả" dừng mọi job lồng tiếng đang chạy / chờ có nguồn là video của Cào kênh — kể cả job gửi từ trang Lồng tiếng.
- Video đang trên đường (chưa vào hàng đợi lồng tiếng) chỉ nằm trong RAM: khởi động lại agent là quên, phải gửi lại. Job đã vào hàng đợi thì không mất.
- "Còn khoảng N phút" tính theo độ dài video; giọng VieNeu chậm hơn Edge nên có thể lệch.
- Lựa chọn của hộp "Lồng tiếng ngay" nhớ theo máy (localStorage), không theo tài khoản.

## Bảo mật
- `POST /api/grab/dub` cần đăng nhập và tính năng gói `dub` (luật mới trong `plans.py`, có test); chỉ nhận id video (≤ 30), giọng và mẫu được kiểm trước khi chạy.
- Không thêm chỗ nào ghi file theo tên người dùng gửi; không có bí mật mới.
