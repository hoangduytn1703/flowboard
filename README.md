# DFlow

Công cụ **chạy trên máy (local), một người dùng** để làm nội dung cho người làm affiliate TikTok Shop / Shopee ở Việt Nam:
tạo clip quảng cáo từ ảnh sản phẩm, lồng tiếng video, viết bài Facebook, lên lịch và tự đăng lên Facebook Page.

## Tính năng chính

- **Clip quảng cáo** (`/clips`): wizard 5 bước — sản phẩm & người mẫu → kịch bản (AI viết theo sản phẩm) → ảnh cảnh → video (Google Flow) → ghép + giọng đọc tiếng Việt, chữ trên video, nhạc nền, ảnh bìa.
- **Sản phẩm, người mẫu, prompt** đã lưu; nhập sản phẩm từ link / tab TikTok, Shopee.
- **Lồng tiếng video** (`/tools/dub`): Whisper → dịch → giọng Việt → phụ đề; trình chỉnh sửa kiểu CapCut, thư viện link.
- **Edit auto CapCut** (`/tools/capcut`, chỉ Windows): ghi thẳng dự án CapCut có phụ đề, chữ nhấn, zoom, SFX.
- **Bài viết Facebook** (`/posts`), **Kênh của tôi** (`/channels`), **Mẫu đang hot** (`/swipes`).
- **Lịch đăng** (`/schedule`): giờ vàng, kéo thả, tự đăng lên Facebook Page (bài viết / Reel), đồng bộ ngược bài đăng tay và số liệu (lượt xem, ❤ 💬 ↗, tỉ lệ giữ chân Reel).
- **Hôm nay** (`/today`): việc cần làm, đang chạy, clip chưa tải.

## Chạy

Cần Python 3.11+, Node 20+, Chrome, `ffmpeg` + `ffprobe` trên PATH.

```bash
make install            # cài dependency (agent/.venv + frontend/node_modules)
cp .env.example .env    # rồi điền cấu hình
make agent              # API :8434, WebSocket extension :8355
make frontend           # giao diện :5174
```

Windows: `.\start.ps1`. Extension Chrome: `chrome://extensions` → Load unpacked → `extension/`, mở sẵn một tab `flow.google.com` đã đăng nhập.

Chi tiết cách chạy, cấu trúc code, các bẫy đã gặp và nhật ký thay đổi: **[CLAUDE.md](CLAUDE.md)**.

---

© 2026 DuyNH
