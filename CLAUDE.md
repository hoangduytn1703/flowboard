# Flowboard — ghi chú cho Claude (đọc đầu mỗi phiên)

Công cụ **local, một người dùng** tạo clip quảng cáo (ảnh → video → ghép + lồng tiếng) cho **người làm affiliate TikTok Shop ở Việt Nam**. Tập trung vào chế độ **Quicktool** (`/clips`, `/products`), không phải Canvas (node).
Tạo ảnh/video đi qua Google Flow (cần gói Pro/Ultra) bằng extension Chrome; LLM dùng Gemini API key (nhập trong Cài đặt).

## Quy ước làm việc với người dùng
- Trả lời **tiếng Việt**, ngắn gọn. UI hiển thị **tiếng Việt**; prompt ảnh/video giữ **tiếng Anh** (Flow hiểu tốt hơn).
- Chỉ commit/push khi được bảo. Xoá dữ liệu hoặc dừng tiến trình đang chạy: hỏi trước (trừ khi được bảo rõ).
- Người dùng code ở 2 máy (cty + nhà), đồng bộ bằng git. Trí nhớ của Claude không đi theo máy, nên **tự cập nhật file này** khi cuối phiên hoặc sau một thay đổi quan trọng (tính năng mới, quyết định, bẫy vừa gặp, việc dở) — người dùng đã dặn **không cần nhắc**. Chỉ sửa file; commit/push vẫn chờ được bảo (nhưng nhắc rằng file cần push để máy kia thấy).

## Chạy
- Python 3.11+, Node 20+, Chrome, **ffmpeg + ffprobe** trên PATH. Máy Linux không có sudo: `uv` và ffmpeg nằm ở `~/.local/bin` (nhớ `export PATH=$HOME/.local/bin:$PATH`).
- `make install` (cần `python3-venv`; không có thì dùng `uv venv` + `uv pip install -e .` trong `agent/`), `cp .env.example .env`.
- `make agent` (FastAPI :8434, WebSocket extension :8355) và `make frontend` (Vite :5174).
- Extension: `chrome://extensions` → Load unpacked → `extension/`. Sửa extension thì phải **reload** nó. Cần một tab `flow.google.com` đã đăng nhập, để mở.
- Project Flow: đặt trong Cài đặt (`PUT /api/flow/projects/pinned`, tự chuyển các board sang project mới). Gói Pro/Ultra: `FLOWBOARD_PAYGATE_TIER` trong `.env`.

## Bẫy đã gặp (đừng lặp lại)
- **Gemini chậm/treo không hẳn do key rẻ, mà do model**: đo cùng một câu hỏi, `gemini-3.1-flash-lite` ~4 s, `3.5-flash` ~21 s (nhiều thinking token), `3.7`/`3.8-flash` quá 40 s. Việc đọc sản phẩm từ link dùng `product_link.EXTRACT_MODEL` (lite, ~13 s cả quy trình). Kịch bản clip (`analyze`) vẫn dùng model mặc định, có thể chậm; chưa đổi vì chưa so chất lượng. Fallback chỉ xử lý 503, không xử lý treo/timeout.
- **`NANO_BANANA_2` (NARWHAL) bị Flow từ chối** (`ogiZ0b failed: [5]`). Dùng `NANO_BANANA_PRO`. Giá trị đã lưu trong localStorage được ưu tiên hơn mặc định.
- Video: mặc định Omni Flash. Flow tự sinh giọng tiếng Anh vào video → `flow_sdk.silent_prompt()` thêm câu "no speech"; ở bước Ghép chọn "Tiếng gốc của clip" = nhỏ lại/tắt hẳn.
- `agent/flowboard/services/flow_batch.py` giữ **giống hệt bản flowkit upstream**, đừng sửa. Chính sách model nằm ở `flow_sdk.py`.
- `video_export`: bản ffmpeg static có NVENC nhưng máy không có GPU → đã có kiểm tra mã hoá thử. File clip 0 byte = lỗi.
- **Kill uvicorn thì worker con có thể mồ côi và giữ cổng 8355** → extension nối vào tiến trình cũ (`extension_disconnected`). Kill theo PID cả cây, **không dùng `pkill -f`** (giết luôn shell). `--reload` từng treo ở "Waiting for connections to close": Makefile đã có `--timeout-graceful-shutdown 3`.
- Wizard (`QuicktoolApp.tsx`) chỉ `switchBoard(id)` khi board có trong `boards` **và** `boardsLoaded` (store) đã true; không thì xoá clip sẽ gọi lại board vừa xoá → toast 404, còn mở thẳng link khi danh sách chưa tải thì bị đẩy về `/clips`.
- `PATCH /api/boards/{id}` gộp `data` một cấp (để lưu `step` không xoá `template_id`/`product_id`).
- `Product.media_ids` là media id của **Flow**, thuộc project lúc upload; ảnh gốc nằm trong `storage/media` (đổi project thì `media_project_sync` upload lại).

## Chỗ cần biết trong code
- Backend `agent/flowboard/`: `routes/products.py` (CRUD, `from-link`, `import-tiktok`, `bulk-delete`), `services/product_link.py` (đọc trang sản phẩm bằng httpx + Gemini; chặn IP nội bộ), `services/tiktok_import.py`, `services/reference_video.py` (clip từ video mẫu / link: `/api/reference-video/analyze`, `analyze-link`, `build`), `services/video_export.py`, `services/flow_sdk.py`, `templates/*.json` (4 kiểu clip).
- Frontend `frontend/src/quicktool/`: `QuicktoolApp.tsx` (route + wizard 5 bước), `NewClipDialog.tsx` (chọn sản phẩm, kiểu clip, "Số clip" N clip/1 sản phẩm), `quicktool.css`. `components/ProductsPanel.tsx` (trang `/products`, chọn nhiều + xoá). Cỡ chữ: thang riêng (chữ nội dung 16px); Canvas cố ý giữ chữ nhỏ.
- **Chế độ chỉ bàn tay**: ô "Giới tính mẫu" của mọi kiểu clip có thêm `Tay nữ` / `Tay nam` (`hands_female` / `hands_male`). `templates.render()` khi đó bỏ node nhân vật + cạnh nối, thêm câu "HANDS-ONLY SHOT…" vào prompt ảnh/video (không viết lại từng prompt), mô tả tay lấy từ ô `handLook` (mặc định "beautiful, well-groomed hands…"), quốc gia từ `charCountry`. **`fashion_ad` (quần áo) bắt buộc có người** (`person_required`): không có lựa chọn tay trên UI, backend/chat agent trả lỗi `PersonRequiredError` nếu gửi `hands_*`. Clip "theo video mẫu / link": màn review có ô **Người mẫu** (AI gợi ý / Nữ / Nam / Tay nữ / Tay nam / Không có người) + Quốc gia, gửi `character` lên `/api/reference-video/build` → `reference_video._character_for`. **Bước 1 wizard** có nút gạt Người mẫu ⇄ Chỉ bàn tay: `POST /api/boards/{id}/model-mode` (`services/model_mode.py`) xoá/tạo lại node nhân vật + cạnh, thêm/bỏ câu `HANDS_MARKER` trong prompt cảnh (idempotent), lưu `quicktool.hands`. Sản phẩm/kiểu thời trang bị từ chối ở cả ba chỗ. **Chưa tạo thử clip thật** để xem Flow vẽ tay có ổn không (kiểu quần áo chỉ tay có thể gượng).
- **Bước 1 · Sản phẩm nhận nhiều ảnh** (tối đa `MAX_PRODUCT_PHOTOS = 4`, `store/quicktool.ts`): "+ Thêm góc khác" tạo node `visual_asset` mới nối vào đúng các cảnh mà ảnh chính đang nối, rồi upload; "Bỏ ảnh" xoá node phụ (không xoá ảnh chính). Upload qua Flow mất ~10–15 s/ảnh.
- Sidebar chỉ có **một** mục "Công cụ nhanh" (mở hộp "Clip mới"; 6 kiểu clip chọn ở mục 2).
- Trang TikTok `shop.tiktok.com/.../pdp/<id>` đọc được không cần đăng nhập; ảnh `ibyteimg` đổi `resize-webp:260:260` → `800:800` để lấy ảnh to. Giá trên trang có nhiều mức nên Gemini có thể chọn sai: để người dùng kiểm tra.

## Việc đang dở / chưa kiểm chứng
- **Nhập từ TikTok bằng extension** (`scrape_page` trong `extension/background.js`) mới test trên HTML giả, chưa chạy trên trang TikTok thật. Trang chi tiết sản phẩm thì chỉ lấy sản phẩm chính (không lấy "sản phẩm liên quan").
- Chưa có: nút chạy tất cả N clip theo hàng đợi; kịch bản/giọng khác nhau cho từng clip (hiện chỉ khác bối cảnh).
- Chọn gói Pro/Ultra ngay trong Cài đặt (hiện sửa `.env`).
- Triển khai cho người khác: **để sau**. Hướng đã bàn: bạn cài local (đóng gói script + agent phục vụ giao diện build sẵn) là rẻ nhất; chạy trên server cần sửa extension (địa chỉ server, `wss`), đăng nhập, và vì hệ thống là một người dùng nên mỗi người một bản. Vercel đơn thuần không chạy được agent.
- Test: `pytest` toàn bộ chạy ~35 phút trên máy này; 41 test lỗi, trong đó phần thấy được là `test_llm_gemini.py` (CLI `agy`, nghi do môi trường), chưa rà hết.
