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

## Đăng nhập & dữ liệu theo tài khoản (phase 1.5, 22/10)
Mục tiêu người dùng: đăng nhập ở máy nào cũng thấy đúng dữ liệu của mình ("như web thường"). Làm 2 bước:
**Bước A (xong 22/10)**: đăng nhập + tách dữ liệu theo tài khoản. **Bước B (xong 22/10, đã chạy thật)**: dữ liệu tài khoản
nằm trên cloud — Postgres **Neon** (project `flowboard`, vùng Singapore, schema riêng mỗi tài khoản) + bucket **Backblaze B2**
`flowboard-media-akira` (endpoint `s3.us-east-005.backblazeb2.com`) cho media. Tài khoản Neon/B2 đăng nhập bằng Google/email
của người dùng (console.neon.tech, secure.backblaze.com).
- `flowboard/accounts.py`: kho **trung tâm** `storage/accounts.db` (bảng `account_user`, `account_session`; SQLAlchemy Core,
  metadata riêng — KHÔNG nằm trong `SQLModel.metadata` để `create_all`/`drop_all` của dữ liệu không đụng tới; sau này
  `FLOWBOARD_CENTRAL_DB_URL` trỏ lên cloud). Mật khẩu `pbkdf2_sha256` 200k vòng (stdlib). Phiên = cookie `fb_session`
  (httponly, 30 ngày), cache 5 phút trong RAM. Tài khoản tạo sẵn khi kho trống: **`akiragosho` / `Password@123`**
  (`FLOWBOARD_SEED_USER/PASSWORD`). Đăng ký thêm chỉ khi `FLOWBOARD_ALLOW_REGISTER=1` (`POST /api/account/register`),
  hoặc gọi `accounts.create_user()` trong Python.
- **Dữ liệu mỗi tài khoản**: `storage/accounts/<username>/` (`flowboard.db`, `media/`, `chat_uploads/`). Cột `backend` (JSON)
  của user nói dữ liệu ở đâu: `{"type":"sqlite"}` hôm nay, `{"type":"postgres","url":…}` ở bước B.
- **Một tài khoản active tại một thời điểm** (agent lái Chrome bên cạnh): request có cookie hợp lệ → middleware `_require_login`
  (`main.py`) gọi `accounts.activate(user)` → đổi engine (`db.set_engine`) + đổi `config.STORAGE_DIR/DB_PATH`,
  `media.MEDIA_CACHE_DIR`, `tts.TTS_DIR` (các hằng module được gán lại — đừng `from … import MEDIA_CACHE_DIR` ở nơi khác)
  → `init_db` + hook `after_activate` (phục hồi job mồ côi, backfill media, prompt mẫu). Đổi sang tài khoản khác thì chờ
  worker rảnh tối đa 30 s, không thì 409. Lần đầu seed-user đăng nhập mà còn dữ liệu cũ (`storage/flowboard.db`) → **di dời**
  vào thư mục tài khoản (đã làm thật 22/10: 297 file media, DB giữ nguyên).
- Routes: `routes/account.py` — `POST /api/account/login|logout|password|register`, `GET /api/account/me` (401 khi chưa đăng
  nhập). Mọi `/api/*` và `/media/*` khác đều cần cookie, trừ `OPEN_PATHS` trong `main.py` (login, me, register, health, ext callback).
- **`FLOWBOARD_AUTH=off`** = chế độ cũ không đăng nhập (dữ liệu `storage/flowboard.db`); **bộ test chạy ở chế độ này**
  (`conftest.py`), riêng `test_account_login.py` tự bật auth. Khi auth bật, `db.session._state["engine"]` khởi đầu là **None**:
  `get_session()` trước khi đăng nhập ném `NoActiveAccount` (bẫy đã gặp: extension kết nối ngay lúc khởi động →
  `account_pool.on_account_read` mở DB cũ qua engine mặc định → Windows khoá file → di dời thất bại; giờ hook đó bỏ qua
  khi `db.has_engine()` False).
- Frontend: `App.tsx` = cổng đăng nhập (`GET /api/account/me` → `LoginPage` hay app; sự kiện `flowboard:unauthorized` do
  `api()` bắn khi gặp 401 → về trang đăng nhập), `store/account.ts`, `components/LoginPage.tsx`, `components/UserChip.tsx`
  (sidebar: 👤 tên + Đăng xuất), `api/account.ts`. Đã thử thật bằng Playwright: đăng nhập sai/đúng, dữ liệu hiện, F5 giữ phiên, đăng xuất.
- **Bước B — đã chạy thật 22/10 trên máy nhà** (akiragosho: 346 dòng → schema `acct_akiragosho`; 178 file media (236 MB, mọi Asset có file) đã lên B2; đã thử dời một file đi rồi gọi `/media/<id>` → tự tải về từ B2):
  - `.env` mỗi máy thêm **`FLOWBOARD_CENTRAL_DB_URL=postgresql://…-pooler.c-3.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`**
    (chuỗi lấy ở Neon Console → Connect, hoặc chép từ `.env` máy nhà — **không commit**) → kho trung tâm (user/session/setting)
    nằm trên Neon; `db.make_engine(url, schema=)` tạo engine Postgres (psycopg); migration `ALTER` kiểu SQLite chỉ chạy khi
    dialect = sqlite. **Máy cty chỉ cần: `git pull`, `make install` (psycopg, boto3), thêm dòng đó vào `.env`, chạy, đăng nhập
    `akiragosho` → thấy dữ liệu; B2 đã lưu trong kho trung tâm nên không phải nhập lại; file media tải về khi cần.**
  - **Bẫy Neon (dính 22/10)**: host `-pooler` là PgBouncer chế độ transaction → từ chối `options=-c search_path` lúc kết nối và
    `SET search_path` **mất sau mỗi transaction** (bảng bị tạo nhầm vào `public`). `make_engine(schema=…)` vì thế **bỏ `-pooler.`**
    khỏi host (nối thẳng compute, pool 5+5) + `SET search_path` ở event `connect` + `schema_translate_map={None: schema}` để
    ORM luôn ghi rõ schema. Kho trung tâm (không schema) vẫn dùng pooler.
  - Dữ liệu tài khoản lên cloud: `accounts.move_to_cloud(username)` (route `POST /api/cloud/migrate`, nút "☁ Chuyển dữ liệu
    lên cloud" ở Cài đặt → Dữ liệu): chép từng bảng SQLite → schema `acct_<user>` (JSON/datetime/bool đổi kiểu, `setval` sequence),
    từ chối nếu schema đã có clip/sản phẩm, đổi `backend` của user thành `{"type":"postgres","schema":…}`; SQLite giữ làm sao lưu.
    Sau đó `accounts.data_engine(user)` mở Postgres ở mọi máy có `FLOWBOARD_CENTRAL_DB_URL`.
  - **File media** `services/file_store.py` (boto3, S3 API — B2/R2): key = `<username>/media/x.mp4`; Asset có file → đẩy nền
    (event SQLAlchemy); `media.cached_path` thiếu file → tải về; `reconcile()` khi tài khoản active. Cấu hình lưu **kho trung tâm**
    (`account_setting` khoá `s3`) nên mọi máy đăng nhập đều có; đặt ở Cài đặt → Dữ liệu (`PUT /api/cloud/s3`, kiểm tra ghi/xoá
    thử trước khi lưu) hoặc env `FLOWBOARD_S3_*`. Khi chưa đăng nhập prefix là `local/`.
  - **`Asset.local_path` lưu tương đối** (`db/paths.py`, kiểu `StoragePath`): ghi `media/x.mp4` khi file nằm trong thư mục dữ
    liệu (ngoài thì giữ nguyên tuyệt đối); đọc ra đường dẫn tuyệt đối của máy đang chạy; đường dẫn tuyệt đối cũ của máy khác vẫn
    đọc được; `normalize_asset_paths` chạy trong `init_db`. Bắt buộc cho Ubuntu + Windows dùng chung DB.
  - `move_to_cloud` đổi kiểu khi chép: cột ngày của SQLModel là `UTCDateTime` (TypeDecorator → nhìn `.impl`), chuỗi SQLite
    naive → gắn UTC; chỉ `setval` sequence cho bảng có `id` kiểu số (`providerjob.id` là text).
  - Test: `test_db_paths.py`, `test_file_store.py` (S3 giả moto), `test_cloud_postgres.py` (**chỉ chạy khi có
    `FLOWBOARD_TEST_PG_URL`**, tạo schema + user tạm rồi xoá bằng finalizer; 2 pass trên Neon thật).
    **`conftest.py` ép `FLOWBOARD_CENTRAL_DB_URL=""` và `FLOWBOARD_S3_*=""`** — bẫy 22/10: `.env` có chuỗi Neon nên
    `test_account_login.py` đã chạy thẳng lên kho thật (tạo user `ban`/`new`, đổi mật khẩu akiragosho; đã dọn + đặt lại).
    `seed_default()` chỉ seed khi kho **trống** → user rác trên Neon làm mất `akiragosho`; dọn bằng SQL rồi gọi `seed_default()`.
  - Mật khẩu/khóa: Neon URL chỉ trong `.env`; B2 key chỉ trong `account_setting` trên Neon (`PUT /api/cloud/s3`). Đổi key:
    Backblaze → Application Keys (key `flowboard-app` chỉ cho bucket đó).
- **Cái gì đi theo tài khoản (22/10)** — mọi thứ dưới đây nằm trên Neon nên đăng nhập máy nào cũng có:
  - **API key Gemini / OpenAI / xAI + cấu hình provider** (`featureConfig`, `activeProviders`): `services/llm/secrets.py`
    `read()/write()` khi auth bật + có tài khoản active → `account_setting` khoá **`secrets:<username>`** (cache RAM 60 s), lần đầu
    tự chép `~/.flowboard/secrets.json` của máy lên (đã làm thật: 7 key Gemini). Không đăng nhập / `FLOWBOARD_SECRETS_PATH` (test)
    → vẫn dùng file. File cũ trên máy không bị ghi nữa (chỉ còn là bản sao cũ).
  - **Project Flow đang ghim** + `flow_project_for:<email>` + hàng tài khoản Flow: `AppSetting` trong DB tài khoản (có sẵn từ trước).
    `.env` `FLOWBOARD_FLOW_PROJECT_ID` chỉ là dự phòng khi chưa ghim.
  - **Tuỳ chọn UI** (model ảnh, chất lượng video, Omni/Veo, thời lượng, nguồn ảnh, chế độ Quicktool/Canvas): `AppSetting` **`ui_prefs`**
    qua `GET/PUT /api/account/prefs`; `store/settings.ts` `hydrateFromAccount()` gọi trong `AppInner` sau khi đăng nhập (tài khoản chưa
    có → đẩy giá trị localStorage hiện tại lên), mỗi setter ghi localStorage + PUT (debounce 400 ms). localStorage chỉ còn là cache.
  - **Vẫn theo máy**: gói Pro/Ultra `FLOWBOARD_PAYGATE_TIER` trong `.env`, extension Chrome, Gemini key cho test.

## Bẫy đã gặp (đừng lặp lại)
- **Sửa file lớn bằng script: tính điểm cuối bằng `index()` của chính đoạn cần xoá, đừng trỏ tới marker ở xa** — 21/10 một lệnh xoá nhầm ~11 nghìn ký tự CSS của `quicktool.css` (phục hồi từ git HEAD + dựng lại phần chưa commit; luôn `git diff --stat` ngay sau khi sửa file lớn).
- **TikTok lúc có lúc không trả trang "Security Check"** thay cho trang sản phẩm (thấy thật 21/10): `product_link.fetch_page` nhận diện trang chặn (`_looks_blocked`), thử lại 1 lần sau 3 s rồi báo lỗi — trước đó đã lưu một sản phẩm tên "Security Check".
- **Vite có lúc giữ bản biên dịch RỖNG của một file vừa sửa** (21/10: `AccountPanel.tsx` trả 0 byte → cả app trắng, lỗi "does not provide an export named …" dù `tsc` sạch). Kiểm tra `curl -s -o /dev/null -w '%{size_download}' localhost:5174/src/<file>`; sửa bằng `touch <file>`.
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
- Backend `agent/flowboard/`: `routes/products.py` (CRUD, `from-link`, `open-tabs` + `import-tabs`, `bulk-delete`), `services/product_link.py` (đọc trang sản phẩm bằng httpx + Gemini; chặn IP nội bộ), `services/tiktok_import.py`, `services/reference_video.py` (clip từ video mẫu / link: `/api/reference-video/analyze`, `analyze-link`, `build`), `services/video_export.py`, `services/flow_sdk.py`, `templates/*.json` (8 kiểu clip), `services/llm/gemini_api.py` (gọi Gemini bằng API key: xoay vòng nhiều key khi 429, key lỗi 400/401/403 nghỉ 6 h, 503 thử lại + lùi model `3.8-flash → 3.7 → 3.6 → 3.5 → 3.1-flash-lite`; `speak()` cho giọng Gemini TTS).
- Frontend `frontend/src/quicktool/`: `QuicktoolApp.tsx` (route + wizard 5 bước), `NewClipDialog.tsx` (chọn sản phẩm, kiểu clip, "Số clip" N clip/1 sản phẩm), `quicktool.css`. `components/ProductsPanel.tsx` (trang `/products`, chọn nhiều + xoá). Cỡ chữ: thang riêng (chữ nội dung 16px); Canvas cố ý giữ chữ nhỏ.
- **Chế độ chỉ bàn tay**: ô "Giới tính mẫu" của mọi kiểu clip có thêm `Tay nữ` / `Tay nam` (`hands_female` / `hands_male`). `templates.render()` khi đó bỏ node nhân vật + cạnh nối, thêm câu "HANDS-ONLY SHOT…" vào prompt ảnh/video (không viết lại từng prompt), mô tả tay lấy từ ô `handLook` (mặc định "beautiful, well-groomed hands…"), quốc gia từ `charCountry`. **`fashion_ad` (quần áo) bắt buộc có người** (`person_required`): không có lựa chọn tay trên UI, backend/chat agent trả lỗi `PersonRequiredError` nếu gửi `hands_*`. Clip "theo video mẫu / link": màn review có ô **Người mẫu** (AI gợi ý / Nữ / Nam / Tay nữ / Tay nam / Không có người) + Quốc gia, gửi `character` lên `/api/reference-video/build` → `reference_video._character_for`. **Bước 1 wizard** có nút gạt Người mẫu ⇄ Chỉ bàn tay: `POST /api/boards/{id}/model-mode` (`services/model_mode.py`) xoá/tạo lại node nhân vật + cạnh, thêm/bỏ câu `HANDS_MARKER` trong prompt cảnh (idempotent), lưu `quicktool.hands`. Sản phẩm/kiểu thời trang bị từ chối ở cả ba chỗ. **Chưa tạo thử clip thật** để xem Flow vẽ tay có ổn không (kiểu quần áo chỉ tay có thể gượng).
- **Bước 1 · Sản phẩm nhận nhiều ảnh** (tối đa `MAX_PRODUCT_PHOTOS = 4`, `store/quicktool.ts`): "+ Thêm góc khác" tạo node `visual_asset` mới nối vào đúng các cảnh mà ảnh chính đang nối, rồi upload; "Bỏ ảnh" xoá node phụ (không xoá ảnh chính). Upload qua Flow mất ~10–15 s/ảnh.
- Sidebar: "Clip của tôi" (trang này có nút + thẻ "Clip mới" mở hộp "Clip mới": 8 mẫu theo ngành hàng + 2 nguồn có sẵn chọn ở mục 2; **sidebar không còn mục "+ Clip mới"**, 21/10), Sản phẩm, Người mẫu đã lưu (`/models`), Prompt đã lưu (`/prompts`), Lịch sử & credit (`/history`), Xoá chữ / logo (`/tools/clean`), Canvas, Cài đặt; cuối sidebar có `CreditBadge` (credit Flow).
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

- **Prompt mẫu có sẵn** (21/10): `agent/flowboard/prompt_seeds.json` (43 mẫu: 14 ảnh, 12 chuyển động, 17 lời thoại;
  nhóm hook / chi tiết / demo / chốt đơn / chỉ tay + theo ngành). `services/prompt_seeds.py`: `seed_on_start()` (gọi trong
  `main.lifespan`) thêm một lần mỗi `version` (AppSetting `prompt_seeds_version`) — mẫu bị xoá không tự quay lại;
  `POST /api/prompt-library/samples` thêm lại mẫu thiếu. Mẫu có tag `mẫu có sẵn`. Trang `/prompts`: lưới 3 cột, phân trang 15 thẻ/trang (5 hàng; lọc nào cũng về trang 1), nhãn "Mẫu", lọc
  theo nhóm, nút "↺ Prompt mẫu". **Thêm/sửa mẫu: sửa JSON rồi tăng `version`.** Lời thoại ≤ 24 từ, không nêu
  giảm giá/số liệu/công dụng y tế (test `test_prompt_seeds.py` kiểm tra quy ước).

- **Hộp Clip mới ↔ Sản phẩm đang bán** (21/10): mục 3 ô **"Sản phẩm đang bán"** là `<select>` các sản phẩm đã lưu, cùng
  state `productId` với thẻ ở mục 1 (chưa có sản phẩm → trống, bị khoá). Mục 1 có thẻ **"🔗 Thêm sản phẩm từ link"**:
  `productFromLink` → upload ảnh (`ensureProjectId` + `uploadImageFromUrl`) → `createProduct` → chọn luôn (~12 s).
  Ô **Bối cảnh**: `quicktool/SuggestField.tsx` (gõ tự do + "▾ Chọn", Esc chỉ đóng danh sách) với `quicktool/suggestions.ts`
  `BACKDROPS` theo category của **sản phẩm đã chọn**, không có thì theo kiểu clip (nhãn Việt, giá trị Anh). Trang Sản phẩm:
  mỗi thẻ hiện "🎬 N clip" / "Chưa có clip" (đếm `board.data.quicktool.product_id` từ `listBoardSummaries`).
  Chọn sản phẩm vẫn đổi kiểu clip sang mẫu hợp ngành của nó (hành vi cũ).

- **Link Shopee** (21/10): server không đọc được (trang chỉ là khung JS, API 403, trình duyệt lạ bị đẩy sang "Cần đăng nhập").
  `product_link.get_page()` chuyển link `shopee.vn` / `s.shopee.vn` / `shp.ee` (`BROWSER_ONLY_HOSTS`) sang
  `read_via_extension()` → lệnh extension **`read_page`** (bản **0.4.0**, manifest thêm quyền shopee.vn, shp.ee,
  susercontent.com): mở link trong tab nền Chrome của người dùng (đã đăng nhập Shopee), chờ tối đa 25 s đến khi có
  JSON-LD Product hoặc ≥ 1500 ký tự, đọc title/og/JSON-LD/ảnh lớn/innerText, đóng tab. `page_from_browser()` ưu tiên
  tên + ảnh + giá trong JSON-LD; ảnh `_tn` → ảnh gốc; `clean_link` bỏ query. Dùng cho mọi chỗ đọc link: "Thêm từ link"
  (trang Sản phẩm + hộp Clip mới) và kiểu clip "Theo link sản phẩm". Lỗi rõ ràng khi chưa đăng nhập / captcha / extension cũ.
  Test `test_shopee_link.py`. **Chưa thử với trang Shopee thật** (máy dev không đăng nhập Shopee).

- **"📥 Nhập từ tab đang mở" = một nút chung cho TikTok + Shopee, nhiều tab một lần** (22/10; thay 2 nút "Nhập từ TikTok" /
  "Nhập từ Shopee" và route `import-tiktok` / `import-shopee`, lệnh extension `read_open_tab` đã bỏ). `services/tab_import.py`:
  `GET /api/products/open-tabs` → lệnh extension **`list_shop_tabs`** (bản **0.5.0**, phải Reload) → `classify(url)`: Shopee
  `-i.<shop>.<item>` / `/product/..` = `product`, trang Shopee khác = không nhập được; TikTok PDP (`tiktok_import.pdp_url`) =
  `product`, showcase / shop / affiliate = `list`, còn lại `other` (vẫn tick được). `POST /api/products/import-tabs {tab_ids}`
  liệt kê lại tab (không tin URL từ trình duyệt gửi lên), đọc 3 tab một lúc: `product` → lệnh **`read_tab`** (đánh thức tab bị
  Chrome cho ngủ, chờ load) → `page_from_browser` → `extract_from_page` → `save_draft(source=Shopee|TikTok)`; tab TikTok bị
  captcha / chưa hiện → `fetch_page` của agent. `list` → `scrape_page {tabId}` → `save_products`. Mỗi tab một kết quả, tab lỗi không
  chặn tab khác; ảnh tải nền một hàng. UI (`ProductsPanel` `TabPicker`): 1 tab nhập được → nhập luôn; nhiều tab → bảng chọn (tick
  sẵn trang sản phẩm + showcase), kết quả từng tab hiện dưới dòng, tab đã nhập tự bỏ tick. Test `test_tab_import.py`.
  **Chưa thử với tab thật** (extension trên máy dev vẫn 0.4.1 lúc làm).

- **Trang Sản phẩm đang bán — danh sách** (21/10, `components/ProductsPanel.tsx`): hàng nút trên cùng (+ Thêm sản phẩm,
  🔗 Thêm từ link, 📥 Nhập từ tab đang mở) rồi hàng điều khiển: tìm kiếm (tên/mô tả/link/giá/ngành), lọc
  ngành, sắp xếp (mới/cũ nhất, tên A→Z/Z→A, giá thấp→cao/cao→thấp — `priceValue()` hiểu "399k", "76.064đ", "₫ 1.250.000", "2tr",
  không có giá luôn xuống cuối —, nhiều clip nhất), nút **Lưới / Danh sách** (nhớ trong localStorage `flowboard.products.view`).
  Lưới 5 cột (4/3/2 khi hẹp) × 5 hàng = 25 SP/trang; danh sách 15 dòng/trang (checkbox, ảnh, tên, ngành, giá, số clip, ngày
  thêm, Sửa, Tạo clip). Phân trang dùng `.qt-pager` (chung với `/prompts`); đổi bộ lọc/sắp xếp/kiểu xem về trang 1. "Chọn trang này"
  chọn các SP của trang đang xem; vẫn xoá hàng loạt. Đã thử với 32 SP.

- **Thông báo = toast** (21/10): `store/toast.ts` (`toast.success|info|warning|error(msg)`, hook `useToastOn(message, kind, clear)`
  để component giữ state thông báo rồi bật toast), `components/Toaster.tsx` (một chồng ở góc phải trên, tối đa 4, z-index 1200
  trên mọi hộp thoại; mỗi toast có nhãn Lỗi/Lưu ý/Thông báo/Thành công, thanh đếm ngược, rê chuột thì giữ lại, nút ×; thời gian
  theo độ dài chữ, lỗi lâu hơn; lỗi trong các store board/chat/generation/pipeline vẫn tự lên toast lỗi). **Quy ước: kết quả
  của một hành động (đã lưu, đã thêm, trùng, thất bại) → toast; trạng thái cần ở lại trên trang (đang chạy, node lỗi, thiếu ảnh,
  lỗi tải kèm nút "Thử lại") → giữ inline.** Đã chuyển: trang Sản phẩm (nhập từ tab/thêm từ link), hộp Clip mới (lỗi, "đã tạo
  N clip" — mở clip 1 ngay, không chờ 1,5 s), Prompt đã lưu (lưu / thêm lại mẫu), Người mẫu, bước 1/5 của wizard, lỗi `quicktool` store,
  hàng đợi xong (toast từ `runQueue`, không phụ thuộc trang đang mở), Lịch sử (chạy lại), Xoá chữ/logo, Cài đặt (key Gemini,
  tài khoản Flow, hàng tài khoản, nguồn ảnh, AI provider) và `AccountSwitchBanner`. Code mới: dùng toast, đừng thêm dòng `product-form__error`.
  Form sản phẩm: **"Lưu" → toast "Đã thêm / Đã lưu thay đổi" → về danh sách** (bỏ nút "Lưu & tạo clip"; tạo clip bấm từ thẻ/dòng
  trong danh sách); xoá sản phẩm cũng toast. Đã thử thêm → sửa → xoá trên UI.

- **Người mẫu đã lưu: tạo / sửa ngay trên trang + giọng đọc + câu nói** (21/10): trang `/models` có một form dùng chung
  **`ModelEditor`** (`pages/ModelsPage.tsx`) cho "+ Tạo người mẫu" và **bấm vào thẻ** (không còn nút Sửa): ảnh + giới tính / quốc gia / phong cách
  / mô tả thêm / tên / giọng (+ phong cách đọc nếu giọng Gemini) / câu nói. **Ảnh AI hay upload chỉ là xem trước — chỉ lưu khi
  bấm "★ Lưu vào thư viện" / "Lưu thay đổi"** (nút khoá khi chưa có ảnh). AI = `quicktool/standaloneImage.ts`
  `generateStandaloneImage()` (request `gen_image` **không có node**, poll `/api/requests/{id}`; ~26 s, 1 lượt ảnh Flow); ảnh vừa
  tạo có thể 404 vài giây đầu → `RetryImg`. Sửa: đổi ảnh (AI/upload, có "Giữ ảnh cũ"), không tự vẽ lại ảnh khi đổi thông tin.
  `PATCH /api/references/{id}` nhận thêm `media_id` / `aspect_ratio` / `ai_brief` (đổi ảnh xoá ai_brief cũ; ảnh đã thuộc mục khác → 409).
  Thẻ người mẫu: cả thẻ bấm được (Enter/Space cũng mở) → form sửa; ▶ nghe thử, "Mở clip gốc", nút Xoá đỏ
  (`project-modal__btn--danger`) chặn lan click. Nút đỏ `--danger` giữ màu đỏ khi hover (trước đó hover thành nền tối).
  `Reference.meta` có **`voice`**, `voiceStyle`, **`line`** (tuỳ chọn); `api/characters.ts` `voiceOf()` = giọng riêng hoặc mặc
  định theo giới tính (`defaultVoiceFor`: nam → Nam Minh, còn lại → Hoài My). Bước 1 "Dùng người mẫu này" → `applyModelVoice`:
  giọng thành `voice` của node xuất video (`ensureExportNode`), câu nói **thêm vào đầu lời thoại cảnh 1** (nếu chưa có); picker
  bước 1 hiện 🎙 giọng. `quicktool/VoiceField.tsx`: `VoiceField` (chọn giọng + nghe thử) và `VoicePreview` (chỉ nút ▶);
  `/api/llm/voices/preview` nhận `text` (Edge ~9 s lần đầu, sau đó cache).

- **Sản phẩm "Dành cho" Nam / Nữ / Unisex — người mẫu phải cùng giới** (21/10): cột `Product.gender` (male / female / unisex /
  "" = không rõ; migration `db.ensure_product_gender_column` thêm cột và **đoán một lần** cho sản phẩm cũ).
  `services/product_gender.py`: `guess()` theo từ khoá ("nam" trừ "Việt Nam/miền Nam", "nữ", "unisex", "nam nữ", váy/đầm…),
  `check(product, char_gender)` → `GenderMismatchError` (400). Tạo sản phẩm không gửi `gender` → tự đoán; đọc từ link → Gemini
  điền (`_PRODUCT_SCHEMA.gender`), TikTok/Shopee giữ lại. Chặn ở: `products.template_board_spec` (kể cả giới tính mặc định của
  template), `reference_video._character_for` (cả gợi ý của AI), `model_mode` (bàn tay), chat agent. UI: form sản phẩm có ô
  "Dành cho"; hộp Clip mới lọc ô Giới tính mẫu (+ tự chuyển Nữ→Nam khi chọn đồ nam) và màn review link/video; Bước 1 lọc ô giới
  tính / bàn tay, cảnh báo + nút "Đổi sang người mẫu nam" nếu clip cũ đang sai, thư viện khoá mẫu khác giới ("Không hợp đồ nam").
  Unisex / không rõ: không chặn. Bước 1 sửa `charGender` thẳng lên node (không qua backend) nên chỉ UI chặn ở đó.
- **Hộp Cài đặt rộng 880 px, hai cột** (`.settings-panel__grid`; mục dài thêm `settings-panel__section--wide`): Gói | Project,
  Model video (rộng, 2 cột lựa chọn), Model ảnh | Nguồn tạo ảnh, Danh sách tài khoản | Tài khoản Flow, Gemini key | Thông tin,
  Đăng xuất (rộng). ≤ 760 px về 1 cột.

- **Khung focus** (21/10, cuối `styles.css`): bấm chuột không còn viền trắng của trình duyệt (`:focus { outline: none }`);
  bàn phím (Tab) có quầng cam mờ `:focus-visible { box-shadow: 0 0 0 2px rgba(255,106,43,.45) }`. Ô nhập giữ kiểu viền riêng.

- **Đăng xuất Flow phải bấm 2 lần** (21/10, `SettingsPanel.tsx`): lần đầu nút đổi thành "Bấm lần nữa để đăng xuất…" + "Huỷ",
  tự quay lại sau 5 s / khi đóng hộp; xong có toast (`AccountPanel.handleLogout`). Nút chỉ có ở hộp Cài đặt mở từ ⚙ cạnh tài khoản.

## Việc đang dở / chưa kiểm chứng
- **Nhập từ tab đang mở** (`list_shop_tabs` / `read_tab` / `scrape_page` trong `extension/background.js`, bản 0.5.0) mới test bằng extension giả + UI giả lập, chưa chạy trên tab TikTok / Shopee thật. Trang chi tiết sản phẩm thì chỉ lấy sản phẩm chính (không lấy "sản phẩm liên quan").
- **Chưa thử thật (20/10)**: prompt 4 mẫu clip mới qua Flow; chế độ chỉ bàn tay qua Flow; tình huống hết credit → tự chuyển
  tài khoản; 2 Chrome profile cùng lúc; key OpenAI/xAI; nghe hội thoại nhiều giọng; hàng đợi nhiều clip với credit thật.
- Chưa có: kịch bản khác nhau cho từng clip (hiện chỉ khác bối cảnh). Còn thiếu so với AI Dễ Ẹc (người dùng chưa chọn làm):
  upscale 2K/4K, storyboard lưới trong wizard ("storyboard 2"), trim / chèn chữ lên video thật.
- Còn trong báo cáo UX chưa sửa: Canvas chat dock quá to, toolbar Canvas tiếng Anh, "req ✗" không bấm được, thư viện tham chiếu cũ.
- Test `test_chat_agent.py::test_gen_video_renders_on_veo_only_when_asked` lỗi sẵn trên Linux (22/10, lỗi cả khi chưa có thay đổi mới), chưa xem nguyên nhân.
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
- **21/10** — Bỏ mục "+ Clip mới" trùng ở sidebar (`QuicktoolSidebar.tsx`); "Clip của tôi" sáng cả khi hộp Clip mới mở. Kiểm tra bằng `tsc`, chưa chụp UI.
- **21/10** — 43 prompt mẫu có sẵn trong "Prompt đã lưu" (`prompt_seeds.json`, tự thêm khi agent khởi động, nút "↺ Prompt mẫu", lọc theo nhóm). Đã thử trên UI; chưa thử chạy prompt mẫu qua Flow.
- **21/10** — Trang `/prompts`: lưới 3 cột (2 cột ≤1100px, 1 cột ≤760px), phân trang 15/trang, đầu thẻ gọn (loại + Mẫu + Xoá / tên / số lần dùng). Đã thử trên UI.
- **21/10** — Hộp Clip mới: ô "Sản phẩm" và "Bối cảnh" có nút "▾ Chọn" gợi ý theo ngành của kiểu clip (+ sản phẩm đã lưu). Đã thử trên UI (chọn bối cảnh, chọn sản phẩm đã lưu, Esc).
- **21/10** — Hộp Clip mới: ô "Sản phẩm" thành danh sách sản phẩm đang bán (đồng bộ mục 1), bỏ gợi ý loại sản phẩm chung; thêm sản phẩm từ link ngay trong hộp; bối cảnh gợi ý theo ngành của sản phẩm; trang Sản phẩm hiện số clip. Sửa lỗi lưu trang "Security Check" thành sản phẩm. Đã thử thật (link TikTok, upload ảnh), test `test_products.py` 8 pass.
- **21/10** — Nhập sản phẩm từ link Shopee qua extension (`read_page`, extension 0.4.0 → phải Reload). Test giả lập 18 pass; chưa thử link Shopee thật.
- **21/10** — Nút "🛒 Nhập từ Shopee" ở trang Sản phẩm (đọc tab Shopee đang mở, extension 0.4.1). Test 47 pass; chưa thử với tab Shopee thật.
- **21/10** — Trang Sản phẩm: nút thêm/nhập gom lên một hàng, tìm kiếm + lọc ngành + sắp xếp (7 kiểu), chế độ Lưới/Danh sách, lưới 5 cột × 5 hàng và phân trang (15/trang ở chế độ danh sách). Đã thử trên UI với 32 sản phẩm tạm (đã xoá).
- **21/10** — Hệ thống toast 4 loại (thành công/thông tin/lưu ý/lỗi) thay cho dòng chữ mờ và toast lỗi một dòng; chuyển ~20 chỗ báo kết quả sang toast. Đã thử trên UI (xếp chồng, rê chuột giữ, đóng); các luồng Cài đặt chưa bấm thử từng cái.
- **21/10** — Form sản phẩm: Lưu xong báo toast và quay về danh sách, bỏ "Lưu & tạo clip".
- **21/10** — Trang Người mẫu: tạo người mẫu ngay trên trang (AI hoặc ảnh thật), mỗi mẫu có giọng đọc (mặc định theo giới tính, đổi được) và câu nói tuỳ chọn; dùng mẫu cho clip thì giọng → giọng đọc clip, câu nói → đầu lời thoại cảnh 1. Đã thử thật (1 ảnh AI qua Flow, upload, đổi giọng, nghe thử, áp vào clip tạm); mẫu thử đã xoá.
- **21/10** — Người mẫu: upload/AI chỉ xem trước, bấm Lưu mới lưu; thêm "✎ Sửa" (tên, ảnh, thông tin, giọng, câu nói) bằng cùng một form; API đổi ảnh của mục đã lưu. Đã thử thật tạo → sửa (đổi tên, giọng Gemini, đổi ảnh) → lưu; mẫu thử đã xoá.
- **21/10** — Sản phẩm có "Dành cho" (Nam/Nữ/Unisex, tự đoán + AI điền), chặn chọn người mẫu khác giới ở hộp Clip mới, review link/video, Bước 1, thư viện và backend; hộp Cài đặt rộng gấp đôi, hai cột. Đã thử trên UI với sản phẩm thật (áo ba lỗ → nam); test 85 pass.
- **21/10** — Bỏ viền trắng khi bấm vào nút/mục menu (giữ quầng cam khi dùng Tab); đăng xuất Flow cần xác nhận. Commit + push gộp mọi việc 21/10.
- **21/10** — Người mẫu: bấm vào thẻ là mở form sửa (bỏ nút "✎ Sửa"); nút Xoá thành nút đỏ như form sản phẩm; sửa lỗi nút đỏ hover bị đổi thành nền tối (mọi chỗ dùng `project-modal__btn--danger`). Đã thử trên UI (bấm thẻ → form sửa; ▶ / Xoá không mở form). Commit + push.
- **22/10** — Gộp "Nhập từ TikTok" + "Nhập từ Shopee" thành một nút **"📥 Nhập từ tab đang mở"**: tự nhận tab TikTok / Shopee, trang sản phẩm hay showcase, nhập nhiều tab một lần (bảng chọn + kết quả từng tab). `services/tab_import.py`, `GET /api/products/open-tabs`, `POST /api/products/import-tabs`, extension **0.5.0** (`list_shop_tabs`, `read_tab`, `scrape_page` nhận `tabId`) → **phải Reload extension**. Test `test_tab_import.py` (15) pass, cả bộ 836 pass + 1 lỗi có sẵn; UI thử bằng dữ liệu giả + agent thật báo đúng "cần Reload 0.5.0"; chưa thử tab thật. Commit + push.
- **22/10** — Phase 1.5 bước A: đăng nhập (`akiragosho` / `Password@123`) + dữ liệu tách theo tài khoản trong `storage/accounts/<user>/`; mọi API cần cookie; test `test_account_login.py` 7 pass, cả bộ 786 pass; thử thật trên UI (Playwright) và API. Dữ liệu cũ đã dời vào tài khoản akiragosho. Chờ Neon + B2 để làm bước B (dữ liệu lên cloud).
- **22/10** — Bước B (code, chưa nối thật): Postgres theo schema mỗi tài khoản + `move_to_cloud`, kho file S3 theo tài khoản (`file_store.py`), `Asset.local_path` tương đối, routes `/api/cloud/*`, Cài đặt → "Dữ liệu của tài khoản". Test 833 pass, 2 skip chờ Neon, 1 lỗi quyền file 0600 có sẵn trên Windows. Đã thử trên UI: mục Dữ liệu hiện đúng trạng thái "trên máy này". Chờ người dùng đưa Neon URL + B2 key.
- **22/10** — Bước B chạy thật: tạo project Neon `flowboard` (Singapore) + bucket B2 `flowboard-media-akira` + key qua Claude in Chrome; sửa 4 lỗi gặp khi nối thật (Neon pooler/search_path, UTCDateTime, id text, test đụng kho thật); `POST /api/cloud/migrate` chuyển akiragosho lên `acct_akiragosho` (346 dòng), media đẩy lên B2 nền; UI Cài đặt báo "trên cloud (Postgres)". Máy cty: chỉ cần thêm `FLOWBOARD_CENTRAL_DB_URL` vào `.env`. Chưa commit.
- **22/10** — API key + cấu hình provider (`secrets:<user>` trên Neon, tự chép từ file lần đầu) và tuỳ chọn UI (`ui_prefs`, `/api/account/prefs`) đi theo tài khoản; project Flow ghim vốn đã theo tài khoản. Thử thật: restart → 7 key Gemini thấy trên Neon, prefs ghi/đọc; UI đăng nhập gọi GET prefs. Test login 8 pass, cả bộ 833 pass. Chưa commit.

