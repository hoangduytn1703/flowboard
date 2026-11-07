# DFlow

Công cụ **chạy trên máy (local), một người dùng** để làm nội dung cho người làm affiliate TikTok Shop / Shopee ở Việt Nam:
tạo clip quảng cáo từ ảnh sản phẩm, lồng tiếng video, viết bài Facebook, lên lịch và tự đăng lên Facebook Page.

## Tính năng chính

- **Clip quảng cáo** (`/clips`): wizard 5 bước — sản phẩm & người mẫu → kịch bản (AI viết theo sản phẩm, quay kiểu điện thoại như người thật) → ảnh cảnh → video (Google Flow) → ghép + giọng đọc tiếng Việt, chữ trên video, nhạc nền, ảnh bìa. Có chế độ **🔇 Không lời** (chỉ hình + tiếng động thật).
- **Sản phẩm, người mẫu, prompt** đã lưu; nhập sản phẩm từ link / tab TikTok, Shopee.
- **Lồng tiếng video** (`/tools/dub`): Whisper → dịch (Google miễn phí, AI rà tên riêng) → giọng Việt → phụ đề; trình chỉnh sửa kiểu CapCut, thư viện link, cắt thành nhiều clip.
- **Edit auto CapCut** (`/tools/capcut`, chỉ Windows): ghi thẳng dự án CapCut có phụ đề, chữ nhấn, zoom, SFX.
- **Bài viết Facebook** (`/posts`), **Kênh của tôi** (`/channels`), **Mẫu đang hot** (`/swipes`), **🤖 Trợ lý AI** (nút tròn góc dưới phải).
- **Lịch đăng** (`/schedule`): giờ vàng, kéo thả, tự đăng lên Facebook Page (bài viết / Reel / tin), **🤖 tự động đăng theo lịch**, đồng bộ ngược bài đăng tay và số liệu.
- **Hôm nay** (`/today`): việc cần làm, đang chạy, clip chưa tải.

## Cần gì cho nhu cầu nào

Không phải ai cũng cần hết. Phần **lõi** là bắt buộc; các dòng dưới chỉ cài khi dùng tới tính năng đó.

| Nhu cầu | Bắt buộc | Tuỳ chọn |
|---|---|---|
| **Lõi** (mở app, sản phẩm, người mẫu, prompt, lịch) | Python 3.11+, Node 20+, `ffmpeg` + `ffprobe` trên PATH, Chrome | `uv` (cài nhanh hơn pip) |
| **Clip quảng cáo** (ảnh + video) | Lõi + tài khoản Google có **Flow gói Pro / Ultra**, extension **DFlow Bridge** trong Chrome, một tab `flow.google.com` đã đăng nhập, một project Flow | — |
| **AI viết kịch bản, bài viết, trợ lý, lời thoại** | Một AI trong Cài đặt → AI Providers: **Claude Code CLI** (`claude`), **Gemini CLI** (`agy`) hoặc **Codex CLI** (`codex`) đã đăng nhập | — |
| **Đọc sản phẩm từ link, clip theo link / video mẫu, giọng Gemini, rà tên riêng khi lồng tiếng** | **Gemini API key** (miễn phí ở aistudio.google.com, nhập ở Cài đặt → Gemini key; nên có nhiều key) | — |
| **Giọng đọc** | Edge (miễn phí, cần internet) — có sẵn | Gemini TTS (key ở trên), **VieNeu** (miễn phí, chạy trên máy — cần bộ lồng tiếng bên dưới), FPT.AI (key riêng) |
| **Phụ đề kiểu Remotion** (đẹp hơn ffmpeg) | Đã nằm trong `npm install`; lần render đầu tự tải Chrome Headless (~150 MB) | — |
| **Tải video từ link** (TikTok, YouTube, IG, FB, X) | `yt-dlp` trên PATH (`winget install yt-dlp`) — Douyin không cần | — |
| **Lồng tiếng video**, **xoá phụ đề AI** | Bộ **pyvideotrans / VieDub** có `.venv` + model Whisper large-v3-turbo (xem bên dưới) | GPU NVIDIA (nhanh hơn nhiều; CPU vẫn chạy), model spleeter (giữ nhạc nền), LaMa (xoá phụ đề) |
| **Edit auto CapCut** | Windows + **CapCut bản máy tính**, CapCut đang đóng khi tạo dự án | Bộ lồng tiếng (để có phụ đề cho clip / video tải lên) |
| **Tự đăng Facebook Page**, đồng bộ & số liệu | App Meta + token Page có quyền `pages_show_list`, `pages_manage_posts`, `pages_read_engagement`, `pages_manage_engagement` | `read_insights` (lượt xem, giữ chân Reel) |
| **Tự động đăng theo lịch** | Máy bật + agent đang chạy lúc tới giờ | — |
| **Dữ liệu trên cloud** (dùng nhiều máy) | Postgres (Neon) + bucket S3 (Backblaze B2) | Không có thì dữ liệu nằm trong `storage/` trên máy |

## Cài phần lõi

### Windows (khuyên dùng)

1. Cài Python 3.11, Node 20, Git, ffmpeg (`winget install Gyan.FFmpeg`), Chrome. Mở terminal mới để PATH nhận ffmpeg.
2. Lấy code: `git clone git@github.com:hoangduytn1703/flowboard.git` rồi `cd flowboard`.
3. Chạy lần đầu, kèm project Flow và gói:

   ```powershell
   .\start.ps1 -FlowProjectId <uuid trong URL project Flow> -Plan Ultra   # hoặc -Plan Pro
   ```

   Script tự tạo `.env`, tạo `agent/.venv`, cài thư viện Python + `npm install` (chỉ khi thay đổi), chạy giao diện và agent.
   Những lần sau chỉ cần `.\start.ps1`. **Để cửa sổ đó mở** — đóng là agent tắt (lịch tự đăng cũng dừng).
4. Extension: `chrome://extensions` → bật Developer mode → **Load unpacked** → chọn thư mục `extension/`. Mỗi lần extension đổi phiên bản phải bấm **Reload**.
5. Mở một tab `flow.google.com` đã đăng nhập (đúng tài khoản có gói Pro / Ultra) và để nó mở.
6. Vào **http://localhost:5174**, đăng nhập bằng tài khoản tạo sẵn (`FLOWBOARD_SEED_USER` / `FLOWBOARD_SEED_PASSWORD`, xem CLAUDE.md mục "Đăng nhập").
   Rồi vào **Cài đặt**: chọn AI (AI Providers), dán Gemini key, kiểm tra project Flow ở tab Google Flow.

### Linux / macOS

```bash
make install            # agent/.venv (uv nếu có) + frontend/node_modules
cp .env.example .env    # điền FLOWBOARD_FLOW_PROJECT_ID và FLOWBOARD_PAYGATE_TIER (TIER_ONE = Pro, TIER_TWO = Ultra)
make agent              # API :8434, WebSocket extension :8355
make frontend           # giao diện :5174 (terminal khác)
```

Bước extension, tab Flow và đăng nhập giống Windows. Không có `sudo`: cài `uv` và ffmpeg vào `~/.local/bin`.

**Cổng cố định** (đừng đổi — extension và Vite ghi cứng): giao diện **5174**, API **8434**, WebSocket extension **8355**.
Chạy song song được với flowkit (5173 / 8100 / 9222).

## Cài thêm theo nhu cầu

### Lồng tiếng video / xoá phụ đề AI / giọng VieNeu

Phần nặng (Whisper, tách nhạc, LaMa, VieNeu) chạy bằng **môi trường Python của pyvideotrans (VieDub)** — không cài torch vào DFlow.

1. Clone và cài pyvideotrans / VieDub theo hướng dẫn của repo đó (tạo `.venv`, cài torch bản CUDA nếu có GPU NVIDIA).
2. Mở VieDub chạy thử một video để nó tự tải model về `models/`:
   - Whisper: `models/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/` (bắt buộc cho lồng tiếng, ~1,6 GB)
   - Tách nhạc nền: `models/onnx/vocals.fp16.onnx`, `accompaniment.fp16.onnx` (cho ô "Giữ nhạc nền")
   - Xoá phụ đề: `models/lama/big-lama.pt`
   - VieNeu: gói `vieneu` trong `.venv` của VieDub; model tự tải lần đầu (~580 MB)
3. Nếu repo không nằm ở `D:\codes\pyvideotrans`, thêm vào `.env`:

   ```
   FLOWBOARD_ERASE_ROOT=<thư mục pyvideotrans>
   FLOWBOARD_ERASE_PYTHON=<thư mục pyvideotrans>\.venv\Scripts\python.exe
   ```

Trang Lồng tiếng tự báo thiếu gì. Không có bộ này thì trang Lồng tiếng báo "chưa dùng được", công cụ xoá chữ chỉ còn chế độ khoanh vùng (ffmpeg); các phần khác vẫn chạy bình thường.

### Edit auto CapCut (Windows)

Cài CapCut bản máy tính, mở một dự án có sẵn các kiểu chữ bạn hay dùng (gõ dòng "Phụ đề" / "Nhấn mạnh" / "Tiêu đề" để tool nhận vai) rồi **đóng CapCut** và bấm "Học" trong trang. Thư mục dự án mặc định `%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft` (đổi bằng `FLOWBOARD_CAPCUT_DRAFTS`).

### Tự đăng Facebook Page

Tạo app ở developers.facebook.com (trường hợp sử dụng "Quản lý mọi thứ trên Trang"), lấy token người dùng có đủ quyền ở bảng trên bằng Graph API Explorer, gia hạn thành token dài hạn, rồi dán ở **Kênh → Tự đăng lên Facebook Page**. Các bước chi tiết và lỗi hay gặp: CLAUDE.md mục "Bẫy đã gặp" → "Lấy token Facebook Page".

### Dữ liệu trên cloud (nhiều máy)

Thêm `FLOWBOARD_CENTRAL_DB_URL=postgresql://…` (chuỗi kết nối Neon) vào `.env` của mỗi máy, rồi cấu hình bucket ở **Cài đặt → Dữ liệu**. Đăng nhập máy nào cũng thấy cùng dữ liệu; file media tự tải về khi cần. Chuỗi kết nối và key chỉ để trong `.env` / Cài đặt, **không commit**.

## Gặp lỗi

- Giao diện báo mất kết nối extension → Reload extension, kiểm tra tab `flow.google.com` còn mở và agent đang chạy (cổng 8355).
- Video "Flow bỏ lượt" / timeout hàng loạt → xem project Flow đang ghim (Cài đặt → Google Flow), người mẫu có bị Flow chặn không (nút "🎬 Kiểm tra với Flow" ở Bước 1).
- AI không viết được → Cài đặt → AI Providers chưa chọn, hoặc CLI chưa đăng nhập / hết lượt.

Chi tiết cách chạy, cấu trúc code, các bẫy đã gặp và nhật ký thay đổi: **[CLAUDE.md](CLAUDE.md)**.

---

© 2026 DuyNH
