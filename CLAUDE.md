# Flowboard — ghi chú cho Claude (đọc đầu mỗi phiên)

Công cụ **local, một người dùng** tạo clip quảng cáo (ảnh → video → ghép + lồng tiếng) cho **người làm affiliate TikTok Shop ở Việt Nam**. Tập trung vào chế độ **Quicktool** (`/clips`, `/products`), không phải Canvas (node).
Tạo ảnh/video đi qua Google Flow (cần gói Pro/Ultra) bằng extension Chrome; LLM dùng Gemini API key (nhập trong Cài đặt).

## Quy ước làm việc với người dùng
- Trả lời **tiếng Việt**, ngắn gọn. UI hiển thị **tiếng Việt**; prompt ảnh/video giữ **tiếng Anh** (Flow hiểu tốt hơn).
- Chỉ commit/push khi được bảo. Xoá dữ liệu hoặc dừng tiến trình đang chạy: hỏi trước (trừ khi được bảo rõ).
- Người dùng code ở 2 máy (cty + nhà), đồng bộ bằng git. Trí nhớ của Claude không đi theo máy, nên file này là trí nhớ chung.
- **BẮT BUỘC (người dùng dặn 20/10, không cần nhắc lại): code xong / sửa xong bất cứ thứ gì thì ghi ngay vào file này**, trước khi báo cáo:
  1. thêm một dòng vào **Nhật ký** (cuối file): ngày, làm gì, file/route chính, đã thử thật chưa;
  2. cập nhật mục **Chỗ cần biết trong code** nếu có module/route/bảng mới, **Bẫy đã gặp** nếu vừa dính bẫy,
     **Việc đang dở** nếu còn phần chưa xong / chưa kiểm chứng; xoá hoặc sửa dòng đã lỗi thời.
  Mục tiêu: mở máy khác, đọc file này là làm tiếp được. Commit/push vẫn chờ được bảo (nhắc rằng file cần push để máy kia thấy).
- Nhật ký lỗi/tính năng chi tiết (FB-xxx) nằm ở `D:\codes\flow-AI\BUGLOG.md` — **ngoài repo, không đồng bộ qua git**; điều cần cho máy kia phải có trong file này.

## Chạy
- Python 3.11+, Node 20+, Chrome, **ffmpeg + ffprobe** trên PATH. Máy Linux không có sudo: `uv` và ffmpeg nằm ở `~/.local/bin` (nhớ `export PATH=$HOME/.local/bin:$PATH`).
- `make install` (cần `python3-venv`; không có thì dùng `uv venv` + `uv pip install -e .` trong `agent/`), `cp .env.example .env`.
- `make agent` (FastAPI :8434, WebSocket extension :8355) và `make frontend` (Vite :5174).
- Extension: `chrome://extensions` → Load unpacked → `extension/`. Sửa extension thì phải **reload** nó. Cần một tab `flow.google.com` đã đăng nhập, để mở.
- Project Flow: đặt trong Cài đặt (`PUT /api/flow/projects/pinned`, tự chuyển các board sang project mới). Gói Pro/Ultra: `FLOWBOARD_PAYGATE_TIER` trong `.env`.
- **Windows**: `.\start.ps1` (ghi `.env`, dừng bản cũ, cài dependency khi đổi, chạy frontend + agent); chạy nền thì
  `powershell -ExecutionPolicy Bypass -File .\start.ps1 *> storage\logs\startN.log` (dùng tên log mới mỗi lần, file cũ hay bị khoá).
  Cổng cố định: flowboard UI **5174** / API 8434 / WS 8355; flowkit 5173 / 8100 / 9222 — chạy song song, không đổi.
- Python venv `agent/.venv`. Test: `cd agent && PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests`
  (~3 phút). Typecheck frontend: `cd frontend && npx tsc -b --noEmit`.
- Bí mật **ngoài git**: `~/.flowboard/secrets.json` (Gemini API keys `geminiApiKeys`, `apiKeys.openai|xai`), nhập qua Cài đặt.
  Máy mới phải nhập lại key.
- Tuỳ chọn: công cụ AI xoá phụ đề cần repo `pyvideotrans` có `.venv` (torch CUDA) + `models/lama/big-lama.pt`
  (`FLOWBOARD_ERASE_PYTHON`, `FLOWBOARD_ERASE_ROOT`); thiếu thì chỉ có chế độ khoanh vùng.

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
- Backend `agent/flowboard/`: `routes/products.py` (CRUD, `from-link`, `import-tiktok`, `bulk-delete`), `services/product_link.py` (đọc trang sản phẩm bằng httpx + Gemini; chặn IP nội bộ), `services/tiktok_import.py`, `services/reference_video.py` (clip từ video mẫu / link: `/api/reference-video/analyze`, `analyze-link`, `build`), `services/video_export.py`, `services/flow_sdk.py`, `templates/*.json` (8 kiểu clip), `services/llm/gemini_api.py` (gọi Gemini bằng API key: xoay vòng nhiều key khi 429, key lỗi 400/401/403 nghỉ 6 h, 503 thử lại + lùi model `3.8-flash → 3.7 → 3.6 → 3.5 → 3.1-flash-lite`; `speak()` cho giọng Gemini TTS).
- Frontend `frontend/src/quicktool/`: `QuicktoolApp.tsx` (route + wizard 5 bước), `NewClipDialog.tsx` (chọn sản phẩm, kiểu clip, "Số clip" N clip/1 sản phẩm), `quicktool.css`. `components/ProductsPanel.tsx` (trang `/products`, chọn nhiều + xoá). Cỡ chữ: thang riêng (chữ nội dung 16px); Canvas cố ý giữ chữ nhỏ.
- **Chế độ chỉ bàn tay**: ô "Giới tính mẫu" của mọi kiểu clip có thêm `Tay nữ` / `Tay nam` (`hands_female` / `hands_male`). `templates.render()` khi đó bỏ node nhân vật + cạnh nối, thêm câu "HANDS-ONLY SHOT…" vào prompt ảnh/video (không viết lại từng prompt), mô tả tay lấy từ ô `handLook` (mặc định "beautiful, well-groomed hands…"), quốc gia từ `charCountry`. **`fashion_ad` (quần áo) bắt buộc có người** (`person_required`): không có lựa chọn tay trên UI, backend/chat agent trả lỗi `PersonRequiredError` nếu gửi `hands_*`. Clip "theo video mẫu / link": màn review có ô **Người mẫu** (AI gợi ý / Nữ / Nam / Tay nữ / Tay nam / Không có người) + Quốc gia, gửi `character` lên `/api/reference-video/build` → `reference_video._character_for`. **Bước 1 wizard** có nút gạt Người mẫu ⇄ Chỉ bàn tay: `POST /api/boards/{id}/model-mode` (`services/model_mode.py`) xoá/tạo lại node nhân vật + cạnh, thêm/bỏ câu `HANDS_MARKER` trong prompt cảnh (idempotent), lưu `quicktool.hands`. Sản phẩm/kiểu thời trang bị từ chối ở cả ba chỗ. **Chưa tạo thử clip thật** để xem Flow vẽ tay có ổn không (kiểu quần áo chỉ tay có thể gượng).
- **Bước 1 · Sản phẩm nhận nhiều ảnh** (tối đa `MAX_PRODUCT_PHOTOS = 4`, `store/quicktool.ts`): "+ Thêm góc khác" tạo node `visual_asset` mới nối vào đúng các cảnh mà ảnh chính đang nối, rồi upload; "Bỏ ảnh" xoá node phụ (không xoá ảnh chính). Upload qua Flow mất ~10–15 s/ảnh.
- Sidebar: "+ Clip mới" (mở hộp "Clip mới"; 8 mẫu theo ngành hàng + 2 nguồn có sẵn chọn ở mục 2), Sản phẩm, Người mẫu đã lưu (`/models`), Prompt đã lưu (`/prompts`), Lịch sử & credit (`/history`), Xoá chữ / logo (`/tools/clean`), Canvas, Cài đặt; cuối sidebar có `CreditBadge` (credit Flow).
- Trang TikTok `shop.tiktok.com/.../pdp/<id>` đọc được không cần đăng nhập; ảnh `ibyteimg` đổi `resize-webp:260:260` → `800:800` để lấy ảnh to. Giá trên trang có nhiều mức nên Gemini có thể chọn sai: để người dùng kiểm tra.

- **Tạo drama** (2026-10-20): thẻ "📰 Tạo drama" trong hộp Clip mới — dán link bài viết hoặc gõ
  câu chuyện → `POST /api/drama/analyze` (`services/drama.py`, đọc trang bằng `product_link.fetch_page`,
  Gemini `PLAN_MODEL = gemini-3.5-flash` vì 3.8-flash mất ~4 phút) → plan {title, hook, beats[{caption,
  narration, image_prompt}]} → `POST /api/drama/build`: board chỉ có note + N node ảnh (narration + caption
  nằm trên node ảnh, **không có node video**), `quicktool.sequence` = thứ tự phát (short id).
  Wizard: bước 4 là `StepSequence` (lên/xuống, bỏ, "Chèn clip sau" = upload video → node video done →
  chèn vào sequence, giữ tiếng gốc mặc định). Export: `video_export.ExportItem` (kind image|video), ảnh
  được `_image_clip` dựng thành clip dài bằng lời đọc (zoompan + fade + tiêu đề ASS style "Headline" +
  phụ đề), worker nhận `params.items`; `dispatchExport(rfId, items?)`. Chưa thử tạo ảnh thật cho drama
  qua Flow (prompt có câu cấm chữ/mặt người thật), chưa chạy nút "Tạo video tự động" cho drama.

- **Giọng đọc** (2026-10-20): ngoài 2 giọng Edge (Hoài My / Nam Minh) có thêm **14 giọng Gemini TTS**
  (`tts.GEMINI_VOICES`, id `gemini:<Name>`, model `gemini-3.8-flash-tts`, qua pool key — `gemini_api.speak`),
  có ô "Phong cách đọc" (câu lệnh tiếng Việt, ví dụ "giọng kể chuyện kịch tính") → `NarrationOptions.style`
  → worker `voice_style`. Gemini không trả mốc từng từ nên phụ đề chia đều theo độ dài; không chỉnh được
  tốc độ (rate ≥ 15 thành gợi ý "nói nhanh hơn"). Chọn giọng trong bước 5 (`optgroup` Edge / Gemini),
  `GET /api/llm/voices`. Tham khảo cách gọi từ pyvideotrans `_geminitts.py`.

- **Drama đang ẩn** (2026-10-20, theo yêu cầu): thẻ "Tạo drama" tắt bằng `NewClipDialog.DRAMA_ENABLED = false`,
  API chỉ mount khi `FLOWBOARD_DRAMA=1`. Code giữ nguyên, bật lại khi cần.
- **Báo cáo UX 20/10** (agent thử như người dùng mới): `docs/ux-report-2026-10-20.md` — 3 lỗi chặn:
  (1) trang Sản phẩm không upload được ảnh khi chưa mở board nào (`ensureProjectId()` đòi boardId, báo sai
  "Chưa có Flow project"), (2) "Nhập từ TikTok" không có tab TikTok treo 180 s, (3) không có cách đưa
  video có sẵn vào cảnh/bước 4. Kèm ~20 lỗi nhỏ và bảng so sánh với AI Dễ Ẹc. **Đã sửa 5 khuyến nghị
  của báo cáo (20/10, BUGLOG FB-032)** — còn lại trong báo cáo: Canvas chat dock, "req ✗", thư viện tham chiếu cũ.
- **Đợt sửa theo báo cáo UX (2026-10-20, FB-032)** — chỗ cần biết:
  - `ensureProjectId()` (`store/generation.ts`) không cần board: lấy `/api/flow/projects/pinned` khi chưa mở board.
  - Nhập TikTok: extension gửi `version` trong `extension_ready` (`flow_client.extension_version`);
    `tiktok_import.scrape` từ chối ngay nếu bản < 0.2.0 (bản cũ không trả lời → trước đây treo 180 s);
    timeout còn 45 s. **Sau khi sửa extension phải Reload ở chrome://extensions**.
  - Bước 1: **một** `<input type=file>` cho cả "Upload ảnh" lẫn "+ Thêm góc khác" (`pendingNode` quyết định);
    không chọn node (kéo thả / tool tự động) thì ảnh đầu rơi vào node sản phẩm chính nếu còn trống.
  - Bước 4: "⬆ Dùng video của bạn" → `uploadVideoToScene` (`/api/reference-video/upload`, Asset local, node video
    `status: done`, không tốn credit). Nút "Tạo N video còn thiếu" hỏi `confirm` kèm số credit (`roles.creditsPerClip`).
  - "⚡ Tạo video tự động" hỏi confirm (số ảnh/video, credit, phút). Thư viện có checkbox trên thẻ + "Chạy N clip
    đã chọn" / "Chạy tất cả N clip dở" → `runQueue(boardIds)` (`store/quicktool.ts`, chạy tuần tự `switchBoard`
    → `runAuto`, trạng thái `queue` hiện trên thẻ: chờ / đang chạy / ✓ / lỗi). Khi hàng đợi chạy, thẻ khác bị khoá.
  - Thư viện: skeleton khi tải, chữ 16/14px, thẻ có dòng trạng thái; `document.title` theo trang; Esc/Đóng của
    hộp thoại quay về trang trước (`useCloseOverlay`), tạo clip xong `navigate(..., {replace:true})`.
    Stepper ✓ theo `roles.stepDone(n)` (từng bước tự đủ), "Tiếp tục" ở bước 4 cần ≥ 1 video.
  - Bước 5 thêm: "▶ Nghe thử" (`POST /api/llm/voices/preview` → `GET …/preview/{file}`, cache theo giọng+style);
    **Nhạc nền** (`POST /api/llm/music` ≤ 20 MB mp3/m4a/wav → Asset audio; export node `bgmMediaId/bgmVolume`
    → worker `bgm_media_id/bgm_volume` → `video_export.mix_background_music` sau khi ghép, loop + fade 1,5 s);
    **Ảnh bìa** (`POST /api/boards/{id}/cover {media_id,title,subtitle?,style}` → `video_export.render_cover`
    1080×1920, dải tối dưới bằng `geq` alpha — bộ lọc `gradients` bị ngược alpha; chữ ASS "Cover" qua libass;
    nguồn ảnh: ảnh cảnh hoặc ảnh sản phẩm). Route mới ở `routes/export_extras.py`.
  - `components/llmConfigCache.ts`: cache `GET /api/llm/config` 60 s dùng chung (trước đây 4 component poll 30 s).
  - `prompt_synth.restore_product_guard`: "Viết lại chuẩn" giữ lại câu ràng buộc sản phẩm; `product_link.PLAN_MODEL
    = gemini-3.5-flash`; `vision.py` mô tả tiếng Anh; ResultViewer tiếng Việt + `Ctrl` thay `⌘` ngoài Mac.

- **Đợt tính năng 20/10 tối (FB-033, 6 việc so với AI Dễ Ẹc)** — chỗ cần biết:
  - **Mẫu clip mới**: `grocery_ad` (tạp hoá & phụ kiện, mặc định tay nữ), `home_appliance_review` (gia dụng),
    `food_review` (bắt buộc có người, `person_reason`), `affiliate_reel` (category `any`, hiện cho mọi sản phẩm).
    `templates.CATEGORIES` = fashion, cosmetics, food, grocery, home, other (products + product_link + reference_video
    dùng chung); JSON có `order`; `templates_for_category()`; `person_required_message()`. Hộp Clip mới chia 2 nhóm,
    mẫu hợp ngành hàng xếp trước và gắn "phù hợp". Prompt các mẫu mới **chưa thử qua Flow**.
  - **Xoá chữ / logo / watermark** (`services/video_clean.py`, `routes/video_clean.py`, trang `/tools/clean`):
    chế độ khoanh vùng (ffmpeg `delogo` / `boxblur`, không cần AI) và chế độ AI xoá phụ đề cứng dùng lại
    `D:\codes\pyvideotrans\vi_dub_erase.py` (RapidOCR + LaMa, GPU) chạy bằng **venv của pyvideotrans** qua
    `video_clean_runner.py` (`FLOWBOARD_ERASE_PYTHON` mặc định `D:\codes\pyvideotrans\.venv\Scripts\python.exe`,
    `FLOWBOARD_ERASE_ROOT`); không import torch vào venv flowboard. Thử thật: detect 15 s, erase 46 s cho clip 6 s
    720×1280 (RTX 3060). Job AI chạy nền trong RAM (`/api/clean/jobs/{id}`), mất khi restart. Máy khác không có
    pyvideotrans thì chỉ có chế độ khoanh vùng.
  - **Lịch sử & credit**: `routes/history.py` (`GET /api/history`, `/summary`, `/{id}`; ước tính credit theo
    `params.model`/`video_quality`; `can_retry`), trang `/history` (lọc, tải media, thử lại qua `POST /api/requests`).
    `components/credits.ts` `useFlowCredits()` (cache 60 s, `refresh()` = `/api/auth/scan`), `CreditBadge`; hộp
    xác nhận "Tạo video tự động" / "Tạo N video" / hàng đợi ghi số credit còn lại và cảnh báo KHÔNG ĐỦ.
  - **Credit Flow đọc từ trang**: flow.google.com không cấp Bearer nữa nên credit/email lấy bằng lệnh extension
    `read_account` (mở bảng tài khoản `.header-user-button` trên tab Flow, đọc `flow-account-panel .credits-count`
    + `.user-email` + `flow-user-tier-chip`, rồi đóng — tab nháy nhẹ). Cần extension **≥ 0.3.0** (manifest đã lên
    0.3.0 → phải Reload). `flow_client.read_account()`, tự gọi khi extension_ready; `/api/auth/scan` gọi lại.
  - **Nhiều tài khoản Flow**: `flow_client` giữ `ExtConn` cho từng extension kết nối (mỗi Chrome profile một
    tài khoản), một cái `active`; `GET /api/auth/accounts`, `POST /api/auth/accounts/{id}/activate` (ghim lại
    project nhớ theo email: AppSetting `flow_project_for:<email>`, ghi khi `PUT /api/flow/projects/pinned`),
    `POST /api/auth/accounts/refresh`. UI: Cài đặt → "Tài khoản Flow". Mất kết nối đang dùng thì tự chuyển sang
    cái còn lại. **Chưa thử thật với 2 profile Chrome**.
  - **Hàng tài khoản Flow tự chuyển khi hết credit** (`services/account_pool.py`, AppSetting `flow_account_pool`):
    một Chrome đăng nhập nhiều tài khoản Google, mỗi tài khoản có project Flow riêng. Tài khoản đang đăng nhập trên
    tab Flow tự vào danh sách (kèm project đang ghim) khi `read_account` đọc được; thêm tay ở Cài đặt → "Danh sách
    tài khoản Flow". Worker gọi `account_pool.ensure_credits(job_cost(params))` trước mỗi job video Flow
    (`_handle_gen_video` / `_handle_gen_video_omni`): credit đã biết < giá clip → đánh dấu hết, ghim project
    tài khoản kế (`set_override`), extension `open_flow_tab` (`?authuser=<email>`), rồi **job chờ** (đọc panel
    mỗi 12 s, tối đa 15 phút) đến khi tab Flow ở đúng tài khoản; frontend `AccountSwitchBanner` (cam, poll
    `/api/auth/pool` 5 s khi pending) có nút "Mở tab Flow" / "Đã đổi, kiểm tra" (`POST /api/auth/pool/check`).
    `note_result` trừ credit ước tính sau mỗi job và bắt lỗi Flow có chữ credit/quota. Routes `/api/auth/pool*`.
    **Chưa thử thật tình huống hết credit** (mới test bằng mock + chuyển tay qua UI). Lưu ý: "Dùng tài khoản này"
    ghim project ngay → đừng bấm với tài khoản có project giả.
  - **Nguồn tạo ảnh ngoài Flow** (`services/image_providers.py`, `routes/image_providers.py`, Cài đặt → "Nguồn tạo
    ảnh"): OpenAI `gpt-image-1` (nhận ảnh tham chiếu qua `/v1/images/edits`), xAI `grok-imagine-image-2.0` (không
    nhận tham chiếu); key lưu `apiKeys.openai|xai` trong secrets.json; `settings.imageProvider` → params
    `image_provider` → hook đầu `_handle_gen_image` → ảnh vẫn được upload vào Flow làm nguyên liệu video.
    **Chưa có key để thử thật.**
  - **Hội thoại nhiều giọng**: tag `[A] … [B] …` trong lời thoại (`tts.parse_speakers`, `synthesize_dialogue`,
    ngắt 0,3 s), export node `speakers {A: voice}`, node video `voice` riêng; worker params `speakers`, `voices`;
    bước 2 có chọn giọng từng cảnh, bước 5 hộp "Nhân vật lồng tiếng". Chưa nghe thử thật.
  - **Thư viện người mẫu**: `Reference.meta` (cột JSON, migration `ensure_reference_meta_column` trong
    `db/__init__.py`), `GET /api/references?kind=character`; bước 1 "★ Lưu người mẫu" / "Chọn từ thư viện"
    (copy mediaId + charGender/Country/Vibe/Extras sang node); trang `/models`. `generateModel()` bỏ qua khi
    node đã có ảnh → muốn tạo lại phải chọn/upload ảnh khác.
  - **Thư viện prompt**: bảng `SavedPrompt` (kind image|video|narration, create_all tự tạo), `routes/prompt_library.py`
    (`/api/prompt-library`, lưu trùng text = trả bản cũ, `/use` đếm lượt), bước 2 mỗi ô có "★ Lưu" / "📚 Dùng lại"
    (`quicktool/PromptLibraryButtons.tsx`), trang `/prompts` sửa tại chỗ.

## Việc đang dở / chưa kiểm chứng
- **Nhập từ TikTok bằng extension** (`scrape_page` trong `extension/background.js`) mới test trên HTML giả, chưa chạy trên trang TikTok thật. Trang chi tiết sản phẩm thì chỉ lấy sản phẩm chính (không lấy "sản phẩm liên quan").
- **Chưa thử thật (20/10)**: prompt 4 mẫu clip mới qua Flow; chế độ chỉ bàn tay qua Flow; tình huống hết credit → tự chuyển
  tài khoản; 2 Chrome profile cùng lúc; key OpenAI/xAI; nghe hội thoại nhiều giọng; hàng đợi nhiều clip với credit thật.
- Chưa có: kịch bản khác nhau cho từng clip (hiện chỉ khác bối cảnh). Còn thiếu so với AI Dễ Ẹc (người dùng chưa chọn làm):
  upscale 2K/4K, storyboard lưới trong wizard ("storyboard 2"), trim / chèn chữ lên video thật.
- Còn trong báo cáo UX chưa sửa: Canvas chat dock quá to, toolbar Canvas tiếng Anh, "req ✗" không bấm được, thư viện tham chiếu cũ.
- Chọn gói Pro/Ultra ngay trong Cài đặt (hiện sửa `.env`).
- Triển khai cho người khác: **để sau**. Hướng đã bàn: bạn cài local (đóng gói script + agent phục vụ giao diện build sẵn) là rẻ nhất; chạy trên server cần sửa extension (địa chỉ server, `wss`), đăng nhập, và vì hệ thống là một người dùng nên mỗi người một bản. Vercel đơn thuần không chạy được agent.
- Test trên Windows (20/10): 743 pass khi bỏ 5 file lỗi do môi trường — `test_llm_gemini.py` (CLI `agy`), `test_llm_secrets.py::…0600`
  (quyền file), `test_provider_jobs.py` + `test_muse2api.py` (muse `file://`, FB-026), `test_auth.py` (tier đọc từ `.env` máy này).
  Chạy cả 5 file đó: thêm khoảng 45 lỗi, đều đã biết, không liên quan code mới.

## Nhật ký (mới nhất ở dưới — thêm một dòng mỗi khi code xong)
- **19/10** — Quicktool wizard 5 bước, Gemini key pool, clip từ video mẫu, router trang (commit `09bbbc9`); máy kia thêm clip từ link sản phẩm, trang Sản phẩm, nhập TikTok, N clip/sản phẩm, chế độ chỉ bàn tay, nhiều ảnh bước 1 (`fc32fb1` … `59b0c11`).
- **20/10 sáng** — Tạo drama (đang ẩn, `FLOWBOARD_DRAMA=1`); 14 giọng Gemini TTS + phong cách đọc; báo cáo UX `docs/ux-report-2026-10-20.md`.
- **20/10 chiều** — Sửa 5 khuyến nghị báo cáo UX (FB-032): upload ảnh sản phẩm không cần board, TikTok fail nhanh, video của mình vào cảnh, xác nhận credit, hàng đợi nhiều clip, skeleton thư viện, viewer tiếng Việt, nghe thử giọng, nhạc nền, ảnh bìa. Đã thử thật trên UI.
- **20/10 tối** — 6 tính năng so với AI Dễ Ẹc (FB-033): 4 mẫu clip mới, xoá chữ/logo (thử thật OK), lịch sử & credit, nhiều tài khoản + nguồn ảnh OpenAI/xAI, hội thoại nhiều giọng, thư viện người mẫu. Extension 0.3.0 đọc credit từ tab Flow (thử thật: 1.002 credit).
- **20/10 tối** — Hàng tài khoản Flow tự chuyển khi hết credit + banner đổi tài khoản (FB-034). Thử thật: chuyển tay qua UI; chưa thử hết credit thật.
- **20/10 tối** — Thư viện prompt (bước 2 "★ Lưu" / "📚 Dùng lại", trang `/prompts`); thử thật trên UI. Commit + push `b7cfdf1` (gộp mọi việc 20/10). Test 743 pass.
- **20/10** — Viết lại quy tắc: code xong phải ghi Nhật ký + cập nhật các mục trên ngay.
