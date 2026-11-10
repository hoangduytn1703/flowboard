# DFlow (tên cũ Flowboard) — ghi chú cho Claude (đọc đầu mỗi phiên)

Công cụ **local, một người dùng** tạo clip quảng cáo (ảnh → video → ghép + lồng tiếng) cho **người làm affiliate TikTok Shop ở Việt Nam**. Tập trung vào chế độ **Quicktool** (`/clips`, `/products`), không phải Canvas (node).
Tạo ảnh/video đi qua Google Flow (cần gói Pro/Ultra) bằng extension Chrome; LLM dùng Gemini API key (nhập trong Cài đặt).

## Quy ước làm việc với người dùng
- **Tính năng mới nào hợp thì dạy luôn cho 🤖 Trợ lý AI** (người dùng dặn 30/10, không cần nhắc lại): thêm / sửa kỹ năng trong
  `services/assistant.py` (`_SYSTEM`, `_clean_args`, `_plan_summary`, `_HANDLERS`) + test `test_assistant.py`, để người dùng nói một câu là trợ lý làm được.
- **Tên sản phẩm là DFlow** (đổi 30/10; logo chữ D cam `frontend/public/dflow-logo.png`, favicon, chữ "DFLOW" `.dflow-wordmark`, "© năm DFlow · Dev DuyNH" ở cuối
  sidebar). Chỉ đổi chữ người dùng nhìn thấy; **trong code vẫn là `flowboard`** (package Python, thư mục, biến `FLOWBOARD_*`, khoá localStorage
  `flowboard.*`, tên kiểu `FlowboardNodeData`, log `[Flowboard]` của extension) — đừng đổi (hỏng `.env`, dữ liệu, extension). Đã gỡ hết dấu vết tác giả
  gốc (link, tài trợ / Ko-fi, QR, nhóm Facebook, README gốc, `.omc/`, `.github/`); lịch sử git vẫn còn commit của họ (chỉ xoá được bằng viết lại lịch sử).
- Trả lời **tiếng Việt**, ngắn gọn. UI hiển thị **tiếng Việt**; prompt ảnh/video giữ **tiếng Anh** (Flow hiểu tốt hơn).
- Chỉ commit/push khi được bảo. Xoá dữ liệu hoặc dừng tiến trình đang chạy: hỏi trước (trừ khi được bảo rõ).
- **Git (29/10, người dùng yêu cầu): repo chỉ còn remote `origin` = `hoangduytn1703/flowboard`, chỉ nhánh `main`** — đã gỡ remote `upstream` (repo gốc) và xoá các nhánh worktree cũ. Không thêm lại upstream, không chạy skill `sync-upstream` cho repo này; pull / push `main` với origin.
- Người dùng code ở 2 máy (cty + nhà), đồng bộ bằng git. Trí nhớ của Claude không đi theo máy, nên file này là trí nhớ chung.
- **BẮT BUỘC (người dùng dặn 20/10, không cần nhắc lại): code xong / sửa xong bất cứ thứ gì thì ghi ngay vào file này**, trước khi báo cáo:
  1. thêm một dòng vào **Nhật ký** (cuối file): ngày, làm gì, file/route chính, đã thử thật chưa;
  2. cập nhật mục **Chỗ cần biết trong code** nếu có module/route/bảng mới, **Bẫy đã gặp** nếu vừa dính bẫy,
     **Việc đang dở** nếu còn phần chưa xong / chưa kiểm chứng; xoá hoặc sửa dòng đã lỗi thời.
  Mục tiêu: mở máy khác, đọc file này là làm tiếp được. Commit/push vẫn chờ được bảo (nhắc rằng file cần push để máy kia thấy).
- Nhật ký lỗi/tính năng chi tiết (FB-xxx) nằm ở `D:\codes\flow-AI\BUGLOG.md` — **ngoài repo, không đồng bộ qua git**; điều cần cho máy kia phải có trong file này.

## Chạy
- Python 3.11+, Node 20+, Chrome, **ffmpeg + ffprobe** trên PATH. Máy Linux không có sudo: `uv` và ffmpeg nằm ở `~/.local/bin` (nhớ `export PATH=$HOME/.local/bin:$PATH`).
- `make install` (cần `python3-venv`; không có thì dùng `uv venv` + `uv pip install -e ".[dev]"` trong `agent/` — `[dev]` có pytest + moto cho test; chạy lại sau mỗi lần `pyproject.toml` đổi), `cp .env.example .env`.
- `make agent` (FastAPI :8434, WebSocket extension :8355) và `make frontend` (Vite :5174).
- Extension: `chrome://extensions` → Load unpacked → `extension/`. Sửa extension thì phải **reload** nó. Cần một tab `flow.google.com` đã đăng nhập, để mở.
- Project Flow: đặt trong Cài đặt (`PUT /api/flow/projects/pinned`, tự chuyển các board sang project mới). Gói Pro/Ultra: `FLOWBOARD_PAYGATE_TIER` trong `.env`.
- **App desktop (7/11, Phase B bản đầu)**: bộ cài `DFlow_<ver>_x64-setup.exe` build trên **GitHub Actions** (`.github/workflows/desktop.yml`: Actions →
  "Desktop app" → Run workflow → tải ở Artifacts; hoặc đẩy tag `v*` → GitHub Release). Không cần Rust / Visual Studio trên máy (máy nhà không có). Xem
  "Chỗ cần biết" → "App desktop".
- **Windows**: `.\start.ps1` (ghi `.env`, dừng bản cũ, cài dependency khi đổi, chạy frontend + agent); chạy nền thì
  `powershell -ExecutionPolicy Bypass -File .\start.ps1 *> storage\logs\startN.log` (dùng tên log mới mỗi lần, file cũ hay bị khoá).
  Cổng cố định: flowboard UI **5174** / API 8434 / WS 8355; flowkit 5173 / 8100 / 9222 — chạy song song, không đổi.
- Python venv `agent/.venv`. Test: `cd agent && PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests`
  (~3 phút). Typecheck frontend: `cd frontend && npx tsc -b --noEmit`.
- Bí mật **ngoài git**: `~/.flowboard/secrets.json` (Gemini API keys `geminiApiKeys`, `apiKeys.openai|xai`), nhập qua Cài đặt.
  Máy mới phải nhập lại key.
- **Remotion** (phụ đề lồng tiếng kiểu mới, 25/10): gói npm nằm trong `frontend/package.json` (`remotion`, `@remotion/player|bundler|renderer|google-fonts`
  4.0.538, ~130 MB) — `npm install` trong `frontend/` là đủ; lần render đầu Remotion tự tải Chrome Headless Shell (~150 MB, vào cache của Remotion)
  và đóng gói webpack vào `frontend/node_modules/.cache/flowboard-remotion/` (~10 s, làm lại khi file trong `src/remotion/` đổi). Cần `node` trên PATH
  (`FLOWBOARD_NODE` để chỉ đường dẫn khác). Không có thì trang lồng tiếng chỉ hiện engine ffmpeg.
- **Giọng VieNeu** (miễn phí, chạy trên máy, 27/10): cần venv pyvideotrans có gói `vieneu` (VieDub đã cài) + model
  `pnnbao-ump/VieNeu-TTS-v3-Turbo` trong cache HuggingFace (~580 MB, tự tải lần đầu; máy nhà đã có). Máy không có → nhóm VieNeu mờ trong ô chọn giọng.
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
  (`FLOWBOARD_SEED_USER/PASSWORD`). **Không còn đăng ký tự do** (8/11 bỏ `POST /api/account/register` + `FLOWBOARD_ALLOW_REGISTER`):
  chỉ tài khoản quản trị tạo tài khoản ở menu **👥 Quản lý tài khoản** (xem "Chỗ cần biết" → "Quản lý tài khoản"), hoặc `accounts.create_user()` trong Python.
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
- **Sửa file lớn bằng script: tính điểm cuối bằng `index()` của chính đoạn cần xoá, đừng trỏ tới marker ở xa** — 21/10 một lệnh xoá nhầm ~11 nghìn ký tự CSS của `quicktool.css` (phục hồi từ git HEAD + dựng lại phần chưa commit; luôn `git diff --stat` ngay sau khi sửa file lớn; 8/11 một script chèn mục mới vào giữa CLAUDE.md viết `t[:i] + mới` quên `+ t[i:]` → mất 514 dòng (Lộ trình, Việc đang dở, Nhật ký) — `git diff --stat` bắt được, phục hồi từ bản CLAUDE.md trong transcript phiên).
- **Viết bài: prompt đừng mời AI nêu "nhược điểm"** — kiểu Review từng ghi "một nhược điểm nhỏ hoặc mẹo" → AI bịa "sốt hơi
  mặn" (không có trong dữ liệu sản phẩm). Giờ chỉ xin "mẹo lấy từ dữ kiện đã cho", cấm bịa lỗi / nhận xét vị. Lệnh sửa bài kiểu
  "ngắn hơn" hay làm rơi `image_prompts` → `write_post` giữ lại prompt cũ. Gọi `curl -d '<json tiếng Việt>'` trong Git Bash bị
  lỗi mã hoá ("error parsing the body") — ghi JSON ra file rồi `--data-binary @file`.
- **Playwright: toast ở góc phải trên che đúng các nút đầu thẻ bên phải** ("Lưu bài", "+ Bài mới"): bấm ngay sau một toast thì
  click chờ/trượt. Script e2e đóng toast (`.toast__close`) trước khi bấm. Tên clip-creation `nodes` trả về là **short id**, còn
  `PATCH /api/nodes/{id}` cần id số → lấy từ `GET /api/boards/{id}`.
- **`video_export.probe_clip` chỉ trả kết quả cho file có luồng video** — dùng cho WAV thì ra None (24/10: track giọng lồng tiếng
  dài 24 s cho video 12,6 s vì mọi khoảng lặng đều bị cộng thêm). Đo audio bằng `tts._probe_duration`. ASS `WrapStyle: 2` = không
  xuống dòng → chữ tràn khung; dùng `WrapStyle: 0` + cắt câu theo số ký tự vừa chiều rộng. Vá frontend bằng heredoc Python có
  `||` fallback → script không chạy mà vẫn in "patched" (route `/tools/dub` thiếu tới khi Playwright báo) — ghi script bằng Write
  rồi chạy, kiểm `grep` sau khi vá. `curl -F file=@/c/…` trong Git Bash upload rỗng → dùng httpx trong Python.
- **Douyin không tải được bằng yt-dlp** (25/10: `[Douyin] …: Fresh cookies (not necessarily logged in) are needed`) — đi đường trang
  chia sẻ mobile (xem `video_fetch`). Nút Share của Douyin chép cả câu kèm link → mọi ô nhập link phải `extract_url` trước. Link
  dạng "合集" (tuyển tập) là video dài hàng giờ, không phải clip lẻ.
- **Pydantic `dict[str, float]` từ chối dict lồng** (25/10: body `layout.blur` bị 422 "Input should be a valid number") — dùng
  `dict[str, Any]` cho JSON tự do. Agent **không auto-reload**: sửa route/service xong phải khởi động lại (kiểm `/api/history` +
  `/api/dub/jobs` không có gì chạy; job dub đã lưu `job.json` nên không mất).
- **spleeter trong sherpa-onnx: `stems[0]` là GIỌNG, `stems[1]` là nhạc nền** — VieDub (`_audio_separate.py`) gán ngược, mình chép
  theo nên "nhạc nền" giữ lại nguyên giọng Trung ở −12 dB đè lên giọng Việt −19 dB (người dùng nghe như chưa lồng tiếng, 25/10).
  Đã đảo trong `dub_runner.separate` (kiểm bằng Whisper: stem giọng ra 20 câu tiếng Trung, stem nền 0 câu). bgm.wav cũ trong
  `media/dub/*/` đã xoá để render lại tách lại. Lưu ý VieDub bên pyvideotrans vẫn còn lỗi này.
- **`innerText` của trang Facebook đầy dòng "Facebook" ẩn** (hàng trăm dòng, 25/10) — chiếm hết giới hạn ký tự trước khi tới bài
  viết. Lọc ở cả extension (`readChannelPageInPage`) lẫn backend (`channel_page.clean_text`). Script vá có `assert` giữa chừng:
  assert lỗi thì các thay đổi trước đó trong cùng script cũng không được ghi — chạy lại kiểm `grep`.
- **`cd frontend && npm install …` trong Bash có lúc chạy ở thư mục gốc repo** (25/10: shell bị đặt lại cwd giữa chừng → npm tạo `package.json` +
  `node_modules` ở `D:\codeslow-AIlowboard\` thay vì `frontend/`, Remotion resolve từ gốc). Dùng `npm install --prefix <đường dẫn tuyệt đối frontend>`;
  kiểm `git status` không thấy `package.json` lạ ở gốc. Đã xoá bản cài nhầm.
- **Flow trả 200 nhưng không có ảnh ("image generation returned no media url") = bộ lọc nội dung, không phải lỗi hệ thống** (25/10:
  prompt "pregnancy pillow" bị bỏ 2/2, "red apple" ra sau 29 s cùng lúc). `flow_sdk` giờ ghi WARNING kèm payload và báo lỗi tiếng Việt
  gợi ý sửa prompt. Thấy lỗi này: đổi từ nhạy cảm trong prompt trước khi nghi extension/project.
- **Lấy token Facebook Page qua Graph API Explorer** (26/10, app kiểu "trường hợp sử dụng" mới):
  - Token từ Explorer sống ~1 giờ → phải gia hạn: trang Gỡ lỗi mã truy cập → "Mã truy cập mở rộng" (Extend) → token dài hạn ~60 ngày hiện dưới dòng
    "sẽ hết hạn vào…" (khác chuỗi ở ô trên cùng). Dán **token người dùng đã gia hạn** vào Flowboard, không dán token Page lấy thẳng từ Explorer:
    `facebook_publish.inspect_token` gọi `/me/accounts` rồi lưu token của Page; từ token người dùng dài hạn thì token Page nhận về không hết hạn.
  - Quyền chữ **xanh** trong Explorer = đã thêm vào danh sách nhưng token hiện tại chưa có → phải Generate Access Token lại (lần đầu chỉ được
    `pages_show_list` + `pages_read_engagement`). Luôn kiểm bằng trang Gỡ lỗi, mục "Phạm vi", đừng tin màu. Cần đủ `pages_show_list`,
    `pages_manage_posts`, `pages_read_engagement`, `pages_manage_engagement`; trong hộp thoại Facebook phải tick **đúng Page**.
  - Hộp thoại đăng nhập báo "Invalid Scopes: pages_read_user_content" dù danh sách quyền của Explorer không có quyền đó (Explorer giữ yêu cầu cũ).
    Qua được sau khi thêm luôn `pages_read_user_content` vào danh sách quyền của Explorer rồi Generate lại (app đã có quyền này, "Sẵn sàng thử
    nghiệm"). Flowboard không cần quyền này. Nếu vẫn lỗi: xoá app khỏi facebook.com/settings?tab=business_tools, hoặc mở Explorer ở cửa sổ ẩn danh.
  - Tạo app: trường hợp sử dụng **"Quản lý mọi thứ trên Trang"**; màn "Hồ sơ doanh nghiệp" chọn "Tôi chưa muốn kết nối". Admin Page + app ở chế độ
    Development vẫn đăng được lên Page của mình, không cần gửi duyệt. Dropdown "Người dùng hoặc Trang" chọn **Lấy mã truy cập người dùng**
    (tooltip "Không có cấu hình nào" là của tab Configurations, bỏ qua). Phương thức GET/POST ở Explorer không liên quan, chỉ để thử gọi API.
  - Shopee không liên quan tới app Facebook: link aff chỉ là text trong bình luận đầu. Token hết hạn thì lặp lại Generate → Extend → dán lại ở Kênh.
- **Component mount cùng lúc với "token" đã bump thì effect `useRef(token)` không chạy** (25/10, `PostEditor` chỉ xuất hiện sau lần viết
  đầu nên `seenToken` khởi tạo = token mới → bỏ qua): khởi tạo ref = 0, coi 0 là "không làm gì", chỗ mở dữ liệu cũ đặt token về 0.
- **Gemini TTS đọc to cả câu lệnh hướng dẫn tiếng Anh** (26/10, bug người dùng báo trong video lồng tiếng "Bài tập vai cổ…" giây 8): ngoài lỗi
  đọc "phong cách" đã sửa 22/10, Gemini còn thỉnh thoảng đọc nguyên khối prompt ("Read the transcript below… The director's notes… Director's notes.
  Giọng đọc tự nhiên, rõ ràng.") rồi mới tới câu thoại — đo thật: 8/41 câu (~20 %) của job đó, câu 6 chữ ra 11,8 s. Không đoán được câu nào bị, nên
  **kiểm tra bằng độ dài**: `tts.gemini_leaked(text, dur)` = dài hơn `max_speech_seconds` (số chữ / 2,5 + 1,5 s; câu bình thường chỉ tới 0,79 lần ngưỡng,
  câu lỗi 1,5–4 lần) → đọc lại, tối đa `GEMINI_ATTEMPTS = 3`, **lần cuối gửi đúng câu thoại không kèm hướng dẫn** (`_synth_gemini(plain=True)`); 3 lần đều
  lỗi → `TTSError` rõ ràng. File cache cũ bị lỗi cũng được kiểm khi đọc lại và tự đọc lại. Áp cho mọi chỗ dùng giọng Gemini (lồng tiếng, ghép Bước 5,
  nghe thử). Lồng tiếng: in lại nhanh dùng lại `voice.wav` khi câu/giọng không đổi → job cũ dính lỗi phải bỏ `voice.wav` rồi render lại. Test
  `test_tts_gemini_leak.py` (5).
- **Giọng Gemini TTS: bản miễn phí chỉ 10 lượt/ngày/key, quota tính theo TỪNG MODEL** (27/10, người dùng báo "7 key mà hết 1 key là
  báo hết hạn"): 429 của Google kèm `quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue 10`, `quotaDimensions.model
  gemini-3.8-flash-tts`, `retryDelay ~59000s`. Code cũ "nghỉ" **cả key** 16 giờ khi chỉ model TTS hết → 6 key nghỉ từ hôm trước, lần sau
  chỉ còn 1 key thử → thông báo "(1 key đã thử)" gây hiểu nhầm; đồng thời không thử model dự phòng `gemini-3.8-flash-lite-tts` (cùng key
  vẫn trả 200, đo thật) và chặn luôn cả việc viết bài bằng key đó. Giờ `gemini_api`: nghỉ theo **(key, model)** (`KeyState.model_parked`,
  `GeminiQuotaError.model/limit/per_day` đọc từ `QuotaFailure`), `speak()` thử **mọi key trên model chính rồi mọi key trên model dự phòng**
  (`MODEL_FALLBACKS[TTS_MODEL]`), `with_key(model=, max_wait_s=)` chờ key hồi (giới hạn phút, `MAX_WAIT_S` 45 s / TTS 180 s) thay vì lỗi
  ngay, thông báo nói rõ "N key hết quota ngày — 10 lượt/ngày/key, key sớm nhất dùng lại sau X giờ". **Ngân sách thật**: 7 key × 10 = 70 câu/ngày
  cho model chính + 70 câu cho lite; video 3–10 phút (40–100 câu) ngốn gần hết trong một lần → video dài nên dùng giọng Edge (không giới hạn).
  Câu đã đọc được cache theo text+giọng nên render lại chỉ đọc phần còn thiếu. pyvideotrans (VieDub, `_geminitts.py`) cũng bắt người dùng tự
  nhập key (`gemini_key`, cách nhau dấu phẩy), chỉ xoay vòng từng câu, gặp lỗi API là dừng cả việc — không có key sẵn, không xử lý quota.
- **Khung chỉnh vị trí phụ đề luôn dọc 9:16 → lệch với video ngang** (26/10, người dùng báo: chỉnh trên khung thì chuẩn, lên clip thì lệch):
  `DubPage` truyền `width={0} height={0}` nên `SubPositioner` dùng 9:16, video ngang bị thu nhỏ có viền đen trên dưới nhưng toạ độ (x, y = tỉ lệ
  khung) lại tính theo cả khung dọc → 80 % khung dọc ≈ 40 % hình thật. Giờ khung lấy tỉ lệ thật: props `job.width/height` (job lưu từ lần render),
  không có thì `videoWidth/videoHeight` của thẻ video; video ngang dùng khung rộng 720 px (`.qt-subpos__stage--landscape`). Bố cục đã chỉnh trên
  khung sai trước đây phải chỉnh lại rồi "Áp dụng".
- **Viết tập tiếp của loạt truyện bị lẫn ghi chú của page khác** (27/10, người dùng báo: Tập 6 "những thú vị về hệ mặt trời" của page
  "Chúng ta hay tò mò" thành "Mẹ bầu và cuốn sách của bố"): nút "✍️ Viết Tập N" gộp `{...brief của form, ...brief tập cuối}` → trường tập cuối
  không có (`image_wish: "liên quan người mẹ bầu…"` gõ cho page Mẹ bầu, cả sản phẩm đang chọn) lọt vào. Giờ `seriesBrief(last)` = mặc định +
  brief tập cuối, sản phẩm = của tập cuối; chọn loạt có sẵn ở form cũng nạp cài đặt của loạt. Prompt: luật "Each page is separate" trong `_SYSTEM`,
  `_series_block` dặn loạt thuộc đúng page, bám chủ đề + mạch tập trước, **chi tiết lạc đề ở tập trước là nhầm — không viết tiếp**, mong muốn ảnh chỉ lấy
  phần hợp page. Thử AI thật: cùng brief dính "mẹ bầu" + Tập 6 lạc đề trong ngữ cảnh → bài + ảnh Tập 7 quay về Sao Thổ (trước khi siết: vẫn "em bé khẽ cựa").
  Loạt đã lạc một tập thì tập đó vẫn kéo các tập sau — nên xoá / viết lại tập lạc.
- **Phụ đề chạy trước giọng 1–6 s** (28/10, người dùng: "sub đang chạy nhanh hơn tiếng khoảng 1–2 s"): đo video Enceladus 3:35 — 35/89 câu
  dài hơn chỗ của nó dù đã tăng tốc tối đa 1,45×, `_timeline_wav` đẩy câu sau lùi lại (không chồng), phụ đề vẫn theo mốc gốc → giọng trễ trung bình
  3,07 s, tối đa 5,72 s; Edge còn đệm ~0,22 s im lặng đầu mỗi câu. Sửa: (1) **phụ đề theo giọng** — `_timeline_wav` trả nơi từng câu thật sự nằm,
  `follow_voice` đặt lại start/end của câu đó (hết câu + `SUB_TAIL_S` 0,25 s, không lấn câu sau; câu bị bỏ trượt ra sau câu trước), rồi `voice_key`
  tính lại; (2) **cắt im lặng đầu/cuối** mỗi câu (`TRIM_SILENCE`, silenceremove + areverse) trước khi đo; (3) **khớp vào cửa sổ** = chỗ của câu + khoảng
  lặng tới câu sau (`line_window`) thay vì chỉ chỗ của câu; (4) bản dịch nhận **giới hạn từ mỗi câu** (`word_budget` = cửa sổ × `WORDS_PER_SECOND` 4,2;
  Edge đọc ~3,3 từ/s) trong prompt "(… , ≤ N từ)". Kết quả in lại video đó: phụ đề–giọng lệch 0,00 s (62 câu có khoảng lặng trước, đo bằng silencedetect),
  giọng so với lời gốc trễ 0 s (trước 3,07 s TB). Dịch thử có giới hạn: không lẫn ghi chú vào câu, 16/89 câu vượt 1–2 từ (vẫn trong mức tăng tốc).
- **Giọng Edge từ chối ngẫu nhiên 30–60 % lượt gọi ("No audio was received")** (28/10, người dùng báo video Douyin 3:35 lồng tiếng lỗi ở
  câu 16/89): không phải do câu chữ (cùng câu gọi lại là được), không phải giới hạn tốc độ — đo thật: chờ 0,5 s hay chờ tăng dần, 1 hay 8 lượt cùng lúc
  đều bị từ chối như nhau. Code cũ: đọc lần lượt từng câu, 4 lần thử, chờ 1–4 s → một câu trượt 4 lần là cả video chết, và mỗi câu trung bình 10–21 s
  (89 câu ≈ 15–30 phút). Giờ: `tts.ATTEMPTS = 10` (4 lần đầu chờ 0,5 s, sau tăng dần tới 5 s, ~21 s), `dub._prefetch_edge` đọc **8 câu một lúc**
  (`EDGE_PARALLEL`; đo: 1 lúc 21,6 s/câu, 4 lúc 3,3–4,8 s, 8 lúc 1,5–3,1 s), câu vẫn trượt thì `_voice_pieces` chờ 30 s rồi đọc lại (tối đa
  `VOICE_ROUNDS` 3 vòng, có đếm ngược trên phase), hết vòng mới báo lỗi (kèm gợi ý đổi sang VieNeu). Chạy lại đúng link đó: 156 s cả quy trình, Edge
  từ chối 70 lần nhưng không câu nào phải sang vòng 2.
- **Lượt gọi Edge có thể treo mãi khi mạng rớt** (29/10, người dùng: "sao nó 71% quài"): video 10:51, 332 câu, sau 196 câu thì 8 lượt `communicate.stream()` cùng kẹt lúc 20:36 (không lỗi, không log, `receive_timeout=60` của edge-tts không cứu), job đứng ở 71 %, bấm Dừng cũng vô ích (`job.stop` chỉ được xem trước khi một câu bắt đầu). Gọi Edge riêng lúc đó vẫn ra 0,7 s. Giờ mỗi lượt có hạn `tts.edge_attempt_timeout(text)` (20 s + độ dài/20, tối đa 60 s) qua `asyncio.wait_for`, quá hạn = một lần thử hỏng rồi thử lại. Bản dịch trước đây **chỉ nằm trong RAM** cho tới khi job xong → khởi động lại là mất; giờ `_prepare` gọi `persist(job)` ngay sau khi dịch, và job có câu mà bị cắt ngang giữa chừng thì mở lại với lỗi "bản dịch vẫn còn, bấm Xuất lại video" (không phải "làm lại từ link"). Job treo: đọc job đang chạy qua `GET /api/dub/jobs/{id}` (có `segments`) → ghi vào `job.json` → restart → `POST …/render {}` (câu đã đọc lấy từ cache TTS). Test `test_tts_edge_hang.py` (2), `test_dub_reopen.py` (+1).
- **Ghép giọng video dài: "[WinError 206] The filename or extension is too long"** (29/10, cùng job 332 câu): `_timeline_wav` đưa mọi câu vào MỘT lệnh ffmpeg (`-i <đường dẫn>` + một nhánh filter mỗi câu) → vượt giới hạn 32 767 ký tự dòng lệnh Windows (~200 câu là chạm). Giờ quá `TIMELINE_CHUNK` (48) câu thì tính vị trí trước (cùng luật đẩy câu dài), ghép từng nhóm ra `<out>.part<n>.wav` (`_timeline_part`), rồi ghép các phần lại, xoá file phần. Test `test_a_long_video_lays_out_its_voice_in_parts_with_the_same_timing` (vị trí + độ dài giống ghép một lượt). Video ≥ ~200 câu trước 29/10 đều chết ở bước "Đang xếp giọng theo thời gian" (81 %).
- **Bước 5 của clip hiện / tải video CŨ sau khi xuất lại ở trang Lồng tiếng** (29/10, người dùng tưởng phụ đề + vùng mờ trong file lệch với màn chỉnh): file mới (`c22a7c…`) đúng y màn chỉnh, nhưng `store/board.ts switchBoard` bỏ qua khi clip đã là clip hiện tại (`id === boardId`) → node export vẫn giữ `mediaId` của lần nạp trước (bản 20:55) nên video xem và nút "⬇ Tải về" ở Bước 5 đều là bản cũ. Mọi việc ghi lên clip từ phía agent (lồng tiếng, Edit auto CapCut, job nền) đều dính. Giờ `Wizard` (`QuicktoolApp.tsx`) gọi `refreshBoardState()` một lần mỗi khi mở route của clip đang là clip hiện tại (`freshFor` ref). Thấy "file xuất ra khác màn chỉnh": so `mediaId` của node export với `job.media_id` trước khi nghi phần dựng hình.
- **yt-dlp `--match-filter` không có phép HOẶC bằng `|`** (10/11, mọi link YouTube / TikTok tải qua yt-dlp chết "ERROR: Invalid filter part '!duration | duration <= 3600'" — dính từ 1.8.4, commit `0b88d5c`; test chỉ so chuỗi lệnh nên không bắt được): "thiếu trường thì cho qua" viết là `duration <=? 3600` (dấu `?` sau toán tử). `routes/reference_video._run_ytdlp`. Đã thử với yt-dlp thật: video 19 s qua, giới hạn 10 s ra đúng câu "does not pass filter". **Bản 1.8.4 đã phát hành dính lỗi này** — cần phát hành bản sửa. Đổi tham số yt-dlp: chạy thử một lệnh thật, đừng chỉ so chuỗi.
- **`setState([])` trong effect không có deps = vòng render vô hạn** (29/10, "Maximum update depth exceeded" ở trình chỉnh sửa lồng tiếng, do effect cảnh báo "📱 Xem trên" của `EditorStage` đặt mảng rỗng MỚI mỗi lần render khi không bật nền tảng): giữ nguyên mảng cũ khi không có gì đổi (`setX((prev) => (prev.length ? [] : prev))`). Quét lỗi trang bằng Playwright (`pageerror` + console error + HTTP ≥ 400) sau mỗi đợt sửa giao diện lớn.
- **Đọc token Facebook Page (kho trung tâm Neon) ~0,15 s mỗi lần** — đừng gọi `facebook_publish.get_token` trong vòng lặp theo từng dòng: `scheduler._decorate` gọi cho mỗi lịch đăng → 13 lịch = ~2 s mỗi lần gọi API, trang Lịch đăng gọi nhiều lần (~11 s mở trang). Giờ tính `connected` một lần mỗi kênh (~0,55 s; trang ~5,6 s).
- **Đăng video lớn lên Facebook Page bị "413 Request Entity Too Large"** (28/10, người dùng tưởng token hết hạn): bài #33 gắn clip #30 (lồng tiếng 3:35, file 152 MB) → `facebook_publish` gửi cả file trong một request `source` tới `graph-video …/{page}/videos` → Facebook từ chối 413, thông báo cũ chỉ ghi "Facebook từ chối (413): " (rỗng). Token hết hạn là mã **190**. Giờ video > `CHUNKED_ABOVE` (20 MB) đi đường chia nhỏ `_upload_video_chunked`: `upload_phase=start` (`file_size`) → `transfer` đúng khoảng byte Facebook trả về (`start_offset`/`end_offset`, `video_file_chunk`, thử lại 3 lần khi rớt mạng) → `finish` (`description`), tối đa 1,75 GB / 45 phút; 413 báo "file gửi lên quá lớn". Test `test_a_big_video_goes_up_in_pieces`. Chưa đăng lại bài #33 (để người dùng tự bấm).
- **Lồng tiếng dịch bằng Claude CLI → hết lượt gói Max là cả loạt video chết "dịch thất bại: claude CLI exited 1: "** (30/10, thư viện link 184 link: 4 video lỗi liền): bước dịch gọi `run_llm("auto_prompt")` = provider đặt trong Cài đặt (máy nhà là Claude CLI) nên **mỗi video tốn lượt Claude**; CLI hết lượt thì thoát 1, lý do nằm trong envelope JSON ở stdout chứ không ở stderr → thông báo rỗng. VieDub / pyvideotrans dịch bằng **Google Dịch miễn phí** (kênh 0), không tốn gì. Giờ: lồng tiếng mặc định **dịch bằng Google** (`services/free_translate.py`, xem Chỗ cần biết), AI là lựa chọn và lỗi giữa chừng thì phần còn lại tự sang Google; `claude_cli._stdout_reason` đưa lý do thật vào lỗi. Trang `/m` của Google mà pyvideotrans gọi đang trả trang "sorry" 429 từ IP máy nhà — dùng `translate.googleapis.com … client=gtx` (vẫn chạy) + Microsoft dự phòng.
- **Douyin chập chờn, không phải video bị xoá** (30/10): cùng link lúc thì trang chia sẻ trả dữ liệu, lúc thì "Douyin không trả dữ liệu: video đã xoá, riêng tư…" (link 7648… lỗi 19:31, tải được 23:00; link 7690… ngược lại). VieDub có đường dự phòng mở Edge/Chrome ẩn để vượt chặn — **không làm cho Flowboard** (lách cơ chế chống bot; lệnh thử bị chặn). Link lỗi kiểu này: đợi một lúc rồi chọn lại trong Thư viện link → "🎙 Lồng tiếng".
- **Remotion `interpolate` ném lỗi khi câu phụ đề ngắn hơn 0,2 s** (28/10, "inputRange must be strictly monotonically increasing"): fade của `DubSubtitles` dùng mốc `start+0,12` và `end−0,08` → câu 0,16 s làm mốc đảo thứ tự, cả lượt render Remotion lỗi. Giờ kẹp hai mốc về giữa câu. Bug có sẵn, lộ ra khi test nhấn chữ với câu ngắn.
- **Remotion render lỗi "Error while getting compositions … localhost:3000 … getStaticCompositions"** (1/11): cổng 3000 bị dự án khác chiếm
  (TikTok Live Games `node src/server.js` nghe `[::]:3000`) — Remotion chỉ kiểm cổng trống ở IPv4 rồi mở `http://localhost:3000`, trình duyệt ẩn đi vào ::1 → gặp trang
  khác. `frontend/remotion/render.mjs` giờ tự lấy một cổng trống cả IPv4 lẫn IPv6 (`freePort`) và truyền `port` cho `selectComposition` + `renderMedia`. Lỗi
  Remotion kiểu "không phải dự án Remotion" → nghĩ tới cổng bị chiếm trước.
- **Zoom theo thời gian trong ffmpeg**: `crop` không đổi được w/h theo khung, `scale eval=frame` đổi cỡ khung làm link filter đổi kích thước — dùng `zoompan` với `d=1`, biểu thức theo `in_time`, `s=` đúng cỡ nguồn và `fps=` đúng r_frame_rate (sai fps thì lệch tiếng dần). Nhanh (6 s video 0,5 s).
- **Graph API: tool gọi `v21.0` nhưng Facebook trả lời bằng `v26.0`** (header `facebook-api-version`, thấy 30/10): v21 đã hết hạn, Facebook tự nâng lên bản cũ
  nhất còn chạy → luật của v26 áp dụng (ví dụ tham số `ids=` gom nhiều id đã bị bỏ: lỗi 500 "The ids query parameter is deprecated in v26.0+" → dùng edge của page
  như `video_reels` kèm field expansion). Đăng bài / Reel vẫn chạy; muốn rõ ràng thì đổi `facebook_publish.GRAPH` sang v26 và chạy lại test schedule.
- **Chữ in hoa tiếng Việt bị cắt dấu khi phần tử có `overflow: hidden` + `line-height` thấp** (30/10, tiêu đề trang "BÀI VIẾT" hiện "BÀI VIÊT",
  "LỒNG" hiện "LÔNG"): dấu chồng (Ế, Ồ, Ẫ…) cao hơn dòng 1.3 nên bị cắt — không phải lỗi font (font hệ thống có đủ dấu). Chữ in hoa cần
  `line-height` ≥ 1.5 (+ đệm trên) khi bị `overflow` cắt (ví dụ để có "…"). Dò nhanh bằng Playwright: phần tử có chữ dấu chồng, overflow ≠ visible, lh/size < 1.45.
- **App dựng các trang hai lần lúc khởi động** (tìm ra 30/10): store board khởi đầu `loading: false` nên `AppInner` render các trang ngay, rồi
  `loadInitialBoard` bật `loading` → thay bằng `<AppLoading>` (gỡ trang) → tải xong dựng lại từ đầu: trang mất tham số URL vừa đọc rồi xoá (`?post=`,
  `?assistant=`, `?job=`) và mọi thứ bấm trong lúc đó. Giờ `AppInner` có `booted` — chỉ render trang sau lần tải board đầu. (Trước đó tưởng nhầm do `key`
  của `AppInner`.) **Bẫy test UI**: bấm một lựa chọn rồi bấm nút có lưu bài (vd "📅 Lên lịch" lưu bài trước) → lựa chọn được lưu vào bài, lần chạy sau
  bấm là TẮT nó — kết quả xen kẽ đúng / sai, không phải lỗi.
- **Ảnh trên B2 bị cắt cụt** (tìm ra 30/10): `media.fetch_and_cache` ghi dòng Asset (→ hook đẩy B2 ở luồng nền) RỒI mới xoá logo Gemini ghi đè
  file bằng bản to hơn → boto3 `upload_file` đọc kích thước cũ + nội dung mới → B2 giữ bản cụt (dấu hiệu: JPEG q95 4:4:4 của chính tool, thiếu đuôi), máy
  kia tải về ảnh nửa dưới là mảng màu. Giờ: xoá logo TRƯỚC khi ghi Asset (cả `ingest_inline_bytes`), ghi file qua `.part` (`media.write_atomic`),
  `upload_now` đẩy từ một lần đọc bytes (`put_object`) và không đẩy ảnh hỏng (`media.image_ok`), xoá logo hàng loạt thì `requeue`, `file_store.repair_images`
  (chạy trong `reconcile` khi đăng nhập; nhớ `media_checked.json`) tải lại ảnh hỏng từ B2 / đẩy lại ảnh lành khi bản B2 khác cỡ, `scheduler._check_picture` không
  đăng ảnh hỏng. **Ghi file đang được đọc / đẩy: luôn qua file tạm + `os.replace`, và cập nhật Asset sau cùng.**
- **Gói lồng tiếng báo "Could not find module …\ctranslate2.dll (or one of its dependencies)"** (10/11, máy bạn người dùng, GTX 1660 SUPER,
  app 1.8.2): không phải lỗi card / CUDA — `ctranslate2.dll` lúc nạp cần `MSVCP140.dll`, `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll` trong System32 (đọc bảng
  import của wheel 4.8.0 bằng `objdump -p`; cuBLAS / cuDNN nạp sau), Python của uv không mang MSVCP140, máy chưa cài Microsoft Visual C++ Redistributable
  (hoặc chỉ bản 2015 / 2017, thiếu VCRUNTIME140_1). Máy nhà có sẵn nên thử 9/11 không lộ. Lỗi ở chính `import faster_whisper` nên rơi về CPU cũng không cứu;
  onnxruntime (VieNeu, RapidOCR) cũng cần runtime này. Gỡ ngay không cần bản mới: cài https://aka.ms/vs/17/release/vc_redist.x64.exe rồi bấm "Cài lại". Code
  đã tự lo (xem "Gói lồng tiếng"). **Thư viện native cài vào máy khách: đọc bảng import DLL của nó, đừng tin "máy mình chạy được".**
- **TikTok lúc có lúc không trả trang "Security Check"** thay cho trang sản phẩm (thấy thật 21/10): `product_link.fetch_page` nhận diện trang chặn (`_looks_blocked`), thử lại 1 lần sau 3 s rồi báo lỗi — trước đó đã lưu một sản phẩm tên "Security Check".
- **Vite có lúc giữ bản biên dịch RỖNG của một file vừa sửa** (21/10: `AccountPanel.tsx` trả 0 byte → cả app trắng, lỗi "does not provide an export named …" dù `tsc` sạch). Kiểm tra `curl -s -o /dev/null -w '%{size_download}' localhost:5174/src/<file>`; sửa bằng `touch <file>`.
- **Gemini chậm/treo không hẳn do key rẻ, mà do model**: đo cùng một câu hỏi, `gemini-3.1-flash-lite` ~4 s, `3.5-flash` ~21 s (nhiều thinking token), `3.7`/`3.8-flash` quá 40 s. Việc đọc sản phẩm từ link dùng `product_link.EXTRACT_MODEL` (lite, ~13 s cả quy trình). Kịch bản clip (`analyze`) vẫn dùng model mặc định, có thể chậm; chưa đổi vì chưa so chất lượng. Fallback chỉ xử lý 503, không xử lý treo/timeout.
- **`NANO_BANANA_2` (NARWHAL) bị Flow từ chối** (`ogiZ0b failed: [5]`). Dùng `NANO_BANANA_PRO`. Giá trị đã lưu trong localStorage được ưu tiên hơn mặc định.
- Video: mặc định Omni Flash. Flow tự sinh giọng tiếng Anh vào video → `flow_sdk.silent_prompt()` thêm câu "no speech"; ở bước Ghép chọn "Tiếng gốc của clip" = nhỏ lại/tắt hẳn.
- `agent/flowboard/services/flow_batch.py` giữ **giống hệt bản flowkit upstream**, đừng sửa. Chính sách model nằm ở `flow_sdk.py`.
- `video_export`: bản ffmpeg static có NVENC nhưng máy không có GPU → đã có kiểm tra mã hoá thử. File clip 0 byte = lỗi.
- **Kill uvicorn thì worker con có thể mồ côi và giữ cổng 8355** → extension nối vào tiến trình cũ (`extension_disconnected`). Kill theo PID cả cây, **không dùng `pkill -f`** (giết luôn shell). `--reload` từng treo ở "Waiting for connections to close": Makefile đã có `--timeout-graceful-shutdown 3`.
- Wizard (`QuicktoolApp.tsx`) chỉ `switchBoard(id)` khi board có trong `boards` **và** `boardsLoaded` (store) đã true; không thì xoá clip sẽ gọi lại board vừa xoá → toast 404, còn mở thẳng link khi danh sách chưa tải thì bị đẩy về `/clips`.
- **Clip tạo phía agent (🎁 Gói, 🔥 Mẫu hot, lồng tiếng) bấm vào "giật một cái" rồi về `/clips`** (26/10): danh sách `boards` của store
  đọc lúc mở app nên thiếu clip mới → wizard coi link là cũ. Giờ effect trong `QuicktoolApp.tsx` gọi `refreshBoards()` (store/board.ts)
  một lần trước khi bỏ cuộc, và **chờ refresh xong** (state `refreshing`) — `navigate` của react-router đổi identity mỗi lần URL đổi
  (`/clips/17` → `/clips/17/setup`) nên effect chạy lại giữa chừng và đẩy về `/clips` nếu không chờ.
  **31/10 vẫn dính** (bấm "Mở clip" của phần vừa cắt là về thư viện): `refreshing` là **state** → effect chạy lại trước khi state kịp cập nhật
  (StrictMode ở bản dev chạy effect 2 lần; deps đổi trong cùng một lần commit) thấy `refreshedFor === routeId` → đẩy về `/clips`. Giờ lượt
  tải đang chạy là **ref** (`refreshing.current`) + state `refreshTick` chỉ để chạy lại effect khi tải xong. Cờ "đang làm" mà effect dựa vào để
  quyết định: dùng ref, đừng dùng state. Kiểm: tạo board qua API sau khi trang đã mở rồi `pushState` sang `/clips/<id>/export`.
- **Sau "⚡ Tạo video tự động", bấm bước 1–4 bị kéo về bước 5** (bug 22/10): effect trong `QuicktoolApp.tsx` điều hướng sang
  `/export` mỗi khi `auto === "done"` mà đang ở bước khác — `auto` giữ "done" mãi nên mọi lần bấm bước đều bị kéo lại. Giờ chỉ
  điều hướng một lần lúc `auto` vừa chuyển sang "done" (`prevAuto` ref). Effect dựa trên trạng thái kéo dài: luôn so với giá trị trước.
- **Gemini TTS đọc luôn "phong cách đọc"** (bug 22/10: ô "GIỌNG HÀO HỨNG" → clip mở đầu bằng "Giọng hào hứng…"): prompt cũ
  `"<style>: <text>"`. Giờ `tts.gemini_tts_prompt()` = câu lệnh "đọc TRANSCRIPT, đừng đọc ghi chú" + khối `### DIRECTOR'S NOTES`
  + khối `### TRANSCRIPT`. Đo thật bằng Gemini chép lại: cách cũ đọc lẫn 2/3 câu, cách mới 0/3. **Cache giọng theo khoá
  `_cache_key`** — đổi prompt Gemini thì tăng `GEMINI_PROMPT_VERSION` (đang "v2"), không thì "Ghép lại" vẫn dùng file cũ.
- **Bộ test từng đọc file key thật `~/.flowboard/secrets.json` và gọi AI thật** (dính 22/10: route tạo clip gọi `run_llm` → test
  chạy 97 s, kết quả lệ thuộc AI). `conftest.py` giờ đặt `FLOWBOARD_SECRETS_PATH` vào thư mục tạm; test cần cấu hình thì tự ghi file.
- **Mẫu clip viết cứng chi tiết của một món điển hình** (fast_food_ad: "melted cheese", "lifts the top bun") → áp cho cơm cháy ra
  prompt burger. Đừng sửa từng JSON: `script_tailor` viết lại theo sản phẩm (xem Chỗ cần biết).
- **Gọi agent qua `localhost` trên Windows mất ~200 ms mỗi lần** (agent chỉ nghe IPv4 `127.0.0.1`, Node/curl thử `::1` trước):
  proxy Vite trỏ `localhost:8434` làm mọi API chậm thêm ~200 ms (24/10: `/api/health` 209 ms → 4 ms). `vite.config.ts` giờ dùng
  `127.0.0.1`; script/curl thử nghiệm cũng nên dùng `127.0.0.1` (lưu ý cookie đăng nhập gắn theo host). Ngược lại Vite chỉ nghe
  `localhost`: mở `127.0.0.1:5174` thì chờ ~2 s.
- **Neon: mỗi câu truy vấn ~44 ms từ máy nhà**; mỗi request còn tốn lượt mở/đóng transaction. `pool_pre_ping` (thêm 1 lượt mỗi
  request) đã thay bằng `_ping_when_idle` (`db/session.py`): chỉ ping kết nối ngồi yên > `IDLE_PING_S` (60 s), ping lỗi →
  `DisconnectionError` → pool lấy kết nối mới. Test `test_db_idle_ping.py`.
- **Hai PATCH cùng một node chạy song song thì mất một cái** (agent đọc → gộp → ghi cả `data`): bấm nhanh nhiều tuỳ chọn Bước 5
  lưu sai (24/10). `api/client.ts patchNode` giờ xếp hàng theo node (cùng node chạy lần lượt, node khác vẫn song song).
- `PATCH /api/boards/{id}` gộp `data` một cấp (để lưu `step` không xoá `template_id`/`product_id`).
- **Frontend bỏ mọi trường `node.data` không có trong danh sách** khi tải board (`store/board.ts`, 3 chỗ map `n.data[...]`
  + kiểu `FlowboardNodeData`): thêm trường mới lưu trên node thì phải thêm vào cả 3 chỗ, không thì F5 là mất (dính 22/10 với `lastRequest`).
- **Viết lại prompt bằng LLM hay làm mất tên sản phẩm** (thay "Women's short-sleeved round-neck t-shirt" bằng "the product" → Flow vẽ
  áo vest, thấy thật 22/10). Mọi system prompt viết lại phải dặn giữ nguyên mô tả sản phẩm (`_REVISE_SUFFIX` có câu VERBATIM).
- **Hàng tài khoản Flow từng tự "chuyển nhầm" sang project của tài khoản Google khác** (dính 22/10, nguyên nhân lớn nhất của
  chuỗi timeout): `account_pool._CREDIT_ERROR` dò chữ `credit`/`paygate` → khớp `FLOW_DROPPED_JOB` ("… refunded the credits") →
  `mark_exhausted(email, 0)` → job sau `ensure_credits` ghim project của tài khoản kế (hoangduytn173, `dfba8ba8`) trong khi tab Flow
  vẫn là HoangDuyTN1703 → mọi ảnh/video gửi vào project lạ, video bị bỏ hết. Thêm: từ khi có đăng nhập, `on_account_read` lúc
  extension kết nối (trước khi login) bị bỏ qua nên credit thật không bao giờ ghi đè con số 0. Đã sửa: `is_credit_error()` hẹp
  (insufficient / not enough credit / quota exceeded / resource_exhausted…, loại trừ FLOW_DROPPED_JOB / refund / timeout / paygate_tier),
  `account_pool.after_login()` (hook `after_activate`) phát lại lần đọc tab Flow cuối, số dư ≥ `REVIVE_CREDITS` (50) xoá cờ exhausted.
  **Thấy timeout hàng loạt: xem `GET /api/auth/pool` (pinned_project_id, exhausted) trước khi nghi gì khác.**
- **Video "Timed out" thường KHÔNG phải Flow chậm mà là Flow bỏ lượt** (22/10, đo thật): Flow nhận lệnh Omni, trả operation id,
  rồi bỏ không báo — poll `jwpduf` trả "Media not found." từ đầu đến cuối, job không bao giờ vào listing, credit được hoàn. Chạy
  cùng ảnh trong giao diện Flow thì Flow nói rõ: "câu lệnh có thể vi phạm chính sách về video liên quan đến **người nổi tiếng**".
  **Có gương mặt bị Flow chặn thật**: mặt "#rm60" bị bỏ 5/5 lần trong đúng project (chân dung lẫn ảnh cảnh, Omni lẫn Veo), cùng
  prompt với mặt khác thì ra video ~60 s. Nhưng các "mặt mới bị chặn" chiều 22/10 (7 mặt) là **kết quả sai do ghim nhầm project**
  (xem mục trên) — chạy lại trong đúng project thì 4/4 mặt mới đều qua. Mặt bị chặn thì mọi cảnh có người đó đều chết; vẽ lại ảnh "không lộ mặt" **không đủ** (cảnh 3 cắt mặt
  vẫn bị bỏ; "từ cằm xuống" bị vẽ thành không mặc quần → dính bộ lọc khác) — đừng làm nút tự sửa kiểu đó. Cách đúng: kiểm tra người
  mẫu trước (nút "🎬 Kiểm tra với Flow", xem Chỗ cần biết) rồi đổi mẫu nếu bị chặn. Thư viện có mẫu "Lisa" mô tả "like Lisa of
  blackpink" — chắc chắn bị chặn.
  **Omni 4 s bị Flow bỏ** (cùng ảnh/prompt: 4 s bỏ sau 52 s, 8 s ra sau 68 s; mới thử 1 lần) — dùng 8 s. Thăm dò: `GET /api/flow/operations/{op}/lookup`, `/inflight`, `/listing` (`routes/flow_debug.py`).
  Tab Claude in Chrome là profile khác (akiragosho2000); project của extension mở được bằng `flow.google.com/u/5/project/<id>`.
- **Ảnh sản phẩm lấy từ shop có mặt người mẫu thật → Flow bỏ video** (đo thật 26/10): ảnh shop Đầm Bầu (2 mặt người mẫu Hàn +
  logo + chữ "OOTD") làm nguyên liệu Omni → lần 1 bị bỏ (42 s), lần 2 cùng ảnh/prompt lại ra (33 s) — chặn **không đều**. Ảnh mẹ bầu AI
  vẽ (có mặt) ra ngay 33 s. Tệ hơn: ảnh sản phẩm là tham chiếu của **mọi ảnh cảnh**, mặt người mẫu shop lọt vào cảnh → video cảnh nào
  cũng dễ bị bỏ (rid 211 lúc 16:07 chờ hết 5 phút rồi thử lại). Cách xử lý: Bước 1 cảnh báo + "✨ Tạo ảnh chỉ có sản phẩm" (xem Chỗ
  cần biết). Preset người mẫu cũ ghi thẳng "K-pop idol styling" / "flawless porcelain" — kéo mặt về kiểu idol; đã bỏ.
- **Sửa file backend trong lúc có job Flow chạy = mất job** (26/10): agent chạy `--reload` → khởi động lại → job đang chạy thành
  `agent_restart_lost`. Kiểm `/api/history?status=queued,running` trống rồi mới sửa file trong `agent/`.
- **Nhịp poll video Flow (đo 26/10)**: clip Flow giữ thì có trong danh sách project ngay vòng poll đầu (~10 s), có link video sau ~33 s.
  Bị bỏ có 2 kiểu: (a) vào danh sách rồi media thành NOT_FOUND → `DROP_DETECT_ROUNDS` bắt sau ~40 s; (b) **không bao giờ vào danh
  sách** → trước đây chờ đủ 5 phút, giờ `NOT_LISTED_DROP_S` (90 s, ≥ 2 lần tra danh sách rỗng) báo `FLOW_DROPPED_JOB` → worker thử lại ngay.
- **`_voice_clip` với clip không có tiếng và không có lời thoại làm ffmpeg lỗi "Error binding filtergraph"** (thấy 26/10 khi viết test
  ghép clip Muse): chỉ số luồng `anullsrc` tính bằng `len(inputs) // 2 - 1` sai khi input lavfi 4 token / có `-ss -t`. Giờ đếm `inputs.count("-i")`.
  Trước đây dính khi cắt cảnh (Bước 5) một clip câm không có lời thoại.
- `Product.media_ids` là media id của **Flow**, thuộc project lúc upload; ảnh gốc nằm trong `storage/media` (đổi project thì `media_project_sync` upload lại).

- **Clip 4 cảnh từ link mất hơn 30 phút** (7/11, áo khoác có quạt, clip #67): (1) ô **"Mượt 60 fps"** chạy `minterpolate` trên CẢ clip đã ghép
  sau cùng — **minterpolate chỉ dùng 1 nhân**, ~14 s xử lý cho mỗi giây video → 8 phút 49 s cho clip 32 s (ghép lần đó 10 phút 18 s, giọng VieNeu thêm ~1,5 phút
  vì nạp model lại cho từng cảnh); (2) **nút "Ghép" bấm 2 lần** → 2 request export giống hệt cách nhau 80 ms (nút chỉ khoá khi request đã vào hàng, còn lúc nối
  cạnh thì chưa) → lượt 2 làm lại từ đầu, trang theo dõi lượt 2 nên vẫn "Đang ghép"; (3) agent chạy từ phiên Claude Code (`run_in_background`) **chết theo phiên**
  khi phiên đó đóng (03:12, giống start127 20:39 — log không có lỗi nào). Sửa (1)(2) xem "Chỗ cần biết" → "Ghép nhanh"; (3): người dùng nên tự chạy `.\start.ps1`.
  Đo lỗi chậm: bảng `request` (created_at / finished_at) + các file trung gian `media/export_*.mp4` (giờ ghép xong) so với giờ request xong.
- **Đo "phần sót" của logo bằng nền lấp từ xung quanh là KHÔNG tin được trên nền nhiều vân / mép cứng** (7/11): số đo nói chăn len tệ đi, ảnh phóng to cho thấy
  bản mới sạch nhất; xu hướng "logo màu xám 227" cũng do lấp nền qua mép. Mọi thay đổi bộ xoá logo: so **ảnh phóng to trước / sau trên nhiều clip thật**
  (script đo + ghép ô góc theo thời gian), số đo chỉ để tìm khung đáng xem. Clip Flow mẫu trong `media/` (tên uuid) + `media/clean/`.

- **Clip trông "máy móc" là do prompt viết kiểu chụp quảng cáo studio** (7/11, người dùng: "video review từ link SP… máy móc quá"): cả 8 mẫu clip ghi
  "editorial photo", "soft even studio lighting", "Locked-off camera", người mẫu "holds the pose" rồi cười / vẫy / giơ ngón cái vào ống kính, lời thoại đọc
  thông số ("Mọi người ơi, đây là…"); `script_tailor` còn bắt chép nguyên văn các câu đó. Thêm 2 lỗi: phong cách mặc định "Clean Girl" (son bóng, khuyên tai
  vàng) gắn cho cả **người mẫu nam**, và kịch bản viết "she" cho người mẫu nam (tailor không biết giới tính). Đọc hướng dẫn prompt UGC cho Veo / Flow rồi viết
  lại hết theo `services/clip_style.py` (xem Chỗ cần biết). **Viết prompt cảnh mới: đọc `clip_style` trước, đừng dùng chữ studio / editorial / cinematic /
  flawless / locked-off, đừng cho người mẫu nhìn ống kính tạo dáng, đừng viết "slowly"** (Veo ra quay chậm, giật ở 24 fps).
- **Lồng tiếng dịch Google làm hỏng tên riêng** (7/11, người dùng: "việt hóa mạnh quá… tên các nhân vật nổi tiếng cũng bị việt hóa, đọc sai"): video tiếng Trung
  "thoát khỏi thiên hà" — Whisper nghe 爱因斯坦 thành 安音斯坦 → Google ra "Anyinstein"; 洛希极限 → "Losey", 奥尔特云 → "Ultra Cloud", 比邻星 → "Billing Star",
  旅行者一号 → "Du hành 1", còn hành tinh để tiếng Anh ("Mercury", "Neptune") thay vì Sao Thủy / Sao Hải Vương; giọng VieNeu đọc các chữ đó sai. Google không biết
  ngữ cảnh — sửa bằng gợi ý tiêu đề cho Whisper + một lượt Gemini rà tên riêng + bảng cách đọc (xem Chỗ cần biết → "Tên riêng khi lồng tiếng").
- **Vỏ app Tauri chỉ build được trên CI** (máy nhà không có Rust): lỗi biên dịch chỉ thấy ở log Actions — `gh run view <id> --log-failed`
  (máy nhà đã `gh auth login` 7/11; trong phiên Claude Code chạy `echo "" | gh auth login -h github.com -p ssh --skip-ssh-key -w` ở nền để lấy mã 8 ký tự,
  vì `! gh auth login` kiểu hỏi-đáp không chạy trong khung chat). Lần đầu lỗi E0597: `if let Ok(mut g) = state.child.lock() { … }` ở cuối hàm — guard tạm sống
  lâu hơn `state` (`app.state::<T>()`); lấy giá trị ra trước (`let child = state.child.lock().ok().and_then(|mut g| g.take());`). Một vòng build ~13 phút. Lần 2 (tag v0.1.2, 7/11) lỗi E0433
  "cannot find `serde_json`" ở `tauri::generate_context!()`: có config plugin (updater) / capability remote thì macro sinh code dùng `serde_json` → crate phải có
  `serde_json` trong `[dependencies]` (template Tauri luôn có, mình đã bỏ).
- **Tauri: trang nạp từ ngoài (remote, ở đây `http://127.0.0.1:8434`) gọi lệnh riêng của app bị "Command dflow_check_update not allowed by ACL"**
  (8/11, app 0.1.2 + 1.5.0: nút "Kiểm tra cập nhật" báo lỗi đó): mã Tauri (`crates/tauri/src/webview/mod.rs`) kiểm ACL cho lệnh plugin, khi app có manifest ACL,
  **hoặc khi trang không phải local** — "remote content can never reach custom commands unless an explicit `remote` capability has been configured for them".
  Chỉ ghi `remote.urls` trong capability là chưa đủ: phải khai lệnh trong `build.rs` (`tauri_build::Attributes::new().app_manifest(AppManifest::new().commands(&[…]))`,
  sinh quyền `allow-<lệnh-gạch-nối>` vào `src-tauri/permissions/autogenerated/`, đã gitignore) rồi liệt kê quyền đó (không tiền tố) trong `permissions` của capability.
  Tài liệu chỉ nói "mặc định mọi lệnh được phép" (đúng cho trang local). Hệ quả: app 0.1.2 và 1.5.0 **không tự cập nhật được** — phải cài tay 1.5.1 một lần.
  Không build / chạy Rust trên máy được, nên lần sau thêm lệnh Tauri mới: thêm vào `build.rs` + `ui.json` cùng lúc.
- **Checkbox ẩn `position: absolute` mà ô chứa không `position: relative` → bấm vào là CẢ TRANG cuộn, app bị đẩy lên, lộ nền đen** (8/11, bảng
  📦 Gói & tính năng, người dùng chụp màn hình): input ẩn tính toạ độ theo trang (không nằm trong vùng cuộn `.qt-content`) nên kéo dài trang ra; bấm nhãn = focus
  input → trình duyệt cuộn trang tới nó (thêm cột gói càng nhiều càng xa). Sửa: ô chứa `position: relative` + input `inset: 0`. Cùng lỗi tiềm ẩn ở `.cc-radio`
  (Edit auto CapCut) — đã sửa luôn. Kiểm: `document.scrollingElement.scrollTop` phải luôn 0 và `scrollHeight == innerHeight` (app tự cuộn bên trong).
- **Bảng tràn khung khi cửa sổ app hẹp dù đã có `@media`** (8/11, người dùng: "trên app thu nhỏ lại mà mất 1 khúc"): bảng tài khoản / bảng giá / lịch sử
  giao dịch là lưới cột cố định, `@media (max-width: …)` tính theo **cửa sổ** nên lệch với chỗ thật của thẻ (sidebar 280 px, app thu nhỏ) → tràn ở ~1024–1366 px.
  Giờ dùng **container query** (`container-type: inline-size` trên `.acc-table`, `.bill__requests`, `.bill__terms`, `.me-tx`, `.me` + `@container (max-width: …)`).
  **Bẫy kèm**: khối `@container` phải đứng **sau** quy tắc gốc của phần tử trong file CSS (cùng độ ưu tiên → quy tắc sau thắng; dính với `.bill__term`). Mỗi hàng
  `.acc-row` là một lưới riêng → đừng dùng `max-content` cho cột (mỗi hàng một bề rộng, cột lệch). Quét bằng Playwright `e2e/acc_layout.js` (14 cỡ 1920 → 600 px:
  trang cuộn ngang, phần tử thò ra ngoài thẻ, chữ bị cắt trong nút, khoảng trống bên phải).
- **App desktop (WebView2 của Tauri) không hiện `window.confirm` / `window.prompt`** (7/11, người dùng: "tạo bài xong… không post được"): hàm trả về false
  ngay, không hiện gì → mọi nút có hộp hỏi im lặng không làm gì ("🚀 Đăng ngay" chưa từng gửi request nào; nút xoá 2 bước thì chạy). Giờ **không dùng
  `window.confirm` / `window.prompt` nữa**: `components/Dialogs.tsx` `askConfirm(msg, {ok, cancel, danger})` / `askText(msg, value)` (Promise, hộp riêng của app,
  `DialogHost` gắn ở `App.tsx`, z-index 1300, Enter = đồng ý, Esc = huỷ) — đã thay cả 41 chỗ. Code mới: `if (!(await askConfirm("…"))) return;` trong hàm async.
  Dò lỗi kiểu này: `agent.log` của app (`<DFlowData>\logs`) — bấm nút mà không có request nào là lỗi phía giao diện.
- **Postgres 16+ (Neon): role vừa tạo bằng CREATEROLE chỉ cho người tạo quyền ADMIN, không SET / INHERIT** (8/11 khuya, Phase C: `CREATE SCHEMA … AUTHORIZATION` báo
  "must be able to SET ROLE"; `pg_has_role(…, 'MEMBER')` vẫn trả true nên kiểm kiểu đó là sai): phải `GRANT role TO current_user WITH INHERIT TRUE, SET TRUE` (kiểm bằng
  `pg_has_role(current_user, role, 'SET')` + `'USAGE'`). Cũng vậy: **`CREATE SCHEMA IF NOT EXISTS` kiểm quyền CREATE trên database TRƯỚC khi xem schema có chưa** → role
  của tài khoản (không có quyền đó) chạy `init_db` cũ là lỗi dù schema đã có — `init_db` giờ hỏi `pg_namespace` trước.
- **Backblaze B2 đầy gói miễn phí → mọi lượt đẩy file lỗi "Cannot upload files, storage cap exceeded"** (thấy 8/11 khuya khi thử Phase C: bucket 410 file / **10,40 GB**,
  toàn bộ của akiragosho; B2 cho 10 GB miễn phí rồi dừng ở mức "cap" đặt trong tài khoản). Không phải lỗi chữ ký. Sửa: Backblaze → Caps & Alerts nâng mức trần (giá ~$6 /
  TB / tháng) hoặc dọn file lớn (video lồng tiếng / ghép cũ); `GET /api/cloud/status` → `upload_errors`, `last_error` cho thấy.
- **Ảnh / video cũ 404 trong app (hoặc máy mới)**: chỉ là file chưa từng lên B2 (B2 trả 403 cho key không có → `download_errors` ở `GET /api/cloud/status`), không
  phải lỗi app; trên máy nhà chúng nằm ở `storage/accounts/akiragosho/media` của repo. Muốn app thấy: đặt Thư mục dữ liệu (Cài đặt → 🖥 Máy này) = thư mục
  `storage` của repo (app và start.ps1 không chạy cùng lúc nên dùng chung được) hoặc chép thư mục media sang.
- **Thử bản cài (`dflow-agent.exe`) trên máy người dùng: đừng `taskkill /IM dflow-agent.exe`** — app DFlow đã cài chạy agent cùng tên; dừng theo PID / cổng (bản thử
  chạy cổng 8534 / 8455). (8/11 khuya: lệnh như vậy bị chặn quyền đúng lúc.)
- **CI: github.com/<owner>/<repo>/releases/download trả 504 hàng giờ dù trang status GitHub báo "All Systems Operational"** (8/11 khuya, build 1.7.0 chết 2 lần ở bước tải ffmpeg (BtbN) rồi bước bundler Tauri tải NSIS + nsis_tauri_utils). Đường API `api.github.com/repos/<o>/<r>/releases/assets/<id>` + `Accept: application/octet-stream` vẫn chạy. Workflow giờ: ffmpeg thử BtbN rồi gyan.dev (4 lần, chờ tăng dần), bước "NSIS toolset (prefetch)" (`continue-on-error`) tải NSIS 3.13 + nsis_tauri_utils v0.5.3 qua API asset, kiểm SHA1 đúng như bundler (tauri-cli 2.12.4) rồi đặt vào `%LOCALAPPDATA%\tauri\NSIS` (bundler thấy có sẵn thì không tải nữa), bước Tauri thử 3 lần. Đổi bản tauri-cli thì xem lại SHA1 / tên file trong `tauri-bundler/src/bundle/windows/nsis/mod.rs`. Trong PowerShell 5 đừng dùng `gh --jq` có dấu ngoặc kép (bị bỏ) — dùng `Invoke-RestMethod`. Tag chưa phát hành thì dời tag sang commit sửa là được (`git tag -f vX && git push -f origin vX`).
- **Hành động chính của một danh sách phải là NÚT CÓ CHỮ, không phải "bấm vào tên"** (9/11, người dùng: "mẫu đã lưu chưa đúng ý… add mẫu đó vào nó ko apply đúng"): popover ★ Mẫu chỉ áp mẫu khi bấm vào tên mẫu, nút chữ duy nhất bên cạnh là "Mặc định" → log agent cho thấy người dùng mở popover 5 lần, bấm "Mặc định" 2–3 lần mỗi lần (bật / tắt), **không một lần** `POST …/use` (áp) — rồi tự làm lại tay (tải nền, render). Thêm nút "✓ Áp dụng" + tooltip nói "Mặc định" không đổi clip đang mở; và mẫu mặc định phải tới được mọi đường tạo video (cắt video trước đó không nhận). Dò lỗi kiểu này: đếm request theo route trong `agent.log` thay vì đoán.
- **Heredoc của Bash (Git Bash trong Claude Code) nuốt một lớp `\\`** (10/11): script Python dán qua `python - <<'EOF'` có `\\n` / `\\s` bị đổi thành xuống dòng thật / `\s` → vá sai hoặc assert không khớp; file CRLF (nhiều file `.tsx` / `CLAUDE.md`) cũng làm chuỗi nhiều dòng không khớp. Cách làm: ghi script bằng Write vào scratchpad rồi chạy, script tự đổi CRLF → LF trước khi so và trả lại khi ghi; sửa nhỏ thì dùng Edit.
- **`yt-dlp --match-filter` từ chối video mà vẫn thoát mã 0, có lúc không in gì** (10/11, Windows, khi kèm `--print`): "thoát 0 mà không có file" + đang có giới hạn thời lượng = video dài quá (`reference_video._run_ytdlp`), đừng chỉ dò chữ "does not pass filter".
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

- **Giọng đọc miễn phí như VieDub: VieNeu + FPT.AI** (27/10, người dùng: "tool này làm giống pyvideotrans được không, tiết kiệm được
  nhiêu thì tiết kiệm"): `tts.py` có 4 họ giọng — `voice_kind()` edge | vieneu | gemini | fpt; `voice_groups()` trả cả 4 kèm `available` + `reason`.
  **VieNeu-TTS v3 Turbo** (`VIENEU_VOICES`, id `vieneu:<Tên>`, 25 giọng 3 miền, đúng gói `vieneu` VieDub dùng): chạy bằng venv pyvideotrans qua
  `dub_runner.py vieneu <giọng> <lines.json>` (ONNX/CPU như VieDub; nạp model ~20–30 s rồi ~0,5 s cho mỗi giây giọng) — `tts._synth_vieneu_many`
  gửi **nhiều câu một lượt** (model nạp một lần), `tts.synthesize_many()` dùng ở `dub._voice_pieces` (phase "Đang tạo giọng đọc VieNeu (N câu)")
  rồi từng câu là cache hit; nghe thử / Bước 5 một câu thì nạp model mỗi lần (~23 s). File cache `.wav` như Gemini (`_audio_name`, `_cached`,
  `_finish` dùng chung). **FPT.AI TTS v5** (`FPT_VOICES`, id `fpt:<code>`, Ban Mai…): key `secrets.apiKeys.fpt` (theo tài khoản như key Gemini),
  `GET/PUT /api/llm/fpt-key`, `_synth_fpt` (POST → poll link `async`, 120 s); Cài đặt → tab Gemini key có mục "FPT.AI" (`GeminiKeysSection.FptKeySection`).
  Frontend: `client.fetchVoiceGroups()` (`GET /api/llm/voices`, một lần) điền `VOICES`; hook `useVoiceGroups()` + `<VoiceOptions>` (`VoiceField.tsx`)
  dùng ở VoiceField, Bước 5 (giọng chung + từng nhân vật), Bước 2 (giọng từng cảnh); họ không dùng được thì option mờ + lý do trên nhãn nhóm;
  `VOICE_GROUPS` tĩnh chỉ là dự phòng. Thử thật 27/10: nghe thử Ngọc Huyền 23 s; lồng tiếng clip mẫu 12,6 s giọng Hải Đăng 53 s, không tốn gì.
  Tốc độ (`rate`) không áp cho VieNeu/FPT (dub tự ép bằng atempo). Chưa thử FPT thật (chưa có key).
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
  - "⚡ Tạo video tự động" hỏi confirm (số ảnh/video, credit, phút). Thư viện (29/10: mọi clip tick được, kể cả đã ghép; hàng "Chọn tất cả (N)" + "🗑 Xoá N clip" bấm 2 lần, xoá lần lượt qua `deleteBoardById`; "Chạy" chỉ nhận clip chưa ghép; xoá clip = xoá board + snapshot lồng tiếng của nó, video đã xuất trong media/ không mất) có checkbox trên thẻ + "Chạy N clip / "Chạy tất cả N clip dở" → `runQueue(boardIds)` (`store/quicktool.ts`, chạy tuần tự `switchBoard`
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
    (`/api/prompt-library`, lưu trùng text = trả bản cũ **+ gộp nhãn mới**, `/use` đếm lượt), bước 2 mỗi ô có "★ Lưu" /
    "📚 Chọn prompt" (`quicktool/PromptLibraryButtons.tsx`), trang `/prompts` sửa tại chỗ.
  - **Prompt theo ngành + loại cảnh** (23/10): nhãn là chữ trong `SavedPrompt.tags` (cùng từ với prompt mẫu), định nghĩa ở
    `quicktool/promptTags.ts`: ngành `INDUSTRY_TAG` (fashion→"thời trang", cosmetics→"mỹ phẩm", food→"đồ ăn", grocery→"tạp hoá",
    home→"gia dụng", other→"khác", + "mọi ngành"), loại cảnh `SCENE_TAGS` (hook, chi tiết, demo, mở hộp, chốt đơn, chỉ tay, hội thoại).
    `sceneTagOf(title, index, count)` đoán loại cảnh từ tên cảnh của template ("Cảnh 3 - Cận kết cấu" → chi tiết), không ra thì cảnh
    đầu = hook, cuối = chốt đơn. Bước 2 (`StepScript` nhận `category` = ngành của sản phẩm, không có thì `qt.reference.category`
    / ngành của template): "📚 Chọn prompt" → `groupPrompts()` chia **Hợp nhất** (cùng ngành/mọi ngành + cùng loại cảnh) → **Hợp ngành ·
    cảnh khác** → **Chưa gắn ngành** → ngành khác ẩn sau nút "Xem cả N prompt ngành khác". "★ Lưu" tự gắn nhãn ngành + loại cảnh.
    Trang `/prompts`: lọc theo ngành (có "Chưa gắn ngành") + loại cảnh, Thêm nhanh chọn ngành + loại cảnh, mỗi thẻ sửa nhãn
    (chip cam = ngành, tím = loại cảnh, × bỏ, "+ nhãn" thêm / nhãn tuỳ ý). Prompt cũ lưu trước 23/10 không có nhãn → nhóm "Chưa gắn ngành".

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
  để component giữ state thông báo rồi bật toast), `components/Toaster.tsx` (một chồng ở **góc dưới trái** — 10/11 đổi từ góc phải trên vì che nút đang bấm —, tối đa 4, z-index 1200
  trên mọi hộp thoại; mỗi toast có nhãn Lỗi/Lưu ý/Thông báo/Thành công, thanh đếm ngược, rê chuột thì giữ lại, nút ×; **mọi toast chỉ
  1,5 s** (`TOAST_MS` trong `store/toast.ts`, tuỳ chọn `duration` của nơi gọi bị bỏ qua — rê chuột để đọc câu dài); lỗi trong các store board/chat/generation/pipeline vẫn tự lên toast lỗi). **Quy ước: kết quả
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
  `PATCH /api/references/{id}` nhận thêm `media_id` / `aspect_ratio` / `ai_brief` (đổi ảnh xoá ai_brief cũ; ảnh trùng mục khác vẫn cho).
  **⧉ Nhân bản** (23/10) trên thẻ: `POST /api/references/{id}/clone` chép nguyên (ảnh, tên, meta, tags), **không bắt trùng**, bản sao
  lên đầu danh sách và mở luôn form sửa bản sao. Vì vậy `Reference.media_id` **không còn unique** (`db.ensure_reference_media_id_not_unique`
  đổi index unique của DB cũ thành index thường, chạy trong `init_db`, SQLite + Postgres). `POST /api/references` vẫn idempotent theo
  media_id (★ Lưu ở bước 1 không lưu đôi) — muốn có bản thứ hai thì dùng clone.
  Thẻ người mẫu: cả thẻ bấm được (Enter/Space cũng mở) → form sửa; ▶ nghe thử, "Mở clip gốc", ⧉ Nhân bản, nút Xoá đỏ
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
- **Hộp Cài đặt = tab bên trái** (25/10, thay bố cục 2 cột dài ~2.700 px; 7/11 thêm tab **🤖 AI viết** = `AiProvidersSection` — trước đó chỉ có ở thanh công cụ Canvas đã ẩn, nên sau lần chọn AI đầu tiên không đổi được): `SettingsPanel.tsx` `TABS` — 🎬 Tạo ảnh & video (Model
  video, Model ảnh, Nguồn tạo ảnh — **đều là `<select>`**, chỉ hiện mô tả của mục đang chọn; model "chỉ Ultra" là option disabled khi
  gói Pro), ⚡ Google Flow (Project + chip "Gói Pro/Ultra", Tài khoản Flow, Danh sách tài khoản tự chuyển, Đăng xuất Flow), 🔑 Gemini
  key, ☁ Dữ liệu, ℹ Thông tin (chấm xanh khi có bản mới). Tab nhớ trong localStorage `flowboard.settings.tab`; hộp cao cố định
  `min(680px, 100vh-64px)`, chỉ phần nội dung cuộn (`.settings-panel--tabs`, `__body`, `__nav`, `__tab`, `__content`, `__select`,
  `settings-field`). `ImageProvidersSection`: select + ô key **chỉ cho nguồn đang chọn** — chọn nguồn chưa có key thì chỉ hiện ô dán key,
  lưu key xong mới chuyển sang nguồn đó. Đoạn hướng dẫn dài của 2 mục tài khoản Flow gập trong `<details class=settings-panel__more>`.
  ≤ 760 px: tab thành hàng ngang trên đầu.

- **Trạng thái đang tải / trống của trang** (23/10): `quicktool/PageState.tsx` — `PageLoading` (vòng xoay cam + chấm sáng, chữ ở giữa,
  hiện sau 150 ms để tải nhanh không bị nháy) và `PageEmpty` (icon tròn, tiêu đề, gợi ý, nút hành động), căn giữa trang
  (`.qt-pagestate`, min-height 58vh; `compact` cho modal/lọc rỗng). Đã dùng ở Sản phẩm (tải / chưa có / lọc rỗng), Người mẫu (chưa có),
  Prompt (tải / chưa có), Lịch sử (chưa có / lọc rỗng), Clip của tôi (chưa có, "Đang mở clip…"). Lưới clip / người mẫu / lịch sử vẫn
  dùng skeleton khi tải. **Trang mới: dùng hai component này, đừng viết dòng "Đang tải…" nhỏ.**
- **Hệ nút Quicktool** (26/10, `quicktool.css` `.qt-btn*`): nút thường = nền gradient sáng `#2c313d→#252a35` + viền `#3a4050` + chữ trắng
  15px (trước là nền đen mờ hoà vào panel), hover viền cam; `--accent` cam gradient + bóng cam; `--ghost` viền rõ, nền trong; `--danger`
  nền đỏ nhạt viền đỏ, hover đỏ đặc; `--small` 14px (7×12), `--big` 16px. `.qt-link` 13px đậm, gạch chân khi hover. `.project-modal__btn`
  (styles.css, dùng chung Canvas) cùng kiểu nút thường; trong `.qt-app` nút `--primary` thành cam (trước tím `--accent` của Canvas).
  `.qt-chip` sáng hơn, chip đang chọn chữ trắng đậm. Nút Xoá dạng chữ (`qt-link--danger`) ở Bài đã lưu, thẻ prompt, "Bỏ" prompt ảnh →
  `qt-btn--small qt-btn--danger` ("🗑 Xoá"). **Nút mới: dùng `.qt-btn` + biến thể, đừng tự đặt nền tối.**
- **Khung focus** (21/10, cuối `styles.css`): bấm chuột không còn viền trắng của trình duyệt (`:focus { outline: none }`);
  bàn phím (Tab) có quầng cam mờ `:focus-visible { box-shadow: 0 0 0 2px rgba(255,106,43,.45) }`. Ô nhập giữ kiểu viền riêng.

- **"Tạo lại…" có ô yêu cầu** (22/10, bước 3 ảnh + bước 4 video, `quicktool/steps/StepMedia.tsx` `RegenBox`): cảnh đã có
  ảnh/video thì nút "Tạo lại…" mở ô "Muốn … khác thế nào?" (gõ tiếng Việt, 5 gợi ý nhanh mỗi loại, Ctrl+Enter) với "✨ Tạo lại theo yêu
  cầu" / "Tạo lại y như cũ" / "Huỷ". Theo yêu cầu → `POST /api/prompt/revise {node_id, request, current}` (`prompt_synth.revise_prompt`,
  `_REVISE_SUFFIX`, giữ câu bảo vệ sản phẩm, tối đa 1200 ký tự) → lưu `prompt` mới + `prevPrompt` + `lastRequest` lên node → tạo lại
  (`generateScene/generateVideo(index, request)` trong `store/quicktool.ts`, helper `reviseNodePrompt`). Ô hiện "Lần trước đã yêu cầu …"
  và "↺ Về prompt trước đó" (chỉ đổi prompt, chưa tạo).

- **Video chạy song song** (22/10, `worker/processor.py`): `WorkerController` vẫn một hàng, nhưng `PARALLEL_TYPES` (`gen_video`,
  `gen_video_omni`) được tách thành task riêng, tối đa `FLOWBOARD_VIDEO_PARALLEL` (mặc định 3) cùng lúc; `active_count` = đang chạy +
  đang chờ slot. Thử thật: 3 video bắt đầu cùng 07:53:40, xong cùng 07:59:47 (trước đây nối đuôi ~6 phút mỗi cái). Ảnh: 2 cái một lúc từ 26/10 (`IMAGE_PARALLEL_TYPES`).
  Job lỗi/timeout của loại có media giờ ghi `node.data.error` (trước chỉ ghi trên request → F5 thấy "lỗi:" trống).
  Bước 4: video timeout hiện "Flow bỏ lượt này" + hộp `.qt-dropped` (`FLOW_DROPPED_VIDEO` trong `store/generation.ts`, nhận cả
  `timeout_waiting_video` / `FLOW_DROPPED_JOB` / chữ "Timed out" cũ) gợi ý tạo lại / đổi ảnh cảnh / dùng video của bạn.
  **Giá Omni Flash 8 s = 12 credit** (Flow báo + trừ thật 22/10, trước ghi 25): `flow_sdk.OMNI_FLASH_CREDIT_COST = {4:6, 6:9, 8:12, 10:15}`
  (4/6/10 s là ước 1,5 credit/s), `account_pool` dùng chung bảng này, frontend `settings.ts` + `roles.creditsPerClip`.

- **"🎬 Kiểm tra với Flow" cho người mẫu** (22/10, `quicktool/flowModelCheck.ts`): `probeModel(mediaId)` gửi `gen_video_omni`
  8 s chỉ với ảnh người mẫu làm nguyên liệu + `max_wait_s: 150` (worker `_poll_cycles(params)`, kẹp 60–300 s) → `done` = qua
  (~12 credit, ~70 s), `timeout`/`FLOW_DROPPED_JOB` = bị chặn (hoàn credit, ~3 phút). Kết quả `flowCheck {status, at, requestId}`
  lưu trên node nhân vật (whitelist `store/board.ts`) và `meta.flowCheck` của mẫu cùng ảnh trong thư viện (`characterBadges` hiện
  "✓ Flow làm video được" / "✕ Flow chặn video" ở `/models` + picker). Bước 1: nút + dòng kết luận (`FlowCheckButton`/`FlowCheckNote`
  trong `StepSetup.tsx`). Bước 4: hộp "Flow bỏ lượt này" nói nguyên nhân là người mẫu + nút "Sang Bước 1 · người mẫu".
  (Đã thử thêm câu "original fictional person, natural everyday look…" vào `buildCharacterPrompt` rồi gỡ: mặt ra giống ảnh thật hơn.)

- **Kịch bản viết theo sản phẩm** (22/10, `services/script_tailor.py`): `POST /api/boards/from-template` có `product_id` →
  `tailor_spec()` gửi một lượt `run_llm("auto_prompt")` (tên, ngành, giá, mô tả, điểm bán, ghi chú + các cảnh của mẫu) → mỗi cảnh
  viết lại `image_prompt` / `video_prompt` (tiếng Anh, giữ mốc 0-3s/3-6s/6-8s, giữ ai có trong khung hình, bỏ chi tiết không đúng
  sản phẩm) + lời thoại tiếng Việt ≤ 24 từ có điểm bán cụ thể, câu cuối kêu gọi mua. Giữ câu bảo vệ sản phẩm
  (`restore_product_guard`) và câu `HANDS-ONLY` (tách ra trước, gắn lại sau). Body có `tailor` (mặc định true), `variant`/`variant_of`
  (N clip/1 sản phẩm → mỗi clip một góc); mô tả người dùng gõ ở ô Sản phẩm → `shown_as` (giữ nguyên văn). Lỗi/sai số cảnh →
  `TailorError` → giữ chữ của mẫu. `quicktool.tailored` lưu trên board. Hộp Clip mới tạo N clip **song song**, nút ghi "AI đang viết
  kịch bản theo sản phẩm…". Thử thật với Cơm cháy (fast_food_ad, tay nữ): 15 s, hết burger, lời thoại có giòn rụm / sốt mắm / chà bông.
  Chưa áp cho chat agent (`chat_agent.py` vẫn dùng chữ mẫu).

- **Tối ưu tốc độ 24/10**: (1) proxy Vite `127.0.0.1` (xem Bẫy); (2) ping Neon chỉ khi kết nối ngồi yên; (3) `GET /media/<id>` nhớ
  lần tải từ xa thất bại 5 phút (`media_service.recently_missed/remember_miss/forget_miss`; vẫn xem file/Asset trên máy trước,
  `ingest_urls` xoá mục nhớ khi có URL mới) — trang Lịch sử từng tốn ~0,7 s cho mỗi media không có trên máy; (4) ghép nối
  stream-copy (`video_concat._run_concat`) thêm `-movflags +faststart` (clip ghép phát được ngay, không phải tải hết). Đo qua Vite:
  `/api/boards` 356 → 121 ms, `/api/boards/2` 481 → 237 ms, Lịch sử 6,2 → 3,2 s (lần 2). StrictMode bật ở dev nên số lần gọi API
  trùng trên màn đo là gấp đôi thực tế. Bản build production chỉ nhanh hơn dev ~0,3 s/lần mở trang.

- **Nhóm "đỡ hỏng" 24/10**:
  - **Tự thử lại video bị Flow bỏ**: `worker/processor.py` — job `PARALLEL_TYPES` trả `timeout_waiting_video` hoặc `FLOW_DROPPED_JOB…`
    (`_flow_dropped`) thì gọi handler thêm 1 lần (`params["__retried"]`), lỗi khác không thử lại. Test `test_requests.py`.
  - **Tự kiểm tra người mẫu trước khi tạo video tự động**: `store/quicktool.ts runAuto` — có người mẫu mà `knownFlowCheck` chưa "ok"
    thì chạy `checkModelNode` trước khi vẽ cảnh; bị chặn → dừng, báo đổi mẫu. Nút "Tạo N video còn thiếu" (bước 4) từ chối khi mẫu đã
    biết là bị chặn. **Chưa chạy thật cả lượt tự động** (tốn credit).
  - **Viết lại kịch bản cho clip đã có**: `script_tailor.tailor_scenes` (lõi dùng chung) + `tailor_board` → `POST /api/boards/{id}/tailor
    {scenes:[{image_id, video_id}], instructions?}` (cần clip gắn sản phẩm). Lưu prompt cũ vào `prevPrompt` + `lastRequest =
    "Viết lại kịch bản theo sản phẩm"` → nút "↺ Về prompt trước đó" trong ô "Tạo lại…" hoàn tác từng cảnh (lời thoại cũ không giữ).
    Bước 2: nút "✨ Viết lại kịch bản theo sản phẩm" + ô "Muốn nhấn mạnh gì?" (`StepScript.tsx`, `tailorBoardApi`; ô nhập không điều
    khiển → `rev` đổi `key` để hiện chữ mới). Thử thật trên clip tạm: 16 s, lời thoại dùng "phơi 36 tiếng", "vị cay", "hạn dùng 6 tháng".
  - **Lưu đủ chi tiết trang sản phẩm**: `product_link._PRODUCT_SCHEMA.details` (≤ 10 dòng tiếng Việt: nguyên liệu, quy trình, size/vị,
    cách dùng, bảo quản, xuất xứ) → `page_details_note()` → `draft.notes` ("Chi tiết từ trang sản phẩm: …"); nhập từ tab giữ thêm dòng
    "Nhập từ …". `script_tailor` đọc notes. Thử thật với link Shopee Cơm cháy (17 s qua extension); sản phẩm Cơm cháy đã được thêm
    phần chi tiết vào ghi chú. Sản phẩm cũ khác chưa có (thêm từ link lại hoặc gõ tay).

- **Bước 5: thứ tự & cắt cảnh + chữ trên video** (24/10):
  - Dữ liệu trên node xuất video: `clipOrder` (id node video), `clipSkip`, `clipTrims {id: [start, end|null]}`, `overlays`
    (whitelist `store/board.ts`, kiểu `OverlaySpec`). `lib/exportOrder.exportSources` áp thứ tự/bỏ cảnh (thắng vị trí trên canvas);
    `dispatchExport` gửi `trims` (theo thứ tự clip) + `overlays`. UI `quicktool/steps/ExportEditor.tsx`: `ClipArranger` (↑ ↓, Bỏ cảnh /
    Dùng lại, "Cắt từ … đến … s"), `OverlayEditor` (mẫu: Tên sản phẩm 0–3 s trên, Giá & "👇 Bấm giỏ hàng" 4 s cuối dưới, Freeship, chữ
    tự gõ; kiểu title/price/badge/cta, vị trí trên/giữa/dưới, `start` âm = tính từ cuối).
  - Backend: worker đọc `params.trims` / `params.overlays`; `video_export.export_video(trims=, overlays=)` — có trim thì buộc đi đường
    làm từng clip (`_voice_clip(trim=)`, `-ss/-t`, `clip_window()` kẹp, tối thiểu 0,5 s); chữ in sau khi ghép, trước nhạc nền
    (`services/video_overlays.py`: `parse_overlays`, `write_overlay_ass` — ASS + `\pos`, cùng vị trí xếp chồng có tính số dòng khi
    xuống dòng, `burn_overlays`; lỗi thì giữ bản ghép, báo `overlays_error`). Test `test_export_trim_overlays.py` (có ffmpeg thật).
    Đã xem ảnh render chữ tiếng Việt trên clip thật; thử UI trên clip Cơm cháy (chặn lệnh ghép, kiểm tham số, trả tuỳ chọn về cũ).
    **Chưa ghép thật một clip có cắt + chữ qua giao diện.** Emoji (👇) libass vẽ dạng nét viền.

- **Hôm nay — giao diện bảng điều khiển** (26/10, thiết kế lại theo yêu cầu "chuyên nghiệp hơn"): `TodayPage.tsx` + `today.css` viết lại phần trình bày, logic
  tải/poll/hành động giữ nguyên. Bố cục: tiêu đề "Tổng quan hôm nay" + ngày + "N việc cần bạn xử lý" + nút Viết bài / **Clip mới** (→ `/clips/new`); hàng
  5 thẻ KPI (`Kpi`: icon, nhãn, số lớn, ghi chú; đỏ khi có lỗi, cam khi đang chạy); lưới 2 cột (trái: Đến giờ đăng, Cần xử lý, Clip đang làm dở — phải: Đang chạy,
  Đã ghép chưa tải); mỗi khối là `Section` (icon + tiêu đề + số đếm + nút), **khối trống thu thành một dòng "✓ Không có…"**, không còn thẻ lớn rỗng. Icon là
  SVG nét (`ICONS` trong file, không emoji). Hàng danh sách `.qt-today__list li` đổi sang đường kẻ ngăn (dùng chung với `DueList` của Lịch đăng — đã xem lại trang
  `/schedule`). Tiền tố class mới `td-*`. Đã chụp Playwright 1635 px và 900 px; **chưa xem được hàng có dữ liệu** (lúc chụp không có clip lỗi / việc đang chạy).

- **Trang "Hôm nay" + tải hàng loạt** (24/10): `/today` là **trang mở đầu** (`App.tsx` `/` → `/today`; sidebar mục đầu "📋 Hôm nay").
  `quicktool/pages/TodayPage.tsx` (+ `today.css`): ô credit Flow / việc đang chạy / xong / lỗi / credit hôm nay; mục Đang chạy
  (`listHistory status=queued,running`), Cần xử lý (clip có cảnh/video lỗi → nút Sửa sang đúng bước), Đã ghép xong chưa tải về (Tải
  từng clip / "Tải cả N clip (.zip)"), Clip đang làm dở; tự tải lại 10 s khi có việc chạy, 60 s khi không.
  `GET /api/boards?summary=true` thêm `errors`, `clip_errors`, `export_media`, `downloaded_at` và **gộp 1 truy vấn cho mọi board**
  (trước mỗi board 1 truy vấn). `GET /api/exports/zip?ids=…` (`routes/exports.py`): zip không nén các clip đã ghép, tên
  `<slug sản phẩm>_<ngày>_<id>.mp4`, header `X-Skipped-Clips`, đánh dấu `quicktool.downloaded_at`; nút "⬇ Tải về đăng TikTok" ở
  Bước 5 cũng đánh dấu. Thư viện: chọn clip → "⬇ Tải N clip đã ghép". Test `test_exports_zip.py`, `test_boards.py`. Thử thật: zip clip
  Cơm cháy (21 MB, tên đúng), trang Hôm nay hiện đúng 4 mục.

- **Bài viết Facebook** (24/10): trang `/posts` (sidebar Công cụ → "✍️ Bài viết Facebook", `quicktool/pages/PostsPage.tsx`) — tab
  "📝 Điền mẫu" (kiểu bài 7 loại, ý chính, viết cho ai, giọng, độ dài, kêu gọi, số ảnh 0–4, mô tả ảnh) và "💬 Chat với AI" (tin nhắn
  tự do + nút sửa nhanh; chat vẫn dùng các tuỳ chọn của tab mẫu), gắn sản phẩm tuỳ chọn; khung xem trước kiểu Facebook sửa trực tiếp
  (`quicktool/posts/PostEditor.tsx`: nội dung, hashtag, ảnh, "📋 Copy bài" = nội dung + hashtag, "+ Ảnh sản phẩm", prompt ảnh AI
  gợi ý + "🎨 Tạo ảnh" = `generateStandaloneImage(prompt, aspect, refs)` — gửi ảnh sản phẩm làm `ref_media_ids`, khung Vuông/Dọc/Ngang);
  "Bài đã lưu" (mở / copy / xoá 2 bước). `/posts?post=<id>` mở thẳng một bài. Bước 5 có mục thu gọn **"📝 Bài đăng Facebook cho
  clip (không bắt buộc)"** (`steps/ClipPost.tsx`, chỉ tải khi mở): kiểu bài + yêu cầu thêm + số ảnh → viết theo lời thoại clip +
  sản phẩm, ô "Sửa", Lưu (gắn `board_id`), "Mở ở trang Bài viết →"; mở lại thì hiện bài đã lưu gần nhất của clip.
  Backend: bảng `Post` (`db/models.py`, `create_all` tự tạo), `services/post_writer.py` (`POST_TYPES`, `TONES`, `LENGTHS`, `CTAS`,
  `write_post` qua `run_llm("auto_prompt")` → JSON `{reply, title, body, hashtags, image_prompts}`; sửa bài mà AI trả prompt ảnh
  rỗng thì giữ prompt cũ trừ khi tin nhắn nói về ảnh), `routes/posts.py` (`GET /options`, `POST /write`, CRUD `/api/posts`,
  `?board_id=`; `_clip_context` đọc `narration` các node video + `quicktool.product_id`). Frontend API `api/posts.ts`. Test `test_posts.py`.

- **Xoá logo Gemini ✦ trên ảnh Flow** (26/10): Flow trộn một ngôi sao 4 cánh trắng vào góc dưới phải mọi ảnh tạo ra (rộng ~48 px, cách
  mép phải/dưới ~74–124 px). **Vị trí lệch theo cỡ ảnh** (1024² xa góc hơn 768×1376 / 1376×768 khoảng 5 px) và **độ đậm khác nhau**
  (đo 70 ảnh: ~0,20–0,27 ở 1024², ~0,30–0,35 ở 768×1376). Hình ngôi sao (độ phủ từng điểm 0–1) dựng từ 71 ảnh góc phẳng **sau khi căn
  chỉnh từng ảnh** (dựng không căn → sao "béo", lõi nhạt → xoá còn vết) → `agent/flowboard/assets/gemini_star_alpha.png` (160×160 góc
  dưới phải). `services/watermark.py`: `_background` (inpaint vùng sao → nền ước lượng), `locate` (matchTemplate ±10 px → độ lệch + điểm
  khớp), `estimate_alpha` (trung vị `(ảnh − nền)/(255 − nền)` trên lõi), `has_mark` (điểm khớp ≥ 0,35 và lõi sáng hơn nền ≥ 3 mức; nền
  trắng > 248 bỏ qua), `unblend` **hoàn nguyên** `orig = (shown − a·255)/(1 − a)` với `a = k·shape` đã dịch, rồi inpaint viền mỏng 2 px;
  `remove_from_file` (JPEG q95 4:4:4, PNG/WEBP giữ; giữ icc/exif). Hook `clean_if_generated(path, kind, mime)` trong `media.fetch_and_cache`
  (trả bytes đã sạch) và `ingest_inline_bytes` — chỉ `Asset.kind == "image"` + mime image (upload đi `_ingest_image_bytes`, không đụng),
  công tắc AppSetting `clean_gemini_mark` (mặc định bật). Routes `GET/PUT /api/media/clean-marks {enabled}`, `POST /api/media/clean-marks/run`.
  UI: Cài đặt → Tạo ảnh & video → `settings/GeminiMarkSection.tsx`. Cần `numpy` + `opencv-python-headless` (pyproject; máy khác `make
  install`). Test `test_watermark.py` (5). Kết quả thật: nền phẳng sạch (sai ~1–2 mức), nền vân đậm còn vệt rất mờ ở mép khi phóng to.
  Lưu ý: file trên B2 vẫn có logo (file_store chỉ đẩy khi tạo Asset) → máy kia mở ảnh thì hook xoá lại. **Video**: xem mục "Xoá logo Gemini trên video" (1/11).
- **Xoá logo video làm lại 7/11** (đọc trước mục 1/11 bên dưới; đo trên 20 clip Omni thật, so trước / sau từng khung + ảnh phóng to):
  (a) **sao ảnh cảnh NHẤP NHÁY** (~90 px; Flow cho nó từ 0,03 lên trắng đặc rồi xuống, chu kỳ ~20 khung, có clip còn **phóng to / thu nhỏ** theo; 4/20 clip):
  `_twinkles(alphas)` (p90 ≥ `TWINKLE_HIGH` 0,5 và p90 − p25 ≥ 0,2 — logo của Flow không bao giờ đọc quá ~0,45) → `Stamp.varying`; mỗi khung `_Twinkle.read`
  dò cỡ (`TWINKLE_SCALES` ×0,45–1,32, khớp trong đúng hộp của từng cỡ) + độ đậm; khi sao (gần như) tắt thì lưu **mảnh nền sạch** (`_Plate`, lượt đọc trước
  `_collect_plates` gom cả clip), khung sao sáng dán mảnh gần nhất trước / sau trong `PLATE_MAX_AGE` 36 khung nếu vòng quanh vùng dán chưa đổi (`PLATE_RING_DIFF`)
  — vùng dán = sao ở cỡ lớn nhất; không có mảnh khớp thì `_remove` (lấp từ xung quanh từ độ đậm 0,12–0,35). Trừ ngược mô hình không bao giờ khớp loại sao này
  (Flow vẽ nó như vật phát sáng, không phải lớp phủ đều) — đừng quay lại hướng đó. (b) **Sao gốc bị dò lệch 1 px** khi sao bên cạnh sáng trắng → vệt cong sẫm:
  `_track` chỉ dời khi khớp hơn `TRACK_GAIN` 0,03; sao không bao giờ dịch trong clip → `Stamp.fixed` (ghim). (c) **Logo của Flow luôn ở một chỗ**: hộp (155, 155)
  của góc 302 px, mẫu cỡ 1 (tâm cách 2 mép 120,5 px) — 29/31 clip, dọc lẫn ngang; ảnh trung vị bỏ sót khi mép cảnh cắt ngang nó (áo đen trên tường sáng,
  clip cảnh 4 áo khoác) → `_probe_own_stamp` đọc từng khung đúng chỗ đó (độ giống hình sao trên phần chênh với nền lấp + độ đậm nhất quán 0,15–0,45); vòng dò
  chung thử `CANDIDATES` 3 ứng viên thay vì dừng ở cái sai đầu tiên. Trên clip 720 px logo này luôn **ghim** vào hộp đó (không dò, không bao giờ `varying`); vẫn cho
  2 sao chồng nhau (cách 16 px — ảnh cảnh làm từ ảnh đã có sao); sao đứng yên chỉ nhận ở 2 chỗ đã biết (logo Flow / sao ảnh cảnh ~90 px), chỗ khác là quầng sáng
  của cảnh. **Độ đậm logo Flow đọc theo cặp điểm hai bên viền** (`_pair_alpha`, 7/11 khuya): điểm ngay trong viền vs điểm ngay ngoài theo pháp tuyến, chỉ giữ cặp
  nền phẳng hai phía (`PAIR_*`); đủ ≥ 30 % cặp thì dùng, không thì giữ số đọc từ nền lấp. Lý do: nền lấp làm nhoè mép cứng dưới sao (tường sáng / sàn tối) → đọc
  0,347 thay vì ~0,31 → vết chữ V sẫm ở đầu nhọn dưới (cảnh 2 áo khoác); cặp điểm đọc 0,306. Trên các clip nền phẳng hai cách lệch ≤ 0,03 (logo Flow ≈ 0,26–0,31,
  không cố định từng clip). Sao nhấp nháy KHÔNG dùng cách này (độ đậm đổi từng khung, trung vị cặp điểm vô nghĩa). (d) Màu trừ bằng hình sao nhoè `CHROMA_BLUR` 1,2 px (video lưu màu 4:2:0), sáng bằng hình sắc
  (`_unblend` trong YCrCb). (e) **Bộ nhớ đệm có phiên bản** `CLEAN_VERSION` (đang 4: `<id>.clean4.mp4` / `.nostamp4`, bản cũ bị xoá khi làm bản mới) — không thì ghép
  dùng lại bản xoá cũ. Đã thử rồi BỎ: khớp hình sao theo clip (cỡ / dịch nửa pixel / độ nhoè) — trên vải nhiều nếp nó đuổi theo vân vải, để sót sao mà mẫu thường
  xoá được; màu lớp phủ W ≠ 255 (dữ liệu do lấp nền qua mép cứng, không phải thật). Kết quả: 4 clip nhấp nháy từ 8–53 % khung còn sao trắng + 17–22 % sao sẫm
  → 0 % / 0 %; clip sao cố định giữ nguyên hoặc tốt hơn (chăn len); chậm thêm ~1,5–3 s / clip (13,6 → 16,8 s). Test `test_video_watermark_twinkle.py` (6).
- **Xoá logo Gemini ✦ trên video + phụ đề clip chọn kiểu / Remotion** (1/11, người dùng: "khi render clip thì chạy ngầm xoá hết logo gemini
  góc dưới phải" + "Bước 4 có option phụ đề kiểu gì (Remotion hay ffmpeg) hoặc không phụ đề, chọn sẵn giọng"):
  - **`services/video_watermark.py`**: video Flow (Omni 720×1280) có sao **cố định** tâm ~120 px từ mép phải / dưới, rộng ~52 px (cùng hình sao của ảnh,
    `watermark._template()`), độ đậm ~0,3; thường kèm **sao "sót từ ảnh cảnh"** (Flow giữ bản ảnh có logo làm khung đầu) ở ~90 px, nằm yên hoặc trôi theo
    hình rồi biến mất. `find_static_stamps`: trung vị 32 khung của góc (`CORNER_FRAC` 0,42) → high-pass → `matchTemplate` 7 cỡ (`SCALES`) **chỉ trong dải
    tâm 45–175 px từ mép** (`ZONE_PX`, nhân `k` = cạnh ngắn / 720) → nhận **từng sao một** (trừ sao vừa nhận khỏi ảnh trung vị + các khung đọc rồi mới tìm sao kế
    — không thì cùng một sao bắt 2 lần ở 2 cỡ, trừ 2 lần ra sao đen); nhận khi điểm ≥ 0,5, hoặc ≥ 0,38 mà độ đậm đọc ở các khung đều (`STEADY_SPREAD` 0,05)
    và nổi ≥ 5 mức. `clean_video`: mỗi khung dò lại vị trí ±6 px (`_track`), **chỉ trừ khi sao thật sự ở đó** (`_present`: lõi sáng hơn nền ≥ 45 % mức độ đậm
    phải cho — sao sót từ ảnh rời cảnh thì không vẽ sao đen), trừ ngược `(shown − a·255)/(1 − a)` + tô viền nới 3 px (`RIM_GROW`, `RIM_CORE` 0,8); sao trôi dò
    từng khung (`MOVING_MIN_SCORE` 0,62); ghi lại bằng ffmpeg rawvideo → libx264 crf 17, chép tiếng; ~8 s cho clip 8 s. Không có sao → `{"static": 0}` (không
    ghi gì) — video của bạn / Muse / lồng tiếng không bị đụng. `cleaned_copy(src, media/clean/)` → `<id>.clean.mp4` (làm một lần, khoá theo file) hoặc file đánh
    dấu `<id>.nostamp`; công tắc chung với ảnh (`watermark.enabled()`, Cài đặt → Tạo ảnh & video). **Chạy ngầm**: `media._warm_video_stamp` gọi `prewarm` ngay khi
    video Flow về máy (`fetch_and_cache`, `ingest_inline_bytes`); lúc ghép `video_export._stamp_free_paths` lấy bản sạch (chưa có thì làm ngay, 3 luồng), có bản
    sạch thì đi đường encode từng clip; `report.stamps_cleaned`. Đo thật clip #61 (4 cảnh): sạch 4/4, chỉ còn vệt rất mờ ở chỗ chuyển nền tối–sáng khi phóng to.
  - **Phụ đề clip**: `NarrationOptions.sub_engine` "ass" | "remotion" + `sub_style`; `video_export.subtitle_choice` (Remotion không chạy được → kiểu ffmpeg gần
    nhất `REMOTION_TO_ASS`). ffmpeg: `tts.write_ass(style=)` + `tts.SUB_STYLES` (outline cũ / box_yellow / box_white, BorderStyle 3). Remotion: từng clip không in
    phụ đề, giữ `ClipReport.cues` → `_timeline_cues` (dời theo độ dài thật từng clip) → `_remotion_subtitles` dùng composition `DubSubtitles` của lồng tiếng
    (`dub_remotion.build_spec`, y 0,84 như ffmpeg, kiểu rm_box / rm_karaoke / rm_outline) trên clip đã ghép, trước chữ / nhạc nền; lỗi → `_burn_cues` in bằng ffmpeg,
    `report.subtitles_engine/subtitles_error`. Worker đọc `params.sub_engine/sub_style`. Frontend: node xuất có `subEngine`, `subStyle` (đã thêm cả 3 chỗ whitelist
    `store/board.ts`), `dispatchExport` gửi kèm + **giọng mặc định = giọng yêu thích `dubVoice`** khi clip chưa chọn giọng. `quicktool/steps/JoinOptions.tsx`:
    `JoinOptions` ở **Bước 4** (khung "🎙 Giọng đọc & phụ đề khi ghép": giọng + nghe thử, ô Phụ đề 7 lựa chọn: Không / ffmpeg ×3 / Remotion ×3, Remotion mờ khi máy
    chưa có — hỏi `GET /api/dub/status` một lần), `SubtitleField` thay ô tick phụ đề ở **Bước 5**, `joinVoice`, `subChoiceOf`/`subChoicePatch`; đổi giọng ở Bước 4 / 5
    cũng thành giọng yêu thích. Đo thật: ghép 4 cảnh + VieNeu Hải Đăng + Remotion hộp vàng ~60 s. Test `test_clip_stamp_subs.py` (6: xoá sao trên clip dựng sẵn,
    sao rời khung không bị vẽ đen, clip không sao không đụng + không dò lại, export dùng bản sạch, kiểu ASS + chọn engine, Remotion lỗi → ffmpeg).
- **Lịch đăng + tự đăng Facebook Page** (26/10, máy cty): bảng `Schedule` (`kind` post|clip, `post_id`/`board_id`, `channel_id`,
  `scheduled_at` UTC, `status` planned|posted|failed|skipped, `auto`, `note`, `result` JSON {by, post_id, permalink, comment_id | error},
  `posted_at`; `create_all` tự tạo). `services/scheduler.py`: `parse_when` (chuỗi naive = giờ VN), `list_slots`, `due_slots` (planned đã
  quá giờ → Hôm nay nhắc), `create`/`update`/`delete` (đổi giờ slot failed/skipped → planned lại), `suggest_slots` (**giờ vàng** theo
  nền tảng của kênh, `GOLDEN_HOURS`, giờ VN, bỏ giờ đã có slot), `publish` (bài: body+hashtag, ≤ 4 ảnh từ `media.cached_path`, bình
  luận đầu; clip: video `_final_media` của board + caption = bài mới nhất của clip), `tick`/`run_loop` (task `schedule-loop` trong
  `main.lifespan`, mỗi 60 s đăng slot `auto` đến giờ; quá giờ > `AUTO_GRACE` 2 h → failed "Quá giờ"). `services/facebook_publish.py`:
  Graph API v21 (`/me`, `/me/accounts` → token Page; `/{page}/photos published=false` + `attached_media` → `/feed`; video →
  `graph-video…/{page}/videos` multipart; `/{post}/comments`; `permalink_url`), lỗi 190/200 → câu tiếng Việt. **Token Page lưu ở kho
  trung tâm** `account_setting` khoá `fb_token:<user>:<channel_id>` (`accounts.get/set_setting`), không nằm trong row kênh;
  `Channel.fb_page_id/fb_page_name` (migration `ensure_channel_facebook_columns`), row kênh trả `fb_connected`. Routes:
  `routes/schedule.py` (`GET /api/schedule?from&to`, `/due`, `/hours`, `/suggest?channel_id`, `POST`, `PATCH`, `DELETE`,
  `POST /{id}/publish`), `routes/channels.py` `POST /api/channels/facebook/inspect {token}` (chỉ trả id/tên page), `POST /{id}/facebook
  {token, page_id?}`, `DELETE /{id}/facebook`. Chỉ Page: profile/nhóm/TikTok không có API → slot chỉ nhắc. Frontend: `api/schedule.ts`,
  `quicktool/schedule/ScheduleDialog.tsx` (chọn kênh bắt buộc, chip giờ vàng, datetime-local, "Tự đăng" chỉ bật khi kênh kết nối, ghi
  chú), `pages/SchedulePage.tsx` `/schedule` (tuần 7 cột, ⚡ = auto, màu theo bài/clip/đến giờ/đã đăng/lỗi, khung chi tiết: Đăng ngay /
  Copy / Tải clip / Mở FB / Đã đăng tay / Đổi giờ / Xoá; mục "Chưa lên lịch" = bài đã lưu + clip đã ghép chưa có slot; `DueList` dùng
  chung), Hôm nay mục "⏰ Đến giờ đăng", nút 📅 ở trang Bài viết (đầu khung khi đã lưu + thẻ Bài đã lưu), Bước 5 (cạnh Tải về, và
  trong mục bài đăng), `channels/FacebookConnect.tsx` ở trang Kênh (dán token → Kiểm tra → chọn Page → Kết nối; hướng dẫn lấy token
  5 bước). Menu "📅 Lịch đăng" trong Công cụ. Test `test_schedule.py` (9, Graph API giả bằng `httpx.MockTransport`). **Chưa đăng thật
  lên Facebook** (người dùng chưa dán token).
- **Đăng dạng Bài viết hay Reel** (28/10, người dùng: "muốn chia ra reel và post"): `Schedule.fb_format` "post" | "reel" (migration `db.ensure_schedule_format_column`, đã chạy trên Neon). Reel qua API theo developers.facebook.com/docs/video-api/guides/reels-publishing: `facebook_publish.publish_reel` = `POST /{page}/video_reels upload_phase=start` → file lên `upload_url` (rupload.facebook.com, header `Authorization: OAuth`, `offset`, `file_size`; rớt mạng thì đọc `status.uploading_phase.bytes_transfered` để gửi tiếp) → `upload_phase=finish video_state=PUBLISHED description` → chờ `status.video_status` ready ≤ 120 s → bình luận đầu → `permalink_url`. `reel_problem(video)` chỉ chặn video < 3 s / không đọc được; `reel_warning` chỉ **nhắc** (dài hơn 90 s mà tài liệu API ghi, ngang hơn 16:9, cạnh ngắn < 540 px) — người dùng chỉ ra app Facebook đăng được Reel 3:00 (đăng tay), nên không chặn, để Facebook quyết; từ chối thì báo lỗi, đăng lại dạng bài viết (giới hạn API: 30 bài / 24 giờ / Page). `scheduler.reel_check` + `GET /api/schedule/reel-check?kind&post_id|board_id` → `{has_video, ok, reason}`; `create/update(fb_format=)` từ chối Reel khi không có video / video sai chuẩn (clip chưa ghép thì để lúc đăng kiểm). Đường "post" như cũ (`publish_post`: `/videos`, chia nhỏ khi > 20 MB). UI `schedule/FormatPicker.tsx` ("📰 Bài viết / 🎬 Reel", Reel khoá + lý do khi không hợp, khoá trong lúc đang kiểm ~0,8 s; không có video thì ẩn) ở `ScheduleDialog`, `DropTimeDialog`, thanh Đăng bài trang Bài viết (compact, chỉ khi bài có video / gắn clip) và Bước 5 `ClipPost` ("🚀 Đăng Reel ngay"); Lịch đăng ghi "🎬 Reel" trên ô lịch + khung chi tiết "Dạng". Test `test_schedule.py` (+2: chuẩn Reel bằng ffmpeg thật, cả luồng Reel với Graph giả). **Đã đăng Reel thật 29/10 23:08** (slot #16, clip "Tù túng trong Hệ Mặt Trời…" dài **10:51**, `facebook.com/reel/1838607380914775`) → giới hạn 90 s trong tài liệu API **không áp dụng**; `reel_warning` không nhắc độ dài nữa (chỉ còn tỉ lệ ngang > 16:9 và cạnh ngắn < 540 px).
- **Bước 5 → "✍️ Viết bài & đăng"** (29/10; người dùng muốn đủ tuỳ chọn như trang Bài viết thay vì hộp "Đăng ngay" đơn giản): thẻ Kết quả có một hàng `.qt-result__share` = "📅 Lên lịch đăng" (xanh dương `qt-btn--schedule`) + "✍️ Viết bài & đăng" (xanh lá `qt-btn--publish`) → `/posts?clip=<board id>`. `PostsPage` đọc `?clip=`: bài mới nhất đã lưu của clip (bỏ `tiktok_caption`) thì mở bài đó, không thì bài mới với `boardId` = clip, `clipVideo` = `summary.export_media`, kênh + sản phẩm lấy từ `board.data.quicktool`; dòng "🎬 Bài này đi kèm clip <tên>" + "Bỏ gắn clip"; trước khi viết, cột phải hiện video clip (`.qt-posts__clipvid`); `PostEditor` prop `clipVideo` hiện video clip trong khung bài (ẩn hộp "🎬 Video kèm" — video clip thắng). Viết (AI đọc lời thoại clip qua `board_id`) → thanh đăng sẵn có: Đăng ngay (Bài viết / Reel) / Lên lịch, `scheduler._payload` đăng kèm video clip. `ScheduleDialog` vẫn có `mode="now"` (chọn kênh + dạng, đăng ngay, auto=false) nhưng hiện chưa nơi nào dùng. **"Đăng lên Facebook dạng: 📰 Bài viết / 🎬 Reel" nằm ngay ở khối ① của form** (hiện khi bài gắn clip hoặc "Kèm theo" = video; trước đây chỉ có ở thanh đăng sau khi viết xong — người dùng hỏi "sao không có dạng Reel"): lưu vào `brief.fb_format`, đồng bộ với `FormatPicker` của thanh đăng (mở bài cũ thì lấy lại theo brief); `post_writer._brief_block` thêm khối `REEL_CAPTION` (1–3 dòng, ≤ ~220 ký tự, câu đầu giữ người xem, thắng Length / Layout). Thử AI thật: 11 s, 220 ký tự, 3 dòng. **Dọn lại (29/10 tối, người dùng: "bài viết FB lung tung quá… chọn Reel bấm đăng thì nó về Bài viết")**: dạng đăng chỉ còn **một nguồn** = `brief.fb_format` (không còn state `fbFormat` riêng + effect theo `postId` — chính effect đó đặt lại về "post" khi lưu / đăng tạo postId mới) và **một chỗ chọn** = `FormatPicker` ở khối ① (bỏ bản compact ở thanh đăng; thanh đăng ghi "dạng 🎬 Reel · đổi dạng" cuộn lên ô chọn); thanh đăng sau khi đăng: "✓ Đã đăng Reel lên <Page> lúc hh:mm", nút chính "Xem Reel trên Facebook ↗", "Đăng lại" thành nút mờ; "📅 Lên lịch" truyền `fbFormat` sang `ScheduleDialog` (`ScheduleTarget.fbFormat`); nhãn trạng thái "● Đã đăng Reel".
- **Câu mở đầu A/B ("✨ 5 câu mở đầu khác")** (26/10): `services/hooks.py` — `post_hooks(body, channel, product, n)` và
  `clip_hooks(lines, …)` (≤ 14 từ, cắt khi dài), mỗi biến thể một kiểu của `post_writer.HOOKS` (câu hỏi / sự thật / nỗi khổ / con số /
  kể chuyện / ngược số đông), `replace_opening(body, line)` thay đoạn trước dòng trống đầu tiên. Routes `POST /api/posts/hooks {body,
  channel_id?, product_id?, n?}`, `POST /api/posts/clip-hooks {board_id}` (đọc `_clip_context`). UI: `PostEditor` nút "✨ 5 câu mở đầu
  khác" (prop `hookContext` {channelId, productId}; bảng `.qt-hooks`, "Dùng" thay mở đầu, "↺ Về câu mở đầu cũ"), trang Bài viết thêm
  **"⧉ Lưu thành bản sao"** (bài mới "(bản B)" cùng nội dung đang hiện — để đăng thử 2 bản); Bước 2 cảnh 1 có nút cùng tên thay lời
  thoại cảnh 1. Test `test_hooks.py` (4). Thử thật: 5 câu/8 s cho bài và cho clip (bám kênh "Mẹ bầu").
- **🎁 Gói nội dung một chạm** (26/10): `services/bundle.py` `make(product_id, channel_id, template_id?, post_kind, with_clip/post/tiktok)`
  → (1) clip: `routes.templates.create_board_from_template(tailor=True)` (kịch bản viết theo sản phẩm, chưa render), (2) song song:
  bài Facebook (`write_post` brief {kind, cta link, boosts question_end} + clip lines + sản phẩm + kênh → lưu `Post` gắn board) và
  caption TikTok (`brief.platform = "tiktok"`, lưu `Post.kind = "tiktok_caption"`). Lỗi từng phần vào `errors[part]`, không chặn phần khác.
  Route `POST /api/bundles` (+ `GET /options`), `routes/bundles.py`. UI `quicktool/bundle/BundleDialog.tsx` mở từ nút **"🎁 Gói"** trên
  thẻ / dòng sản phẩm (`ProductsPanel`, `.product-card__btns`): chọn kênh (bắt buộc), kiểu clip (hợp ngành xếp trước), kiểu bài, 3 ô tick;
  kết quả có "Mở kịch bản →", "Mở bài" / "📅 Lên lịch", "Copy" caption. Test `test_bundle.py` (2, `tailor_spec` giả). Thử thật: 27 s cho
  sản phẩm Đầm bầu + kênh Mẹ bầu (clip tailored, bài có bình luận đầu kèm link, caption đúng kiểu); dữ liệu thử đã xoá.
- **🔥 Mẫu đang hot (swipe file)** (26/10): bảng `Swipe` (kind post|video, url, platform, title, text, analysis JSON, tags, uses).
  `services/swipes.py`: `read_source(url, text)` — link video (TikTok/Douyin/YouTube/Reels/FB reel, `is_video_link`) → `video_fetch.fetch_video`
  (≤ 10 phút, Asset đăng ký) → `reference_video.analyze(path, None)` lấy hook/transcript/shots (cần Gemini key); link bài (FB/Threads/IG/X/Zalo)
  → `channel_page.read_page` (extension 0.6.0) + `clean_text`; hoặc dán thẳng nội dung. `analyze()` → LLM `_SYSTEM` → JSON {title, summary,
  hook_type, hook, structure[], why_it_works[], triggers[], format, cta, skeleton (khung mẫu tiếng Việt có [chỗ trống]), tags} → lưu.
  `adapt_post` → `post_writer.write_post(extra=adapt_block(analysis))` (khối "FOLLOW THE STRUCTURE… do not copy sentences"), lưu Post
  (`brief.swipe_id`); `adapt_clip` → board từ template (tailor=False) rồi `script_tailor.tailor_board(instructions=khung mẫu)`
  (`_scene_pairs` ghép image→video qua Edge). `write_post` thêm tham số `extra`. Routes `routes/swipes.py` (`GET /api/swipes`, `POST
  /analyze {url?|text?}`, `GET/DELETE /{id}`, `POST /{id}/adapt {as: post|clip, channel_id, product_id?, kind?, template_id?, wish?}`).
  UI `pages/SwipesPage.tsx` `/swipes` (+ `swipes.css`): ô dán link/bài → phân tích; danh sách trái (tìm theo tên/nhãn), chi tiết phải
  (câu mở đầu + loại, các bước, vì sao chạy, chạm vào, định dạng/kêu gọi, khung mẫu, nội dung gốc), khối "Viết bản của mình": kênh
  (bắt buộc), sản phẩm, kiểu bài, kiểu clip, mong muốn → "✍️ Viết bài theo mẫu" (mở bài) / "🎬 Tạo clip theo mẫu" (mở Bước 2). Menu
  "🔥 Mẫu đang hot". Test `test_swipes.py` (5). Thử thật: bài chữ 20 s phân tích đúng (ngược số đông, 6 bước), viết bài theo mẫu 15 s
  cho Đầm bầu + bình luận đầu kèm link; **chưa thử link video thật và link Facebook thật** (cần Chrome đăng nhập FB).
- **Loạt truyện (series) dễ dùng hơn** (26/10 tối; từ 27/10 là ô Có/Không riêng, xem mục "Câu chuyện nhiều kỳ là lựa chọn riêng"): có ô **chọn loạt** (các loạt đã có · số tập, hoặc "＋ Loạt
  truyện mới…" → ô tên); chọn loạt có sẵn hiện "Đã có N tập" + nút **"⚡ Viết nhanh Tập N+1"**. `writeNext(name)` (PostsPage): lấy kênh,
  sản phẩm và `brief` của **tập cuối** (kind serial) → `POST /api/posts/write-batch` với `n: 1` (giờ `ge=1`) → AI đọc các tập trước, tập
  mới **được lưu ngay** rồi mở; nếu brief có ảnh/video thì tự tạo luôn (ảnh tự lưu vào bài qua `changeImages`). **"Bài đã lưu" gom theo
  loạt**: mỗi loạt một khung `<details class=qt-series>` (📖 tên · N tập · kênh + nút "✍️ Viết Tập N+1"), các tập xếp theo số tập, thẻ có
  nhãn "Tập n"; bài không thuộc loạt nằm dưới "📝 Bài lẻ" (phân trang chỉ áp cho bài lẻ). Thẻ/dòng là hàm `savedCard` / `savedRow` (không
  khai báo component trong render). **Bẫy dính lúc làm**: `useMemo` đặt sau `if (!options) return <PageLoading/>` → "Rendered more hooks
  than during the previous render", trang trắng — mọi hook phải đứng trước lệnh return sớm.
- **Bài viết kèm video + kéo thả lịch đăng** (26/10 tối, máy cty):
  - **Video thay ảnh**: `Post.video` (media id; migration `ensure_post_video_column`, PATCH/POST `video`). `standaloneImage.generateStandaloneVideo`
    = request `gen_video_omni` 8 s (Omni Flash ~12 credit) với **ảnh làm nguyên liệu bắt buộc** (Flow không làm video từ chữ không):
    ảnh đầu của bài → không có thì ảnh sản phẩm → không có thì vẽ ảnh từ prompt ảnh đầu rồi mới làm video. Lỗi `timeout`/`FLOW_DROPPED_JOB`
    → "Flow bỏ lượt (gương mặt bị chặn)". `PostEditor`: hộp `<details>` "🎬 Video kèm thay ảnh" (ô chuyển động tiếng Anh `DEFAULT_MOTION`
    sửa được, hỏi xác nhận credit, ↻ Tạo lại, Bỏ video, Tải), xem trước `<video>` thay lưới ảnh; props `video`, `onVideo`,
    `autoVideoToken` (ô "Kèm theo" = "🎬 1 video" → `brief.with_video` + `images: 1` → viết xong vẽ ảnh rồi tự làm video). Trang lưu
    video ngay vào bài đã lưu (`changeVideo`), `onBusyChange` tính cả lúc làm video. **Đăng**: `scheduler._payload` — bài có `video`
    → đăng dạng video (`graph-video …/videos`), ảnh bỏ qua (Facebook nhận ảnh hoặc một video). ClipPost (Bước 5) không có nút video.
  - **Lịch đăng kéo thả** (`SchedulePage.tsx`, `schedule/DropTimeDialog.tsx`): "Chưa lên lịch" thành **lưới thẻ** kéo được (bài + clip
    đã ghép, bỏ `tiktok_caption`), lịch `planned` kéo được sang ngày khác; ngày đã hết thì mờ + không nhận thả (`dayOpen`), ngày nhận thả có
    viền đứt, đang rê thì sáng cam. Thả → hộp **chỉ hỏi giờ** (chip giờ vàng của kênh trong ngày đó, giờ đã qua bị khoá; ô `type=time`;
    dời lịch giữ giờ cũ; lịch mới có "Tự đăng" bật sẵn nếu kênh nối Page; bài chưa gắn kênh thì hỏi kênh). Nút "📅 Lên lịch" vẫn mở
    hộp đủ ngày + giờ (`ScheduleDialog`, `min` + chặn giờ đã qua). **Backend chặn giờ quá khứ** (`scheduler.check_future`, cho lùi
    `PAST_GRACE` 2 phút vì "Đăng ngay" tạo slot lúc này) ở tạo + PATCH `at`; slot đã đăng không đổi giờ được. Sửa bug: bài **đã đăng**
    vẫn hiện trong "Chưa lên lịch" (trước chỉ loại slot `planned`, và chỉ trong cửa sổ tuần đang xem) → giờ đọc mọi slot planned/posted.
  - Trang Bài viết: cột form `minmax(340px, 520px)`, khung bài / thanh đăng / loạt bài `max-width` 780 px (trước 860).
  - Test: `test_schedule.py` (giờ quá khứ bị từ chối, `_backdate` để giả lập "đến giờ", bài có video đăng dạng video) — 20 pass cùng posts.
- **Bài viết: bố cục mới + viết nhiều bài một lúc + Đăng ngay** (26/10 chiều, máy cty, `PostsPage.tsx` + `posts.css`):
  - Trái: khối đánh số **① Đăng ở đâu** (kênh bắt buộc + sản phẩm) / **② Viết gì** (Kiểu bài = `<select>` + một dòng mô tả `KIND_HINT`,
    "Tên câu chuyện" chỉ hiện khi kiểu `serial` — chỉ gửi/lưu `series` khi `serial`; ý chính; **Số bài** 1–5; Ảnh kèm; Kêu gọi) /
    **③ Tuỳ chỉnh thêm** (`<details>` gập, dòng tóm tắt lựa chọn khi gập: viết cho ai, giọng, độ dài, câu mở đầu, trình bày, emoji, kéo
    tương tác). Nút "✍️ Viết bài / Viết N bài / Viết N tập" dính đáy cột (`.qt-posts__go`).
  - Phải: đầu khung = tên bài + nhãn trạng thái (Chưa lưu / ✓ Đã lưu / ● Đã đăng) + "＋ Bài mới", "⧉ Bản sao", "💾 Lưu" (nhỏ);
    dưới bài là **thanh Đăng bài** dính đáy (`.qt-posts__publish`): "Đăng lên <Page> ⚡ tự đăng được" (hoặc "chưa kết nối Page → kết
    nối") + 📋 Copy / 📅 Lên lịch (tự lưu trước) / **🚀 Đăng ngay** (chỉ khi kênh `fb_connected`; hỏi xác nhận → lưu → `createSlot(now)`
    → `publishSlot` → "đã đăng hh:mm — xem bài ↗"). `PostEditor` có prop `hideCopy`. **Ảnh**: đăng / lên lịch gửi `Post.images` (≤ 4,
    file từ `media.cached_path`, đã xoá logo Gemini) — slot đọc ảnh của bài **lúc đến giờ đăng**. Đang tạo ảnh (`PostEditor onBusyChange`)
    thì "Đăng ngay" / "Lên lịch" khoá ("⏳ Đợi ảnh…"); bài đã lưu mà thêm / bỏ ảnh → `changeImages` PATCH riêng `images` ngay
    (chữ chưa lưu vẫn chưa lưu), để bài đã lên lịch không đăng thiếu ảnh. Thanh đăng ghi "kèm N ảnh". Chưa có bài → `PageEmptyHint` 3 bước.
  - **Viết 2–5 bài một lúc**: `POST /api/posts/write-batch {…WriteBody, n}` (`routes/posts.py`, `_write_context` dùng chung với `/write`,
    `_save_written` lưu luôn từng bài). Có `series` → **viết lần lượt**, tập sau nhận các tập vừa viết trong `previous` (tập n đọc tập
    n−1), episode nối tiếp chuỗi cũ; lỗi giữa chừng thì dừng (tập sau không biết chuyện tập trước). Không có series → **song song**,
    mỗi bài một câu mở đầu (`BATCH_HOOKS` xoay vòng khi để "AI tự chọn") + khối `extra` "BATCH: post i of n… clearly different angle".
    UI: khung **"📚 Loạt N bài vừa viết"** trên đầu cột phải — mỗi dòng (Tập n / Bài i, tiêu đề, trích) bấm để mở (`open(p, keepForm)`
    không đổi form), nút **📅 Lên lịch** riêng (sau khi đặt hiện "📅 T3 28/10 · 20:00"), 📋; nút **"📅 Xếp lịch cả loạt (mỗi ngày 1 bài)"**
    = giờ vàng đầu tiên còn trống của mỗi ngày (`suggestSlots`), `auto` = bật nếu kênh đã kết nối Page. Ảnh của từng bài tạo sau khi mở.
    Test `test_write_batch_side_by_side_and_as_a_story`. Thử thật: 3 tập nối tiếp 31 s, tập 2/3 mở bằng "Tiếp tục câu chuyện lần trước…".
    Lưu ý: lưu loạt bài cũng gọi `brainstormIfDue` → kênh đủ 3+ bài là tự brainstorm.
- **Bài viết: kênh bắt buộc + "Tăng view & tương tác" + Bài đã lưu lưới/danh sách** (26/10, máy cty):
  - **Kênh / page bắt buộc** ở trang Bài viết và Bước 5 (`ChannelPicker required`: nhãn "(bắt buộc)", option "— Chọn kênh / page —");
    chưa chọn thì "✍️ Viết bài", "Gửi" (chat), nút sửa nhanh, "Viết bài cho clip" bị khoá + dòng nhắc cam (`.qt-posts__need`).
    Backend `POST /api/posts/write` trả **400** khi không có kênh (body hoặc kênh của clip) hoặc kênh đã xoá — không tốn token.
  - **Kêu gọi** có `none` = "Không kêu gọi — bài để đọc" (**mặc định**; brief thiếu `cta` cũng hiểu là none). System prompt: kết theo dòng
    CALL TO ACTION (có thể là không có), luật tiếp cận Facebook (2 dòng đầu khiến bấm "Xem thêm", **cấm engagement bait** "comment CÓ",
    "tag 3 người"… vì FB giảm reach).
  - Khối riêng **"🚀 Tăng view & tương tác"** (`post_writer.HOOKS` câu mở đầu: AI chọn / câu hỏi / sự thật bất ngờ / nỗi khổ / con số "3
    điều…" / kể chuyện / ngược số đông; `FORMATS` trình bày: đoạn ngắn / danh sách / hỏi–đáp / trước–sau; `EMOJIS` ít / vừa / nhiều;
    `BOOSTS` chọn nhiều: kết bằng câu hỏi dễ trả lời, chọn A hay B, đáng lưu lại, giữ người đọc tới cuối, chạm nỗi niềm chung, đáng chia
    sẻ) → brief `hook`, `format`, `emoji`, `boosts[]` → dòng "Opening line / Layout / Emoji / REACH (do all of these)" trong prompt.
    `GET /api/posts/options` trả thêm `hooks`, `formats`, `boosts`, `emojis`. Bước 5 vẫn `cta: "link"` (caption kèm video).
  - Khung xem trước bài rộng tới 860 px (trước 560), chữ 16px; đầu khung: "＋ Bài mới" (nút thường) + "💾 Lưu bài / Lưu thay đổi"
    (cam) hoặc "✓ Đã lưu" (xanh, khoá) khi không có thay đổi.
  - **Bài đã lưu**: nút ▦ Lưới / ☰ Danh sách (localStorage `flowboard.posts.view`), lưới 4 cột × 3 = 12 bài/trang (thẻ ảnh 16:10, tiêu
    đề, kiểu bài · kênh · clip · giờ, 3 dòng nội dung, Mở / Copy / Xoá), danh sách 10 dòng/trang, `.qt-pager`.
- **Ảnh của bài viết: tự tạo + sửa theo yêu cầu** (25/10, `posts/PostEditor.tsx`): chọn "Ảnh kèm" N ảnh rồi "Viết bài" → viết xong **tự tạo
  cả N ảnh ngay** (prop `autoMakeToken`: trang bump sau mỗi lần viết MỚI — không bump khi sửa qua chat, mở bài đã lưu / "+ Bài mới" đặt về 0;
  editor bỏ qua token 0 và nhớ token đã xử lý), ô ảnh có thẻ chờ "🎨 Đang tạo ảnh…". **Viết lại bài mới = bỏ ảnh bài cũ** (`setImages([])`
  trong `run()` / `write()` khi không có message). Mỗi prompt nhớ ảnh nó tạo (`made[i]`): hiện thumbnail, nút thành "↻ Tạo lại ảnh" (thay
  đúng ảnh đó, không chồng thêm), "✨ Sửa theo yêu cầu" mở ô tiếng Việt + 5 gợi ý → `POST /api/posts/revise-image {prompt, request}`
  (`post_writer.revise_image_prompt`, `_REVISE_IMAGE_SYSTEM`, ≤ 600 ký tự, giữ phần không được yêu cầu đổi) → "Sửa prompt & tạo lại ảnh"
  (Ctrl+Enter) hoặc "Chỉ sửa prompt". Prompt tiếng Anh vẫn sửa tay được. Bước 5 (`ClipPost`) dùng chung. Thử thật: viết 11 s → ảnh tự ra
  31 s; sửa prompt 9 s đúng ý ("book and a cup of tea… warm"); viết lại → ảnh cũ mất, ảnh mới chạy.

- **Kênh ("Kênh của tôi", 24/10)**: một kênh = một page / tài khoản đăng bài. Bảng `Channel` (`db/models.py`: `name`, `platforms`
  JSON — khoá của `services/channels.PLATFORMS` facebook/instagram/tiktok/threads/youtube/zalo, **`categories` JSON ≤ `MAX_CATEGORIES` 3** khoá
  của `CATEGORIES` (22 mục kiểu Facebook: bán gì + nói về gì; migration `db.ensure_channel_categories_column` seed từ `category` cũ; `category`
  = mục đầu, giữ cho code cũ; `category_keys()` đọc cả hai dạng),
  `description`, `audience`, `goal`, `brainstorm` JSON), `Post.channel_id` (migration `db.ensure_post_channel_column`, đã chạy trên Neon),
  clip gắn kênh qua **`board.data.quicktool.channel_id`** (nhận ở `POST /api/boards/from-template` + `/api/reference-video/build`
  `channel_id`, đổi sau bằng PATCH board). Routes `routes/channels.py`: `GET /options`, CRUD `/api/channels` (row kèm `posts`,
  `clips`, `brainstorm_due`; xoá kênh thì bài **và clip** chỉ mất liên kết), `POST /{id}/brainstorm`. `GET /api/posts?channel_id=`.
  **Brainstorm** (`services/channels.brainstorm`): đọc tối đa 12 bài + 8 clip (lời thoại) + mô tả kênh → JSON `positioning, audience,
  voice, pillars[{name,note}], post_mix, do[], dont[], hashtags[], ideas[], summary` + `at/post_count/clip_count`; `brainstorm_due`
  = đủ `BRAINSTORM_MIN_POSTS` (3) bài mà chưa có, hoặc đã thêm ≥ `BRAINSTORM_STALE_POSTS` (5) bài từ lần trước. Frontend
  `api/channels.brainstormIfDue(channelId)` gọi sau khi **lưu bài mới** (PostsPage + ClipPost): due → toast + chạy nền → toast kết quả.
  Trang `/channels` (`quicktool/pages/ChannelsPage.tsx`, `channels.css`): danh sách trái, chi tiết phải (form tạo/sửa, ô thống kê,
  nút "Viết bài cho kênh" → `/posts?channel=`, "Tạo clip cho kênh" → `/clips/new?channel=`), khối "🧠 Định hướng kênh" (brainstorm
  ngay / lại), bài viết + clip của kênh. `quicktool/channels/ChannelPicker.tsx` (select dùng chung, cache 30 s, `invalidateChannels()`
  sau khi sửa kênh) đặt ở: hộp Clip mới (mục "Kênh đăng clip", đọc `?channel=`), Bước 1 (`steps/ClipChannel.tsx`, PATCH
  `quicktool.channel_id`), trang Bài viết (trên ô Sản phẩm), Bước 5 (`ClipPost` mặc định kênh của clip, đổi được).
  **Bài viết bám kênh**: `post_writer.write_post(channel=)` → `channels.channel_block` (mô tả + PAGE DIRECTION: vị thế, giọng, trụ cột,
  nên/không, hashtag nhà) + **định dạng theo nền tảng** (`platform_style`: nền tảng đầu của kênh, hoặc `brief.platform`; thắng độ dài
  khi mâu thuẫn). `POST /api/posts/write` lấy `channel_id` từ body hoặc từ clip (`_clip_context`). Test `test_channels.py` (6).

- **Lồng tiếng video ("🎙 Lồng tiếng video", `/tools/dub`, 24/10)** — bản rút gọn của VieDub/pyvideotrans trong Flowboard: dán link
  (TikTok / Douyin / YouTube / IG / FB / X, qua `_run_ytdlp` của reference-video) hoặc chọn file → Whisper nghe tiếng gốc → LLM dịch sang
  tiếng Việt nói (giữ số câu, ngắn hơn hoặc bằng câu gốc) → TTS từng câu (Edge / Gemini, `tts.synthesize`) ép vừa khung thời gian
  (`atempo` tối đa `MAX_SPEEDUP` 1,45) → xếp lên một track theo mốc câu → **bỏ tiếng gốc**, tuỳ chọn giữ nhạc nền (spleeter tách
  giọng, trộn `BGM_VOLUME` 0,6) → in phụ đề ASS **hộp vàng chữ đen** (`BorderStyle 3`; kiểu `box_yellow` / `box_white` / `outline`;
  cỡ chữ 3,6 % chiều cao, mỗi hộp ≤ `sub_max_chars(w,h)` ký tự — 720×1280 ≈ 24, 1080×1920 ≈ 24) → mp4 faststart → **thành một clip**
  (board `quicktool.template_id = "dub"`, `step 5`, node video có `narration` = lời Việt + node export có `mediaId`) nên vào thư
  viện / Hôm nay / kênh / bài đăng Bước 5 như clip thường. Whisper + spleeter chạy trong **venv pyvideotrans** qua
  `services/dub_runner.py` (`transcribe` → faster-whisper large-v3-turbo tại `models/models--mobiuslabsgmbh--…`, CUDA float16 → CPU
  int8; `separate` → sherpa-onnx spleeter `models/onnx/{vocals,accompaniment}.fp16.onnx`; đọc `FLOWBOARD_ERASE_ROOT` /
  `FLOWBOARD_ERASE_PYTHON` như công cụ xoá chữ). `services/dub.py`: `status()`, `Job` (RAM, mất khi restart; trạng thái queued →
  running → [review] → rendering → done/error), `start_job` (một việc một lúc), `render_job` (sửa câu / giọng / kiểu rồi render lại —
  cập nhật cùng board), `_timeline_wav`, `write_sub_ass`, `split_cue`, `_save_board`. Routes `routes/dub.py`: `GET /api/dub/status`,
  `POST /api/dub/jobs`, `GET /api/dub/jobs[/{id}]`, `POST …/render`, `POST …/stop`. Frontend `api/dub.ts`, `pages/DubPage.tsx` (+
  `dub.css`): link/file, giọng (`VoiceField`), kiểu phụ đề, giữ nhạc nền (ẩn nếu máy thiếu spleeter), "Xem lại bản dịch trước khi
  render", chọn kênh, tiến độ từng bước, bảng câu sửa được + "Render lại", video xem trước, tải về, "Mở clip", `ClipPost` ngay dưới.
  Test `test_dub.py` (8, có ffmpeg thật). Đo thật máy nhà (RTX 3060): video 12,6 s → 39 s; YouTube 69 s tiếng Trung 26 câu → 128 s
  (Whisper ~10 s, dịch ~6 s, TTS ~3 s/câu nối tiếp, spleeter ~4 s). Máy không có pyvideotrans: trang báo "chưa dùng được".

- **Tải video từ link — `services/video_fetch.py`** (25/10): `extract_url(text)` lấy link từ cả đoạn "chia sẻ" dán nguyên (Douyin / TikTok
  kèm tiêu đề, hashtag); `fetch_video(text, media_id, out_dir, max_duration_s=)` → link **Douyin** đi đường trang chia sẻ mobile như
  VieDub (`douyin_info`: theo redirect `v.douyin.com` → `iesdouyin.com/share/video/<id>` → `window._ROUTER_DATA` → tiêu đề, thời
  lượng, `play_addr` bản không watermark; gọi lại tối đa 4 lần vì lượt đầu chỉ cấp cookie; `download_direct` httpx, cap 300 MB; biết
  thời lượng trước nên video dài quá bị từ chối trước khi tải), còn lại / Douyin lỗi → `routes.reference_video._run_ytdlp`. Dùng ở
  lồng tiếng (`dub._download`, tối đa 10 phút) và `POST /api/reference-video/fetch` (clip theo video mẫu). Host cho phép thêm
  `iesdouyin.com`. Test `test_video_fetch.py` (5, MockTransport).

- **yt-dlp tự có + không giới hạn cỡ video** (10/11, người dùng báo: Cắt video link YouTube "yt-dlp không có trên máy — cài bằng winget" trên bản cài, và
  chọn file bị "video too large: 200 MB > 200 MB"): **`services/ytdlp.py`** — `find()` = `FLOWBOARD_YTDLP` → `yt-dlp` trên PATH → bản riêng `<data>/tools/yt-dlp(.exe)`
  (`tools_dir()` = `(config.HOME or config.ROOT)/tools`, `FLOWBOARD_TOOLS_DIR` để đổi — `conftest.py` trỏ vào thư mục tạm; `/tools/` trong .gitignore); `ensure()` tải
  bản chính thức từ `github.com/yt-dlp/yt-dlp/releases/latest/download/<yt-dlp.exe | yt-dlp_linux | yt-dlp_macos>`, **so SHA-256 với `SHA2-256SUMS` của bản phát hành**
  (lệch → bỏ file), bản riêng cũ hơn `UPDATE_AFTER_S` 3 ngày thì `yt-dlp -U` (đồng hồ chạy lại cả khi lỗi); `js_args()` đưa `node` cho YouTube khi máy có node mà không
  có deno (yt-dlp 2026 chỉ tự dùng deno; không có bộ chạy JS vẫn tải được, chỉ cảnh báo "deprecated" — đã thử). `available()` (status lồng tiếng). `_run_ytdlp(url, id,
  max_duration_s)`: bỏ `--max-filesize 200M`, `--match-filter "!duration | duration <= N"` (video dài quá → "video dài hơn N phút" không tải), `FETCH_TIMEOUT_S` 1800.
  **Chọn file** (`POST /api/reference-video/upload`, dùng cho Cắt video, Muse, Xoá chữ, Dùng video của bạn, lồng tiếng): bỏ `MAX_VIDEO_BYTES`, chép ra đĩa từng 1 MB qua
  `.part` (`_save_upload`, không đọc hết vào RAM; đĩa đầy → 507); frontend bỏ mọi chỗ chặn / ghi "200 MB". App: `dflow_agent._temp_in_home` đặt `tempfile.tempdir` =
  `<DFlowData>/tmp` (Starlette ghi tạm file tải lên ở đó trước — trước đây là %TEMP% trên ổ C), xoá file tạm sót > 1 ngày. Test `test_ytdlp.py` (7).
- **Lồng tiếng: vị trí phụ đề + vùng mờ chữ gốc + job sống qua restart** (25/10): `Job.layout = {x, y, scale, blur}` (x/y = đáy-giữa
  hộp phụ đề theo tỉ lệ khung, scale = hệ số cỡ chữ, `blur = {x, y, w, h, amount}` góc trên-trái + kích thước theo tỉ lệ, amount 1–10 — vùng
  làm mờ nhẹ đè lên chữ Trung in sẵn, kiểu page "Bầu bì không khó" làm bằng CapCut). `normalize_layout`, `write_sub_ass(layout=)` ghim
  mỗi dòng bằng `{\an2\pos(x,y)}`, `sub_max_chars(w,h,layout)` hẹp lại khi hộp lệch tâm / chữ to, `blur_filter` (split → crop → boxblur
  bán kính `h*amount/60` → overlay) + `video_filter` gộp với `ass` thành một `-filter_complex`. `POST /api/dub/jobs/{id}/render {layout}`;
  `render_job` **dùng lại voice.wav + bgm.wav** khi `voice_key` (giọng + các câu) không đổi → in lại chỉ mất ~27 s cho video 6 phút
  (phase "Đang in lại phụ đề"). Job ghi `<media>/dub/<id>/job.json` sau mỗi bước (`persist`), `load_jobs()` đọc lại khi gọi
  `GET /api/dub/jobs[/{id}]` (job đang chạy lúc tắt → error "Agent khởi động lại giữa chừng"; work dir, src_path, voice_key suy lại).
  Frontend (cũ, **26/10 đã thay bằng trình chỉnh sửa `dub/editor/`**, xem mục "Trình chỉnh sửa kiểu CapCut") `quicktool/dub/SubPositioner.tsx`: video xem trước (câm, thanh kéo thời điểm ±1 s) + hộp phụ đề kéo được (pointer capture),
  mũi tên 1 % / Shift 5 %, phím +/− cỡ chữ, slider ngang/dọc/cỡ, preset dưới/sát đáy/giữa/trên, kiểu; vùng mờ kéo được + tay nắm góc đổi cỡ
  + slider cao/rộng/vị trí/độ mờ, "🔍 Tự tìm chữ gốc (OCR)" gọi `POST /api/clean/{source_media_id}/detect` (RapidOCR của công cụ xoá
  chữ) → đặt vùng mờ theo dải chữ, "Đặt ngay trên phụ đề"; "✓ Áp dụng" → render với layout. Mục `<details>` "🎯 Vị trí phụ đề &
  làm mờ chữ gốc" dưới video kết quả trong `DubPage`. Test `test_dub.py` 12.

- **Lồng tiếng: engine phụ đề thứ hai = Remotion** (25/10, lựa chọn riêng, đường ffmpeg/ASS giữ nguyên): `Job.engine` `"ass"` (mặc định) |
  `"remotion"`; ô "Công nghệ phụ đề" ở `/tools/dub` (+ kiểu riêng `rm_box` hộp vàng bo góc / `rm_karaoke` bật sáng từng từ / `rm_outline` chữ viền,
  `dub_remotion.STYLES`). Luồng: `dub._render` → cues như cũ → `_render_remotion`: ffmpeg chỉ **mux tiếng** (`-c:v copy`, lỗi thì re-encode) ra
  `<work>/nosub.mp4` → `services/dub_remotion.render(spec)` chạy `node frontend/remotion/render.mjs spec.json` (giao thức stdout `PHASE` /
  `PROGRESS 0.42` / `DONE` / `ERROR …`; script tự `ensureBrowser`, bundle cache, phục vụ video qua http cục bộ có Range vì Remotion cần URL) →
  mp4 h264+aac → Asset + board như engine cũ. Composition `frontend/src/remotion/DubSubtitles.tsx` (props `src, width, height, fps=30, durationS,
  cues, layout, style, muted`; font Be Vietnam Pro qua `@remotion/google-fonts`, vùng mờ = `backdrop-filter: blur`, karaoke chia mốc từ theo số ký tự
  vì TTS không có mốc từng từ), `Root.tsx` (`calculateMetadata` lấy kích thước/thời lượng từ props), `index.ts` (entry bundle). **Cùng component
  đó** hiển thị trong `SubPositioner` bằng `<Player>` khi `player` prop có (`DubPage` truyền `nosub_url` + cues + kích thước): hộp kéo thành khung
  ghost `.qt-subpos__box--ghost`, thanh tua dùng `playerRef.seekTo`, vùng mờ ghost kéo được — xem trước đúng y bản render. `GET /api/dub/jobs/{id}/nosub`
  stream `nosub.mp4` (FileResponse có Range). `status()` trả `remotion` / `remotion_reason` / `remotion_styles`; `start_job`/`render_job` nhận `engine`,
  `_style_for` đổi kiểu về mặc định của engine khi không hợp. Đo thật (video 12,6 s 720×1280, RTX 3060 nhưng Remotion dùng CPU): cả job 101 s
  (Whisper → TTS → spleeter → Remotion ~20 s), in lại (đổi layout/kiểu, giữ giọng) 18 s; render lẻ bằng script 19 s. Test `test_dub_remotion.py` (5,
  script Node giả). Cảnh báo console "`ref` is not a prop … AbsoluteFillWithTiming" là của Remotion 4.0.538 với React 18, vô hại. Chưa: chọn font khác,
  hiệu ứng vào/ra, chữ bật từng từ chính xác theo mốc từ của Edge TTS (có thể lấy từ word boundary sau này).

- **Lồng tiếng: giới hạn 30 phút + dịch theo đợt** (26/10): `dub.MAX_DURATION_S = 30 * 60` (trước 10 phút; `/api/dub/status.max_minutes`
  hiện trên trang). Kéo theo: `STEP_TIMEOUT_S` 45 phút (Whisper / spleeter, nhất là khi rơi về CPU), `ENCODE_TIMEOUT_S` 60 phút (ffmpeg in phụ
  đề), tách WAV 900 s, Remotion `RENDER_TIMEOUT_S` 120 phút. **Dịch chia đợt** `TRANSLATE_BATCH = 60` câu (`translation_batches`, đuôi < 15 câu gộp
  vào đợt trước), chạy lần lượt, mỗi đợt kèm `TRANSLATE_CONTEXT = 4` câu đã dịch ngay trước ("ALREADY TRANSLATED") để giọng và thuật ngữ liền mạch;
  tiêu đề lấy từ đợt 1; phase "Đang dịch sang tiếng Việt (n/N)". `video_fetch`: gợi ý "link là tuyển tập/合集" chỉ khi video dài hơn **gấp đôi**
  giới hạn (trước đó hiện cả với video 11 phút bình thường). Lưu ý: dòng dịch trong `dub.py` từng có ký tự "–" bị hỏng mã hoá thành "�" — đã thay
  bằng "-". **Chưa thử thật video 20–30 phút** (thời gian TTS nối tiếp ~3 s/câu: video 30 phút ~400 câu ≈ 20 phút chỉ riêng bước giọng đọc).
- **Bước 5 của clip lồng tiếng** (26/10): board `template_id = "dub"` không có cảnh/ảnh nên Bước 5 thường hiện "0 clip sẵn sàng" + "Ghép lại"
  bị khoá, không có đường quay lại chỉnh (người dùng hỏi). `StepExport` nhận `dubJobId` (`QuicktoolApp` lấy `quicktool.dub.job_id`): thẻ bên trái
  thay bằng "Chỉnh phụ đề, giọng đọc, bản dịch" + nút **"✏️ Mở trang chỉnh phụ đề & giọng"** → `/tools/dub?job=<id>`; thẻ Kết quả (tải về,
  lên lịch, ảnh bìa) và bài đăng Facebook giữ nguyên. Chỉnh + "Áp dụng"/"Render lại" ở trang Lồng tiếng cập nhật cùng board.
- **Lồng tiếng: khung video + nhân vật nhún nhảy** (26/10, trong khung "Vị trí phụ đề & làm mờ chữ gốc", in chung lượt "✓ Áp dụng"):
  `layout.frame = {scale 0.6–1, bg blur|color, color, border 0–0.03 (tỉ lệ chiều cao), border_color}` và `layout.mascot = {media_id, x, y (đáy-giữa,
  tỉ lệ khung), size 0.08–0.6 (tỉ lệ chiều cao), motion dance|bounce|sway|none, shape circle|plain}` — `services/dub_decor.py` (`normalize_frame/mascot`,
  `frame_filter`, `prepare_mascot`, `mascot_input_args`, `mascot_filter`). Thứ tự graph ffmpeg trong `dub.video_filter`: **nguồn → khung (split, nền
  scale+boxblur hoặc drawbox màu, video thu nhỏ + pad viền, overlay giữa) → vùng mờ → nhân vật → phụ đề**, nên mọi vị trí là tỉ lệ của khung đầu ra.
  Nhân vật chuẩn bị **một lần bằng Pillow** (cắt vuông từ trên xuống — mặt nằm trên, mặt nạ tròn khử răng cưa + viền trắng; hoặc giữ ảnh) rồi
  overlay ảnh tĩnh lặp `-loop 1 -framerate 30` (geq mỗi khung quá chậm cho video dài); GIF động + "giữ nguyên" thì overlay thẳng `-ignore_loop 0`;
  chuyển động = `rotate` theo `t` + biểu thức x/y của `overlay` (`eval=frame:shortest=1` để nhân vật lặp không kéo dài video). Nhân vật lấy từ
  **Người mẫu đã lưu** hoặc tải ảnh/GIF `POST /api/dub/mascot` (≤ 10 MB, Asset ảnh cục bộ, không lên Flow). Engine Remotion: composition vẽ
  khung (video nền blur CSS + video thu nhỏ + box-shadow viền) và nhân vật (`mascotMotion` cùng công thức), `render.mjs` phục vụ thêm file nhân vật
  (`spec.mascot_file` → `/mascot.<ext>`); GIF trong Remotion chỉ hiện khung đầu. Khung chỉnh (`SubPositioner`) giờ xem trước trên **video gốc**
  (`/media/<source_media_id>`, không phải bản đã render) với khung CSS + nhân vật kéo thả (+ CSS animation); điều khiển ở `dub/DecorControls.tsx`.
  Thử thật: in lại khung + người mẫu tròn nhún nhảy 12 s cho video 12,6 s (dùng lại giọng), ảnh khung hình đúng. Test `test_dub_decor.py` (5, có 2 lần
  dựng ffmpeg thật: ảnh tròn + GIF động).
  **AI chat + mẫu đã lưu (26/10)**: trên cùng mục khung/nhân vật là ô **"💬 Nhờ AI tạo khung / nhân vật"** (`DecorControls`): `POST
  /api/dub/decor/chat {message, history, frame, mascot, orientation}` → `services/decor_ai.chat` — system prompt chỉ làm khung + nhân vật (hỏi
  việc khác thì từ chối nhẹ, không đổi gì), đọc khung/nhân vật hiện tại, hướng video, **các mẫu đã lưu (gu của người dùng)** và 8 lượt chat gần nhất →
  JSON `{reply, frame | "off" | null, bg_prompt, mascot | "off" | null, image_prompt}` (prompt ảnh tiếng Anh: nền trang trí giữa trống không chữ; nhân
  vật một mình, toàn thân, nền trắng trơn, không người thật). Trình duyệt vẽ ảnh bằng `generateStandaloneImage` (Flow, ~25–40 s, chạy song song) →
  nền khung `frame.bg = "image"` + `bg_image`; nhân vật dạng "plain" → `POST /api/dub/decor/cutout` (`dub_decor.cutout`: màu viền trung vị, loang
  từ mép các điểm gần màu đó thành trong suốt, viền mềm, cắt sát; ảnh có viền rối thì để nguyên; **tự tải ảnh Flow vừa vẽ về** bằng
  `fetch_and_cache` — bẫy: gọi ngay sau khi vẽ thì ảnh chưa có trên máy). Khung nền ảnh: ffmpeg thêm input ảnh lặp (`frame_filter(bg_index)`,
  `scale+crop` phủ khung, `shortest=1`), Remotion `<Img>` + `render.mjs` phục vụ `/framebg.<ext>`; `dub_decor.local_media` tải ảnh về khi dựng nếu
  máy chưa có. **★ Mẫu đã lưu**: bảng `DecorPreset` (kind frame|mascot, name, data JSON đã chuẩn hoá, thumb, uses; `create_all` tạo — đã tạo trên
  Neon), `GET/POST /api/dub/decor/presets`, `POST …/{id}/use` (đếm lượt, xếp mẫu hay dùng lên đầu), `DELETE …/{id}`; UI: "★ Lưu khung này" / "★ Lưu
  nhân vật này" (tên "Khung n · gợi ý từ câu chat"), danh sách thẻ có ảnh/ô màu, bấm để dùng, × để xoá. Thử thật 26/10: "khung hoa đào hồng nhạt,
  viền trắng; bé chibi mẹ bầu vẫy tay góc dưới phải, nhún nhảy" → 44 s ra nền hoa đào + bé chibi đã tách nền (PNG trong suốt); lưu mẫu chạy (mẫu thử
  đã xoá). Test thêm 5 (`test_dub_decor.py` 10).
- **Lồng tiếng: trình chỉnh sửa kiểu CapCut** (26/10, thay `SubPositioner` + bảng "Bản dịch" + mục `<details>` cuộn dài): mở một video đã có câu
  (`DubPage`: `segments` có và trạng thái review/done/error hoặc đã có `media_id`) → `quicktool/dub/editor/DubEditor.tsx` chiếm cả trang, vừa một màn
  hình (`.dx` cao `100vh − 104px`): thanh trên (← Danh sách, tên, trạng thái "● Chưa xuất: …" / tiến độ + Dừng, ↶ ↷, ▶ Bản đã xuất, ⬇ Tải, Mở clip,
  **✓ Xuất lại video** ghi rõ "đọc lại giọng" hay "nhanh"); giữa `EditorStage.tsx` (video gốc + **giọng Việt `voice.wav` (+ `bgm.wav`) phát đồng bộ**
  bằng `<audio>`, vòng rAF chỉnh lệch > 0,25 s; Remotion đã render thì là `<Player>` thật; chọn nghe Giọng Việt / Tiếng gốc / Tắt): phụ đề **đúng câu
  tại thời điểm đang xem** (cắt hộp y như `split_cue`/`sub_max_chars`, mirror trong `editor/cues.ts`), kéo để dời, chấm cam kéo ngang đổi cỡ, **bấm đúp
  để gõ thẳng trên hình** (Enter lưu, Esc huỷ), vùng mờ + nhân vật kéo như cũ; phải `Inspector.tsx` 5 tab: 💬 Phụ đề (câu đang chọn: câu gốc, ô sửa, số
  ký tự/giây — > 17 là cảnh báo đọc nhanh, giờ bắt đầu/kết thúc ±0,1 s, Bỏ câu, Về bản dịch / thời gian cũ, ▶ Nghe câu này; kiểu chữ + cỡ + vị trí cho mọi
  câu), 📜 Các câu (cả bản dịch, sửa tại chỗ), 🌫 Làm mờ, 🎨 Trang trí (`DecorControls`), ⚙ Xuất (tên, giọng, engine, nhạc nền, kênh); dưới
  `EditorTimeline.tsx` dùng **`@xzdarcy/react-timeline-editor` 1.0.0** (MIT, gói sẵn react-virtualized/interactjs nên không dính lỗi Vite; CSS
  `dist/react-timeline-editor.css`, kiểu `TimelineAction/Row` import từ `@xzdarcy/timeline-engine`): hàng Video (dải hình `GET /api/dub/jobs/{id}/filmstrip.jpg`
  = `dub.filmstrip`, ffmpeg `tile`, video > 4 phút chỉ giải mã key frame), **Phụ đề (mỗi câu một khối: kéo để dời, kéo mép để kéo dài/rút ngắn, không
  vượt câu bên cạnh — `minStart/maxEnd`)**, Giọng (sóng âm `wave.png` = `dub.waveform`, `showwavespic`, vẽ lại khi voice.wav mới hơn), Làm mờ / Khung /
  Nhân vật (khối cả clip, bấm để chọn); zoom −/+/thanh trượt/"Vừa khung", vạch ruler tự chọn bước 0,5 s…10 phút, con trỏ cam theo giờ đang phát (tự cuộn
  theo). Đồng hồ thuộc stage; timeline chỉ `setTime` qua ref và gọi `seek`. **Hoàn tác / làm lại** (Ctrl+Z / Ctrl+Shift+Z, gộp các bước của một lần
  kéo trong 0,9 s). Phím: Space, ←/→ từng khung (Shift 1 s), ↑/↓ câu trước/sau, Enter sửa chữ, Delete bỏ câu. Rời trang khi chưa xuất → trình duyệt hỏi.
  Đang render thì chỉ xem (khoá sửa); render xong tài liệu nạp lại từ job. Backend: `POST …/render` nhận **`timings: [[start, end]…]`** →
  `dub.apply_timings` (giữ thứ tự, không chồng, trong video, tối thiểu `MIN_SLOT_S` 0,3 s); **`voice_key` giờ gồm cả mốc giờ** (dời câu → đọc lại giọng;
  TTS lấy từ cache nên chỉ tốn atempo + ghép), khoá kiểu cũ được `_upgrade_voice_key` coi là còn hợp lệ; `job.public()` có `voice_url`, `bgm_url`; routes
  `GET /jobs/{id}/voice|bgm|filmstrip.jpg|wave.png`. Test `test_dub_editor.py` (4).
  **Độ rộng + chỉnh riêng từng câu (27/10)**: tay nắm hai mép phụ đề trên video đổi **độ rộng** `layout.w` (tỉ lệ khung, `W_MIN` 0,2–`W_MAX` 0,96,
  null = tự động như cũ), **không đổi cỡ chữ** (cỡ chữ chỉ ở thanh "Cỡ chữ" / phím +/−). `sub_max_chars` khi có `w`: chữ vừa `w` (trừ đệm hộp), hệ số
  **0,5 em/ký tự** (đo trên khung đã in; chế độ tự động giữ 0,56 + trần 34); `cues.ts subMaxChars` mirror. Remotion: hộp phụ đề `width: max-content` +
  `maxWidth = w (88 % khi tự động)` — **sửa lỗi hộp bị bóp còn (1 − x) khung nên câu ngắn gãy 3 dòng** (thấy 26/10). Mỗi câu có thể có **`look`**
  `{x?, y?, scale?, w?}` riêng (`Segment.look`, `normalize_look`, `effective_layout`; lưu trong job.json; `POST …/render {looks}`; chỉ đổi hình nên giữ
  giọng): ASS ghi `\pos` + `s`/`ord` riêng cho event của câu đó, Remotion nhận `look` trên từng cue. UI: tab Phụ đề có công tắc **"Chỉnh cho: Riêng
  câu này / Tất cả câu"** (nhớ localStorage `flowboard.dub.scope`, mặc định riêng câu) — kéo trên video + thanh trượt đổi đúng phạm vi đó (câu đã có
  look thì kéo nó luôn sửa look của nó, kể cả ở "Tất cả câu"); câu khác kiểu chung có nút **"⇪ Áp cho tất cả câu"** (look của câu thành kiểu chung, bỏ mọi
  chỉnh riêng) và "↺ Câu này theo kiểu chung"; "Đồng bộ tất cả theo kiểu chung" khi còn N câu riêng; timeline đánh dấu câu riêng bằng ✎ + viền xanh
  ngọc. Kiểu phụ đề (style) vẫn chung cả clip. Test `test_dub_editor.py` (7).
- **Lồng tiếng: nhiều vùng mờ + "Khung xuất" (định dạng video ra)** (29/10, người dùng: "video gốc hay có text nhiều chỗ" + "xem trước ở các định dạng 16:9, 4:3… để khỏi làm lại"): `layout.blurs` = danh sách vùng mờ (≤ `MAX_BLURS` 8; layout cũ chỉ có `blur` vẫn đọc thành danh sách 1 vùng, `blur` = vùng đầu để code cũ đọc; gửi `blurs: []` là bỏ hết). `layout.canvas = {aspect: 9:16|16:9|4:3|3:4|1:1|4:5, fit: blur|black|crop, pos 0–1}` — 31/10 thêm nền màu / lưới / ảnh / video + cỡ video, xem mục "nền tuỳ chỉnh" dưới (`normalize_canvas`, None = kích thước gốc). `canvas_size(w, h, layout)` giữ cạnh dài của video gốc theo tỉ lệ mới (1280×720 → 9:16 = 720×1280, 1:1 = 1280×1280; cùng tỉ lệ thì giữ nguyên). Graph ffmpeg (`video_filter(…, source=(w,h))`): **zoom (trên ảnh gốc) → `canvas_filter` (nền mờ = bản thu nhỏ ¼ boxblur rồi phóng lại + ảnh gốc contain ở giữa; viền đen = pad; cắt = scale increase + crop lệch theo `pos`) → khung trang trí → từng vùng mờ (`blur_filter(tag=i)`, nhãn `[vb{i}…]`) → nhân vật → ASS**; mọi vị trí (phụ đề, vùng mờ, nhân vật, chữ nhấn) là tỉ lệ của khung xuất; `_render` / `render_clean_video` / Remotion dùng `out_w/out_h`. `has_picture_layers` tính cả canvas (Edit auto CapCut dựng video nền theo khung). Remotion: `build_spec` chép thêm `blurs` + `canvas` (**bẫy dính lúc làm**: `build_spec` chỉ chép vài khoá layout → render Remotion ra nền đen + thiếu vùng mờ 2 dù gói đã đóng lại), `DubSubtitles` `picture()` (bản mờ cover + ảnh contain, hoặc cover + `objectPosition`). Frontend: `api/dub.ts` `DubCanvas`, `CANVAS_ASPECTS`, `CANVAS_FITS`, `canvasSize` (mirror), `layoutBlurs`, `withBlurs`, **`normLayout`** (cùng khoá + thứ tự để doc / job so dirty); `dub/editor/FormatBar.tsx` (thanh "Khung xuất" trên sân khấu: Gốc + 6 tỉ lệ có hình nhỏ, Nền mờ / Viền đen / Cắt cho đầy, "Vị trí cắt", "→ W×H"; ẩn nút trùng tỉ lệ gốc; `sourceRect` / `sourceBoxToFrame` đổi toạ độ ảnh gốc → khung xuất, tính cả khung trang trí); `DubEditor` truyền `frameW/frameH = canvasSize(...)` cho sân khấu, Player, `splitAll`; sân khấu vẽ video theo fit (CSS `object-fit`, bản mờ `canvasBg` đồng bộ như `bgVideo`); `Sel {kind:"blur", i}`; tab 🌫 Làm mờ = danh sách vùng (chọn / 🗑 / ＋ Thêm vùng mờ / Bỏ hết / "Độ mờ này cho mọi vùng", thêm thanh "Vị trí ngang"); **OCR thêm một vùng cho mỗi dải chữ** (đổi sang toạ độ khung xuất, bỏ dải đã có vùng phủ > 50 %); timeline "Làm mờ (N)"; "⇪ Áp cho cả loạt" mang theo vùng mờ + khung xuất. Test `test_dub_canvas.py` (8, có ffmpeg thật cả 3 kiểu fit).
- **Lồng tiếng: "📱 Xem trên" nền tảng** (29/10, người dùng: "xuất 16:9 mà lên TikTok sẽ ra sao, xem được không?") — chỉ để xem, không đổi video xuất: ô chọn ở thanh Khung xuất (TikTok / Facebook-Instagram Reels / YouTube Shorts / Facebook bảng tin / Instagram bảng tin / YouTube máy tính; nhớ localStorage `flowboard.dub.platform`). `dub/editor/platforms.ts`: mỗi nền tảng = tỉ lệ màn hình (điện thoại 9:19,5, YouTube 16:9), `zone(tỉ lệ video)` = chỗ video nằm + `contain` / `cover` + lời giải thích (màn dọc toàn màn hình: video vừa khung phía trên thanh menu; **bảng tin FB / IG cắt video cao hơn 4:5 về 4:5**), `chrome(zone)` = các phần giao diện app (`over: true` = phủ lên video: cột nút phải, mô tả, thanh tab; `false` = ngoài video: menu, đầu bài, thanh Thích) — **toạ độ ước lượng theo bố cục phổ biến, app đổi giao diện thì chỉnh ở đây**. `DeviceChrome.tsx` vẽ mô phỏng (nút ❤💬↗, @tên kênh, menu…; phần phủ lên viền đỏ đứt). `EditorStage` (prop `platform`): đo vùng (`areaSz`), `geo` = màn hình → vùng video → khung xem trước đặt vừa / cắt trong vùng (khung vẫn kéo / sửa được), `DeviceNotes` dưới máy: lời giải thích + **cảnh báo phụ đề / nhân vật bị phần giao diện che hoặc bị cắt mất** (đo ô phụ đề thật trên DOM, đổi sang toạ độ màn hình, `overlaps`). Phụ đề ngang rộng 88 % ở y 0,8 luôn bị cột nút phải của TikTok / Shorts che — đúng thực tế.
- **Lồng tiếng: "★ Mẫu chỉnh sửa" (look preset)** (29/10, người dùng: "tránh mỗi clip lại phải edit một kiểu"): một mẫu = **toàn bộ kiểu không phụ thuộc clip** — layout (vị trí / cỡ / độ rộng phụ đề, các vùng mờ, khung xuất, khung trang trí, nhân vật), `style`, `engine`, cài đặt nhấn chữ (không gồm các chỗ nhấn — mỗi clip AI chọn riêng); chữ / mốc giờ / look từng câu không nằm trong mẫu. Lưu ở bảng `DecorPreset` **kind `look`** (`dub.normalize_look_preset`; `GET /api/dub/decor/presets?kind=look`, không `kind` thì chỉ trả frame + mascot như cũ cho bảng Trang trí; `POST` kind look). **Mẫu mặc định** = AppSetting `dub_default_look` (`dub.LOOK_PRESET_KEY`; `GET/PUT /api/dub/decor/presets/default {id}`, xoá mẫu thì default tự thành None). **Job mới dùng mẫu**: `StartBody.look_preset_id` → `dub.look_preset(id)` (DubError → 404 nếu mẫu đã xoá, đếm `uses`; `dub.default_look_id()`, `dub.apply_look(job, look)` dùng chung) → `start_job(layout=, highlights=)` + style / engine của mẫu thắng body. **✂️ Cắt video cũng dùng mẫu (9/11, bản 1.8.2)**: form có ô "Mẫu chỉnh sửa cho các video cắt ra" (chọn sẵn mẫu mặc định) → `POST /api/cut/sessions {look_preset_id}` → `Session.look` (lưu session.json) → `_part_job` mới `dub.apply_look`; `_cut_all` gọi `dub.render_job` ngay cho phần nào `video_cut.needs_render` (layout khác mặc định / có phụ đề / nhấn chữ — cả phần cắt lại đang có kiểu riêng) → video cắt ra đã có khung 9:16 + nền + nhân vật, trang Cắt hiện ⏳ tới khi xuất xong. UI: trình chỉnh sửa có nút **"★ Mẫu"** (`dub/editor/LookPresets.tsx`, popover: "★ Lưu kiểu hiện tại" (prompt tên; mẫu đầu tiên tự thành mặc định), mỗi mẫu một hàng: tên (bấm cũng áp) + nút **"✓ Áp dụng"** (một bước hoàn tác, giữ chỗ nhấn của clip; `setOut engine`) + "Mặc định" bật / tắt (chỉ cho video mới, không đổi clip đang mở — ghi rõ ở tooltip + dòng gợi ý) + 🗑; 9/11 thêm nút Áp dụng vì người dùng bấm "Mặc định" 3 lần mà clip không đổi, xem Bẫy); trang Lồng tiếng mục 2 có ô **"Mẫu chỉnh sửa"** (chỉ hiện khi đã có mẫu; chọn sẵn mẫu mặc định; chọn mẫu thì ô Công nghệ + Kiểu phụ đề khoá). `api/dub.ts`: `LookPresetData`, `listLookPresets`, `saveLookPreset`, `getDefaultLook`, `setDefaultLook`, `DubStart.look_preset_id`. Test `test_dub_look_presets.py` (2) + `test_video_cut.py` (phần cắt ra render theo mẫu, route 404 mẫu đã xoá). Chưa có: mẫu cho Edit auto CapCut, mẫu theo kênh (kênh nào mẫu nấy).
- **Lồng tiếng: "📂 Chỉnh lại video đã làm"** (28/10, người dùng: "edit xong rồi bỏ vào lại để edit tiếp lúc khác, qua ngày hôm sau"): ô đầu cột trái
  trang `/tools/dub` (chọn file) + **thả file video vào bất cứ đâu trên trang** (lớp phủ "Thả video vào để mở lại…") → `POST /api/dub/identify` (file chỉ
  được đọc rồi xoá, ≤ 2 GB) → mở lại trình chỉnh sửa đúng dự án; video là clip làm ở wizard thì sang `/clips/<id>/export`. Nhận ra bằng 3 cách theo thứ tự
  (`dub.identify`): (1) **dấu trong file** — mọi mp4 lồng tiếng ghi `comment=flowboard-dub:<job id>` (`output_tag`; ffmpeg ghi thẳng lúc encode, Remotion
  remux `-c copy` bằng `_tag_file` **trước** khi thành Asset để B2 cũng có dấu), đọc bằng `read_tag` (ffprobe `format_tags`); (2) **dấu vân tay**
  `job.outputs` [{media_id, size, sha256, at}] (`_record_output` sau mỗi lần render, 30 bản gần nhất, lưu job.json); (3) **file cũ chưa có dấu**: so với
  video cuối của mọi clip (node export/merge → Asset, lọc cùng kích thước rồi mới băm), clip lồng tiếng thì ra job của nó. Nền tảng khác nén lại (tải về
  từ TikTok/FB, qua CapCut/Zalo) thì không còn nhận ra — báo lỗi rõ. **Dự án sống cả khi mất `job.json`**: `_save_board` lưu `quicktool.dub.snapshot`
  (`snapshot()`: câu + mốc giờ + look, layout, kiểu, giọng, engine, kích thước, nguồn, outputs) lên board (Neon); `find_job` = `load_jobs` rồi
  `restore_from_board` (dựng lại job, ghi job.json mới; nguồn tải từ B2 nếu thiếu; chưa có voice.wav thì lần xuất sau đọc lại giọng, TTS lấy cache nếu có);
  route `_job()` dùng `find_job`. Clip làm trước 28/10 được **bù snapshot** một lần mỗi lần chạy (`backfill_snapshots`, gọi ở `GET /api/dub/jobs`).
  Chọn file để lồng tiếng mới mà tool nhận ra → hộp "🎬 Video này bạn đã làm bằng tool… [✏️ Mở lại để chỉnh]". "Gần đây" chỉ hiện 5 video mới nhất; **"Xem tất cả (N)"** mở hộp thoại
  `dub/DubJobsDialog.tsx` (portal vào `document.body`; tìm theo tên/link, lọc Tất cả / Xong / Chờ sửa / Lỗi / Đang chạy có số đếm, bảng tên + nguồn +
  tiếng gốc / trạng thái / thời lượng / số câu / ngày làm, 10 dòng một trang với `.qt-pager` có dấu "…", Esc / bấm nền để đóng, "Mở" hoặc bấm đúp dòng).
  **🗑 Xoá khỏi danh sách** (28/10, người dùng: "xoá ở log này thôi, video chưa bị xoá thì vẫn phải còn"): ô chọn từng dòng + ô chọn cả trang + "Chọn cả N
  mục đang lọc", nút 🗑 từng dòng, thanh xác nhận đỏ (Huỷ / "🗑 Xoá N mục"; Esc thoát xác nhận trước). `POST /api/dub/jobs/delete {ids}` →
  `dub.delete_jobs`: bỏ job khỏi `JOBS` + xoá thư mục làm việc `media/dub/<id>/` (job.json, voice/bgm/vocals/full44/speech16 wav, nosub.mp4, filmstrip —
  có cái vài trăm MB; chỉ xoá khi thư mục nằm đúng trong `media/dub/`), **không đụng** video đã xuất (Asset trong media/), video gốc, clip (board).
  Job đang chạy bị từ chối ("dừng trước rồi xoá"). Clip vẫn giữ snapshot nên thả video vào trang / link Bước 5 vẫn mở lại được (job hiện lại trong danh
  sách; lần xuất sau đọc lại giọng, lấy từ cache TTS nếu còn). Mục chưa xuất video (chờ sửa / lỗi) thì mất luôn bản dịch — thanh xác nhận nói rõ.
  Cả hai danh sách dùng `GET /api/dub/jobs?all=true&brief=true` (bỏ câu, `lines` = số câu; `limit` cho bản đầy đủ; `public()` có thêm `started_at`) →
  "Mở" tải job đầy đủ (`openJobById`). `pickNewFile`, `reopenFromFile`, `openMatch`, `onDropPage` trong `DubPage.tsx`; `identifyVideo`, `listDubJobsBrief`
  (`api/dub.ts`). Test `test_dub_reopen.py` (6).
- **Lồng tiếng: loạt video (batch) + mỗi link một ô** (27/10): ô link là **một `<input>` mỗi link** (`DubPage` `links[]`, tối đa `MAX_LINKS` 5):
  dán một lúc nhiều link (mỗi dòng một link, hoặc nhiều đoạn share Douyin) → `linksIn()` (`api/dub.ts`) tách URL → mỗi link một ô; Enter thêm ô,
  × bỏ, Backspace ở ô trống bỏ ô. ≥ 2 link → `startDub(batch_id=<id client tạo>)` cho từng link; `Job.batch_id` (lưu job.json, `public()`),
  `GET /api/dub/jobs?batch=<id>` trả các job của loạt theo thứ tự dán. UI: cột phải hiện **bảng loạt** (từng clip: trạng thái, %, Dừng) và
  **chỉ mở trình chỉnh sửa khi cả loạt xong** (không còn queued/running/rendering); mở job có `batch_id` từ "Gần đây" hay `?batch=` cũng vào chế độ
  loạt. Trình chỉnh sửa (`DubEditor` props `siblings`, `onSwitch`, `onApplyAll`): **select "Clip n/N"** ở thanh trên thay tên (đổi clip có hỏi khi
  còn thay đổi chưa xuất; URL `?batch=&job=`), nút **"⇪ Áp cho cả loạt (N)"**: xuất clip đang mở nếu còn thay đổi rồi `POST …/render {layout, style,
  engine}` cho từng clip khác (giữ giọng; chữ / mốc giờ / câu chỉnh riêng của từng clip không đổi; clip đang chạy hoặc chưa có bản dịch thì bỏ qua +
  báo). Nút "việc đang chạy" link `?job=&batch=` (`isHere` so từng tham số, không phụ thuộc thứ tự). Thử thật Playwright: dán 3 link → 3 ô, loạt 2 clip
  mẫu (Edge) 67 s → mở editor có select, "Giữa" + Áp cho cả loạt → clip 2 in lại 4 s với y = 0,55, chuyển clip qua select đúng URL. Clip thử đã xoá.
- **Lồng tiếng nhanh hơn** (28/10): bước giọng Edge đọc 8 câu một lúc vào cache TTS (`_prefetch_edge`, phase "Đang tạo giọng đọc (k/N, 8 câu một lúc)"),
  vòng lặp sau chỉ lấy từ cache + đọc lại câu bị từ chối theo vòng; khớp độ dài (atempo) chạy song song `CONVERT_PARALLEL` 4 luồng (`fit` trong
  `_voice_pieces`, thứ tự giữ nguyên); **tách nhạc nền chạy song song với bước giọng** (luồng `dub-bgm-<id>` gọi `_separate_bgm` ngay đầu `_render`
  khi cần đọc lại giọng; xong bước giọng thì `join`, lỗi tách nhạc báo sau). Gemini / VieNeu / FPT không đổi (Gemini có quota phút, VieNeu đã gom
  một lượt). Đo thật video Douyin 3:35, 89 câu, Edge Nam Minh, giữ nhạc nền: tải 6 s · Whisper 22 s · dịch 30 s (2 đợt) · giọng 77 s · khớp 3 s ·
  ghép 2 s · in hình 14 s = **156 s**; tách nhạc không còn là bước riêng. Test `test_a_line_edge_keeps_refusing_gets_another_round`,
  `test_music_is_separated_while_the_voice_is_read` (`test_dub_editor.py`).
- **Lồng tiếng: hàng đợi + nhiều link** (25/10): `POST /api/dub/jobs` không từ chối khi đang có việc chạy nữa — job vào `queued`
  (`MAX_QUEUE` 5 đang chờ), `_pump()` chạy lần lượt một video (Whisper/spleeter dùng chung GPU), gọi từ start / render / cuối
  `_run_job`; phase "Chờ đến lượt (n video trước)"; render lại cũng xếp hàng (`_render_only`). Ô link của DubPage là textarea, mỗi dòng
  một link (≤ 5), "Gần đây" tự tải lại 4 s khi còn việc. Test `test_jobs_queue_one_at_a_time`.
- **Lồng tiếng: "Dịch bằng" Google (mặc định) hoặc AI** (30/10, người dùng: "pyvideotrans lồng tiếng bình thường, làm cho giống"): `services/free_translate.py` — `translate_lines(lines, source, target="vi")` → `(bản dịch từng dòng, "google"|"microsoft")`: lô ≤ `BATCH_LINES` 25 dòng / ≤ `GOOGLE_MAX_CHARS` 700 ký tự (`batches`), mỗi lô thử **Google** `translate.googleapis.com/translate_a/single?client=gtx` (GET, các dòng nối "
", câu trả lời giữ đủ dòng; `zh` → `zh-CN`) 3 lần, rồi **Microsoft** `edge.microsoft.com/translate/translatetext` (POST danh sách, mỗi dòng một kết quả); số dòng lệch thì không thử lại mà sang dịch vụ kia; cả hai hỏng → `TranslateError`. Dòng trống giữ trống. Đo thật: 185 câu tiếng Trung 10,5 s. `dub.py`: `TRANSLATORS` {google, ai}, `DEFAULT_TRANSLATOR = "google"`, `Job.translator` + `translated_by` (job.json, `public()`), `normalize_translator`, `start_job(translator=)`; `_translate` → `_translate_free` khi không phải "ai" (tiêu đề = dịch tiêu đề tải về đã bỏ hashtag `_title_source`, không có thì câu đầu); đường AI như cũ (lô 60 câu, giới hạn từ) nhưng lô nào lỗi (LLMError / JSON hỏng) thì **phần còn lại dịch bằng Google**, `translated_by = "google (AI lỗi: …)"`. Routes: `StartBody.translator`, `LinkQueueBody.translator` (→ `options.translator` của thư viện link, link xếp hàng trước đó không có thì Google), `status.translators`. UI `DubPage` ô **"Dịch bằng"** (Google Dịch — miễn phí / AI theo Cài đặt — tốn lượt AI; nhớ localStorage `flowboard.dub.translator`), dòng cài đặt của Thư viện link ghi "dịch bằng …". Google không biết giới hạn từ mỗi câu → câu Việt có thể dài hơn chỗ, phần ép tốc độ (tới 1,45×) + phụ đề theo giọng (`follow_voice`) lo như VieDub. Test `test_free_translate.py` (9).
- **Lồng tiếng: "📚 Import từ thư viện" (thư viện link)** (30/10, người dùng: import file .txt / .md, có link thì lấy hết ra, xếp hàng đợi, biết link nào đã lồng tiếng): bảng **`DubLink`** (`url`, `key`, `label`, `source` = tên file, `position`, `queued`, `queued_at`, `options` JSON, `job_id`, `error`; `create_all` tạo — đã tạo trên Neon). `services/dub_links.py`: `extract_links(text)` (mọi link http(s) theo thứ tự, bỏ trùng; nhãn = chữ của link markdown `[chữ](link)` — thay link md bằng URL trước khi dò vì `_URL_RE` nhận cả `[]()` —, không thì phần còn lại của dòng, vd. tiêu đề đoạn share Douyin; bỏ dấu câu / `)` thừa cuối link), **`link_key(url)`** = khoá chung của một video dù viết kiểu nào (`douyin:<id>` từ `/video/`, `share/video`, `?modal_id=`; `tiktok:<id>`; `youtube:<id>` từ youtu.be / watch?v / shorts / embed; `bilibili:BV…`; còn lại host + path + query đã bỏ tham số theo dõi `utm_`, `share`, `si`…), `key_for` theo redirect của link rút gọn (`SHORT_HOSTS` v.douyin.com, vt/vm.tiktok.com, b23.tv, xhslink — `resolve_final` chỉ đọc header, nhớ trong RAM, lỗi thử lại sau 10 phút), `keys_of` = {khoá thường, khoá đã theo redirect} — hai link khớp khi chung một khoá. `import_texts([{name, text}])` (≤ 20 file, ≤ 2 triệu ký tự / file, ≤ 2000 link / lượt; link rút gọn đi theo redirect song song 8 luồng; link đã có trong thư viện không thêm lại). **Trạng thái** (`library()` → `_row`): gom bằng chứng `_evidence()` = mọi job lồng tiếng (`dub.load_jobs`, theo `keys_of(job.url)`) + clip lồng tiếng mà job đã rời danh sách (`_dubbed_boards`: board `template_id: "dub"`, `quicktool.dub.snapshot.url`) → `new` | `waiting` (đang chờ trong hàng đợi thư viện) | `running` (job queued/running/rendering) | `review` | `done` (`done_count` = số lần) | `error` | **`other`** (không phải link TikTok / Douyin / YouTube / Instagram / Facebook / X — `is_video_link` dùng đúng `_host_allowed` của reference-video vì lồng tiếng chỉ tải được các host đó; vẫn liệt kê, không xếp hàng được). **Hàng đợi thư viện**: `queue(ids, options)` lưu tuỳ chọn lên từng dòng (giọng, nhạc nền, kiểu, engine, kênh, `auto_render`, + `layout`/`highlights` của Mẫu chỉnh sửa đã giải sẵn), bỏ qua link đang chạy / không phải video; **`feed()`** bắt đầu link kế (theo `queued_at` = thứ tự đã tick) **chỉ khi hàng đợi lồng tiếng không có ai chờ** → một chạy + một chờ, link dán tay vẫn còn chỗ (`MAX_QUEUE` 5). Móc vào **`dub.FEEDER`** (gọi đầu `dub._pump` khi `queued_jobs()` rỗng — start_job bên trong gọi lại `_pump` nhưng lúc đó hàng đã có job nên không lặp); `main.lifespan` gán `dub.FEEDER = dub_links.feed_quietly` + `after_activate` → `dub_links.after_login` (cờ `_maybe_queued` để khỏi đọc DB mỗi lần pump); `GET /api/dub/links` cũng gọi feed (sau restart hàng đợi chạy tiếp khi mở thư viện). Link bắt đầu → `job_id` lưu trên dòng, `queued` tắt; start lỗi → `error` trên dòng, sang link kế. Routes `routes/dub.py`: `GET /api/dub/links`, `POST /links/import {files:[{name,text}]}`, `/links/queue {ids, voice, keep_bgm, style, engine, channel_id, auto_render, look_preset_id}`, `/links/unqueue {ids}`, `/links/delete {ids}` (chỉ xoá dòng, job / clip giữ). Nút "đang chạy": `running._dub_link_items` → "Thư viện link lồng tiếng — N link chờ đến lượt" → `/tools/dub?links=1`. Frontend: `api/dub.ts` (`DubLink`, `DubLinkStatus`, `listDubLinks`, `importDubLinks`, `queueDubLinks`, `unqueueDubLinks`, `deleteDubLinks`, `isTextFile`), **`quicktool/dub/DubLinksDialog.tsx`** (portal như `DubJobsDialog`, dùng chung class `qt-dubjobs__*` + `qt-dublinks__*` trong `dub.css`; `pageList` export từ `DubJobsDialog`): khung thả / chọn file (nhiều file; đọc UTF-8, UTF-16 có BOM của Notepad), dòng kết quả import, tìm + lọc (Tất cả / Chưa lồng tiếng / Trong hàng đợi / Đã lồng tiếng / Chờ sửa / Lỗi / Không phải video, có số đếm), bảng 12 dòng / trang (nhãn hoặc tên clip, chip trang web + link mở tab mới, trạng thái + % / lỗi, tên file, "Mở" = mở job trong trình chỉnh sửa / "Mở clip", 🗑), **link mới import được tick sẵn** → một bấm "🎙 Lồng tiếng N link"; chọn cả link đã lồng tiếng → thanh vàng hỏi "Chỉ chạy N link chưa làm / Vẫn làm lại cả M link"; "Chọn cả N link chưa lồng tiếng", "Bỏ N link khỏi hàng đợi", "🗑 Xoá khỏi thư viện" (2 bấm); dòng "Cài đặt dùng cho các link này (lấy từ form Lồng tiếng): …"; tự tải lại 4 s khi có link chờ / chạy. `DubPage`: nút **"📚 Import từ thư viện"** cạnh "＋ Thêm link" (chip "N chưa làm"), `?links=1` mở hộp, **thả file .txt / .md vào trang** cũng mở hộp và import luôn (thả video vẫn là mở lại dự án). Link từ thư viện chạy **không theo loạt** (`batch_id` rỗng) — mỗi video mở riêng, Mẫu chỉnh sửa lo kiểu chung. Test `test_dub_links.py` (7).
- **Lồng tiếng: nền tuỳ chỉnh (màu / lưới / ảnh / video) + "💬 Chỉ chèn phụ đề" + "✂️ Cắt" thành nhiều clip** (31/10, người dùng: nền kiểu
  khung sọc như ảnh mẫu — video ngang trong khung dọc trên nền lưới; cắt thủ công start–end hoặc AI gợi ý; video chỉ cần phụ đề thì làm nhanh hơn;
  tham khảo VieDub — cắt kiểu hàng {tên, a, b} + ⏱ + "Chia đều", nền Mờ / Màu / Ảnh / Video):
  - **Nền của Khung xuất**: `layout.canvas.fit` thêm `color` | `grid` | `image` | `video` (cạnh `blur` / `black` / `crop` cũ) + `scale` 0,5–1 (cỡ video
    trong khung), `color`, `line` (màu vạch lưới), `cell` 0,04–0,3 (cỡ ô theo tỉ lệ cạnh ngắn), `media_id` (ảnh / video nền) — `dub.normalize_canvas`,
    `CANVAS_DEFAULT` (#211915 / #4a3a2e / 0,11 — giống ảnh mẫu). `canvas_rect(src_w, src_h, W, H, canvas)` = chỗ video nguyên vẹn (vừa khung × `scale`,
    `pos` dời theo phía còn trống nhiều hơn), mirror ở `frontend/src/remotion/canvasGeom.ts` (`canvasRect`, `gridCss`). `canvas_filter(…, bg_index)`: màu /
    viền đen = `pad`; lưới = `drawbox` nền + `drawgrid` (lưới cân giữa); ảnh / video = input riêng (`canvas_bg_file` → `canvas_bg_args`: ảnh `-loop 1`,
    video `-stream_loop -1`) scale phủ + overlay `shortest=1`; thiếu file nền → màu. `video_filter(…, canvas_bg_index=)`; `render_clean_video` (Edit
    auto CapCut) cũng dựng nền. Remotion: `build_spec(src_size=)` → props `srcWidth/srcHeight` (+ `canvasBgDurS`), `render.mjs` phục vụ `/canvasbg.<ext>`
    (MIME thêm `.mov`, `.webm`), `DubSubtitles` vẽ nền (video nền lặp bằng `<Loop durationInFrames>` vì `OffthreadVideo` không tự lặp) + video chính đặt theo
    `canvasRect`. Tải nền: `POST /api/dub/background` (ảnh jpg/png/webp ≤ 20 MB, video mp4/mov/webm/gif ≤ 300 MB; GIF đổi sang mp4 `_gif_to_mp4`) →
    `{media_id, url, kind}`. `EditorStage` (props `srcW/srcH`) xem trước nền (`.dx-stage__cbg`) + video ở đúng `canvasRect`.
  - **Video cắt theo hình rồi đặt lên nền** (31/10 tối, người dùng: chọn 4:3 + "Cắt cho đầy" — chuẩn TikTok — rồi muốn nền thay **phần đen TikTok tự
    thêm**; trước đó chọn nền ở khung 4:3 chỉ ra hai dải nền mỏng = "sai"): `canvas.inner` = hình video bên trong ("4:3"…, "" = nguyên hình; chỉ khi
    fit ≠ crop) + `canvas.cut` = chỗ cắt của cả hai kiểu cắt (layout cũ fit crop giữ chỗ cắt ở `pos` → `normalize_canvas` chép sang `cut`). `inner_crop(src_w,
    src_h, canvas)` (mirror `canvasGeom.innerCrop`) → `canvas_rect` đặt phần đã cắt, `canvas_filter` thêm `crop=` trước `scale`; xem trước + Remotion = hộp
    đúng hình + `object-fit: cover` + `object-position` theo `cut`. `FormatBar.tsx` **3 hàng**: Khung xuất (cỡ video ra) → **Video**: "Phủ kín khung" (= crop) /
    "Nguyên hình 16:9" / "Cắt 4:3 · 3:4 · 1:1 · 4:5 · 9:16" (bỏ hình của video gốc và của khung) + Vị trí cắt / Vị trí video / Cỡ video → **Nền** (luôn hiện).
    **Chọn nền khi đang "Phủ kín khung" (hoặc "Gốc")** = giữ nguyên hình đang thấy, chuyển sang khung 9:16 (16:9 nếu "Xem trên" YouTube) với `inner` = khung
    cũ — đúng ý "nền thay phần đen của TikTok"; video gốc đã 9:16 thì thu còn 85 % để thấy nền. `sourceBoxToFrame` (OCR → vùng mờ) tính cả phần bị cắt. Ghi chú
    "📱 Xem trên" TikTok nhắc chọn hàng "Nền". Test `test_dub_bg_sub_split.py` (+3, có ffmpeg thật: dải đỏ mép trái mất khi cắt giữa, còn khi cắt từ trái).
  - **"💬 Chỉ chèn phụ đề"**: `Job.mode` "dub" | "sub" (`MODES`, `normalize_mode`; job.json + snapshot + `public()`). `_render` ở chế độ sub bỏ hẳn đọc giọng,
    tách nhạc nền, khớp độ dài — video giữ nguyên tiếng gốc (`audio_mix_sub`: `0:a:0` + tiếng hiệu ứng nếu có), Remotion mux copy tiếng gốc; tiếng gốc đã là
    tiếng Việt thì không dịch (`translated_by: "none"`); sóng âm timeline lấy tiếng gốc (`wave_src.png`); không có `voice_url`. Đo thật video 25 s tiếng Trung:
    **17,6 s** cả quy trình (Whisper ~11 s, Google dịch ~3 s, in hình ~2 s). Chọn ở trang Lồng tiếng (ô "Làm gì với video" — **luôn mở ở
    "Lồng tiếng Việt"**, không nhớ lựa chọn trước (1/11, người dùng muốn vậy), ẩn giọng + nhạc nền; thư viện link mang theo `mode`) và trình chỉnh sửa tab ⚙ Xuất "Kiểu làm" (đổi qua lại được; sub thì xuất
    luôn kiểu "nhanh"; ô nghe ghi "Tiếng gốc (giữ khi xuất)"). Routes: `StartBody` / `RenderBody` / `LinkQueueBody.mode`. Clip ghi `quicktool.dub.mode`,
    tên node "Video có phụ đề".
  - **Ngôn ngữ phụ đề** (31/10 tối, người dùng: "chèn sub có thể chọn ngôn ngữ hoặc chèn sub gốc từ video"): `Job.sub_lang` (`SUB_LANGS`: vi mặc định /
    **orig** = đúng lời trong video, không dịch / en zh ja ko th id es fr de pt ru; `normalize_sub_lang`; job.json + snapshot + `public()`), chỉ cho chế độ sub
    (lồng tiếng luôn "vi"). `_translate`: orig hoặc trùng tiếng gốc → `text = src`, `translated_by "none"`; ngôn ngữ khác → Google (`_translate_free(target=)`,
    AI chỉ dịch sang tiếng Việt); tên clip vẫn dịch sang tiếng Việt (`_vi_title`). `free_translate` đổi mã đích (`zh` → `zh-CN` Google / `zh-Hans` Microsoft).
    Trình chỉnh sửa: `EditDoc.lang` (Hoàn tác được), tab ⚙ Xuất ô **"Ngôn ngữ phụ đề"** → `POST /api/dub/jobs/{id}/subtitles {lang}` (`dub.subtitle_lines`, không
    lưu gì) → viết lại chữ mọi câu một bước, xuất gửi `sub_lang`; dòng tiêu đề ghi "phụ đề <ngôn ngữ>". Chuyển sang lồng tiếng khi câu không phải tiếng Việt →
    **tự dịch sang tiếng Việt ngay** (`setSubLang("vi", auto)`, một bước hoàn tác, không hỏi; 1/11 — trước đó khoá nút xuất, người dùng tưởng lỗi); dịch
    lỗi / bị hoàn tác thì nút xuất thành "🌐 Dịch sang tiếng Việt"; backend `render_job` vẫn từ chối **trước khi đổi gì**. Trang Lồng tiếng: ô **"Phụ đề bằng"** ngay dưới
    "Làm gì với video" (nhớ localStorage `flowboard.dub.subLang`; ô "Dịch bằng" chỉ hiện khi phụ đề tiếng Việt), thư viện link mang `sub_lang`. **Cắt câu chữ
    Hán / Kana** (không có dấu cách): `text_units` (chữ rộng tính 2), `_cue_tokens` cắt từng chữ, dấu câu dính chữ trước; tiếng Hàn vẫn cắt ở dấu cách —
    mirror `cues.ts` (`textUnits`, `cueTokens`). libass trên Windows tự lấy font có chữ Hán / Nhật / Hàn / Thái (đã thử). Test +5 (`test_dub_bg_sub_split.py`,
    `test_free_translate.py`). Thử thật: video tiếng Anh 18 s → phụ đề tiếng Anh 19 s; đổi sang tiếng Việt trong trình chỉnh sửa, Ctrl+Z về tiếng Anh, xuất
    9:16 + Cắt 4:3 + Lưới (ffmpeg và Remotion ra cùng một khung hình); video tiếng Trung → phụ đề chữ Hán.
  - **"✂️ Cắt" thành nhiều clip** (`services/dub_split.py`, tab ✂️ Cắt `dub/editor/CutPane.tsx`): cắt **video đã xuất** (`job.media_id`; chưa xuất thì báo
    bấm "Xuất lại video" trước; đang xuất thì từ chối) thành các đoạn `{start, end, title}` (≥ `CUT_MIN` 3 s, ≤ `MAX_PARTS` 30, không chồng). Gợi ý:
    **⇔ Chia đều** (`suggest_even`: độ dài mục tiêu 30–180 s ở ô chọn, nhớ localStorage `flowboard.dub.cutTarget`; mốc cắt dời vào khoảng lặng giữa hai câu
    gần nhất trong `SNAP_S` 2,5 s) hoặc **✨ AI gợi ý** (`suggest_ai`: `run_llm("auto_prompt")` đọc các câu có mốc giờ → đoạn trọn ý + tiêu đề tiếng Việt,
    `parts_from_ai` nắn lại; AI lỗi → chia đều + `note`). Tay: thêm / bỏ đoạn, gõ giờ (`m:ss.s`), ⏱ lấy giờ đang xem, ▶ nghe đoạn, ⇥ dời mốc vào khoảng lặng
    gần nhất; hàng lưu lên job (`PUT …/cuts`, debounce). `POST …/split {rows}` → luồng nền: ffmpeg cắt chính xác (re-encode, `-ss` trước `-i`, dấu
    `flowboard-dub:<job>`) → mỗi phần một **clip** (board `template_id: "dub_part"`, `quicktool.dub_part {job_id, index, total, start, end}`, node video +
    export, bước 5); cắt lại thì **dùng lại clip cùng số thứ tự** (bỏ `downloaded_at`); `job.parts` lưu + snapshot. Routes `POST /api/dub/jobs/{id}/split/suggest
    {target_s, ai}`, `PUT /jobs/{id}/cuts`, `POST /jobs/{id}/split`, `GET /jobs/{id}/split`; nút "việc đang chạy" `running._dub_split_items` (`dubsplit:<job>`).
    Bước 5 của clip phần: thẻ "Phần n/N của video lồng tiếng" + nút về trang chỉnh (`StepExport dubPart`, `QuicktoolApp` lấy job từ `dub_part.job_id`).
  - Test `test_dub_bg_sub_split.py` (18: canvas, ffmpeg thật từng kiểu nền, chỉ phụ đề, tiếng Việt không dịch, chia đều / AI / AI lỗi, cắt thật + cắt lại
    dùng lại clip, routes, tải nền, GIF→mp4). Thử thật Playwright (Chrome): job chỉ phụ đề, nền lưới / màu / ảnh trên sân khấu, xuất nền lưới 12 s, cắt 2 phần
    → mở clip phần từ tab Cắt; Remotion nền video (cả video nền 3 s lặp đúng — đồng hồ nền 1,5 s ở 1,5 / 4,5 / 22,5 s); AI gợi ý thật 9 s (3 đoạn, cắt đúng chỗ
    hết câu). Job / clip / phần thử đã xoá.
- **Giọng lồng tiếng mặc định = giọng chọn lần cuối** (1/11, người dùng: lồng tiếng hàng loạt luôn ra Hoài My, muốn mặc định Hải Đăng): pref tài khoản
  **`dubVoice`** trong `store/settings.ts` (`ui_prefs`, theo đăng nhập — cả 2 máy; `isVoiceId` nhận `vi-VN-` / `vieneu:` / `gemini:` / `fpt:`, `setDubVoice`)
  thay cho `useState(DEFAULT_VOICE)` ở `DubPage` và `CapcutPage` (Edit auto CapCut, bước lồng tiếng trước). Hộp **📚 Thư viện link** có hàng **"🎙 Giọng đọc cho link
  xếp hàng · tool nhớ làm mặc định"** (`VoiceField compact`, prop `onVoice`, chỉ khi chế độ lồng tiếng) — chọn ở đây cũng là đổi giọng của form. Link đã xếp hàng
  trước đó giữ giọng lúc xếp (`DubLink.options.voice`): muốn đổi thì "Bỏ khỏi hàng đợi" rồi xếp lại; clip đã làm thì đổi giọng ở tab ⚙ Xuất rồi Xuất lại. Chỉ
  frontend (backend `PUT /api/account/prefs` nhận khoá mới sẵn). Đã đặt `dubVoice = vieneu:Hải Đăng` cho tài khoản akiragosho (Playwright, theo yêu cầu).
- **Bài viết: câu chuyện nhiều kỳ** (25/10): `Post.series` (tên chuỗi) + `Post.episode` (migration `ensure_post_series_columns`,
  đã chạy trên Neon). `POST /api/posts/write {series}` → `_series_context` gom các tập trước (cùng kênh hoặc không kênh, theo
  episode) → `post_writer._series_block`: tập 1 thì dựng bối cảnh + móc tập sau, tập n thì đọc ≤ `SERIES_CONTEXT_EPISODES` (3) tập
  gần nhất (≤ 900 ký tự/tập), mở bằng câu tóm "Tiếp tục câu chuyện lần trước…", thêm một diễn biến mới, kết móc tập n+1, ghi
  "Tập n"; kiểu bài `serial` (27/10: chỉ còn cho brief cũ, không hiện trong form — series là ô Có/Không riêng). Trả về `series`, `episode` để
  lưu. `GET /api/posts/series[?channel_id=]` liệt kê chuỗi (số tập, tập mới nhất). UI: ô "Câu chuyện nhiều kỳ" (datalist các chuỗi
  đã có) ở trang Bài viết và Bước 5; "Bài đã lưu" hiện "<chuỗi> · Tập n". Test `test_series_episodes_feed_the_next_one`.

- **Kênh: link page + "🔎 Xem & đánh giá kênh"** (25/10): `Channel.link` + `Channel.page_review` (JSON; migration
  `db.ensure_channel_link_columns`, Postgres dùng JSONB). Form kênh có ô "Link kênh / page" (không bắt buộc; chỉ Facebook / TikTok /
  Instagram / YouTube / Threads / Zalo, `extract_url` lọc từ cả đoạn dán; đổi link → xoá đánh giá cũ). `POST /api/channels/{id}/review`
  (`routes/channels.py`) → `services/channel_page.read_page`: lệnh extension **`read_channel`** (bản **0.6.0** — manifest thêm quyền
  facebook/instagram/youtube/threads/zalo, **phải Reload extension**): mở link ở tab nền Chrome của người dùng (đã đăng nhập FB), chờ
  tải, cuộn 5 màn để bài gần nhất hiện, đọc `innerText` (bỏ dòng rác "Facebook" lặp + dòng trùng, ≤ 40k ký tự), đóng tab; không có
  extension mới thì thử `product_link.fetch_page` cho trang công khai, trang đòi đăng nhập → lỗi rõ. `channel_page.review` (LLM
  `auto_prompt`, `clean_text` trước) → `page_name, followers, summary, score 1–10, criteria[{name,score,note}], strengths, weaknesses,
  suggestions, house_style, sample_hooks, posts_seen` + `at/url/via`. `channels.channel_block` thêm link + "WHAT THE LIVE PAGE LOOKS
  LIKE" (tóm tắt, house_style "match this", câu mở đầu thật, 4 gợi ý) → bài viết + brainstorm bám phong cách page thật; kênh chỉ có
  page_review cũng brainstorm được. UI `ChannelsPage`: thẻ `PageReviewCard` (điểm lớn, thanh điểm từng tiêu chí, điểm mạnh / cần cải
  thiện, gợi ý, "✍️ Phong cách page đang dùng" + câu mở đầu), tạo kênh có link hoặc đổi link → tự đánh giá nền (`autoReview`, toast).
  Test `test_channel_page.py` (6).

- **🧹 Dọn lịch sử** (25/10, trang `/history`): `POST /api/history/clear {scope: all|errors|older, days, dry_run}` (`routes/history.py`)
  xoá dòng `Request` đã xong (`FINISHED_STATUSES`; `errors` = failed/timeout/error/canceled; `older` = tạo trước `days` ngày) — **không bao
  giờ đụng queued/running** (worker giữ), không xoá Asset/file media, không đổi credit Flow thật (chỉ mất dòng + credit ước tính). Không
  bảng nào có FK tới `request` nên xoá an toàn. `dry_run` trả số dòng để nút xác nhận ghi "Xoá N dòng". Mốc thời gian phải **aware**
  (cột `UTCDateTime` từ chối datetime naive làm tham số). UI `ClearHistoryButton` (popover: select phạm vi → đếm → bấm 2 lần mới xoá).
  Test `test_history_clear.py`.

- **Link tiếp thị liên kết trên sản phẩm + bình luận đầu tiên của bài** (25/10): `Product.aff_link` (link rút gọn Shopee/TikTok
  affiliate: `s.shopee.vn`, `shp.ee`, `vt.tiktok.com`… — `product_link.AFF_LINK_HOSTS` / `affiliate_link(url)`), `Product.shop` (shop
  đang hợp tác), `Post.first_comment`; migration `ensure_product_aff_columns` (đã chạy trên Neon). `routes/products.py`: `_norm_link`
  (nhận cả đoạn share dán nguyên, bỏ `/` cuối), **`_check_duplicate_links` → 409 "Sản phẩm X đã dùng link tiếp thị này rồi"** khi tạo /
  sửa (chỉ `aff_link` là duy nhất; `link` trang gốc không bắt trùng vì nhiều SP chung trang shop); `GET /api/products/shops` (shop +
  số SP, gợi ý datalist). "Thêm từ link" dán link aff → `extract_product` lưu luôn `aff_link`. Bài viết: `post_writer._product_block`
  thêm `Shop:` + dòng `AFFILIATE LINK (goes ONLY in first_comment…)`, system prompt có luật `first_comment` (1 câu thân thiện + link
  nguyên văn, kiểu "Dạ em gửi các mom tham khảo gối bầu ở đây nha 🥰"), `write_post` **tự nối link nếu AI quên**, không có link aff →
  bỏ bình luận AI bịa (giữ cái người dùng gõ trong `current`). `POST /api/posts/write` / CRUD trả `first_comment`. UI: form sản phẩm có
  "🔗 Link tiếp thị liên kết" + "Shop đang hợp tác" (datalist shop đã có), thẻ SP hiện "🏪 shop · 🔗 aff", tìm kiếm theo shop/aff;
  `PostEditor` hộp "💬 Bình luận đầu tiên" (sửa được, nút Copy riêng — chỉ hiện khi có), lưu ở trang Bài viết + Bước 5; ô chọn sản phẩm
  trang Bài viết ghi "🔗 có link aff". Test `test_affiliate.py` (5). Thử thật UI: thêm SP có aff + shop, thêm trùng → toast 409, viết bài
  13 s → bình luận đầu đúng mẫu + link, bài không chứa link và có câu "link ở bình luận". Chưa có: trang riêng "Shop hợp tác" (mới là
  gợi ý + lọc), chưa đếm bài đã đăng theo shop.

- **Flow nhanh hơn + ít bị bỏ lượt** (26/10 tối, máy cty, commit `0dcbe0b`):
  - **Ảnh sản phẩm có mặt người thật**: `services/face_check.py` (OpenCV YuNet `assets/face_detection_yunet_2023mar.onnx`, 230 KB,
    ~20 ms/ảnh, bỏ mặt < 4 % cạnh ngắn) → `GET /api/media/{id}/faces {faces}`. Bước 1 dưới mỗi ảnh sản phẩm: `quicktool/ProductFaceCheck.tsx`
    hiện hộp cam "⚠ Ảnh có N gương mặt người thật" + "✨ Tạo ảnh chỉ có sản phẩm" (`cleanShotPrompt(name)` → `generateStandaloneImage(…,
    SQUARE, [ảnh shop])`, ~25 s, 1 lượt ảnh) → thay `mediaId` của node, lưu `prevMediaId` (whitelist `store/board.ts`) để "↺ Dùng lại ảnh gốc",
    và đưa ảnh sạch lên **đầu `Product.media_ids`** (clip sau dùng luôn). Gợi ý Bước 1 đổi "ảnh người cầm" → "ảnh bàn tay cầm, tránh mặt
    người mẫu thật". Thử thật Đầm Bầu: ảnh sạch đúng đầm, 0 mặt.
  - **Preset người mẫu** (`constants/character.ts`, `lib/characterPrompt.ts`): bỏ "K-pop idol styling", "flawless porcelain", "ethereal";
    mỗi lần tạo thêm câu "ordinary, non-famous everyday person with their own distinctive face (2 nét riêng ngẫu nhiên từ `OWN_TRAITS`:
    nốt ruồi, tàn nhang, lúm đồng tiền…), natural skin texture, not resembling any celebrity, idol…". Người mẫu thử qua kiểm tra Flow.
  - **Kịch bản** (`script_tailor._SYSTEM`): cảnh có người mẫu → sản phẩm + bàn tay dẫn khung, góc nghiêng / ¾, không cận mặt, cấm chữ
    celebrity/idol/K-pop/flawless; mỗi nhịp một động tác đơn giản.
  - **Phát hiện bỏ lượt sớm**: `flow_sdk.NOT_LISTED_DROP_S` (xem Bẫy "Nhịp poll"). Test `test_flow_sdk.py` (+2).
  - **Ảnh chạy song song 2 cái** (`worker/processor.py` `IMAGE_PARALLEL_TYPES`, `FLOWBOARD_IMAGE_PARALLEL`, cách nhau `IMAGE_START_GAP_S` 1 s,
    hàng riêng với video). Test `test_worker_runs_two_scene_images_side_by_side`.
  - **Tạo video tự động** (`store/quicktool.ts runAuto`): kiểm tra người mẫu chạy **song song** với vẽ cảnh (chờ kết luận trước video đầu),
    ảnh cảnh nào xong thì gửi video cảnh đó luôn. Ước tính phút trong hộp xác nhận tính theo song song.
  - Đo thật cả lượt (clip #19 "Đầm Bầu — thử tốc độ Flow", fashion_ad, ảnh sạch): người mẫu 26 s → kiểm tra Flow 60 s chạy cùng 4 ảnh
    (xong trong 58 s, 2 cái/lượt) → 4 video 47/52/94/116 s (1 cái bị bỏ, bắt sau ~70 s, thử lại ra) → ghép 62 s: **~4,5 phút từ lúc bấm**
    (hộp xác nhận cũ ước 12 phút). Tốn ~60 credit. Clip #19 để lại làm mẫu — xoá được.
  - Log httpx in nguyên `access_token` Facebook trong URL → `facebook_publish._RedactToken` che thành `***` (log cũ trong scratchpad còn token).

- **🎬 Làm video bằng Muse (Meta) khi Flow chậm / bỏ lượt** (26/10 tối, máy cty): Muse **không có API** (là trợ lý chat "Sunday" trên
  muse.ai, đăng nhập bằng Facebook; người dùng hỏi thẳng Sunday: ảnh tham chiếu được, ảnh → video được, mỗi clip ~10 s cố định, ≤ 6 video /
  ≤ 4 ảnh mỗi tin nhắn, hạn mức miễn phí theo tuần; gói Power $16 / Maximum $80). Nên làm **cầu nối thủ công một lượt cho cả clip**, không
  tự động hoá trang chat (dễ hỏng, có thể vi phạm điều khoản). Bước 4 (`steps/StepMedia.tsx`) có khung gập **`steps/MuseBridge.tsx`**:
  ① tick cảnh (mặc định: chưa có video / lỗi / Flow chạy ≥ `FLOW_SLOW_AFTER_S` 150 s), ② "📋 Copy tin nhắn" (`muse.ts museMessage`: tiếng
  Việt cho Sunday + prompt chuyển động tiếng Anh của từng cảnh, dọc 9:16, giữ nguyên sản phẩm, không chữ/không lời thoại/không nhạc, "Video 1,
  Video 2…"; > 6 cảnh tách nhiều tin `museBatches`), "⬇ Tải N ảnh cảnh" (tên `<slug>-anh-<thứ tự>-canh-<n>.jpg`, tải lần lượt), "📋 Ảnh"
  từng cảnh (clipboard PNG để Ctrl+V vào Muse), "↗ Mở Muse"; thứ tự ảnh của tin nhắn lưu localStorage `flowboard.muse.batch.<boardId>`;
  ③ thả nhiều video một lần → xếp theo tên file (số tự nhiên) / giờ tải về vào đúng cảnh theo thứ tự đó, đổi được ở ô "Gắn vào", cảnh báo
  video không phải 9:16 / 2 video một cảnh → "✓ Gắn N video vào cảnh" = `store/quicktool.attachMuseVideo` (cảnh đang chạy Flow
  thì hỏi rồi `stopFlowVideo`: bỏ poll `cancelGeneration` + `POST /api/requests/{id}/cancel` — worker không bao giờ ghi node của request đã
  huỷ — rồi `uploadVideoToScene(…, "muse")`). Node video có `uploaded` + **`uploadedFrom: "own" | "muse"`** (đã thêm whitelist `store/board.ts`;
  trước đây `uploaded` không có trong whitelist nên F5 là mất) → ô cảnh có nhãn "Muse" / "Video của bạn". Ô cảnh đang chạy hiện "đang tạo…
  m:ss" (`useFlowWaits` đọc `created_at` từ `GET /api/boards/{id}/requests?active=true`, 15 s/lần), quá 150 s hiện dòng vàng "⏱ Flow đã chạy
  … — 🎬 Làm cảnh này bằng Muse"; hộp "Flow bỏ lượt này" cũng có nút đó. "Tạo video tự động" lỗi ở video → câu lỗi chỉ sang khung Muse.
  **Ghép clip khác kích thước** (`video_export`): `_mixed_frame_size` → `common_size` (khung phổ biến nhất) → mọi clip đi đường encode từng
  clip với `fit_filter` (cùng tỉ lệ ±8 % thì cắt cho đầy, khác xa thì thêm viền đen) — trước đây ghép stream-copy clip khác cỡ ra hình hỏng
  (cũng đúng cho "⬆ Dùng video của bạn" và ảnh drama). Thử thật bằng Playwright + 4 video giả (3 × 720×1280 10 s, 1 × 1080×1080) trên clip thử
  #20 (đã xoá): tin nhắn, tải ảnh, copy ảnh, tự xếp cảnh, dừng Flow cảnh đang chạy, F5 giữ nhãn, ghép thật 20 s → 720×1280, 38 s, video vuông có
  viền đen. **Chưa thử với Muse thật** (người dùng test tối 26/10). Code `muse2api.py` / provider "muse" có sẵn từ flowkit **không dùng** cho việc này.

- **Loạt truyện đi theo kênh** (26/10): ô "Loạt truyện" ở trang Bài viết chỉ liệt kê loạt của kênh đang chọn (`channelSeries` = loạt có
  `channel_id` trùng kênh, hoặc loạt cũ chưa gắn kênh — ghi "· chưa gắn kênh"); nhãn ghi "Loạt truyện của kênh “X”"; chưa chọn kênh → "— Chọn kênh
  trước —"; kênh chưa có loạt → "— Kênh này chưa có loạt truyện —". **Đổi kênh thì bỏ chọn loạt đang chọn** nếu loạt đó thuộc kênh khác (effect theo
  `channelId`), để không viết tập tiếp của page A lên page B. Bỏ đoạn tự đổi kênh theo loạt. Backend `GET /api/posts/series` gom theo **(tên, kênh)**
  thay vì chỉ tên — hai page có loạt trùng tên không bị cộng chung số tập. `_series_context` vốn đã lọc theo kênh. Test
  `test_series_list_is_per_channel_and_never_merges_two_pages`.
- **Nút "việc đang chạy" góc dưới phải** (26/10, yêu cầu: rời trang khi đang làm việc nặng không sợ mất): `components/BackgroundTasks.tsx`
  (+ `backgroundTasks.css`, gắn trong khung `QuicktoolApp` nên có ở mọi trang Quicktool). Nguồn: `GET /api/running` (`routes/running.py`) gom
  job lồng tiếng (queued/running/rendering → `/tools/dub?job=<id>`), job xoá chữ AI (`/tools/clean?job=<id>`), và request Flow đang chờ/chạy
  (`gen_image`, `edit_image`, `gen_video*`, `export_video`) **gom theo clip** → `/clips/<id>/<images|videos|export>`; request không thuộc clip
  (ảnh bài viết / người mẫu) → `/history`; bỏ request cũ hơn 2 giờ (dòng mồ côi). Nút: vòng xoay + tên việc (+ % nếu có) + số việc; **ẩn khi đang
  ở đúng trang của việc** (`isHere`: cùng clip, hoặc cùng `?job=`); 1 việc → bấm là về thẳng, nhiều việc → bảng danh sách. Việc biến khỏi danh sách
  → hỏi `GET /api/running/outcome?key=` → "✓ … xong" (xanh) hoặc "! … lỗi" + lý do (đỏ), giữ 3 phút, xem trang đó rồi thì tự bỏ. Poll 4 s khi có
  việc, 15 s khi không, ngay khi đổi trang và khi có sự kiện `flowboard:running` (`announceRunning()` — gọi ở `createRequest` của `api/client.ts`,
  bắt đầu lồng tiếng, bắt đầu xoá chữ AI). **Trang Lồng tiếng và Xoá chữ giờ mở lại đúng việc qua `?job=`** (URL tự đi theo job đang mở; xoá chữ
  tải lại video nguồn + kết quả nếu đã xong; `CleanJob.source_media_id` thêm vào kiểu TS). Chưa có: các lệnh AI chạy trực tiếp trong trang (viết bài,
  gói nội dung, phân tích mẫu hot) — rời trang lúc đó vẫn mất kết quả hiển thị; ảnh bài viết đang tạo mà rời trang thì ảnh không gắn vào bài.
  Test `test_running.py` (4).
  **Mở rộng 26/10 — mọi thao tác dài trong trang** (người dùng: "cover càng nhiều càng tốt"): middleware `main._track_long_ops` (khai báo trước
  `_require_login` nên nằm bên trong nó — request bị 401 không tính) bọc các request trong `services/op_tracker.TRACKED` (~30 luật: viết bài / nhiều
  bài / câu mở đầu / sửa prompt ảnh, 🎁 gói, định hướng + đánh giá + kết nối Page của kênh, đọc link + nhập tab sản phẩm, tạo clip theo mẫu /
  viết lại kịch bản / ảnh bìa, viết prompt + lời thoại, xem + tải + dựng video mẫu, phân tích + viết theo mẫu hot, drama, OCR + xoá chữ khoanh vùng,
  đăng Facebook, tải ảnh lên Flow, đồng bộ project / cloud, xoá logo Gemini, nghe thử giọng): `start` lúc vào (đường quay lại = **Referer** = trang
  đang mở, không có thì link mặc định của luật), `finish` lúc ra (lỗi ≥ 400 → đọc `detail` làm lời nhắn). Op giữ 15 phút trong RAM (`KEEP_S`),
  `GET /api/running` gộp op đang chạy (`active_items`), outcome key `op:<id>`. Luật `keep_result` (hiện chỉ `post_write`) giữ cả JSON trả về:
  `GET /api/running/latest?kind=post_write&claim=true` → **trang Bài viết tự mở lại bài AI viết xong lúc bạn ở trang khác** (đang chạy thì trang
  chờ + poll 3 s; trang tự `claim` kết quả của chính nó khi còn mở, nhờ `mounted` ref, để không mở lại hai lần). Biểu tượng theo loại
  (`KIND_ICON`, ⏳ mặc định), tên khi xong bỏ "đang" (`doneTitle`). Thêm luật mới: một dòng `_r(...)` trong `TRACKED`. Kết quả các thao tác khác
  phần lớn đã tự lưu ở backend (bài nhiều, gói, đánh giá kênh, kịch bản…) nên quay lại là thấy; còn mất nếu rời trang: đọc sản phẩm từ link (bản
  nháp), câu mở đầu, phân tích video mẫu. Test thêm 3 (`test_running.py` 7).
- **Bài viết của clip đăng kèm video clip** (26/10, người dùng: "làm clip xong, tạo bài viết thì đăng phải kèm video"): trước đó bài viết
  gắn clip (`Post.board_id`, viết ở Bước 5 / 🎁 Gói) đăng từ trang Bài viết (loại lịch `post`) chỉ lên chữ + ảnh, **mất video clip**; chỉ lịch loại
  `clip` mới gửi video. Giờ `scheduler._payload` (loại `post`): có `p.video` riêng → video đó; không có mà có `board_id` → **video clip đã ghép**
  (`exports._final_media`), ảnh riêng của bài bị bỏ (Facebook nhận ảnh HOẶC 1 video); clip chưa ghép → lỗi rõ "clip chưa ghép xong", không bao giờ
  đăng chữ không. `GET /api/posts*` trả thêm `clip_video` (`posts._clip_videos`, một truy vấn cho cả danh sách). Trang Bài viết: thanh đăng ghi
  "kèm **video của clip**" hoặc cảnh báo clip chưa ghép + khoá "🚀 Đăng ngay". **Bước 5 có nút "🚀 Đăng ngay (kèm video)"** trong mục Bài đăng
  Facebook (`ClipPost.publishNow`: lưu bài → lịch `post` lúc này → `publishSlot`; chỉ hiện khi kênh đã kết nối Page). Test
  `test_a_post_written_for_a_clip_goes_out_with_the_clip_video`.
- **Nút "Viết Tập N+1" đang ẨN, loạt truyện vẫn dùng được** (29/10, người dùng: tool không biết tập nào đã đăng tay / tự động nên tập kế bị lệch số và lệch mạch; "Câu chuyện nhiều kỳ" chỉ là một lựa chọn như trước): `PostsPage.tsx` cờ `NEXT_EPISODE_BUTTONS = false` chỉ giấu nút "⚡ Viết nhanh Tập N+1" (form) và "✍️ Viết Tập N" (đầu mỗi loạt ở Bài đã lưu). Ô Có / Không loạt truyện, chọn loạt, viết tập từ form (`series` + AI đọc tập trước) giữ nguyên. Hướng sửa sau: đọc trạng thái đăng (slot posted / đăng tay) để biết tập cuối thật sự rồi mới mở lại nút.
- **Câu chuyện nhiều kỳ là lựa chọn riêng + nhãn lịch trên Bài đã lưu** (27/10, `PostsPage.tsx`, `posts.css`, `routes/posts.py`, `post_writer.py`):
  - Form Bài viết: dưới "Kiểu bài" có ô **"Câu chuyện nhiều kỳ"** = 2 radio Không — bài lẻ / Có — một tập của loạt (state `seriesOn`, `.qt-posts__yesno`);
    Có → hiện ô chọn loạt (`.qt-posts__seriesbox`). **Kiểu bài nào cũng chạy thành loạt được** (Mẹo, Review…): `GET /api/posts/options` bỏ
    `serial` (`post_writer.LEGACY_KINDS`), `write-batch` không ép kind `serial` nữa (chỉ khi kind trống), `_series_block(series, kind)`:
    kind kể chuyện (`NARRATIVE_KINDS` story/serial) → "một diễn biến mới"; kind khác → dòng "Every episode is a '<kiểu>' post" + "nội dung mới, không lặp
    mẹo/ý của tập trước". Brief cũ `kind: "serial"` mở ra thành "Kể chuyện" (`normKind`); Bước 5 (`ClipPost`) cũng không tự đổi kind sang serial.
    Có mà chưa chọn / đặt tên loạt → nút viết khoá + dòng nhắc. Ô chọn loạt gộp tập cùng tên có kênh + chưa gắn kênh thành một (backend vốn đọc cả hai;
    trước đó hiện 2 dòng trùng key React).
  - **Mỗi loạt là của một page** (27/10 chiều): "Bài đã lưu" gom theo (tên loạt, kênh) — `SeriesGroup.key`, tập chưa gắn kênh nhập vào page duy nhất có loạt
    cùng tên; `writeNext(group)` chỉ dùng `seriesBrief(group.last)` + sản phẩm của tập cuối, không lấy gì từ form; chọn loạt có sẵn trong form → nạp
    cài đặt tập cuối vào form (toast "Đã lấy cài đặt của Tập N…"). Xem Bẫy "Viết tập tiếp của loạt truyện bị lẫn…".
  - **Nhãn lịch**: `GET /api/posts` (và mỗi `_row`) trả `schedule` = `posts._post_schedules` (2 truy vấn cho cả danh sách): lịch `planned` sớm nhất
    (`due` khi đã quá giờ), không có thì lần `posted` mới nhất, không có thì `failed` mới nhất; `skipped` bỏ qua; lịch loại `clip` tính cho **bài mới nhất
    của clip** (caption clip đăng kèm). Field `{slot_id, status, at, auto, link, planned}`. UI `ScheduleBadge`: góc trên phải thẻ lưới (`--corner`),
    trong dòng chế độ danh sách, và cạnh "✓ Đã lưu" của bài đang mở; xanh dương "📅 T4 29/10 · 20:00 ⚡" (⚡ = tự đăng), vàng "⏰ Đến giờ đăng", xanh lá
    "✓ Đã đăng 26/10", đỏ "⚠ Đăng lỗi"; bấm → `/schedule`. Danh sách tải lại sau khi lên lịch / xếp lịch cả loạt / Đăng ngay. Test
    `test_saved_posts_say_where_they_stand_on_the_calendar`, `test_any_kind_of_post_can_run_as_a_series`.
- **✂️ Edit auto CapCut** (28/10, menu Công cụ, trang `/tools/capcut`): video lồng tiếng / clip đã ghép / video của người dùng → **một dự án
  CapCut bản máy tính** (Windows) có phụ đề theo kiểu chữ của chính họ, chữ nhấn mạnh + zoom + tiếng hiệu ứng ở chữ quan trọng (AI chọn) → mở CapCut
  chỉnh tay, xuất → thả video đã xuất về đúng dự án để clip dùng bản đó (tải về / lịch đăng / Facebook). Ý tưởng + mã gốc từ skill JunOps
  (`.claude/skills/junops-edit-capcut`, LICENSE cho dùng/sửa; skill vẫn dùng được riêng với Claude). Trang có khối **Yêu cầu** (Windows, CapCut, CapCut
  đang đóng, kiểu chữ đã học, AI, Whisper, ffmpeg — `GET /api/capcut/status`, tự kiểm 8 s) và **Hướng dẫn** gập (5 bước + lưu ý).
  - `services/capcut_draft.py` (phần file, chuyển từ `junops_capcut.py`): `drafts_root()` (`FLOWBOARD_CAPCUT_DRAFTS` / `CAPCUT_DRAFTS` / `%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft`), `capcut_running()` (tasklist), `learn()` quét 12 dự án mới nhất → kiểu chữ `t1…` (gói nguyên segment +
    material + refs làm mẫu), hiệu ứng âm thanh `s1…` (chỉ tiếng có file trong cache CapCut), **mẫu video + mẫu audio** (hình JSON của CapCut máy đó) và
    `base` (dự án cho mượn khung); `default_aliases` gán vai theo **chữ mẫu**: dòng có "Phụ đề" / "Nhấn mạnh" / "Tiêu đề" (hướng dẫn bảo người dùng gõ đúng
    vậy), không thì phụ đề = kiểu dùng nhiều nhất. `DraftBuilder` (khung = draft_content của dự án base, xoá hết track/material, canvas = cỡ video):
    `add_video` (nhiều đoạn một file dùng chung material — cắt khoảng lặng), `add_audio` (file cục bộ: type `extract_music`, lấy hình từ mẫu audio),
    `add_text(style, …, lane=)`, `add_sfx` (lần lượt **mọi** tiếng của người dùng, tiếng dài cắt ≤ 2,5 s, không lặp liền), `add_zoom` (keyframe
    `KFTypeScaleX` như skill — uniform scale bật). **Mỗi lớp một "lane"** (`_lane_track`: phụ đề / chữ nhấn mạnh / sfx có track riêng, chồng thời gian thì
    thêm track của chính lane đó — bẫy lúc làm: lấy "track trống đầu tiên" làm một dòng phụ đề rơi vào track chữ nhấn mạnh). `create_project` từ chối khi
    CapCut mở, tên an toàn + "(2)" khi trùng, chép file cấu hình nhỏ của base, **id mới hết** (draft_id, timeline id, project.json), ghi
    `draft_content.json` ở gốc + `Timelines/<id>/` (CapCut mới có `timeline_layout.json`), `draft_meta_info.json` (thư viện media type 0),
    `draft_virtual_store.json`, `draft_settings`, ảnh bìa (ffmpeg), rồi **đăng vào `root_meta_info.json`** (đầu `all_draft_store`, `draft_ids` + 1, sao lưu
    `root_meta_info.json.flowboard.bak`). `remove_project` (chỉ thư mục nằm trong drafts root có `draft_meta_info.json`).
  - `services/capcut_auto.py`: kiểu chữ đã học lưu **theo máy** ở `<STORAGE_DIR>/capcut/styles.json` (âm thanh là file trong cache CapCut của máy
    đó); `learn()` giữ lựa chọn cũ nếu kiểu đó còn. Nguồn (`sources()`): `dub` = job lồng tiếng có `voice.wav` → `dub.render_clean_video` (mới, khung /
    vùng mờ / nhân vật in vào video **không phụ đề, không tiếng**; không có lớp nào thì dùng thẳng video gốc, volume 0) + `voice.wav` + `bgm.wav` (0,6) thành
    track riêng, câu = segment đã dịch, **phụ đề đặt đúng chỗ đã chỉnh ở trình chỉnh sửa** (`effective_layout` từng câu → toạ độ CapCut: x = 2x − 1,
    y = 1 − 2(y_đáy − 0,025), y dương là lên trên; bỏ tick thì theo vị trí dòng mẫu); `clip` = video cuối của board (`exports._final_media`) +
    **Whisper có mốc từng chữ** (`dub_runner transcribe … auto words` — tham số mới `word_timestamps`); `upload` = `POST /api/capcut/upload` (≤ 2 GB, Asset
    cục bộ) + Whisper + tuỳ chọn **cắt khoảng lặng** (`keep_ranges`: khoảng ngừng > 0,45 s, chừa 0,12 s; `remap_lines` dời mốc). Phụ đề `chunk_lines`:
    `tiktok` ≤ 4 chữ ngắt sau dấu câu, bỏ dấu chấm/phẩy cuối; `line` cả câu (≤ 9 chữ); hiện liền nhau, không chồng. **Chữ quan trọng**: `run_llm("auto_prompt")`
    `_POINTS_SYSTEM` → JSON `{points:[{line, words}]}`, ~1 chỗ / 12 s (`point_budget`), `place_points` chỉ giữ chữ có thật trong câu (tìm mốc theo chữ), cách
    nhau ≥ 5 s; AI lỗi → `fallback_points` (số / câu cảm thán) + cảnh báo. Mỗi chỗ: chữ IN HOA kiểu nhấn mạnh 1,2 s (đè gần phụ đề thì đẩy lên 0,3), zoom
    1,12/1,18 xen kẽ, một tiếng hiệu ứng volume 0,3. Job trong RAM, một việc một lúc (`_RUN_LOCK`), có trong nút "việc đang chạy" (`running._capcut_items`,
    `?job=`). Dự án đã tạo: AppSetting **`capcut_projects`** (≤ 100, theo tài khoản). **Đưa bản CapCut về**: `return_video` → Asset mới, mọi node
    export/merge của clip trỏ sang (`capcutPrev` giữ bản cũ), `quicktool.capcut = {project, media_id, at}`, bỏ `downloaded_at`; video tự quay chưa có
    clip thì tạo board `template_id: "capcut"` (bước 5, node video + export). Lồng tiếng render lại sau đó sẽ ghi đè bản CapCut (bình thường).
  - **Lồng tiếng trước (không bắt buộc) + video theo link + "Không dùng"** (28/10, người dùng: "làm video lồng tiếng từ menu Edit auto CapCut thì có 1 step lồng tiếng trước, tới bước edit thì xài CapCut"): tab đầu bước ② là **"🆕 Video mới (link / file)"** — ô dán link → `POST /api/capcut/fetch {url}` (`capcut_auto.fetch_link` → `video_fetch.fetch_video`, ≤ 30 phút, Asset như upload) hoặc thả file; video mới hiện **Bước ③ "🎙 Lồng tiếng sang tiếng Việt trước"** (`DubCard`: giọng `VoiceField`, giữ nhạc nền; khoá + lý do khi máy không có pyvideotrans — `status.dub`, `dub_reason`, `dub_separate`). Bật thì nút thành "🎙 Lồng tiếng rồi tạo dự án CapCut": source `dub_new` + `dub {source_media_id, voice, keep_bgm}` → `capcut_auto._start_dub` gọi **`dub.start_job(auto_render=True)`** ngay (vào hàng đợi lồng tiếng, tạo clip như menu Lồng tiếng) → `_wait_dub` theo tiến độ job dub (0–70 % thanh, phase "Lồng tiếng: …"), xong thì chạy tiếp như nguồn `dub` (video nền không phụ đề, voice/bgm track riêng, phụ đề từ câu đã dịch). Cắt khoảng lặng ẩn khi lồng tiếng. Ô kiểu chữ ở bước ① có **"— Không dùng —"** (alias `""`, `choose_styles` nhận `""`, học lại vẫn giữ): phụ đề = Không dùng → không phụ đề; chữ nhấn mạnh = Không dùng → chỉ zoom + tiếng ở chỗ quan trọng. **Kiểu chữ đã chọn giữ theo nhãn** (font · cỡ · màu) khi học lại, không theo số t1, t2… Test `test_capcut.py` 14 (thêm: Không dùng, lồng tiếng trước với job dub giả, lấy video theo link).
  - **Phụ đề .srt** (28/10, người dùng: "chỉnh vị trí 1 câu trong CapCut thì các câu khác đi theo được không?"): tool ghi mỗi câu là **chữ thường** (material `type: text`) — CapCut chỉ dời câu đang kéo (dò dự án "test edit auto capcut": 4 câu kéo tay, 198 câu chỗ cũ); chỉ **phụ đề thật** (Captions) mới đồng bộ vị trí / kiểu cả loạt. Giờ: `capcut_draft.read_subtitles(pdir)` (track chữ nhiều đoạn nhất của timeline chính, theo thời gian) + `to_srt`; `GET /api/capcut/projects/{id}/srt` (`capcut_auto.project_srt`: đọc từ dự án — có chữ người dùng đã sửa — không có thì file `media/capcut/<job>/phu_de.srt` lưu lúc tạo; tên file UTF-8 qua `filename*`). Tuỳ chọn **`srt_only`** ("📄 Không chèn chữ phụ đề — chỉ tạo file .srt"): không ghi chữ phụ đề vào dự án, chỉ file .srt để người dùng **Captions → Import** trong CapCut. Nút "⬇ .srt" ở mỗi dự án + "⬇ Phụ đề .srt" ở kết quả. Bước sau (chờ người dùng import thử một lần): học khuôn caption thật từ dự án đó rồi ghi thẳng phụ đề dạng caption. Bỏ ý tự dò chữ Trung bằng OCR (người dùng: chữ Trung nằm nhiều chỗ, sợ nhận sai).
- **Lồng tiếng: "✨ Nhấn chữ quan trọng"** (28/10, người dùng chọn làm sau khi so sánh đường CapCut với công cụ lồng tiếng): chữ to bật lên + zoom nhẹ + tiếng hiệu ứng ở các chữ quan trọng, ngay trong trình lồng tiếng (cả hai engine), không cần CapCut. Phần chọn chữ quan trọng tách ra **`services/key_moments.py`** dùng chung với Edit auto CapCut (`Line`, `timed_words`, `pick_points` (AI, `_POINTS_SYSTEM`, ~1 chỗ / 12 s, cách ≥ 5 s, ≤ 40), `place_points`, `fallback_points` (số / câu cảm thán), `zoom_expr(points)` — biểu thức ffmpeg của đường zoom: lên 0,3 s, giữ 1 s, xuống 0,4 s, mức 1,12 / 1,18 xen kẽ — và `zoom_at` để test / preview; `capcut_auto` import lại các tên cũ). **`services/sfx.py`**: bộ tiếng có sẵn `builtin` (pop, whoosh, ding, click) **tổng hợp bằng ffmpeg lavfi lần đầu** vào `<STORAGE_DIR>/sfx/*.wav` (không có file nhị phân trong repo), bộ `capcut` = tiếng đã học từ CapCut (file trong cache CapCut, nếu có); `sets()`, `pieces(points, set)` lấy lần lượt không lặp liền, cắt ≤ 2,5 s. `dub.py`: `Job.highlights` = `normalize_highlights` `{on (mặc định tắt), words, zoom, sfx, sfx_set, y (null = trên phụ đề 0,2), points: [{at, words, line}], picked: ai|fallback|manual}` — trong `public()`, job.json, **snapshot** (`SNAPSHOT_KEYS`), `_job_from_dict`; `_ensure_points` (bật mà chưa có chỗ → AI chọn lúc render, phase "AI đang chọn chữ quan trọng"), `pick_highlights` (AI lỗi → fallback), `emphasis_y`, `emphasis_events` → `write_sub_ass(emphasis=)` ghi style **`Emph`** (Arial 1,6× cỡ phụ đề, vàng &H0014D8FF, viền đen, `\an5\pos` + pop `\fscx70→100` 120 ms, layer 1, 1,2 s mỗi chữ), `zoom_filter` → **`zoompan=z='…':d=1:s=WxH:fps=<r_frame_rate>`** đặt **đầu** `video_filter` (trước khung / vùng mờ / nhân vật / phụ đề; biến `in_time`, đo trên ffmpeg N-125875: 6 s → 180 khung đúng, 0,5 s), `probe_fps` (r_frame_rate dạng "30000/1001"), tiếng: `sfx.pieces` → `_timeline_wav` ra `<work>/sfx.wav` → `audio_mix(with_bgm, sfx_index)` (voice + nhạc 0,6 + sfx 0,3, `amix normalize=0`). Remotion: `build_spec(highlights=, sfx=)` → props `highlights {words, zoom, y, points}` + `sfx [{at, dur, src}]`, `render.mjs` phục vụ `spec.sfx_files` ở `/sfx<i>.wav`; `DubSubtitles.tsx`: `zoomAt` (cùng đường cong), `emphasisAt`, chữ to `emphasisFont` (co lại khi chữ dài — khung Remotion từng bị cắt "DIMETHYL SULFID"), `<Sequence><Audio volume 0.3>` cho tiếng; video có `transform: scale`. Routes: `RenderBody.highlights`, **`POST /api/dub/jobs/{id}/highlights/pick {lines?, timings?}`** → `{points, picked}` (chọn theo câu đang sửa trong editor, không render, không đổi job); `status.sfx_sets`. Đổi highlights không đụng `voice_key` → xuất lại là "nhanh". **Editor** (`dub/editor/*`): tab **✨ Nhấn** (`HighlightsPane`: bật/tắt, 3 ô chữ to / zoom / tiếng, bộ tiếng, vị trí chữ to + Tự động, "✨ AI chọn chữ quan trọng" (`pickDubHighlights`, ~6 s), "+ Thêm ở <giờ>" (lấy 2 chữ đầu của câu đang nói), danh sách chỗ nhấn sửa chữ / 🗑 / bấm giờ để tua), hàng **✨ Nhấn** trên timeline (khối 1,2 s mỗi chỗ, kéo để dời `onMovePoint`), stage xem trước zoom (CSS scale trên video) + chữ to đúng vị trí (`.dx-stage__emph`), `Sel {kind:"hl"}`, dirty "nhấn chữ quan trọng", "⇪ Áp cho cả loạt" gửi cài đặt nhấn (không gửi chỗ — mỗi clip AI chọn riêng; `BatchLook.highlights`). `api/dub.ts`: `DubHighlights`, `normHighlights` (cùng dạng với backend để so dirty), `emphasisY`, `HL_*`. Test `test_dub_highlights.py` (8: chuẩn hoá, đường zoom ffmpeg = Python, ASS Emph, audio_mix, tiếng có sẵn xoay vòng, fallback, render thật ffmpeg có zoom + sfx rồi tắt đi, route pick).
  - Routes `routes/capcut.py`: `GET /status`, `POST /learn`, `PUT /styles`, `GET /sources`, `POST /upload`, `POST /jobs`, `GET /jobs[/{id}]`,
    `GET /projects`, `POST /projects/{id}/return`, `DELETE /projects/{id}?remove_folder=`. Frontend `api/capcut.ts`, `pages/CapcutPage.tsx` (+ `capcut.css`,
    tiền tố `cc-`): cột chính ① Kiểu chữ & âm thanh (Học / Học lại, 3 ô chọn vai, chip âm thanh) ② Chọn video (tab lồng tiếng / clip đã ghép / tải lên)
    ③ Kiểu dựng (tên dự án, phụ đề TikTok / cả câu / không, vị trí như video lồng tiếng, chữ nhấn mạnh + zoom + âm thanh, cắt khoảng lặng) → "✂️ Tạo dự án
    CapCut" (khoá + lý do khi thiếu gì) → khung tiến độ / kết quả ④ Dự án đã tạo (thả file / "⬆ Đưa video đã xuất về", Mở clip, 🗑 bỏ khỏi danh sách hoặc
    xoá cả dự án trong CapCut); cột phải dính: Yêu cầu + Hướng dẫn. Test `test_capcut.py` (10, drafts root giả dựng trong test + 1 lượt thật có ffmpeg).
- **🔄 Đồng bộ từ Facebook** (30/10, máy cty; người dùng: "fb đăng bài bằng tay thì ở đây cũng thấy"): `services/fb_sync.py` đọc lại bài của Page đã
  kết nối qua Graph `GET /{page}/published_posts` (token Page sẵn có, quyền `pages_read_engagement`; **Reel cũng nằm trong đó** dạng `added_video`, `attachments.target.id`
  = id video của Reel). Bảng **`FbPost`** (`channel_id`, `fb_id`, `media_id`, `created_time`, `kind`, `reel`, `message`, `permalink`, `picture` = URL CDN của FB,
  `slot_id`, `post_id`; unique (channel, fb_id); `create_all` tạo). **Bài tool tự đăng** nhận ra qua `Schedule.result.post_id` (bài feed = `page_post`, Reel / video = id
  video → so với `media_id`) → `slot_id`, không hiện lần nữa. **Bài đăng tay** (`slot_id` rỗng) hiện trên Lịch đăng (thẻ viền xanh ngọc "🌐 … đăng tay trên FB",
  `qt-sched__slot--fb`, không kéo / không đăng / không xoá; khung chi tiết chỉ xem: nội dung, ảnh, dạng, "Mở trên Facebook ↗", Copy, link "Bài #id" nếu khớp).
  **Khớp với Bài đã lưu**: `norm_text` (bỏ hashtag, link, hoa thường, khoảng trắng) + `SequenceMatcher` ≥ `MATCH_RATIO` 0,8; bài lưu tạo sau giờ đăng quá
  `MATCH_AFTER` 1 h không khớp (bản sao "⧉" làm sau vẫn sửa được); hoà điểm → giữ liên kết cũ, rồi bài cũ nhất. Khớp → `GET /api/posts` có **`fb_manual`**
  `{at, link, reel, channel, fb_id, count}` → "Bài đã lưu" nhãn **"🌐 Đăng tay trên FB dd/mm"** (`HandPostedBadge`, thay nhãn lịch) ở góc thẻ / dòng / đầu bài;
  mở bài → **chỉ xem** (`PostEditor readOnly`: ô khoá, ẩn công cụ AI / ảnh / video; ẩn "💾 Lưu"; thanh đăng thay bằng khung xanh ngọc "đã đăng tay… chỉ xem"
  + Copy / "⧉ Bản sao để sửa" / Mở trên Facebook; chat + sửa nhanh bị khoá; "Viết bài" mới khi đang mở bài đó → thành bài mới, không ghi đè).
  Khớp mới → **lịch `planned` của bài đó trên cùng page chuyển `skipped`** + ghi chú "đã đăng tay… tool không đăng lại" (chống đăng 2 lần; page khác giữ nguyên).
  Bài xoá trên Facebook (trong 30 ngày vừa đọc) → xoá `FbPost`. Chạy: vòng `fb_sync.run_loop` (task `fb-sync-loop` trong `main.lifespan`, mỗi
  `SYNC_EVERY_S` 30 phút), mở Lịch đăng / Bài viết (`POST /api/schedule/facebook/sync {max_age: 600}`), nút "🔄 Đồng bộ từ Facebook" (thanh tuần, kèm "lần cuối
  hh:mm" / lỗi). Trạng thái từng kênh: AppSetting `fb_sync:<channel_id>`. Routes `routes/schedule.py`: `GET /api/schedule/facebook?from&to&channel_id`
  (+ `channels` trạng thái), `GET /facebook/status`, `POST /facebook/sync {channel_id?, max_age?}`. Frontend `api/schedule.ts` (`FbHandPost`, `listFacebookPosts`,
  `syncFacebook`), `SchedulePage.tsx`, `PostsPage.tsx`, `PostEditor.tsx`. Test `test_fb_sync.py` (4). Chưa làm: bài hẹn giờ trong Meta Business Suite
  (`scheduled_posts`), insights cấp page, Instagram / TikTok (không có API).
  - **Số liệu (mục 5, 30/10)**: `FbPost.stats` (JSON; migration `db.ensure_fbpost_stats_column`) đọc mỗi lần đồng bộ bằng **2 lệnh gọi / page**: `published_posts` thêm
    `reactions.summary(true).limit(0),comments.summary(true).limit(0),shares,insights.metric(post_media_view,post_total_media_view_unique,post_clicks)` (lấy kỳ
    `lifetime` — `post_total_media_view_unique` có cả kỳ `day`), và `GET /{page}/video_reels?fields=id,length,video_insights.metric(...)` cho Reel (khớp theo
    `media_id`). Khoá: `views, viewers, clicks, reactions, comments, shares` (+ Reel: `plays, replays, avg_watch_s, watch_time_s, followers, length_s, retention`
    41 điểm = tỉ lệ còn xem theo **% độ dài video**, không phải theo giây). Thiếu `read_insights` → đọc lại không có `insights` (vẫn có ❤💬↗), `stats_error` báo
    "chưa đọc được lượt xem"; số không đọc được lần này **giữ giá trị cũ** (gộp với `stats` cũ). Hiện ở: slot đã đăng (`scheduler.row(stats=)` qua
    `fb_sync.stats_for_slots`), bài đăng tay (`list_manual`), Bài đã lưu `fb_stats` (`stats_for_posts`, lần lên FB mới nhất). UI `quicktool/schedule/FbStats.tsx`:
    `StatsLine` (chip 14px chữ sáng + emoji màu: ▶️ lượt phát / 👁️ lượt xem nền xanh ngọc, ❤️ 💬 🔁; thẻ lịch hẹp dùng `dense` — 12px, chỉ chip chính + chip khác 0;
    trên thẻ lịch + thẻ / dòng Bài đã lưu), `StatsPanel` (ô số liệu trong khung chi tiết lịch), `RetentionChart`
    (SVG một đường 2px `#0fa596` — màu đã chạy validator dataviz trên nền `#1c1f27` —, vùng 10 %, lưới 0/50/100 %, rê chuột / phím ← → hiện "x % còn xem ở n s",
    câu tóm "Ở 6 s còn 82 %…; tới cuối còn …", "Xem dạng bảng").
  - **Số liệu đọc được (dò thật 30/10, token có `read_insights`)**: bài — `GET /{post}/insights?metric=` **`post_media_view`** (lượt xem), **`post_total_media_view_unique`** (số người xem), `post_clicks`, `post_reactions_by_type_total`; **`post_impressions*` / `post_engaged_users` đã bị Meta bỏ** (lỗi #100 "must be a valid insights metric"). Reel — `GET /{video_id}/video_insights`: `fb_reels_total_plays`, `blue_reels_play_count`, `fb_reels_replay_count`, `post_video_avg_time_watched` (ms), `post_video_view_time` (ms), `post_video_retention_graph` (tỉ lệ còn xem theo giây), `post_video_followers`, `post_video_likes_by_reaction_type`. Số của bài: field `reactions.summary(true)`, `comments.summary(true)`, `shares`. Insights cấp page chưa dò đúng tên.
- **Ảnh thẻ cho clip chỉ có video + phân trang "Clip của tôi" + tiêu đề trang** (30/10):
  - Clip lồng tiếng / video tải lên / bản CapCut đưa về không có node ảnh nên thẻ chỉ hiện 🎬. **`services/poster.py`**: `poster_for(media_id)` cắt 1 khung
    (ffmpeg `-ss frame_time` = 1/10 độ dài, kẹp 0,5–3 s và ≤ nửa video, rộng 480 px, JPEG) lưu **`<thư mục tài khoản>/posters/<id>.jpg`** (đọc
    `media.MEDIA_CACHE_DIR` lúc gọi — đổi theo tài khoản; không nằm trong `media/` nên không lẫn vào `cached_path`), làm một lần; máy chưa có video thì
    `fetch_and_cache` (tải về một lần). Route **`GET /api/media/{id}/poster`** (`routes/media.py`, Cache-Control 1 ngày; 404 khi không phải video).
    Frontend **`clipThumbUrl(summary)`** (`api/client.ts`): ảnh cảnh đầu → không có thì poster của `export_media` → không có thì 🎬; dùng ở thư viện clip,
    Hôm nay (3 chỗ), Kênh, Lịch đăng (thẻ "Chưa lên lịch"). Test `test_poster.py` (2).
  - **Thư viện "Clip của tôi" phân trang**: tối đa `LIBRARY_ROWS` 3 hàng / trang — số cột đo thật từ grid auto-fill (`useGridColumns`, ResizeObserver),
    mỗi trang `cột × 3 − 1` clip + thẻ "Clip mới" ở đầu mọi trang; `.qt-pager` dùng chung (CSS ở `prompts.css`, luôn được nạp vì `PromptsPage` import tĩnh).
    "Chọn tất cả" vẫn chọn mọi clip (mọi trang).
  - **Tiêu đề trang `.qt-header__crumb`**: **18px** (thử 39px thì tên clip dài chiếm 2 dòng — người dùng bảo về 18px), đậm 800, màu cam `--qt-accent`,
    in hoa, **một dòng, dài thì "…"**. `.dx` (trình chỉnh sửa lồng tiếng) `calc(100vh − 106px)` theo thanh đầu trang mới (**chưa xem lại trên máy nhà**).
- **🤖 Trợ lý AI — bản demo A0** (30/10, máy cty): nút tròn cam góc dưới phải (`components/AssistantWidget.tsx` + `assistant.css`, gắn trong khung
  `QuicktoolApp` cạnh `BackgroundTasks`), **kéo thả được** (pointer capture; vị trí lưu localStorage `dflow.assistant.pos` theo góc gần nhất nên đổi cỡ
  cửa sổ vẫn đúng chỗ; mặc định cao hơn nút "việc đang chạy" một hàng), **không bao giờ đè nút "việc đang chạy"** (`.bgt`: mỗi giây + lúc thả, chồng lên
  thì tự dời lên trên nó). Bấm (không kéo) mở khung chat cạnh nút, phía còn chỗ; đầu khung kéo được; ▶ gợi ý, Enter gửi, "đang trả lời…", 🗑 xoá cuộc
  trò chuyện (2 bấm), vòng quay quanh nút khi có việc nền, chấm xanh + toast khi việc xong lúc khung đang đóng, `?assistant=1` mở khung (link từ nút "việc
  đang chạy"; giữ yêu cầu mở 3 s ở cấp module — xem bẫy "App dựng các trang hai lần lúc khởi động"). Backend `services/assistant.py` + `routes/assistant.py` (`GET /api/assistant`, `POST /chat {message}`, `DELETE`), bảng
  **`AssistantMessage`** (role, text, data {media_id, reference_id, link, link_label, error}, task_id) + **`AssistantTask`** (kind, status running/done/error,
  title, args, state {step, request_id, prompt, started, media_id, reference_id}, error). Một lượt chat: `run_llm("auto_prompt")` với `_SYSTEM` (khả năng hiện
  có, "sắp có" cho clip / bài / lịch, **luật không vẽ mặt người thật** — hỏi "giống <người nổi tiếng>" thì tạo người mới cùng phong cách và nói lý do) +
  ngữ cảnh (extension, project ghim, người mẫu đã lưu) + 12 tin gần nhất → JSON `{reply, action: null | {tool: "create_model", args {name, gender, country,
  look (EN), summary (VI)}}}` (`parse_answer` kiểm, sai giới tính → hỏi lại). Việc nền `create_model`: prompt chân dung giống trang Người mẫu
  (`model_prompt`, 2 nét riêng `OWN_TRAITS`, "not resembling any celebrity"), `Request gen_image` (params `origin: "assistant"`, project ghim, model ảnh theo
  `ui_prefs.imageModel`) → poll → tải ảnh về máy → `create_reference` (kind character, `meta.by = "assistant"`) → tin nhắn "Xong rồi…" có ảnh + nút mở thư
  viện. Việc chạy dở được `resume()` chạy tiếp ở lần đọc sau (sống qua restart). **Lọc trước khi gọi AI** (`quick_reply`, không tốn token): lời chào / "ok, cảm ơn" → câu soạn sẵn;
  tin không có từ nào về việc trong DFlow → câu "chỉ giúp việc trong app" (khớp **cả từ**; từ dễ trùng khi bỏ dấu — tạo/tao, ảnh/anh, mẫu/màu, bài —
  chỉ tính khi có dấu; từ không trùng tính cả khi gõ không dấu; từ mô tả tóc / áo / nam / nữ / quốc gia chỉ tính khi đang chat dở hoặc đi với "muốn /
  cần / tìm"; câu trả lời cho câu hỏi trợ lý vừa hỏi luôn qua). Lọt qua mà vẫn ngoài lề thì `_SYSTEM` dặn AI chỉ đáp một câu. **AI dùng**: feature
  `auto_prompt` của tài khoản — hiện **Claude CLI (Sonnet, gói Max của người dùng)**, mỗi câu ~11 s; bán cho khách thì phải chuyển sang Gemini API key. Nút "việc đang chạy": `running._assistant_items` (link
  `/models?assistant=1`), outcome `assistant:<id>`, request `origin: assistant` không hiện thêm dòng "Ảnh AI". Test `test_assistant.py` (4). Thử thật: "tạo cho
  tao mẫu giống ngọc trinh, xong lưu cho tao" → trả lời 11 s (nói rõ không dùng mặt người thật), Flow vẽ xong + lưu "Bảo Ngọc" (#9) sau 40 s; kéo nút đè lên nút
  "việc đang chạy" → tự dời lên.
- **🤖 Trợ lý AI — kế hoạch nhiều bước + kỹ năng** (30/10, thay phần "một action" của A0): AI trả `{reply, actions: [{tool, args}…]}` (≤ 6 bước, vẫn đọc
  được dạng cũ `action`), chạy lần lượt trong **một** `AssistantTask` kind `"plan"` (`args.actions`, `args.plan` = tóm tắt; `state.done` / `ctx` / `results` +
  khoá theo bước `s{i}_…` để **chạy tiếp đúng chỗ sau restart**, không viết bài lại). Bước sau dùng kết quả bước trước qua `ctx` ("previous": `product_id`,
  `post_ids`, `channel_id`, `board_id`). Kỹ năng (`_HANDLERS`): **`create_model`**; **`add_product {url}`** (`product_link.extract_product` →
  `tiktok_import.save_draft` → `attach_photos` lên Flow); **`write_post {channel_id, product_id?, series?, kind?, topic?, images?, count 1–5}`** (loạt: lấy
  `brief` tập cuối của loạt đó — giống `seriesBrief` frontend, "serial" → "story" — rồi `_series_context`, viết lần lượt, `_save_written`; ảnh AI: mỗi prompt
  một `gen_image` vuông, ảnh sản phẩm làm tham chiếu, ghi `Post.images`); **`schedule_post {post: previous|id, at (giờ VN tuyệt đối), auto?, format?}`**
  (`scheduler.create`, nhiều bài → mỗi ngày 1 bài, `auto` mặc định = Page đã nối); **`create_clip {product_id, template_id?, channel_id?}`**
  (`create_board_from_template(tailor=True)` → link `/clips/<id>/script`; ảnh + video vẫn bấm "⚡ Tạo video tự động"). **Danh mục cho AI** (`catalog()`:
  kênh + `fb_connected`, loạt truyện theo kênh, 40 sản phẩm, kiểu clip, người mẫu) kèm giờ VN + thứ; `_clean_args` kiểm lại phía mình và **so khớp tên gần
  đúng** (`similarity` bỏ dấu + `SequenceMatcher`, `best_match` ≥ 0,72 / sản phẩm 0,6 / loạt 0,7 trong đúng kênh): "chú ta hay tò mò" → "Chúng ta hay tò mò",
  "nhung thu vi ve he mat troi" → tên loạt chuẩn; thiếu kênh (nhiều kênh) / thiếu sản phẩm / **giờ đã qua** → hỏi lại, không chạy. **Chờ xác nhận**:
  `needs_go_ahead` (có lịch tự đăng lên Page đã nối) → task `pending` + tin nhắn có `data.confirm` → nút **✅ Làm luôn / Huỷ** trong chat
  (`POST /api/assistant/tasks/{id}/confirm|cancel`) hoặc gõ "ok / làm đi" / "thôi / huỷ" (không gọi AI); hỏi việc mới thì kế hoạch cũ bị huỷ; xoá chat huỷ
  kế hoạch đang chờ. Tin nhắn "Xong rồi!" gộp dòng từng bước, `data.links` (nhiều nút: bài, Lịch đăng, clip…), `data.media_ids`. Nút "việc đang chạy" mở
  trang của bước đang làm (`task.state.link` + `?assistant=1`). Test `test_assistant.py` (9). Thử thật câu của người dùng "tạo 1 bài viết cho kênh **chú ta**
  hay tò mò, tập 7 trong series những thú vị về hệ mặt trời, xong set lịch post vào 12h hôm nay" → 8 s, hiểu đúng kênh / loạt / Tập 7 / 12:00 30/10 tự đăng,
  dừng chờ "✅ Làm luôn" (**chưa bấm** — task #2 để người dùng tự quyết).
- **📲 Thêm vào tin (Story của Page)** (30/10): token Page có đủ quyền Meta yêu cầu (`pages_manage_posts`, `pages_read_engagement`,
  `pages_show_list`). `Schedule.fb_story` (migration `db.ensure_schedule_story_column`), `scheduler.create(fb_story=)`, PATCH `fb_story` (đã đăng thì không đổi),
  row có `fb_story`. Khi slot đăng xong (tự đăng / Đăng ngay): `scheduler._story` → `facebook_publish.publish_story(video= | photo=)` — **video** (bài có video,
  Reel, clip): `video_stories` start → file lên rupload (`offset 0`, `file_size`, `Authorization: OAuth`) → finish; dài > 60 s thì `story_video` cắt 59,5 s đầu
  (ffmpeg stream copy, ghi `note`); **ảnh**: ảnh đầu **tải lên lại** `published=false` (Meta cấm dùng lại ảnh / video của bài đã đăng) → `photo_stories`;
  **bài chỉ có chữ** → API không có tin chữ (chỉ `photo_stories` / `video_stories`) nên `services/story_card.py` vẽ ảnh 1080×1920 (nền gradient
  kiểu tin chữ Facebook, chọn theo nội dung; đoạn mở đầu ≥ 60 ký tự, ≤ 220, bỏ hashtag / link / emoji; tên Page nhỏ ở đáy; font hệ thống: Segoe UI /
  Arial trên Windows, Noto Sans / DejaVu trên Linux, `FLOWBOARD_STORY_FONT` để đổi) rồi đăng như tin ảnh, `note` "ảnh chữ của đoạn mở đầu". Kết quả `result.story {post_id, kind, note}` hoặc **`result.story_error`** — tin lỗi **không bao giờ** làm bài chính thành lỗi.
  UI: `StoryToggle` (`schedule/FormatPicker.tsx`): ô trong hộp Lên lịch (ngay dưới "Tự đăng"; chọn sẵn từ trang Bài viết thì tự bật "Tự đăng") và hộp kéo
  thả lịch (chỉ khi tự đăng), hộp "Đăng ngay"; chip "📲 Thêm vào tin" trên thanh đăng trang Bài viết (nhớ trong `brief.fb_story`);
  toast báo "+ đã thêm vào tin" hoặc cảnh báo lỗi tin; Lịch đăng: "📲" trên thẻ + dòng "Tin" trong chi tiết. Trợ lý AI: `schedule_post` có `story`
  ("thêm vào tin", "đăng tin", "lên story"), chỉ khi tự đăng. Test `test_schedule.py` (+2: ảnh / video / chữ / Facebook từ chối / đổi lựa chọn; cắt video 70 s
  bằng ffmpeg thật), `test_assistant.py`. **Chưa đăng tin thật lên Page.**
- **👥 Quản lý tài khoản + Đổi mật khẩu** (8/11, người dùng: "chỉ account akiragosho tạo được tài khoản, có menu quản lý; tài khoản khác chỉ đổi mật khẩu"):
  bảng `account_user` (kho trung tâm) thêm cột `role` ("admin" | "user"), `disabled` (0/1), `note` — `accounts._ensure_user_columns` ALTER vào kho cũ
  (Neon) lúc mở `central_engine()` và gán `role = admin` cho `SEED_USER` khi chưa ai là admin; cột NULL = user / không khoá, nên agent bản cũ chạy cùng
  kho vẫn được. `accounts.is_admin`, `new_account_backend` (máy có `FLOWBOARD_CENTRAL_DB_URL` → `{"type":"postgres","schema":"acct_<tên>"}`, tài khoản mới lên
  cloud ngay, không cần "Chuyển lên cloud"; `init_db` tự `CREATE SCHEMA`), `revoke_sessions(username, keep=)`, `set_disabled` (khoá = xoá mọi phiên),
  `set_note`, `account_overview` (phiên gần nhất + tên máy). `authenticate` từ chối tài khoản khoá ("đã bị khoá…"), `resolve_session` trả None. Đăng nhập
  ghi tên máy chạy agent (`socket.gethostname()`), chỉ ghi IP khi gọi từ máy khác. Routes `routes/account_admin.py` (chỉ admin, còn lại 403):
  `GET /api/admin/accounts`, `POST` {username, password, note, cloud}, `PATCH /{username}` {disabled, note} (không khoá được admin),
  `POST /{username}/password` {new} (không áp cho admin — admin đổi ở "Đổi mật khẩu"; đăng xuất mọi phiên của người đó), `POST /{username}/logout`.
  `POST /api/account/password` từ chối mật khẩu mới trùng cũ, đăng xuất các máy khác (giữ trình duyệt đang dùng), trả `logged_out`. `/api/account/me`
  có `is_admin`. Frontend: `api/account.ts` (`call()` giữ câu lỗi của agent, `listAccounts`, `createAccount`, `updateAccount`, `resetAccountPassword`,
  `logoutAccountEverywhere`, `randomPassword` — bỏ 0/O/1/l/I), đổi mật khẩu nằm ở trang **Tài khoản của tôi** (`/account`, xem mục "Gói Dùng thử…" — hộp
  `ChangePasswordDialog` cũ đã bỏ 8/11), sidebar mục **👥 Quản lý tài khoản** chỉ hiện khi `me.is_admin`,
  route `/accounts` (`pages/AccountsPage.tsx` + `accounts.css`, tiền tố `acc-`): tạo tài khoản (mật khẩu ngẫu nhiên 🎲, ghi chú, ô "lưu trên cloud"), khung
  "✓ Đã tạo" + "📋 Copy để gửi" (mật khẩu chỉ hiện lúc đó), bảng tài khoản (vai trò, khoá, ghi chú ✎, ☁ Cloud / 💻 Một máy, đăng nhập gần nhất + máy + số phiên,
  🔑 Đặt lại mật khẩu (copy luôn thông tin đăng nhập), 🔒 Khoá / 🔓 Mở khoá, ⎋ Đăng xuất mọi máy); tài khoản thường mở `/accounts` thấy "Chỉ tài khoản quản
  trị…". Khoá / đổi mật khẩu có hiệu lực ngay trên máy đó; máy khác nhận ra trong ≤ 5 phút (cache phiên trong RAM). Không xoá tài khoản (dữ liệu) — chỉ khoá.
  **Máy mới cài app chưa có dòng Neon thì tài khoản bạn bè không đăng nhập được** (kho trung tâm trên máy đó trống, chỉ có seed) mà ô dòng cloud lại
  nằm trong Cài đặt (cần đăng nhập) → 1.5.2 thêm `GET/POST /api/app/connect` (**mở, không cần đăng nhập**, trong `OPEN_PATHS`): GET `{app, cloud,
  restart_pending}`; POST `{central_db_url}` chỉ khi máy **chưa** nối cloud (đã nối → 409, đổi qua Cài đặt sau khi đăng nhập), chỉ từ loopback, nhận cả
  dòng `FLOWBOARD_CENTRAL_DB_URL=…` (`_db_line`, dùng chung với PUT settings), **thử kết nối trước** (`_probe_cloud`: `SELECT 1`, timeout 12 s, NullPool, phải
  có bảng `account_user` — gõ nhầm / database lạ bị từ chối; lỗi không lộ mật khẩu, bỏ tiền tố `(psycopg.errors.X)`), ghi `.env`, app thì `os._exit(75)` để
  vỏ Tauri khởi động lại, start.ps1 thì báo chạy lại. `LoginPage.tsx` `CloudConnect`: khung "🌐 Dán dòng kết nối trước" khi `!cloud` → textarea → Kết nối →
  "đang khởi động lại…" (poll GET connect tới khi `cloud`, tối đa 120 s) → "✓ Đã nối… đăng nhập bằng tài khoản được cấp". README Cách 1 bước 4 + Mục 6.5 /
  6.6 (cấp tài khoản) + bảng lỗi theo đúng trình tự đó. Test `test_app_mode.py` +2.
  **Không dạy trợ lý AI** (tạo tài khoản / mật khẩu qua chat không hợp). Test `test_account_admin.py` (7), `test_account_login.py` (open sign-up test thay bằng
  "không có đăng ký tự do"). Thử thật bằng Playwright trên agent tách riêng (cổng 8534, `FLOWBOARD_HOME` tạm, kho SQLite, không Neon). **Bảo mật chỉ ở mức
  app**: máy bạn bè vẫn phải có chuỗi Neon đầy đủ quyền (đọc được mọi schema / bảng trung tâm) — muốn chặn thật phải làm Phase C (API riêng đứng giữa).
- **📦 Gói & tính năng + ⬆ Nâng cấp bằng chuyển khoản** (8/11, người dùng: "admin quản lý chức năng cho user qua gói VIP / Pro / Premium (thêm, bớt,
  đổi tên)… mỗi tài khoản có label gói, nút nâng cấp → màn các gói → QR + nội dung + số tiền, akiragosho cài được, nội dung mặc định 'tên tài khoản - tên gói',
  chuyển xong bấm done, kiểm tiền thủ công"):
  - **`flowboard/plans.py`**: `FEATURES` (9 khoá: `auto_clip`, `dub`, `capcut`, `clean`, `posts`, `facebook`, `autopilot`, `swipes`, `assistant` — làm clip / sản
    phẩm / người mẫu / prompt / lịch sử / cài đặt **không bao giờ bị khoá**), `DEFAULT_PLANS` VIP (không dub) / Pro (không facebook + autopilot) / Premium (đủ),
    (8/11 tối: gói mặc định thành **Dùng thử** `trial` — xem mục kế; tài khoản có từ trước được ghi hẳn gói cũ). Lưu ở kho trung tâm `account_setting` khoá `plans` = `{plans: [{id, name, features}], default}`
    (`normalize`: bỏ khoá lạ, tên không trùng, id slug cố định khi đổi tên, id "admin" cấm; cache RAM 30 s; `save` → `accounts.reassign_missing_plans`). Cột
    `account_user.plan` (ALTER như role / disabled / note; NULL = gói mặc định), `accounts.set_plan` (làm mới phiên trong RAM `_refresh_cached`). `plan_of(user)`:
    admin = "Toàn quyền" (mọi khoá). **Chặn API**: `_rule` (regex đường dẫn → khoá, một số chỉ GET, tuple = có một là đủ, `None` = không chặn) + middleware
    `_require_login` (`main.py`, import `account_plans` — **`plans` trong main.py là route Canvas**, bẫy dính lúc làm) trả 403 `{detail, feature}`. Ngoại lệ có chủ
    ý: `/api/dub/status` (Bước 4 hỏi Remotion), `/api/clean/*/detect` (OCR của trình lồng tiếng: clean hoặc dub), `/api/posts/clip-hooks` (Bước 2), GET `/api/posts`
    (posts hoặc facebook — Lịch đăng liệt kê bài), `/api/channels` (hộp Clip mới dùng) — chỉ brainstorm / review (posts) và kết nối Page (facebook) bị chặn. Vòng
    nền: `scheduler.tick` / `autopilot.tick` dừng khi tài khoản đang mở mất facebook / autopilot (`plans.active_allows`, đọc lại user từ kho).
  - **`flowboard/billing.py`**: cài đặt `account_setting` khoá `billing` = `{bank_bin, account_no, account_name (bỏ dấu, IN HOA), template (mặc định
    "{username} - {plan}"), prices {plan_id: VND}, note}`; `BANKS` 20 ngân hàng + BIN NAPAS (khác thì nhập BIN); `transfer_text` (bỏ dấu, ≤ 50 ký tự);
    **`vietqr_payload`** tự dựng chuỗi VietQR NAPAS (EMVCo: 00/01 "12"/38 {A000000727, {BIN, STK}, QRIBFTTA}/53 704/54 số tiền/58 VN/62-08 nội dung/63 CRC-16
    CCITT-FALSE), trình duyệt vẽ QR bằng npm **`qrcode` 1.5.4** (`lib/qr.ts`) — không dịch vụ QR ngoài nào thấy STK. Bảng trung tâm **`account_upgrade`** (id,
    username, plan_id, plan_name, amount, content, status pending|approved|rejected|cancelled, created_at, decided_at; tạo lần đầu dùng `upgrades.create(checkfirst)`
    theo `WeakSet` engine). `offer` / `quote` (lỗi rõ: chưa cài ngân hàng, gói chưa có giá, đang dùng gói đó) / `file_request` (một yêu cầu chờ mỗi tài khoản, gửi
    lại thì huỷ cái cũ) / `cancel_request` / `decide` (duyệt → `set_plan`). Routes: `GET /api/account/upgrade`, `POST …/upgrade/quote|request|cancel` (mọi tài khoản trừ
    admin); admin `GET/PUT /api/admin/plans` (`plans_router`), `GET/PUT /api/admin/billing` + `POST /api/admin/billing/requests/{id}/approve|reject` (`billing_router`,
    trả kèm `sample` QR của gói có giá đầu tiên để admin quét thử); `PATCH /api/admin/accounts/{u}` nhận `plan`, `POST` tạo tài khoản nhận `plan` (mặc định gói mặc định).
    `/api/account/me` trả `plan {id, name}` + `features`.
  - Frontend: `lib/features.ts` (`useFeature`, `canUse`, `hasFeature` — `me.features` thiếu = agent cũ, không chặn), `quicktool/FeatureGate.tsx` (route bị khoá → "🔒 …
    chưa có trong gói X" + "⬆ Nâng cấp gói"), sidebar ẩn mục theo gói, `AssistantWidget` ẩn, nút ⚡ Tạo video tự động / Chạy N clip dở ẩn khi thiếu `auto_clip` (chỉ
    chặn ở giao diện — `runAuto` chạy trong trình duyệt), Bước 5 (📅 Lên lịch đăng ↔ facebook, ✍️ Viết bài ↔ posts, mở trang lồng tiếng ↔ dub), Hôm nay (Đến giờ
    đăng, nút Viết bài; không gọi `/api/schedule/due` khi thiếu), Kênh (Viết bài / Định hướng / Đánh giá page ↔ posts, Kết nối Page ↔ facebook), Sản phẩm (🎁 Gói ↔
    posts), Bài viết (thiếu facebook: thanh đăng chỉ Copy + câu nhắc, ẩn mọi 📅 / Đăng ngay / Xếp lịch cả loạt, không đồng bộ FB; thiếu autopilot: ẩn tab Tự động).
    (`UserChip` 8/11 tối: chỉ còn avatar + tên + gói, bấm mở `/account`, và nút "Thoát".) `components/UpgradeDialog.tsx` (portal, z 1250; mở là gọi lại `/me`): thẻ các gói (giá / "Liên hệ",
    ✓ / — từng tính năng, "Đang dùng") → "Nâng cấp lên X" → QR 300 px + ngân hàng / STK / chủ TK / số tiền / nội dung (Copy từng cái) → "✓ Tôi đã chuyển khoản" → khung
    "⏳ Đã gửi yêu cầu… Huỷ yêu cầu". Admin (`/accounts`): cột **Gói** (select ngay trên dòng), ô Gói khi tạo tài khoản, **`PlansEditor.tsx`** (bảng tính năng × gói:
    tick, đổi tên, ◀ ▶ đổi thứ tự, tất cả / bỏ hết, 🗑 xoá (hỏi khi gói đang có tài khoản), ＋ Thêm gói, "💾 Lưu gói" một lần), **`BillingEditor.tsx`** ("💳 Thanh toán
    nâng cấp": yêu cầu chờ duyệt (✓ Duyệt / ✗ Từ chối, hỏi trước) + huy hiệu số chờ, ngân hàng, STK, chủ TK, mẫu nội dung + ví dụ, giá từng gói, ghi chú, QR mẫu,
    lịch sử yêu cầu). Gói đổi có hiệu lực API ngay (máy khác ≤ 30 s cache gói / 5 phút cache phiên); giao diện người dùng cập nhật khi tải lại trang / mở hộp nâng cấp.
  - Test `test_plans.py` (6), `test_billing.py` (4: chuỗi VietQR + CRC, bỏ dấu, cả luồng trả tiền → duyệt, từ chối / huỷ / quyền). Playwright trên agent tách riêng.
  - **Không dạy trợ lý AI** (quản lý gói / tiền không hợp qua chat). **Không tự kiểm tra tiền** (người dùng: kiểm thủ công).
- **Gói Dùng thử + đổi thứ tự gói + trang "Tài khoản của tôi"** (8/11 tối, người dùng: "chip sidebar xấu, chỉ 1 nút thoát, có màn hình riêng cho user: đổi tên,
  đổi pass, thêm thông tin, upgrade, lịch sử giao dịch… như web thường; các gói đổi vị trí được; gói trial mặc định không cần tạo, luôn đầu tiên, không nạp tiền,
  chỉ set ngày hết hạn 3 / 7 / 14 / 30, hết hạn là như bị ban"):
  - **Dùng thử** (`plans.TRIAL_ID = "trial"`, `TRIAL_DAYS = [3, 7, 14, 30]`, mặc định 7): `normalize` luôn đặt nó **đầu tiên** (thiếu thì thêm, giữ tên / tính năng /
    `days` admin đặt), `default` luôn là `trial`, thứ tự các gói khác = thứ tự gửi lên (cũng là thứ tự ở màn nâng cấp). `trial_end()`, `expires_for(plan_id)` (trial →
    ngày hết hạn, gói khác → None). Cột trung tâm **`account_user.plan_expires`** (TIMESTAMP, naive UTC) + **`profile`** (TEXT JSON: `display_name`, `phone`, `email`,
    `contact` — `accounts.PROFILE_KEYS`, `set_profile`), ALTER như các cột trước. **`accounts.expired(user)`** (có hạn và đã qua; admin không bao giờ hết hạn):
    `authenticate` từ chối "Gói dùng thử của tài khoản này đã hết hạn (dd/mm/YYYY)…", `resolve_session` (cả bản cache) trả None → như tài khoản khoá (máy khác nhận ra
    ≤ 5 phút). Tạo tài khoản không chọn gói → trial + hạn; đổi gói qua PATCH → `set_plan(…, expires_for)` (lên gói trả tiền là xoá hạn); duyệt nâng cấp cũng vậy; gói bị
    xoá → tài khoản về trial **tính từ hôm đó**. **Di trú**: `plans.load()` thấy `plans` đã lưu mà chưa có trial → `accounts.fill_null_plans(default cũ)` (tài khoản NULL
    được ghi hẳn gói cũ, không rơi vào trial), chưa từng lưu → `fill_null_plans("premium")`. Đổi số ngày chỉ áp cho tài khoản tạo sau / lần gia hạn.
  - Routes mới: `POST /api/admin/accounts/{u}/extend` (chỉ tài khoản đang dùng thử: hạn mới = hôm nay + số ngày), `GET /api/admin/plans` thêm `trial_id`, `trial_days`;
    `PUT /api/account/profile`, `GET /api/account/upgrades` (lịch sử của chính mình, `billing.list_requests(username=)`), `POST /api/account/logout-others`; `/me` có
    `profile`, `plan {id, name, trial, expires_at}`. `billing.offer` bỏ trial khỏi danh sách gói, `current` có `trial` / `expires_at`; `quote` từ chối trial.
  - Frontend: **`quicktool/pages/AccountPage.tsx`** (+ `account.css`, tiền tố `me-`, route `/account`): thẻ đầu (avatar chữ cái, tên hiển thị, @username, quản trị,
    dữ liệu cloud / máy, ngày tạo + khung "Gói đang dùng": tên gói, "Dùng thử còn N ngày · hết hạn ngày …" (vàng, đỏ khi hết, cảnh báo khi ≤ 2 ngày), **⬆ Nâng cấp
    gói** (admin: "👥 Quản lý tài khoản & gói"), dòng yêu cầu đang chờ), "Gói X có những gì" (✓ / — 9 tính năng, lấy nhãn từ `getUpgradeOffer`), **Thông tin cá nhân**
    (tên hiển thị → hiện ở chip sidebar, SĐT, email, liên hệ khác; tên đăng nhập không đổi), **🔑 Đổi mật khẩu** ngay trên trang (`?focus=password`), **🧾 Lịch sử
    giao dịch** (thời gian, gói, số tiền, nội dung, trạng thái + giờ duyệt, Huỷ yêu cầu), **Đăng nhập** (⎋ Đăng xuất các máy khác, Thoát khỏi máy này). `UserChip`:
    avatar + tên hiển thị + "Gói X · còn N ngày" (vàng khi ≤ 2 ngày) → `/account`, nút "Thoát" (`signOut()` export dùng chung). `PlansEditor`: cột trial đầu, nhãn
    "Dùng thử · mặc định", ô "Hết hạn sau 3/7/14/30 ngày", không xoá / không dời; gói khác có ◀ #n ▶; bỏ radio mặc định. `AccountsPage`: dưới ô chọn gói của tài khoản
    dùng thử hiện "còn N ngày · tới dd/mm/yyyy" / "Hết hạn …" + **Gia hạn**, chip "hết hạn", tên hiển thị dưới username; `BillingEditor` chỉ nhận gói trả tiền.
    `UpgradeDialog`: "Đang dùng: Dùng thử · còn N ngày (tới …)" + khung vàng nhắc hết hạn là không đăng nhập được. `api/account.ts`: `agentDate`, `timeLeft`, `dayText`,
    `saveProfile`, `listMyUpgrades`, `logoutOthers`, `extendTrial`.
  - Test `test_plans.py` (10: trial đầu / mặc định / chuẩn hoá, đổi thứ tự + xoá gói → trial có hạn, hết hạn không đăng nhập được + phiên đang mở mất + gia hạn, di trú
    gói cũ, hồ sơ + đăng xuất máy khác). Playwright trên agent tách riêng (`e2e/account_trial.js` trong scratchpad): chip → trang, đổi tên → chip đổi, đổi mật khẩu,
    màn nâng cấp không có trial, dời Premium lên đầu + trial 14 ngày lưu đúng thứ tự, ép hết hạn → đăng nhập bị từ chối → Gia hạn → vào được, 760 px không tràn.
- **Thời hạn gói trả phí + bảng giá có giá gốc** (8/11 tối, người dùng: "set time cho gói tuỳ theo tài khoản: 1, 6 tháng, 1 năm hoặc vĩnh viễn; giá để 1
  mức trước sale tạo hiệu ứng giá; set hạn thì hiện lên để người mua biết mà chốt; 1 gói có thể vừa có thời hạn vừa vĩnh viễn, nhiều loại thời hạn"):
  - `plans.TERM_MONTHS = [1, 3, 6, 12, 24, 0]` (0 = vĩnh viễn), `term_label`, `add_months` (ngày 31 → cuối tháng ngắn), **`plan_end(plan_id, months, days, base)`**
    (trial: + days hoặc độ dài trial; trả phí: + months, 0 = None; `base` = hạn hiện tại khi gia hạn cùng gói còn hạn → cộng nối tiếp, quá khứ / không có → từ
    hôm nay). **Gói trả phí hết hạn cũng khoá đăng nhập** như trial (`accounts.expired` áp mọi `plan_expires`; câu báo "Gói dùng thử / Gói đang dùng … đã hết hạn").
  - **Thời hạn + giá là một phần của gói** (8/11 tối, người dùng chỉnh: "set hạn cho gói — VIP 1 tháng 49k, 1 năm 490k, forever 980k"; lần đầu tôi
    để bảng giá ở khung Thanh toán): mỗi gói trả phí trong `plans` (khoá `plans` của kho trung tâm) có **`terms` = `[{months, price, list_price}]`**
    (`plans.clean_terms`: chỉ độ dài trong TERM_MONTHS, mỗi độ dài một lần, phải có giá, `list_price` chỉ giữ khi > giá, ngắn → dài, vĩnh viễn cuối; gói Dùng thử
    không có `terms`). `PUT /api/admin/plans` lưu cả tính năng + thời hạn + thứ tự. **Di trú** trong `plans.load()`: `plans` đã lưu mà chưa gói nào có khoá
    `terms` → lấy từ settings `billing` cũ (`terms` của bản build trước, hoặc `prices {plan: số}` → 1 dòng vĩnh viễn) rồi lưu; settings `billing` giờ chỉ còn ngân
    hàng / STK / tên / mẫu nội dung / ghi chú (không còn `terms` / `prices`). Mẫu nội dung có thêm `{term}` (mặc định vẫn "{username} - {plan}").
    `account_upgrade.months` (ALTER khi thiếu — bảng đã có trên Neon từ lúc người dùng test bản trước). `billing.offer` trả `terms` của từng gói; `quote(user, plan,
    months)` → `months, term, amount, list_price, renew, ends_at` (gia hạn đúng gói đang dùng được — chỉ từ chối khi đang dùng gói đó vĩnh viễn);
    `file_request(…, months)`; **duyệt** → `set_plan(…, plan_end(months, base = hạn còn lại nếu cùng gói))`. Routes: `POST /api/account/upgrade/quote|request
    {plan_id, months}`; admin `POST/PATCH /api/admin/accounts` nhận `months` (0 = vĩnh viễn) / `days` (trial) / `stack` (PATCH: cộng nối tiếp khi cùng gói) /
    **`expires_on` "YYYY-MM-DD"** (PATCH: ngày bất kỳ, hết hạn 23:59:59 giờ VN = 16:59:59 UTC; không gửi `plan` thì giữ gói hiện tại); `POST …/{u}/extend {months?,
    days?}` (trial: từ hôm nay; trả phí: bắt buộc `months`, cộng nối tiếp); `/api/admin/plans` + `/api/admin/billing` trả `term_months`; `/me` trả `plan.expires_at`
    cho mọi gói (null = vĩnh viễn). **Hạn của từng tài khoản** (`account_user.plan_expires`) vẫn riêng từng người: đi theo thời hạn họ mua, quản trị đổi được.
  - UI: **`PlansEditor`** ("📦 Gói & tính năng") — dưới tên mỗi gói trả phí một dòng tóm tắt giá ("49k/1 tháng · 490k/1 năm · 980k vĩnh viễn", `termsSummary`)
    + khối **"💰 Thời hạn & giá bán của từng gói"** (`quicktool/pages/TermsEditor.tsx`, class `bill__*` trong `accounts.css`: mỗi gói một khung "＋ Thêm thời hạn",
    dòng = Thời hạn ▾ / Giá bán / Giá gốc (gạch ngang) / **Khách thấy** (~~giá gốc~~ giá -x%, ≈ /tháng, cảnh báo thiếu giá / giá gốc thấp hơn) / 🗑; gói không dòng
    nào = "Liên hệ"), lưu chung nút "💾 Lưu gói". `BillingEditor` chỉ còn ngân hàng + nội dung + ghi chú + QR mẫu + yêu cầu (dòng nhắc giá ở bảng Gói). **`UpgradeDialog`**:
    mỗi thẻ gói = giá to + giá gốc gạch ngang + nhãn đỏ "-x%", dòng "Dùng 6 tháng · hết hạn dd/mm/yyyy · ≈ 83k/tháng" (gia hạn tính từ hạn còn lại), danh sách thời
    hạn chọn được (nhãn vàng **"Tiết kiệm nhất"** = giá/tháng thấp nhất khi có ≥ 2 thời hạn có hạn; mặc định chọn thời hạn đó), nút "Nâng cấp lên X · 6 tháng" /
    "Gia hạn X · 1 năm" (thẻ "Đang dùng"); đang dùng vĩnh viễn → "✓ Bạn dùng gói này vĩnh viễn"; màn QR có dòng Gói · thời hạn + **Hết hạn** + số tiền kèm giá gốc
    gạch ngang. **`quicktool/pages/PlanAssignDialog.tsx`** (portal, `.pa-backdrop` z 1250, nút `qt-btn` vì nằm ngoài `.qt-app`): chip Gói, chip Thời hạn (trial: số
    ngày; trả phí: **các thời hạn gói đó bán kèm giá**, rồi hàng "Thời hạn khác (gói không bán, chỉ bạn gán)"), chip **"📅 Chọn ngày"** (ô ngày, hết hạn cuối ngày đó;
    ngày đã qua → cảnh báo khoá ngay), ô "Cộng nối tiếp thời gian còn lại" (cùng gói còn hạn), dòng kết quả "→ VIP · 3 tháng — hết hạn dd/mm/yyyy".
    `AccountsPage`: ô Gói thành nút `acc-planbtn` (tên gói ✎ → hộp trên) + dòng hạn ("còn N ngày · tới …" / "Hết hạn …" / "vĩnh viễn") + Gia hạn (trial: nhanh từ hôm
    nay; trả phí: mở hộp); tạo tài khoản gói trả phí có ô "Thời hạn" (thời hạn gói bán ghi kèm giá, mặc định thời hạn đầu của gói). `AccountPage` / `UserChip`: hạn + "còn N ngày" cho mọi gói có hạn (vàng khi
    ≤ 3 ngày), nút "↻ Gia hạn / nâng cấp gói", lịch sử ghi "VIP · 1 năm". `api/account.ts`: `PlanTerm`, `termLabel`, `discountPct`, `addMonths`, `extendPlan` (thay
    `extendTrial`).
  - Test `test_billing.py` (7: chuẩn hoá thời hạn, giá cũ ở settings thanh toán dời vào gói, mua 6 tháng → hết hạn đúng + gia hạn cộng nối tiếp, gói trả phí hết hạn khoá đăng nhập + extend /
    stack / đổi gói / vĩnh viễn / trial theo ngày / ngày bất kỳ). Playwright `e2e/plan_terms2.js` (giá trong bảng Gói, hộp tài khoản có thời hạn gói bán +
    chọn ngày 14/02/2027, khách thấy 59k → 49k -17%, 1 năm "Tiết kiệm nhất") và `e2e/plan_terms.js` (bản trước): nhập bảng giá qua giao diện, tạo VIP 1 tháng, hộp gán + cộng 3 tháng (→ 120 ngày),
    khách thấy giá gốc / -% / Tiết kiệm nhất, gia hạn 1 năm → QR + hết hạn 08/03/2028, quản trị duyệt → còn 486 ngày, lịch sử đúng, 760 px không tràn.
- **Bảo mật — đã vá 8/11 tối** (người dùng: "check kỹ security, đảm bảo crack app không dễ"):
  - **Bản cài (PyInstaller) luôn bắt đăng nhập + không tạo sẵn admin**: `config.PACKAGED = getattr(sys, "frozen", False)` (không dựa vào biến môi trường người dùng
    sửa được) → `accounts.auth_enabled()` luôn True (`FLOWBOARD_AUTH=off` trong `DFlowData\.env` không mở khoá được nữa), `seed_default()` không tạo
    `akiragosho / Password@123` (mật khẩu công khai trong code / README — trước đây xoá dòng cloud khỏi `.env` là kho trống → được admin). Máy cài mới không có dòng
    cloud thì không ai đăng nhập được → dán dòng cloud ở trang đăng nhập (có sẵn). Chạy từ repo (start.ps1) vẫn như cũ.
  - **Phiên đăng nhập lưu dạng băm**: `account_session.token` = HMAC-SHA256 của cookie với pepper (`licensing.session_key`, gọi qua `accounts._token_key`; bản đầu
    8/11 tối là SHA-256 thường; tạo / tra / cập nhật / xoá / `revoke_sessions(keep)`); cookie = `<user id>.<ngẫu nhiên>`, phải khớp `user_id` của dòng phiên (sửa tay
    `user_id` của phiên mình sang người khác không chiếm được tài khoản đó);
    ai đọc được bảng (mọi máy nối Neon) không lấy cookie của người khác để đăng nhập. Phiên cũ (chữ thường) không còn hợp lệ với agent mới → đăng nhập lại một lần;
    app bản cũ (≤ 1.5.2) vẫn lưu chữ thường cho tới khi cập nhật.
  - **Trang web lạ không điều khiển được agent**: CORS chỉ cho `localhost` / `127.0.0.1` / `[::1]` (mọi cổng), `chrome-extension://<32 a–p>`, `tauri.localhost`
    (`main.ALLOWED_ORIGIN`, trước là `*` kèm credentials); middleware `_refuse_foreign_pages` (ngoài cùng) trả 403 cho POST / PUT / PATCH / DELETE có `Origin` lạ hoặc
    `null` (CORS chỉ giấu câu trả lời, lệnh vẫn chạy — vd. trang web lạ POST `/api/app/connect` trỏ máy cài mới sang Postgres của kẻ xấu). Extension gọi agent
    bằng quyền host (`host_permissions` 127.0.0.1:8434) nên không bị chặn.
  - Test `test_security.py` (3).
  - **Lỗ còn lại**: ai có dòng Neon vẫn đọc / sửa được dữ liệu mọi tài khoản (sửa quyền thì hết tác dụng — mục "Chữ ký số quyền dùng" ngay dưới, và Việc đang dở).
- **🔏 Chữ ký số quyền dùng + agent dịch bằng Nuitka** (8/11 khuya, "hướng B" — người dùng: "làm B luôn đi"; miễn phí, không cần máy chủ):
  - **`flowboard/licensing.py`**: Ed25519 (`cryptography`, thêm vào dependency chính). **Khoá công khai** nhúng trong code (`PUBLIC_KEY_B64`); **khoá riêng chỉ ở máy nhà**
    `%USERPROFILE%\.flowboard\dflow-license.key` (ngoài git; `FLOWBOARD_LICENSE_KEY` để trỏ chỗ khác) — **không bao giờ in / commit / gửi đi**; người dùng cần **sao lưu**
    (USB / trình quản lý mật khẩu): mất khoá = không cấp / đổi quyền được nữa (phải tạo cặp khoá mới, đổi `PUBLIC_KEY_B64`, phát hành bản mới, xoá `license_epoch` +
    `license-state.json` + cột `license` rồi để máy có khoá ký lại từ đầu). Máy khác muốn quản lý (máy cty) → chép file khoá vào cùng chỗ.
  - **Giấy phép từng tài khoản** = cột `account_user.license` (`"<b64 JSON>.<b64 chữ ký>"`, ký `b"dflow-license:1:" + JSON chuẩn hoá`): `{v, u, id, r, p, n, f, e, x, lh, t}` =
    phiên bản, tên, id, vai trò, gói, tên gói, tính năng, hạn (UTC, null = vĩnh viễn), khoá, vân tay băm mật khẩu kiểu cũ, lúc ký. Gắn với tên + id (chép giấy phép
    người khác sang dòng mình không dùng được). `licensing.apply()` chạy trong `accounts._row_to_user` → mọi chỗ đọc `role / plan / plan_expires / disabled / features`
    thấy giá trị **đã ký**; giá trị của dòng giữ ở `user["db"]`, lệch thì `user["tampered"]` (trang quản lý hiện "⚠ bị sửa tay"). **Tài liệu ký** ở `account_setting`
    `"<khoá>:sig"`: `plans` (bảng gói + giá), `billing` (ngân hàng / STK — khách chỉ thấy QR + giá khi cả hai đã ký, `billing.trusted()`), `min_app` (bản app cũ nhất được dùng).
    Chữ ký tài liệu kiểm **đúng bản đã lưu** (`sign_doc` lưu đúng thứ nó ký; `doc_state(key)` đọc lại bản lưu), không phải bản code chuẩn hoá lại từ nó → sửa
    `plans.normalize` / `billing.normalize` sau này (thêm khoá, đổi mặc định) không làm lệch chữ ký, khách không mất QR.
  - **Kho "đã ký"** khi có `account_setting` `license_epoch`; `licensing.active()` = kho đã ký **hoặc** chế độ chặt (`strict()`: bản cài `config.PACKAGED`, hoặc
    `FLOWBOARD_LICENSE_STRICT=1`) → tài khoản không có giấy phép hợp lệ **không đăng nhập được** (`unlicensed`, câu "chưa được người quản lý cấp quyền…"). Kho chưa ai
    ký + chạy từ repo = như cũ (test, dev). **Ký lần đầu** (`ensure_epoch`, "tin lần đầu"): máy có khoá, lúc `accounts.startup()` hoặc mở trang Quản lý tài khoản →
    ký mọi tài khoản theo dòng hiện có (tài khoản quản trị trước — rớt kết nối giữa chừng thì quản trị vẫn vào được để gán tay phần còn lại) + bảng gói +
    thanh toán + `min_app` = bản đang chạy, đặt dấu, nhớ store id ở `~/.flowboard/license-state.json`; **chỉ một lần mỗi
    kho mỗi máy có khoá** — sau đó không bao giờ ký lại theo dòng (mất dấu → đặt lại dấu, không ký gì; xoá hết giấy phép → không ai đăng nhập được → khôi phục Neon).
  - **Chỉ máy có khoá đổi quyền**: tạo tài khoản, đổi gói / hạn, khoá / mở khoá, lưu bảng gói, lưu thanh toán, duyệt nâng cấp → `licensing.guard()` → `LicenseError`
    (403 + câu "🔒 Máy này không có khoá ký…"); máy không khoá = trang quản trị chỉ xem (banner 🔒), máy có khoá banner 🔑 kèm nhắc sao lưu. `issue()` lấy phần không
    đổi từ **giấy phép hợp lệ hiện tại**, không bao giờ từ dòng (dòng có thể bị sửa tay); duyệt nâng cấp kiểm số tiền = giá hiện tại của gói + thời hạn (chặn yêu cầu
    tự chèn số tiền nhỏ); `plans.load()` không ghi đè bảng gói trên kho đã ký; lưu gói → ký lại giấy phép của tài khoản có gói đổi tên / tính năng / bị xoá
    (`resign_after_plans`). Đặt lại mật khẩu / ghi chú / đăng xuất mọi máy không cần khoá.
  - **Mật khẩu có pepper**: `licensing.PEPPER` (bí mật dịch vào app; **không in ra**) → băm `dflow2$200000$salt$hex` = pbkdf2(pepper \0 tên \0 mật khẩu) — không giả được
    nếu không có mã của app, gắn với tên đăng nhập. **App ≤ 1.5.2 không đọc được băm mới** → tài khoản tạo / đổi mật khẩu bằng code mới không đăng nhập được ở app cũ.
    Băm kiểu cũ `pbkdf2_sha256` chỉ nhận khi `legacy_fp(băm) == licence.lh` (ghim lúc ký lần đầu) → băm tự chế dán vào dòng bị từ chối ("Mật khẩu của tài khoản này cần
    được người quản lý đặt lại"). Bản cài (chặt) đổi băm cũ sang `dflow2` lúc đăng nhập (→ tài khoản đó hết đăng nhập được ở app cũ); chạy từ repo thì không đổi.
    **Bẫy**: đổi mật khẩu bằng app cũ (≤ 1.5.2) sau khi kho đã ký → băm cũ mới không khớp `lh` → code mới từ chối. Cứu (cả tài khoản quản trị): trên máy có repo + `.env`
    chạy `cd agent; .venv\Scripts\python.exe -c "from flowboard import accounts; accounts.set_password('<tên>', '<mật khẩu mới>')"`.
  - **Agent dịch Nuitka** (bản cài): CI (`.github/workflows/desktop.yml`, bước "Agent (Nuitka + PyInstaller)") dịch cả gói `flowboard` thành **một** extension mã máy
    `flowboard.cp311-win_amd64.pyd` (`python -m nuitka --module flowboard --include-package=flowboard --msvc=latest --jobs=4 --lto=no`, ~4 phút), spec đọc `DFLOW_COMPILED`
    → bỏ mọi module `flowboard.*` khỏi archive PyInstaller, thêm `.pyd`; Nuitka đặt `__file__` dưới `<thư mục pyd>/flowboard/…` nên file dữ liệu trong `_internal/flowboard/`
    vẫn tìm thấy. CI kiểm `.pyd` có trong bộ + chạy thử agent (`/api/health` 200, `/api/account/me` 401). Không đặt `DFLOW_COMPILED` = bytecode như cũ (thử nhanh).
    Thử thật trên máy nhà (bản dịch + PyInstaller, cổng 8534, kho SQLite tạm ký bằng khoá thật): không còn module flowboard dạng bytecode, admin đăng nhập, 8 mẫu clip /
    prompt mẫu đọc được, tạo tài khoản VIP → sửa tay dòng thành admin / Premium / bỏ hạn → vẫn VIP, không vào trang quản trị (403), lệnh từ trang lạ 403.
  - `flowboard/__init__.py` `__version__` (= bản phát hành; CI "Version check" kiểm cùng các file khác) dùng cho `min_app` (`licensing.outdated()` chặn bản cũ hơn bản
    đã ký). Nâng `min_app` **chưa có nút**: trên máy có khoá `accounts.set_setting("min_app", {"v": "X.Y.Z"}); licensing.sign_doc("min_app", {"v": "X.Y.Z"})`.
  - Test `test_licensing.py` (12: ký lần đầu, sửa tay vô hiệu, chép / giả / tự chế giấy phép + băm bị từ chối, dời phiên sang người khác bị từ chối, khoá + hạn nằm
    trong giấy phép, máy không khoá chỉ xem, đổi STK / duyệt gian bị từ chối, không ký lại theo dòng, `min_app`, sửa code chuẩn hoá không lệch chữ ký, chữ ký của website, băm cũ đổi ở chế độ chặt — khoá thử tự tạo trong tmp),
    `test_security.py` (3); `conftest.py` trỏ `FLOWBOARD_LICENSE_KEY` vào đường dẫn tạm không có file (test không bao giờ dùng khoá thật), bỏ `FLOWBOARD_LICENSE_STRICT`.
  - **Không chặn được (cần máy chủ riêng, Phase C)**: phát lại giấy phép **cũ của chính mình** (vd. bản lưu trước khi bị khoá); **app ≤ 1.5.2 không có chặn gói nào** và
    bộ cài đang công khai trên dflow-releases; ai có **mã nguồn** (được mời vào repo — Cách 2 README) sửa được code chạy trên máy họ + biết pepper → chỉ mời người tin
    tuyệt đối, khách dùng bản cài; dòng Neon vẫn đọc được dữ liệu / key của mọi tài khoản; bản dịch Nuitka vẫn dịch ngược được bằng công cụ chuyên (khó hơn nhiều).
  - **Khoá ký của website** (8/11 khuya, người dùng: web quản lý tài khoản / gói song song, "web là ngoại lệ chữ ký số"): không bỏ hẳn chữ ký cho web được
    (ai có dòng Neon cũng giả được là web) → web có **khoá riêng**, app tin như khoá quản trị: `licensing.WEB_PUBLIC_KEY_B64` (`_trusted()` / `_ok()` thử cả hai
    khoá; app vẫn chỉ ký bằng khoá quản trị; `status()` có `web_fingerprint`). Khoá riêng của web: **`%USERPROFILE%\.flowboard\dflow-web-license.key`** (ngoài
    git, không in / gửi; sao lưu như khoá quản trị) — web đọc qua `DFLOW_LICENSE_KEY_FILE` (máy nhà, đã đặt trong `dflow-web/.env.local`) hoặc dán dòng khoá vào
    `DFLOW_LICENSE_KEY` (máy chủ). Ai cầm khoá web = cấp được mọi gói như khoá quản trị → chỉ để trên máy chủ web. Lộ khoá web: tạo cặp mới, đổi
    `WEB_PUBLIC_KEY_B64` (+ `WEB_PUBLIC_KEY` bên web), phát hành app mới, ký lại các giấy phép web đã ký. Test `test_the_websites_key_counts_like_the_admins`;
    thử chéo: node ký bằng file khoá web theo đúng cách của web → `licensing.unseal` nhận, token bị sửa → từ chối.
  - **`../dflow-web`** (site Next.js cổng 3030, chung Neon, phiên khác làm) có bản port `src/lib/licensing.ts` + `websync.ts` + `password.ts`: **đổi định dạng
    giấy phép / tài liệu ký / băm mật khẩu / luật gói ở đây thì sửa bên đó luôn** (người dùng 8/11: "việc code sẽ làm song song nếu bên web cần update"). 8/11
    khuya đã sửa bên web: tin cả khoá web + khoá quản trị, giấy phép web ký **mang theo `lh`** (trước đó thiếu → tài khoản còn băm cũ bị app khoá đăng nhập khi
    web ký lại), không lưu mật khẩu khi thiếu `DFLOW_PEPPER` trên kho đã ký. Bên này: `doc_state(key)` kiểm **bản đã lưu**, `sign_doc` lưu luôn tài liệu vừa ký.
- **🌐 Phase C — app đăng nhập qua dflow.io.vn, không cầm dòng Neon** (8/11 khuya, người dùng: "bạn toàn quyền, triển hướng C đi, làm hết"; miễn phí — Vercel
  Hobby + Neon free; máy nhà không cần bật 24/7):
  - **Bật khi nào**: bản cài (`config.PACKAGED`) mà `.env` **không có** `FLOWBOARD_CENTRAL_DB_URL` → `cloud_api.enabled()` (mặc định `https://dflow.io.vn`;
    `FLOWBOARD_CLOUD_API` đổi địa chỉ, để trống = tắt — `conftest.py` đặt trống; chạy từ repo muốn thử thì đặt `FLOWBOARD_CLOUD_API=http://127.0.0.1:3030`).
    Máy có dòng Neon (máy nhà / start.ps1) vẫn **chế độ trực tiếp** như cũ (owner: ký số, quản trị trong app).
  - **Web (`dflow-web`)**: API cho app `src/app/api/app/*` — `POST login` (kiểm mật khẩu + khoá + hết hạn + giấy phép + băm cũ có ghim `lh`, 10 lần sai / 15 phút → 429,
    băm cũ → băm lại có pepper), `GET me` (app hỏi lại mỗi 10 phút), `GET/PUT settings` (chỉ khoá `secrets:<user>` và `fb_token:<user>:<số>`), `POST media`
    (`op` put / get → link ký sẵn 15 phút, list thư mục `<user>/`, delete; key ngoài thư mục mình → 403), `upgrade` (GET pending + lịch sử, `request`, `cancel` — giá tính
    lại trên web), `account/profile|password|logout-others` (đổi mật khẩu / đăng xuất máy khác trả token mới cho máy đang dùng). Thư viện: `lib/appapi.ts` (token
    `dfa1.` HMAC với SESSION_SECRET + nhãn riêng, gắn dấu vân tay băm mật khẩu + mốc `app_after:<user>`; `appPayload` = dòng tài khoản thô + **chữ JSON nguyên văn**
    của `plans` / `billing` / `min_app` + chữ ký + `license_epoch` + dòng DB riêng), `lib/dbrole.ts`, `lib/media.ts` (aws-sdk v3, `requestChecksumCalculation:
    "WHEN_REQUIRED"` — B2 không nhận header checksum CRC). Khoá tài khoản trên web (`setDisabled`) → `lockRole` (NOLOGIN + ngắt kết nối).
  - **Role Postgres riêng từng tài khoản** (`dbrole.provision`, mỗi lần app đăng nhập, khoá `pg_advisory_xact_lock`): `CREATE ROLE "u_<username>" LOGIN` (mật khẩu 192
    bit, lưu **mã hoá AES-256-GCM** khoá từ DFLOW_PEPPER ở bảng `account_dbrole` — mọi máy của tài khoản nhận cùng một dòng), `GRANT role TO current_user WITH INHERIT
    TRUE, SET TRUE`, schema `acct_<user>` (tạo với AUTHORIZATION role, hoặc giao chủ), **giao chủ mọi bảng / view / sequence lẻ / kiểu** do người khác tạo trong schema,
    `ALTER DEFAULT PRIVILEGES` (bảng owner tạo sau vẫn dùng được), `search_path`; tài khoản backend sqlite / thiếu schema → ghi `{"type":"postgres","schema":…}`.
    Dòng DB trả về = dòng owner đổi user / mật khẩu, bỏ `-pooler.`. **Đã thử thật trên Neon** (tài khoản thử `phasec-test`, đã xoá sạch): role ghi được schema của nó,
    bị từ chối `account_user`, `account_setting`, `account_dbrole`, `acct_akiragosho`, CREATE SCHEMA; khoá → `rolcanlogin` false + web 403; mở khoá + đăng nhập → bật lại.
  - **Agent** `flowboard/cloud_api.py`: `login` / `store` (chép dòng tài khoản vào **kho cục bộ** `storage/accounts.db` — **giữ đúng id của web** vì giấy phép gắn id —,
    `backend = {"type":"postgres","schema","url","via":"api"}`, băm mật khẩu cục bộ để đăng nhập offline, tài liệu ký vào `account_setting` cục bộ, token `api_token:<user>`,
    `api_seen:<user>`), `maybe_refresh` (gọi từ `accounts.resolve_session`, nền, mỗi `REFRESH_S` 600 s; 401/403 → `drop` = đăng xuất máy này; offline quá `OFFLINE_OK_S`
    7 ngày → đăng xuất), `get_remote` / `set_remote` (cache 60 s), `account_call` (401 → drop). `accounts.py`: `via_api()`, `get_setting` / `set_setting` chuyển khoá
    `secrets:` / `fb_token:` qua API (`_remote`), `_authenticate_via_api` (web lỗi mạng / 5xx → dùng bản sao nếu mật khẩu khớp + web xác nhận trong 7 ngày; 403 → xoá
    băm cục bộ để không vào offline được), `startup` không seed / không ký trong chế độ này, `status().via_api`, `lock_db_role` (máy trực tiếp khoá tài khoản cũng NOLOGIN
    role). `file_store._ApiBucket` thay boto3 (put_object / upload_file / download_file / list_objects_v2 / delete_object qua link ký sẵn; 404 → `_NotInBucket`).
    `billing`: `pending_for` / `file_request` / `cancel_request` / `list_requests` gọi web (bảng giá + QR vẫn tính từ bản ký cục bộ). `routes/account.py`: password / profile /
    logout-others qua web, `_me_payload.site` (link web, admin, tài khoản); `account_admin._admin` → 409 "quản lý ở …/quan-tri"; `cloud.py` `/s3` (giờ chỉ admin, kể cả chế
    độ trực tiếp — trước đó tài khoản thường nào cũng ghi đè được key kho file) + `/migrate` → 409; `app.py` `GET /api/app/connect` có `site` (signup / forgot) và
    `cloud: true`. `db/session.init_db`: chỉ `CREATE SCHEMA` khi chưa có (xem Bẫy). Frontend: trang đăng nhập bỏ ô dán dòng, thêm "Đăng ký trên dflow.io.vn" + "Quên mật
    khẩu, hết hạn gói?" (`.login__site`, `.login__links`), menu "👥 Quản lý tài khoản ↗" + nút ở Tài khoản của tôi mở `…/quan-tri`, Cài đặt → Dữ liệu ẩn ô kho file + nút
    chuyển lên cloud khi `via_api`. Test `test_cloud_api.py` (10, web giả MockTransport) + `test_app_mode` sửa kỳ vọng.
  - **Vẫn còn**: máy trực tiếp (máy nhà, có dòng Neon) vẫn là owner — giữ dòng đó cho riêng mình; role đọc được tên các schema khác (catalog — lộ tên đăng nhập); một
    tài khoản có thể ghi đầy dung lượng Neon free (0,5 GB) của chính nó; agent bản cài vẫn là mã máy dịch từ Python (Nuitka) — giấy phép ký số lo phần gói.
- **Đăng xuất Flow phải bấm 2 lần** (21/10, `SettingsPanel.tsx`): lần đầu nút đổi thành "Bấm lần nữa để đăng xuất…" + "Huỷ",
  tự quay lại sau 5 s / khi đóng hộp; xong có toast (`AccountPanel.handleLogout`). Nút chỉ có ở hộp Cài đặt mở từ ⚙ cạnh tài khoản.

- **Ghép nhanh** (7/11, `video_export.py`): **60 fps làm trên từng clip nguồn, song song, có lưu lại** — `smooth_sources(paths)` chạy `smoothed_copy`
  cho mỗi clip (bản đã xoá logo) trong `SMOOTH_PARALLEL` (= nửa số luồng CPU, tối đa 6) ffmpeg cùng lúc, lưu `<thư mục tài khoản>/media/smooth60/<tên>.<cỡ>.60.mp4`
  (ghi qua `.part.mp4` + `os.replace`, khoá theo file nên 2 lượt ghép cùng clip chờ nhau) **trước** khi lồng giọng / phụ đề; `_voice_clip(fps=60)` mã hoá 60 fps
  nên phụ đề in trên hình đã mượt (trước đây nội suy cả chữ) và ghép vẫn stream-copy; Remotion vẽ phụ đề ở 60 fps (`_remotion_subtitles(fps=)`); clip nào làm mượt
  hỏng thì giữ khung gốc (lặp lên 60), `report.smooth60_error`. Drama (ảnh) và đường ghép trơn (không giọng / không logo) vẫn làm mượt clip ghép như cũ.
  **Đọc giọng trước** `_prefetch_voices` (luồng riêng, chạy cùng lúc làm mượt): VieNeu đọc mọi câu một lần nạp model (`tts.synthesize_many`), Edge đọc song song,
  vòng từng cảnh chỉ lấy cache; `_synth_to_fit` không đọc lại "nhanh hơn" với VieNeu / FPT (giọng đó bỏ qua tốc độ, đọc lại chỉ tốn nạp model ~20 s).
  **Một lượt ghép mỗi node**: `routes/requests.py` — `export_video` cùng node + cùng params khi đã có một cái queued / running thì trả lại cái đó (khoá
  `_create_lock` để 2 request 80 ms không cùng lọt); frontend `exportClip` dùng chung lượt đang gửi (`exportInFlight`), nút Bước 5 khoá ngay khi bấm (`sending`).
  Đo thật 4 clip áo khoác (Ryzen 7 5800H): ghép 60 fps + giọng VieNeu chưa có cache **179 s** (trước 618 s), "Ghép lại" đổi giọng **29 s** (đã có bản mượt).
  Test `test_export_speed.py` (6).
  **60 fps làm ngầm khi từng cảnh về** (`services/smooth_prewarm.py`, 7/11 tối): worker xong một `gen_video*` có node → `after_clip(node_id, media_id)` →
  nếu clip cần 60 fps (`board_wants`: node xuất `smooth60` của clip; clip chưa có node xuất thì lựa chọn quen dùng của tài khoản `ui_prefs.smooth60`)
  thì một pool `SMOOTH_PARALLEL` luồng: tải clip về nếu chưa có → `video_watermark.cleaned_copy` (đúng bản export sẽ dùng) → `smoothed_copy(low_priority=True)`
  (ffmpeg `BELOW_NORMAL_PRIORITY_CLASS` / `nice 10`). Ghép lúc đó gặp file đang làm thì chờ khoá của file, không làm lại. Routes `GET /api/boards/{id}/smooth60`
  → `{total, ready, running}`, `POST …/smooth60` = làm ngầm mọi cảnh của clip (`routes/export_extras.py`). Frontend: pref tài khoản **`smooth60`**
  (`store/settings.ts`), node xuất mới lấy sẵn giá trị đó (`_createExportNode`), ô dùng chung **`Smooth60Field`** (`JoinOptions.tsx`) ở **Bước 4** (khung "🎙 Giọng
  đọc, phụ đề & độ mượt khi ghép") và Bước 5: bật → lưu node + pref + POST; dòng trạng thái poll 5 s ("Đang làm mượt sẵn r/N cảnh" / "✓ Đã làm mượt sẵn cả N
  cảnh — ghép sẽ nhanh"); thấy ô đang bật mà còn cảnh chưa làm và không chạy → tự POST một lần (clip về trước khi bật, agent khởi động lại).
  Test `test_smooth_prewarm.py` (5).
- **🤖 Tự động đăng theo lịch** (7/11, người dùng: "tự soạn content xong tự post lên page mà user không phải làm gì, set cứng lịch, tới lúc đó mà có
  bài thôi"; chỉ Facebook Page, nằm trong trang Bài viết; AI: Claude CLI mặc định + Gemini): bảng **`AutoPlan`** (kênh, `days` 0 = T2…6 = CN, `times` "HH:MM"
  giờ VN ≤ 6, `lead_minutes` 30–1440 mặc định 180, `brief` = form Bài viết (`autopilot.clean_brief`), `series`, `product_mode` none | fixed | rotate +
  `product_ids`, `ai` claude | gemini, `fb_story`, `enabled`, `enabled_at`) + **`AutoRun`** (một dòng cho mỗi khung giờ; **unique (plan_id, slot_at) = giữ
  chỗ** → 2 máy không cùng viết; `lease_until` 10 phút gia hạn mỗi bước; status writing → pictures → ready | waiting (thử lại sau 10 phút, tối đa 3 lần) |
  failed | skipped | missed; `post_id`, `schedule_id`, `image_requests`, `ai_used`, `note`). `services/autopilot.py`: vòng `run_loop` (task `autopilot-loop`
  trong `main.lifespan`, 60 s) — `tick()` lấy khung trong `(now, now + lead]` → `_claim` → `_prepare`: kiểm Page còn nối (`scheduler.can_auto`) → `_write`
  (brief + sản phẩm theo lượt `_pick_product` (lâu nhất chưa nhắc), cta "link" khi sản phẩm có link aff, câu mở đầu xoay `ROTATE_HOOKS`, khối `extra` "AUTO
  SCHEDULE … nobody reads it — không bịa" + 8 bài gần nhất của lịch để không trùng chủ đề / câu mở đầu, loạt truyện = `_series_context` tập kế; AI của lịch
  trước, lỗi thì cái còn lại, ghi `note`) → `_save_written` (brief có `auto_plan`) → `_pictures` (gửi hết `gen_image` vuông một lượt, ảnh sản phẩm làm tham
  chiếu, chờ tới `slot − 2 phút`; ảnh hỏng thì đăng không ảnh + `note`) → `scheduler.create(auto=True, note "🤖 Tự động: …")` lúc `max(slot, now)`; xong trễ quá
  `LATE_OK` 10 phút → skipped. Khung trôi qua lúc agent tắt (sau `enabled_at`, trong 12 h) → **missed, không đăng bù**. Tạm dừng / xoá / đổi giờ →
  `_cancel_future` bỏ các khung chưa đăng (lịch `planned` → skipped; bài vẫn trong Bài đã lưu). `prepare_next` = "⚡ Soạn ngay bài kế tiếp". **Chọn AI**:
  `services/llm/registry.py` `use_ai("claude" | "gemini")` (ContextVar `AI_OVERRIDE`) — mọi `run_llm` trong khối đó đi Claude CLI (model / effort đang ghim nếu
  provider là claude) hoặc **pool Gemini API key** `gemini_api.generate_text` model `GEMINI_TEXT_MODEL` = gemini-3.5-flash (provider "gemini" của registry là CLI
  `agy`, không phải pool key). Routes `routes/autopilot.py`: `GET/POST /api/autopilot/plans`, `GET/PATCH/DELETE /plans/{id}` (PATCH `enabled:false` = tạm dừng),
  `POST /plans/{id}/prepare`, `GET /runs`, `GET /status` (AI nào chạy được). Nút "việc đang chạy": `running._autopilot_items` (`/posts?auto=1`), request
  `origin: autopilot` không hiện thêm dòng ảnh. Frontend: `api/autopilot.ts` (`RUN_STATUS`), `quicktool/posts/AutoPilot.tsx` + `autopilot.css` (tiền tố `ap-`):
  trang Bài viết có công tắc **"✍️ Viết & đăng" ⇄ "🤖 Tự động đăng theo lịch"** (`mode`, `?auto=1`); trái danh sách lịch (công tắc bật / dừng, bài kế + trạng thái,
  lần trước), phải form 3 khối (Page + ngày + giờ + soạn trước + 📲 tin / Đăng gì: kiểu, loạt truyện, ý chính, ảnh, kêu gọi, giọng, độ dài, sản phẩm / AI viết),
  "Sắp tới" + "Nhật ký" (bấm tên bài → mở bài ở tab viết). Form viết có nút **"🤖 Tự động đăng theo lịch với cài đặt này"** (mang kênh, brief, sản phẩm, loạt
  sang lịch mới). Trợ lý AI: kỹ năng **`auto_post`** {channel_id, days, times, kind?, topic?, series?, images?, product_id?, ai?, story?} — luôn chờ "✅ Làm luôn".
  Test `test_autopilot.py` (10), `test_assistant.py` (+1). Thử thật 7/11 (Page "Chúng ta hay tò mò", khung 6 ngày sau, đã dừng + xoá ngay, không đăng gì):
  Claude CLI viết 19 s đúng kiểu "Mẹo" (ngắm Sao Thổ), lịch auto được tạo; ảnh Flow lỗi `CAPTCHA_FAILED: grecaptcha not available` → bài vẫn sẵn sàng, ghi chú.
- **Clip quay như người thật + "🔇 Không lời"** (7/11, người dùng: "video review từ link SP máy móc quá… tối ưu prompt cho thật, người hơn" +
  "thêm option review không lời, chỉ mặc / thao tác dùng SP"):
  - **`services/clip_style.py`** = luật chung cho mọi chỗ AI viết cảnh: `LOOK_RULES` (video dọc quay điện thoại, nói rõ điện thoại ở đâu — bạn cầm ngang ngực /
    dựng trên kệ / chụp gương, nơi thật mà người mua dùng sản phẩm + 1–2 chi tiết đời thường, ánh sáng có thật, vân vải / da có lỗ chân lông, cấm chữ
    editorial / studio / cinematic / commercial / flawless / perfect / hero shot / chừa chỗ cho logo), `MOTION_RULES` (giữ mốc 0-3s/3-6s/6-8s, MỘT hành động chính +
    MỘT chi tiết người thật, nhìn sản phẩm / gương chứ không nhìn ống kính, không tạo dáng / ngón cái / vẫy, điện thoại cầm tay rung nhẹ hoặc dựng yên, không
    locked-off / dolly, tốc độ thật không "slow", kết bằng `Audio: ` 1–2 tiếng thật, miệng ngậm), `VOICE_RULES` (kể như người mua nói với bạn, mỗi câu một ý,
    đổi thông số thành cảm giác, câu 1 móc trong 2 giây — không mở bằng "Mọi người ơi, đây là…", câu cuối nhắc giỏ hàng nhẹ, không bịa lịch sử dùng / kết quả),
    `VOICELESS_RULES` (lời rỗng, kể bằng hình: tình huống → mặc / lấy ra → dùng thật → kết nhẹ nhàng; `Audio:` quan trọng nhất, không nhạc không lời),
    `person_line(gender, country)` (nam → "write he"; tay → chỉ tay), `POLISH_WORDS` / `polish_words()` (test giữ mẫu sạch), `NOTE_VOICE` / `NOTE_VOICELESS`
    (dòng hướng dẫn trong ghi chú kịch bản).
  - **8 mẫu clip viết lại** (`templates/*.json`: cảnh, chuyển động có `Audio:`, lời thoại, bối cảnh mặc định là nơi đời thường — phòng ngủ có gương, nhà tắm, quán ăn,
    bàn làm việc ở nhà, bếp nhà hơi bừa — `charVibe` mặc định `casual`, ghi chú + blurb). Gợi ý bối cảnh (`quicktool/suggestions.ts BACKDROPS`) và bối cảnh cho clip
    2–5 (`NewClipDialog SETTING_IDEAS`) cũng bỏ studio.
  - **`script_tailor`**: `system_prompt(voiceless)` = `_BASE` + `clip_style.scene_rules`; `tailor_scenes/tailor_spec(voiceless=, person=, place=, place_fixed=)` —
    bối cảnh mặc định của mẫu chỉ là gợi ý ("dời tới nơi sản phẩm thật sự được dùng": áo điều hoà → công trường / chạy xe), bối cảnh người bán gõ khác mặc định
    (`setting_choice(template, inputs)`) thì giữ nguyên; tả sản phẩm bằng chữ hình ảnh, bỏ size / màu / giá (trước đây dán nguyên mô tả "Available in grey…, sized M
    to 3XL" vào prompt ảnh); ảnh ≤ ~550 ký tự, chuyển động ≤ ~450. `tailor_board` đọc giới tính từ node nhân vật / `quicktool.hands` và `quicktool.voiceless`.
  - **"Theo link sản phẩm" / "Theo video mẫu"**: `product_link._SYSTEM_HEAD`, `reference_video._SYSTEM_HEAD` + `reference_video.plan_rules(voiceless)` /
    `system_prompt(head, voiceless)`; `analyze(..., voiceless=)`, `normalize(..., voiceless=)` (bỏ `narration_vi`, đánh dấu `analysis.voiceless`), `board_spec/build_board(
    voiceless=)`; nhân vật gợi ý vibe `casual`. Routes `/api/reference-video/analyze|analyze-link|build` nhận `voiceless`.
  - **Viết lời thoại** (`narration._SYSTEM`) dùng `VOICE_RULES`; "✨ Viết lại chuẩn" / "Tạo lại theo yêu cầu" (`prompt_synth._KEEP_LOOK` trong `_REFINE_SUFFIX` /
    `_REVISE_SUFFIX`) giữ kiểu quay điện thoại, không kéo về studio; Bước 2 "Viết lại chuẩn" chuyển động không ép camera "static" nữa.
  - **Người mẫu**: `constants/character.ts` mỗi phong cách có thêm `male` (tóc ngắn, cạo râu / râu lún phún, áo thun — không trang điểm / khuyên tai),
    `buildCharacterPrompt` dùng nó khi giới tính nam; chân dung tham chiếu đổi "Studio portrait headshot" → "Natural daylight head-and-shoulders portrait photo"
    (cả `assistant.model_prompt`).
  - **"🔇 Không lời"**: hộp Clip mới có ô **"Lời thoại: 🎙 Có lồng tiếng / 🔇 Không lời"** (`voiceChoice`, ở mục 3 của mẫu, link sản phẩm, video mẫu; đổi từ Không lời
    sang Có lồng tiếng sau khi đã phân tích link / video thì phân tích lại vì kế hoạch không có lời). `POST /api/boards/from-template {voiceless}` → tailor không lời +
    `templates.voiceless_spec` (lời rỗng, ghi chú `NOTE_VOICELESS`, cả khi tailor lỗi / không có sản phẩm) + **`quicktool.voiceless: true`**. Ghép: lời rỗng →
    worker không lồng tiếng, không phụ đề, giữ nguyên tiếng của từng clip (đường ghép có sẵn). Store `isVoiceless()` / `setVoiceless(on)` (bật = xoá lời mọi cảnh;
    tắt mà lời đều trống = AI viết lời), "⚡ Tạo video tự động" bỏ bước viết lời khi không lời. Bước 2: thanh "🔇 Clip không lời" (+ "🎙 Thêm lời thoại") hoặc
    "🔇 Chuyển thành clip không lời", ẩn ô lời thoại; Bước 4 (`JoinOptions voiceless`) và Bước 5 ẩn giọng / phụ đề / tiếng gốc, ghi "không lời — giữ tiếng thật"
    (nhạc nền, 60 fps, chữ trên video vẫn có). Trợ lý AI: `create_clip {voiceless}` ("không lời", "chỉ quay mặc thử", "kiểu ASMR").
  - Test `test_clip_style.py` (8: mẫu không còn chữ studio / có `Audio:` / có câu giữ sản phẩm / không "slow"; giới tính; voiceless_spec; tailor biết người + nơi;
    tailor không lời không giữ lời; route tạo clip không lời; kế hoạch link không lời; trợ lý). Sửa test cũ theo nội dung mẫu mới (`test_script_tailor`,
    `test_templates`, `test_reference_video`, `test_assistant`).
- **Tên riêng khi lồng tiếng** (7/11, `services/dub_names.py`): (1) **Whisper nghe đúng tên**: `asr_hint(title)` (tiêu đề tải về + hashtag, bỏ #/@/link, ≤ 160
  ký tự) → `dub_runner transcribe <wav> <out> auto - <hint>` → faster-whisper **`hotwords`** (đặt vào MỌI cửa sổ 30 s; `initial_prompt` chỉ tới cửa sổ đầu khi
  `condition_on_previous_text=False`); chỉ khi job có `url`. (2) **AI rà tên riêng ngay sau Google** (`dub.needs_name_check`: lời tiếng Việt do google / microsoft dịch;
  AI dịch thì bỏ qua) → `dub._check_names` → `dub_names.check(src, lines, title, language)`: Gemini `gemini-3.5-flash` qua pool key miễn phí (không tốn lượt Claude),
  200 câu một lượt, 3 lượt cùng lúc, JSON `{fixes: [{line, text}], names: [{write, say}]}`; câu sửa chỉ nhận khi giữ gần hết chữ cũ (`is_name_fix`: thay ≤ 3 từ hoặc
  ≤ 1/3 câu); lỗi / chưa có key → giữ bản Google, ghi `job.names_note`. Luật dạng tên: hành tinh / thiên thể quen dùng tên Việt (Sao Thủy… Trái Đất, Mặt Trời, Dải Ngân Hà),
  tên nước ngoài khác giữ chữ Latin như báo Việt viết (Einstein, Titan, đám mây Oort, giới hạn Roche), người / nơi Trung Quốc theo dạng quen (Hán-Việt). (3) **Giọng đọc
  theo bảng tên**: `Job.names` `[{write, say}]` (job.json, snapshot, `public()`, `normalize_names` bỏ gạch nối) → `dub.speech(job, text)` thay `write` bằng `say` (cả từ,
  dài trước) trước khi đưa TTS — phụ đề vẫn ghi `write`; giọng Gemini đọc nguyên văn (tự đọc tên nước ngoài được); `voice_key` tính theo chữ được đọc → đổi bảng tên là
  đọc lại giọng (TTS cache theo chữ). Routes: `POST /api/dub/jobs/{id}/names {lines?}` → `{fixes: {"i": text}, names}` (không lưu; nút "việc đang chạy" có "AI đang rà
  tên riêng"), `RenderBody.names`. Editor: tab "📜 Các câu" có khung **"🔤 Tên riêng"** (`dub/editor/NamesPanel.tsx`: phụ đề ghi → đọc là, sửa / 🗑 / ＋ Thêm tên, dòng
  `names_note`, nút **"✨ AI rà tên riêng"** = `checkDubNames` → sửa câu + thêm tên, một bước hoàn tác); `EditDoc.names`, thay đổi = "tên riêng" (xuất lại đọc giọng).
  `api/dub.ts`: `DubName`, `normNames`, `checkDubNames`, `DubJob.names|names_note`, `DubRender.names`. Thử thật read-only trên job 46bfc7232d1b (813 câu): 43 s, sửa 28 câu
  (Anyinstein → Einstein, Losey → Roche, Billing Star → Proxima Centauri, Ultra Cloud → đám mây Oort, Neptune → Sao Hải Vương, Du hành 1 → Voyager 1, 插绒 → Charon),
  11 tên có cách đọc (Einstein → Anh xtanh, Roche → Rốt sơ, Oort → Ót). Còn sót vài chữ ("Taitan", "Olet Yunwai", "Sora"). Test `test_dub_names.py` (8).
- **App desktop (Tauri 2 + agent đóng gói PyInstaller, 7/11)** — người dùng chọn build trên GitHub Actions, bản đầu cho chính họ + vài người tin cậy (chưa làm Phase C):
  - **Agent chế độ app**: `config.HOME` (= `FLOWBOARD_HOME`, app truyền thư mục dữ liệu — xem `dflow_home` ở vỏ Tauri), `config.APP_MODE` (`FLOWBOARD_APP=1`), `config.ENV_FILE`
    (= `HOME/.env`, không có HOME thì `.env` ở gốc repo như cũ), `STORAGE_DIR` mặc định `HOME/storage`. Entry `agent/packaging/dflow_agent.py`: log ra `HOME/logs/agent.log`
    (xoay vòng 5 MB), vá `subprocess.Popen` thêm `CREATE_NO_WINDOW` (ffmpeg / yt-dlp / claude không nháy cửa sổ đen), tự thoát khi tiến trình cha
    (`FLOWBOARD_PARENT_PID` = DFlow.exe) mất — để bộ cài cập nhật không bị khoá file, `uvicorn.run(app, 127.0.0.1, FLOWBOARD_HTTP_PORT|8434)`. Spec
    `agent/packaging/dflow-agent.spec` (onedir `agent/dflow-agent.exe` + `_internal`, console build vì app chạy nó với CREATE_NO_WINDOW; data: `templates/`, `assets/`,
    `prompt_seeds.json`, **`dub_runner.py` + `video_clean_runner.py` dạng file thật** — pyvideotrans chạy chúng theo đường dẫn; collect_all psycopg / psycopg_binary /
    edge_tts / certifi; ~250 MB, build 2 phút trên máy nhà; bản phát hành thay mã `flowboard` bằng bản dịch Nuitka — mục "Chữ ký số quyền dùng").
  - **Agent tự phục vụ giao diện**: `flowboard/web_ui.py` `mount(app)` (gọi CUỐI `main.py`) — `FLOWBOARD_WEB_DIR` = bản `vite build`; GET không route nào nhận → file
    trong đó hoặc `index.html` (F5 ở `/clips/12/export` vẫn đúng), `/api/*` và `/media/*` không bao giờ rơi vào; `assets/` cache immutable, index no-cache; chặn đọc file
    ngoài thư mục. Chạy từ repo cũng dùng được (`FLOWBOARD_WEB_DIR=frontend/dist`).
  - **Cài đặt → 🖥 Máy này** (`components/settings/MachineSection.tsx`, `routes/app.py`, `services/app_env.py`): gói Flow Pro / Ultra (**có hiệu lực ngay** —
    `app_env.apply_tier` gán `flow_sdk.DEFAULT_PAYGATE_TIER` + `config` + env; trước đây chỉ đọc lúc khởi động), dòng dữ liệu cloud (dán cả `FLOWBOARD_CENTRAL_DB_URL=…`
    cũng được; chỉ trả `host`, không bao giờ trả mật khẩu), thư mục dữ liệu (`FLOWBOARD_STORAGE`, thử ghi trước khi lưu), đường dẫn VieDub (`FLOWBOARD_ERASE_ROOT|PYTHON`,
    có hiệu lực ngay), thư mục extension + hướng dẫn Load unpacked, mở thư mục dữ liệu / log / `.env` (Windows: `os.startfile`, notepad), **↻ Khởi động lại** khi có khoá
    cần restart (`restart_pending` = giá trị file khác lúc agent khởi động). Routes `GET /api/app/status`, `PUT /api/app/settings`, `POST /api/app/open {what}`,
    `POST /api/app/restart {force}` (chỉ `APP_MODE`; có việc đang chạy → 409 trừ khi force; thoát mã **75** sau 0,6 s, app khởi động lại agent). `app_env.write_values`
    giữ dòng viết tay, ghi UTF-8 không BOM qua file tạm. Dùng được cả khi chạy bằng start.ps1 (ghi `.env` gốc repo; restart thì chạy lại start.ps1).
    Cài đặt cũng có tab **🤖 AI viết** (AiProvidersSection).
  - **Vỏ Tauri** `desktop/` (`src-tauri/src/main.rs`, `tauri.conf.json` identifier `vn.dflow.desktop`, NSIS currentUser, `embedBootstrapper` WebView2, resources
    `resources/` → `$RESOURCE` gồm `agent/`, `web/`, `ffmpeg/`, `extension/` do CI gom; icon sinh từ `frontend/public/dflow-logo.png` bằng `npx tauri icon`, đã commit):
    khởi động `resources/agent/dflow-agent.exe` (env `FLOWBOARD_APP/HOME/WEB_DIR/EXTENSION_DIR/PARENT_PID`, PATH thêm `resources/ffmpeg` đầu tiên, CREATE_NO_WINDOW) —
    bỏ qua nếu cổng 8434 đã có agent trả lời (dev đang chạy); theo dõi: thoát mã 75 → chạy lại, crash → chạy lại tối đa 3 lần liền; thoát app → `taskkill /T /F` cả cây.
    Cửa sổ mở trang chờ `desktop/ui/index.html` (fetch no-cors `/api/health` mỗi 0,7 s → `location.replace("http://127.0.0.1:8434/")`, 120 s không lên thì chỉ chỗ log).
    Link mở cửa sổ mới (`on_new_window`): trang của app → điều hướng ngay cửa sổ chính, còn lại → trình duyệt mặc định (`explorer <url>`). Đóng cửa sổ = ẩn xuống khay
    (lịch đăng / tự động đăng vẫn chạy); khay: Mở DFlow / Mở thư mục dữ liệu / Thoát DFlow; `tauri-plugin-single-instance` (mở lần 2 = hiện cửa sổ cũ). Dữ liệu app ở
    **`X:\DFlowData` trên ổ cố định đầu tiên khác C còn ≥ 5 GB trống** (người dùng: "né ổ C ra"; `roomy_data_drive` gọi thẳng `GetDriveTypeW` /
    `GetDiskFreeSpaceExW`), không có thì `%LOCALAPPDATA%\DFlowData`; chọn một lần rồi nhớ ở `%APPDATA%\vn.dflow.desktop\home.txt` (thư mục đã nhớ không ghi được
    nữa → chọn lại). Không phải thư mục cài, gỡ / cập nhật không đụng. Hồ sơ WebView2 (cookie đăng nhập, cache) cũng ở `<home>\webview` (`data_directory`);
    trang chờ nhận đường dẫn log thật qua `initialization_script` (`window.__DFLOW_LOG__`). Thư mục cài (~300 MB) mặc định `%LOCALAPPDATA%\DFlow`, đổi ở trang
    Choose Install Location của bộ cài (Tauri NSIS không có tuỳ chọn thư mục cài mặc định).
  - **Tự cập nhật (7/11, từ 0.1.2)**: `tauri-plugin-updater` + lệnh riêng `dflow_check_update` / `dflow_install_update` (`main.rs`; tải trước, rồi
    `stop_agent`, rồi `install` — NSIS chế độ passive, Windows tự đóng app, bộ cài mở lại; cài lỗi → `app.restart()`). Giao diện (trang web ở
    `http://127.0.0.1:8434`) gọi được nhờ `capabilities/ui.json` (`remote.urls` 127.0.0.1:8434 **+ quyền `allow-dflow-check-update`,
    `allow-dflow-install-update`** do `build.rs` sinh từ `AppManifest::commands` — thiếu là "not allowed by ACL", xem Bẫy) qua `window.__TAURI_INTERNALS__.invoke` —
    `frontend/src/lib/desktopApp.ts` (`inDesktopApp`, `checkAppUpdate`, `installAppUpdate`), `components/AppUpdate.tsx` (`AppUpdateBanner` ở `App.tsx`: kiểm
    sau 20 s rồi mỗi 6 giờ, "Để sau" giấu đúng bản đó; `AppVersionSection` ở 🖥 Máy này; có việc đang chạy thì hỏi trước). Nguồn bản mới: repo **công khai**
    `hoangduytn1703/dflow-releases` (chỉ chứa bản cài; người dùng chọn 7/11) — `latest.json` ở `releases/latest/download/latest.json`, khoá công khai trong
    `tauri.conf.json > plugins.updater.pubkey`, bản build có `createUpdaterArtifacts` (ra thêm `.exe.sig`). **Phát hành**: **một số phiên bản chung** (8/11, trước đó giao diện 1.4.0 còn app 0.1.x — gộp thành 1.5.0): tăng `version` ở
    `frontend/package.json` (+ 2 dòng gốc của `package-lock.json`; `desktop/package.json` + lock cũng đổi cho đồng bộ), `agent/pyproject.toml`, `agent/flowboard/__init__.py` (`__version__`, từ 8/11 khuya), `tauri.conf.json`, `Cargo.toml` (workflow bước "Version check" từ chối tag
    lệch trước khi build), commit, `git tag vX.Y.Z && git push origin vX.Y.Z` → workflow build, kiểm tag = version, viết `latest.json`, `gh release create` trên
    dflow-releases (`GH_TOKEN = secrets.RELEASES_TOKEN`). Secrets repo code: `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`, `RELEASES_TOKEN`
    (người dùng đã đặt 7/11 bằng script — lệnh ghi secret của Claude bị chặn quyền; `RELEASES_TOKEN` = token `gh` của người dùng, có quyền mọi repo — muốn gọn
    thì thay bằng fine-grained token chỉ cho dflow-releases). Đẩy tag thì đừng `git push --tags`: repo còn tag cũ v1.x trên máy (không có trên origin). **Khoá ký chỉ có ở máy nhà**: `%USERPROFILE%\.flowboard\dflow-updater.key` + `.password`
    (ngoài git) — mất khoá thì mọi app đã cài không nhận bản cập nhật nữa (phải cài tay bản có khoá mới). `api/github.ts` cũng trỏ sang dflow-releases (hết 404).
  - **Bản app chưa có**: Remotion (cần Node + `frontend/node_modules` → `dub_remotion` tự báo không dùng được, chọn kiểu ffmpeg), ký số (Windows hiện màn
    "Windows protected your PC" → More info → Run anyway), Chrome Web Store cho extension. Lồng tiếng / CapCut / Claude CLI / yt-dlp vẫn dùng đồ cài trên máy như bản repo.
  - Test `test_app_mode.py` (5: `.env` giữ dòng tay + BOM, settings áp gói ngay + cờ restart + không lộ mật khẩu, restart chỉ ở app + 409 khi bận, phục vụ UI + SPA + không
    đọc ngoài thư mục, status chỉ thư mục extension). Thử thật bản PyInstaller trên cổng phụ 8534 / 8455 với HOME tạm: giao diện, F5 trang con, 8 mẫu clip, 43 prompt mẫu,
    đổi gói Pro có hiệu lực ngay, dán dòng cloud → cờ restart.
- **✂️ Cắt video — menu riêng, không lồng tiếng** (8/11 khuya, người dùng: "dù chỉ cần cắt và edit thì vẫn phải qua lồng tiếng là không cần thiết… 1 menu riêng,
  bỏ link vào, có prompt cắt hoặc AI tự prompt, bấm là ra nhiều video nhỏ, edit từng video hoặc nhiều video; muốn lồng tiếng thì lấy từ Clip của tôi"):
  - **`services/video_cut.py`** + **`routes/cut.py`** (`/api/cut/*`): một link / file = một **session** (`Session`, lưu `<media>/cut/<id>/session.json` trên máy
    này; nhiều link dán cùng lúc chung `run_id`). Luồng `_run` (một session nghe một lúc, `_pump`): `_prepare` = tải (`video_fetch.fetch_video`, ≤ 60 phút,
    Asset) → probe → **Whisper một lần** (`dub._runner transcribe`, gợi ý tên bằng tiêu đề như lồng tiếng; máy không có pyvideotrans thì bỏ qua, `heard` false) →
    `suggest`: `how` = **ai** (AI tự chọn đoạn đáng thành video ngắn, bỏ chào hỏi / quảng cáo / lan man) | **prompt** (yêu cầu của người bán thắng mọi luật) |
    **even** (chia đều, cắt ở chỗ ngừng); AI = `run_llm("auto_prompt")` với `_SYSTEM` + `ai_prompt` (dòng có số + giờ, độ dài min–max, tối đa N video) → JSON
    `{parts: [{from, to, title}], note}` → `dub_split.parts_from_ai` (dùng lại, qua `_as_job`); trả lời không phải JSON thì hỏi lại 1 lần (thấy thật 1 lần từ Claude
    CLI), vẫn hỏng / không có lời / không có Whisper → chia đều + `note` → (`review` thì dừng ở `status: review`) → `_cut_all`: ffmpeg cắt chính xác
    (`dub_split._cut`, dấu `flowboard-cut:<session>`) → mỗi phần `_part_job`: một **`dub.Job` kind "cut"** (mode "sub", **`sub_lang: "none"`** = không in phụ
    đề, giữ tiếng gốc; `cut = {session_id, run_id, index, total, start, end, source_url, source_title}`, `batch_id = run_id`, câu = lời Whisper trong đoạn dời về 0
    `part_lines`, `media_id` = file cắt nên "đã xuất" ngay) + clip (`dub._save_board` → board **`template_id: "cut_part"`**, `quicktool.cut`). Cắt lại (`cut()`, tab
    "✂️ Sửa chỗ cắt" / review) dùng lại job + clip cùng số thứ tự, giữ kiểu đã chỉnh (layout, kiểu, nhấn chữ — chỗ nhấn bỏ), phụ đề đã dịch thì dịch lại câu mới.
    `again` (↻ Làm lại, không nghe lại nếu đã nghe), `stop`, `delete` (chỉ session + thư mục; clip / dự án phần giữ), `part_jobs(run|session)` theo thứ tự cắt,
    `clip_media(board_ids)` (video cuối của clip — trang Lồng tiếng). Routes: `GET /status`, `POST/GET /sessions`, `GET /sessions/{id}`, `POST …/suggest|cut|stop|again`,
    `POST /sessions/delete`, `GET /parts?run=|session=`, `POST /clips`.
  - **`dub.py` cho phần cắt**: `Job.kind`, `Job.cut` (public, job.json, snapshot, `_job_from_dict`, `restore_from_board` nhận cả phần không có câu);
    `SUB_LANGS["none"]` ("không có phụ đề": `_render` không tạo cue nào, câu vẫn giữ; `subtitle_lines("none")` trả nguyên câu); `_run_job` / `_pump` / `render_job`
    cho phần cắt xuất cả khi không có câu; `_save_board` kind cut → template `cut_part`, tên clip theo tên phần. `GET /api/dub/jobs` (danh sách lồng tiếng) **bỏ** job
    kind cut; Edit auto CapCut cũng không liệt kê chúng ở tab lồng tiếng (vẫn có ở tab clip). Nút "việc đang chạy": `running._cut_items` (session, `/tools/cut?session=`)
    + phần đang xuất (`kind: "cut"`, `/tools/cut?job=&run=`), outcome `cut:<id>`; `op_tracker` "AI đang chọn đoạn cắt".
  - **Prompt cắt đã lưu + tiêu đề từng đoạn + tiêu đề chung (10/11, tham khảo `D:\codes\cutYoutube`)**: ô "Yêu cầu cắt" = `quicktool/cut/PromptBox.tsx` — ô chọn **prompt đã lưu** (theo tài khoản: AppSetting `cut_prompts` = `[{id, name, text}]`, ≤ `MAX_SAVED_PROMPTS` 30; `GET/PUT /api/cut/prompts` gửi cả danh sách; tài khoản chưa lưu gì thì có sẵn một prompt `video_cut.DEFAULT_PROMPT` "Hook TikTok · 70–150 giây · tiêu đề từng đoạn", xoá được), textarea cao kéo được, 💾 Lưu thay đổi / ＋ Lưu thành prompt mới / ✎ đổi tên / 🗑, ô **"Tiêu đề bằng tiếng"** (`title_lang`: "" = theo prompt, hoặc `TITLE_LANGS` Việt / Tây Ban Nha / Anh…; thắng mọi chỉ dẫn ngôn ngữ trong prompt; chế độ "AI tự chọn" cũng có ô này). Prompt giờ dài tới `PROMPT_MAX` 4000 ký tự và **giữ xuống dòng** (`clean_prompt`; trước 600 ký tự, gộp một dòng). `_SYSTEM`: luật tiêu đề trong prompt (ngôn ngữ, số từ, hook, không tên riêng) áp cho `title` từng đoạn; prompt xin một tiêu đề cho cả video ("Name") → khoá `name` của JSON; bố cục đầu ra prompt tự tả (`start_1 | end_1 | title_bottom_1`) bị bỏ qua — luôn trả JSON; độ dài / số đoạn ghi trong prompt thắng ô chọn độ dài. `Session.name`, `Session.title_lang` (session.json, `public()`), `suggest()` trả thêm `name`. Giao diện: dòng "🏷 Tiêu đề video: …" trên thẻ video + 📋 Copy và "📋 Copy cả tiêu đề các đoạn" (`api/cut.pipeText` = một dòng `Name: … | start_1: mm:ss | end_1 | title_bottom_1 | …` như tool cutYoutube); khung "✨ Gợi ý lại" dùng cùng PromptBox (compact). Chip gợi ý nhanh **ẩn** bằng `SHOW_PROMPT_IDEAS = false` (`CutPage.tsx`). Prompt + ngôn ngữ chọn lần cuối nhớ trong localStorage `flowboard.cut.form`. Test `test_video_cut.py` (+2). Chưa làm: in tiêu đề lên hình (title_top / title_bottom như tool kia), trợ lý AI chưa nhận `title_lang`.
  - **Gói**: tính năng mới **`cut`** ("✂️ Cắt video"; icon Edit auto CapCut đổi sang 🎞) — `plans.FEATURES` + web `src/lib/catalog.ts` / `FeatureIcon.tsx`. Luật:
    `/api/cut/*` → cut; `/api/cut/clips` → cut hoặc dub; route của trình chỉnh sửa `/api/dub/jobs/<id>[/render|subtitles|highlights/pick|names|stop|nosub|voice|bgm|filmstrip.jpg|wave.png]`
    và `/api/dub/(mascot|background|decor)` → dub hoặc cut; OCR `/api/clean/*/detect` → clean / dub / cut. **Bảng gói đã ký chưa có `cut`** → chỉ quản trị thấy menu tới khi
    quản trị tick "Cắt video" cho từng gói ở 📦 Gói & tính năng (máy có khoá ký) rồi Lưu.
  - Frontend: **`quicktool/pages/CutPage.tsx`** (+ `cut.css`, tiền tố `ct-`; route `/tools/cut`, menu Công cụ "✂️ Cắt video", `FeatureGate` "cut"): trái = ô link (mỗi link một
    ô, dán nhiều link tự tách, ≤ 10) + "📁 Chọn file video…" (`uploadDubVideo` = `/api/reference-video/upload`), "Cắt thế nào" (3 thẻ AI tự chọn / Theo yêu cầu + 5 gợi ý /
    Chia đều; cảnh báo khi máy không có Whisper), độ dài (`LENGTHS` 15–30 s … 3–10 phút), số video tối đa, "xem lại trước khi cắt", kênh (form nhớ localStorage
    `flowboard.cut.form`); phải = danh sách session (`SessionCard`: tiến độ / lỗi / ↻ / Dừng / 🗑, ghi chú AI, `RowsEditor` = video gốc + ✨ Gợi ý lại + bảng tên / từ / đến
    (`TimeBox` export từ `CutPane`) / ▶ xem đoạn / 🗑 / ＋ Thêm đoạn / ✂️ Cắt N đoạn; lưới `PartCard` có ảnh (poster), ✓ đã chỉnh, ✏️ Chỉnh, ⬇, 🎙, Clip →; chọn nhiều →
    "✏️ Chỉnh N video" / "🎙 Lồng tiếng N" (≤ 5) / "⬇ Tải N (.zip)"). Trình chỉnh sửa = **`DubEditor`** nhúng trong trang (`?job=&run=[&parts=]`, select "Video n/N",
    "⇪ Áp cho cả loạt" = `applyToOthers`: layout / kiểu / nhấn chữ **+ ngôn ngữ phụ đề** (`BatchLook.lang`; mỗi phần lấy câu của chính nó qua `/subtitles`). `DubEditor`
    với `job.kind === "cut"`: không có ô "Kiểu làm" / tab ✂️ Cắt (`Inspector cutPart`), tab 💬 Phụ đề có ô **Phụ đề: Không có / Đúng lời trong video / ngôn ngữ khác**
    ở đầu, `EditorStage noSubs` khi tắt. Bước 5 của clip `cut_part`: thẻ "Video n/N cắt từ video dài" + ✏️ Mở trình chỉnh sửa + 🎙 Lồng tiếng (`StepExport cutPart`,
    `QuicktoolApp cutPartOf`). **Trang Lồng tiếng** có "🎬 Chọn từ Clip của tôi" (`dub/ClipPickDialog.tsx`: clip có video, lọc "Chỉ video đã cắt", ≤ 5) và nhận
    `?clips=<board ids>` — mỗi clip thành một job lồng tiếng với `source_media_id` = video cuối của clip (tên = tên clip). Trợ lý AI: kỹ năng **`cut_video`** {urls, prompt?,
    how?, min_s?, max_s?, max_parts?, channel_id?} (từ "cắt" vào bộ lọc chủ đề).
  - Test `test_video_cut.py` (9: tuỳ chọn, chia đều ở chỗ ngừng + số video, AI theo yêu cầu + note + tối đa, không lời / không Whisper / AI lỗi → chia đều, câu trong đoạn
    dời về 0, cắt thật bằng ffmpeg → job + clip đúng → sửa phần 1 (1:1 nền lưới, không phụ đề) → cắt lại giữ job / clip / kiểu, routes, luật gói, trợ lý). Thử thật trên
    agent phụ (cổng 8534, dữ liệu tạm, không Neon): video Enceladus 3:35 tiếng Trung → Whisper ~80 s → cắt 5 video ~16 s (lần đó AI trả không phải JSON → chia đều; gọi lại
    AI 10,8 s ra 3 đoạn đúng chủ đề kèm tiêu đề); phần 1 dịch phụ đề Google 2,4 s + xuất 9:16 nền lưới 6,9 s; Playwright: trang, form, sửa chỗ cắt, chọn nhiều, trình
    chỉnh sửa (tắt / bật phụ đề), "Chọn từ Clip của tôi", Bước 5, 760 px không tràn, không lỗi console.
- **🎙 Gói lồng tiếng — cài một chạm trên máy không có VieDub** (9/11, người dùng: bạn họ cài 1.8.0, máy có card NVIDIA mà trang Lồng tiếng báo "Không thấy
  Python của pyvideotrans"; "t tưởng file exe khi install xong là chỉ có xài thôi"): bộ cài 191 MB không chứa Whisper / spleeter / VieNeu — trước đây chỉ máy nhà
  chạy được nhờ mượn `.venv` của VieDub. **`services/dub_addon.py`**: thư mục `addon_dir()` = `(config.HOME or config.ROOT)/addons/dub` (app: `<DFlowData>\addons\dub`;
  không dùng `STORAGE_DIR` vì nó đổi theo tài khoản; `FLOWBOARD_DUB_ADDON_DIR` để đổi — `conftest.py` trỏ vào thư mục tạm). Cài (`install()` → luồng `_worker` →
  `_install(gpu)`): kiểm ổ trống (`NEED_FREE_MB` 9 GB có card / 5 GB không) → **uv** (`UV_VERSION` 0.13.2: wheel từ PyPI JSON, lấy `uv.exe` trong `*.data/scripts/`) →
  `uv venv --python 3.11` (python-build-standalone vào `addons/dub/python`, `UV_PYTHON_PREFERENCE=only-managed`, cache `addons/dub/uv-cache`) → có card NVIDIA
  (`nvidia_gpu()` = `nvidia-smi --query-gpu=name,driver_version,memory.total`; driver < 528 → `old_driver`) thì tự tải 2 wheel `GPU_WHEELS` nvidia-cudnn-cu12
  9.10.2.21 + nvidia-cublas-cu12 12.8.4.1 (có thanh tiến độ theo byte) → `uv pip install` các wheel đó + `PACKAGES` (faster-whisper 1.2.1, ctranslate2 4.8.0,
  sherpa-onnx 1.13.0, vieneu 3.8.3, rapidocr-onnxruntime 1.4.4, zhconv 1.4.3, soundfile, numpy — đúng bản VieDub máy nhà) → Whisper large-v3-turbo 5 file từ
  HuggingFace (`hf-mirror.com` dự phòng) vào `models/<WHISPER_DIR>` → spleeter 2 file (HF mortimerme/repocollect, modelscope dự phòng) → **tải sẵn giọng VieNeu**
  (`_warm_vieneu`: chạy runner `vieneu` một câu với `HF_HOME=addons/dub/hf`; lỗi thì không chặn, ghi `note`) → **`dub_runner check`** (nạp Whisper như job + nghe 2 s
  tiếng ồn; card lỗi thì thử CPU, ghi `cuda_error`) → ghi **`addon.json`** sau cùng (`ready()` = có addon.json + python + model.bin) → xoá `downloads/` + cache uv.
  `download()` tải tiếp từ `.part` (Range), thử 4 lần mỗi nguồn rồi sang nguồn kế, "Huỷ" (`cancel()` → `_stop` + kill tiến trình) dừng giữa chừng; bấm Cài lại là
  tải tiếp. Tiến độ: `_state` trong RAM (`phase`, `done_mb`/`total_mb` theo `SIZE_MB`, bước uv / VieNeu đo bằng cỡ thư mục lớn dần `_watch_dir`). **Nơi dùng**:
  `runtime()` → `(root, python, env)`: VieDub (biến `FLOWBOARD_ERASE_*` hoặc `D:\codes\pyvideotrans`) thắng, không thì add-on (env thêm `HF_HOME`), không thì None;
  `dub.status()` (`runtime` viedub|addon|none, khi none có `addon` = `dub_addon.status()` + câu `NO_RUNTIME` cho khách), `dub._runner`, `tts.vieneu_available`,
  `video_clean.detect_bands` (máy không VieDub mà có add-on → `dub_runner detect`: RapidOCR trên 24–48 khung, `sub_like` + `bands_from_lines` gom dải chữ lặp lại;
  không có gì → `UnavailableError` → 503; route xoá chữ / OCR so kiểu lỗi thay vì so câu "Không thấy Python"). Xoá chữ AI (LaMa, torch) vẫn chỉ có với VieDub.
  **`dub_runner`**: không có torch thì `_nvidia_dlls()` (add_dll_directory + PATH + nạp sẵn `cublas64_12` / `cublasLt64_12` / `cudnn64_9` từ `site-packages/nvidia/*/bin`)
  rồi `ctranslate2.get_cuda_device_count()`; `_load_whisper(cpu=)` trả `(model, device)`; card lỗi giữa lúc nghe (`_gpu_failed`) → nghe lại bằng CPU; mode mới `check`,
  `detect`. Routes `GET /api/dub/addon`, `POST /api/dub/addon/install|cancel|remove` (luật gói `None` — việc của máy), nút "việc đang chạy" `running._addon_items`
  (`dubaddon:install`, outcome). Frontend: `api/dub.ts` (`DubAddon`, `DubGpu`, `getDubAddon`, `installDubAddon`, `cancelDubAddon`, `removeDubAddon`, `DubStatus.addon|runtime`),
  **`quicktool/dub/DubAddonCard.tsx`** (+ `.qt-addon*` trong `dub.css`: card / tóm tắt máy / thanh tiến độ + GB + thời gian / Huỷ / lỗi + "Cài lại (tải tiếp)" /
  đã cài + "Gỡ gói"), thay "Chưa dùng được" ở `DubPage` (xong thì tải lại status), mục "🎙 Gói lồng tiếng" ở Cài đặt → 🖥 Máy này (`MachineSection`, mục VieDub
  đổi thành "không bắt buộc — chỉ cho xoá chữ AI"), link "Cài gói lồng tiếng →" ở cảnh báo Whisper của Cắt video + Edit auto CapCut. README Mục 6.2 + trang
  hướng dẫn cài viết lại. **Visual C++ Runtime (10/11)**: `vc_runtime_missing()` (3 DLL `VC_DLLS` trong `%SystemRoot%\System32`) → ngay đầu `_install` gọi `_install_vc_runtime`
  (tải `VC_REDIST_URL` = aka.ms vc_redist.x64.exe, kiểm Authenticode bằng PowerShell `Get-AuthenticodeSignature` = Valid + `O=Microsoft Corporation`, đường dẫn đi qua
  biến môi trường `DFLOW_VC`; chạy `Start-Process -Verb RunAs … /install /quiet /norestart` → một hộp UAC; mã `VC_OK_CODES` 0 / 1638 / 3010 / 1641 là được; bấm No →
  câu tiếng Việt kèm link); sau bước pip `_ensure_libraries_load` = `_probe` (Python của gói nạp ctranslate2 / onnxruntime / sherpa_onnx bằng `PROBE`) — lỗi DLL
  (`dll_problem`: 126 / 127, "could not find module", "dll load failed") thì cài runtime rồi thử lại một lần, vẫn lỗi → `load_failure` (link runtime + nhắc diệt virus
  xoá file); lỗi DLL ở bước check cuối cũng ra câu đó. Thẻ gói cho bấm link trong câu lỗi (`DubAddonCard` `withLinks`). Test `test_dub_addon.py` (15). Thử thật: trên máy nhà (RTX 3060 Laptop, driver 616) bằng agent phụ 8534 giấu VieDub (`FLOWBOARD_ERASE_ROOT` trỏ chỗ không có, gói ở `D:\dflow-addon-test`): bấm nút trên giao diện → cài xong **3 phút 30 giây** (mạng nhanh: cuBLAS + cuDNN 1,3 GB ~50 s, Whisper 1,6 GB ~45 s, VieNeu ~45 s), `check` báo Whisper chạy trên card (cuda), gói chiếm 4,8 GB; lồng tiếng thật phần video Enceladus 46 s tiếng Trung giọng VieNeu Hải Đăng + giữ nhạc nền: 20 câu, Google dịch, AI rà tên riêng, xong ~1,5 phút; "Tự tìm chữ gốc" 17 s ra đúng 3 dải (phụ đề 75–81 %, watermark trôi giữa, chữ trên cùng). Playwright: thẻ chưa cài / đang cài / nút việc đang chạy / đã cài ở Cài đặt → 🖥 Máy này, 760 px không tràn, không lỗi console. Cả bộ test 1191 pass / 2 skip.
- **✂️ Cắt video: phân tích trước, chọn đoạn sau (10/11 khuya — thay luồng "chọn cách cắt rồi mới tải")**: form bên trái chỉ còn link / file + mẫu chỉnh sửa + kênh + nút **"🔍 Phân tích N video"** (`startCut({analyze: true})` → `video_cut.start(analyze=True)` → `Session.ask`; `_run` tải + nghe xong thì dừng ở `status: "review"`, `rows: []`, phase "Đã phân tích — chọn các đoạn…"; nhiều video chạy lần lượt, **xong cái nào thẻ cái đó hiện bảng ngay**). Thẻ video (`SessionCard` → `RowsEditor`, dùng cho cả "✂️ Sửa chỗ cắt"): video xem trước + hộp **"✨ Để AI chọn đoạn (không bắt buộc)"** (AI tự chọn / Theo yêu cầu (PromptBox) / Chia đều + độ dài + số đoạn; nút "✨ AI chọn đoạn" = `POST …/suggest` điền bảng; "✨ …cho cả N video đang chờ" gọi suggest cho các video đã phân tích chưa có đoạn — thẻ kia tự nhận hàng mới nếu chưa gõ gì) + bảng **`quicktool/cut/PartsTable.tsx`** + "✂️ Cắt N đoạn" (`cutNow(id, rows, "manual")` khi hàng do người dùng gõ → thẻ ghi "tự cắt"). **Nhập giờ = 2 ô phút : giây** (`cut/MinSec.tsx`: chỉ gõ số; `:` `.` dấu cách ở ô phút nhảy sang ô giây; giây ≥ 60 tự dồn sang phút khi rời ô; `null` = chưa điền, hiện giờ tool tự hiểu màu xám). **Giờ bỏ trống**: Kết thúc trống = tới đầu đoạn sau, đoạn cuối = hết video; Bắt đầu trống = nối tiếp đoạn trước (đoạn 1 = 0) — `checkPlan` / `planParts`. Kiểm lỗi theo **độ dài thật**: bắt đầu / kết thúc sau cuối video, kết thúc ≤ bắt đầu, < 3 s báo ngay khi gõ; "thiếu …" (kể cả tên đoạn — bắt buộc; tiêu đề phụ không bắt buộc) báo sau khi bấm Cắt. Thêm: dải màu các đoạn trên chiều dài video, cột Dài, ⏱ lấy giờ video đang xem, ▶ xem đoạn, dòng tổng "N đoạn hợp lệ · tổng m:ss / video m:ss". Lựa chọn AI lần cuối (cách, độ dài, prompt, ngôn ngữ) nhớ ở localStorage `flowboard.cut.form`. Đường cũ còn nguyên cho trợ lý AI (`start(how=ai|prompt|even|manual + rows)` không `analyze`): `manual_rows` kiểm đoạn nhập trước khi biết độ dài, `_run` rút đoạn quá cuối video. `subtitle` đi theo hàng (`dub_split.normalize_rows`) → `parts[].subtitle`, `job.cut.subtitle`, hiện dưới tên ở thẻ phần; **chưa in lên video**. Đã bỏ `cut/ManualRows.tsx`, `PROMPT_IDEAS`, `TimeBox` ở trang này. Test `test_video_cut.py` (+3).
- **Kiểm tra máy một lần rồi nhớ (10/11, `services/machine.py`)**: card NVIDIA hỏi bằng `nvidia-smi` **một lần**, kết quả lưu `machine.json` cạnh dữ liệu app (`(config.HOME or ROOT)/machine.json`, theo máy; `FLOWBOARD_MACHINE_FILE` để đổi — `conftest.py` trỏ vào thư mục tạm). Lần mở sau chỉ đọc file. Tự kiểm lại khi **"chữ ký" driver đổi** (`signature()` = đường dẫn + cỡ + ngày của `nvidia-smi.exe`, chỉ một `stat`, không chạy tiến trình nào) → lắp card / cập nhật driver sau này tự nhận; hoặc bấm "↻ Kiểm tra lại" (Cài đặt → 🖥 Máy này, `POST /api/app/machine/recheck`). `machine.warm()` chạy ở luồng riêng trong `main.lifespan`. `dub_addon.nvidia_gpu()` giờ gọi `machine.gpu()`. Không có card (`machine.limits()`): **xoá phụ đề bằng AI (LaMa) tắt** (`video_clean.ai_status` → `available: false, no_gpu`, `start_ai_job` cũng từ chối), **AI nghe lời (Whisper) đánh dấu chậm** (`dub.status().gpu / slow_reason`, `cut status.slow_reason` → dòng 🐢 vàng ở trang Lồng tiếng + Cắt video; vẫn chạy bằng CPU). `/api/app/status.machine` = `{gpu, checked_at, limits}`. Test `test_machine.py` (4).
- **AI dự phòng bằng Gemini key (10/11, `services/llm/registry.run_llm`)**: tài khoản mới chưa chọn AI, AI đã chọn không có trên máy (app cài ở máy bạn bè không có Claude CLI), hoặc AI đã chọn báo lỗi (hết lượt) → **tự dùng pool Gemini key của tài khoản** thay vì lỗi; không áp khi nơi gọi chỉ định AI (`use_ai`). Không có key nào → lỗi tiếng Việt `registry.NO_AI` chỉ chỗ thêm key (đuôi tiếng Anh "No AI provider configured for …" giữ cho `chat_agent`). Trước đó người mới gặp "No AI provider configured for auto_prompt" ở mọi tính năng AI. Test `test_llm_registry.py` (+3).
- **Trình chỉnh sửa bố cục kiểu CapCut + tách / gộp / thêm / xoá câu (10/11)**: `DubEditor` 3 cột — **trái = công cụ** (`LEFT_TABS`: 🎞 Khung & nền (FormatBar dọc), 📜 Các câu, 🎨 Trang trí, 🌫 Làm mờ, ✨ Nhấn chữ), **giữa = màn xem** (thanh phát: giờ trái / nút giữa / tiếng phải), **phải = chi tiết** (`RIGHT_TABS`: 💬 Phụ đề, ✂️ Cắt, ⚙ Xuất). `Inspector` có prop `bare` (chỉ nội dung tab, không thanh tab) và được dựng 2 lần (trái + phải) với cùng props; chọn vùng mờ / nhấn / khung / nhân vật mở tab bên trái, chọn câu mở "Phụ đề" bên phải. **Thanh công cụ timeline** (`EditorTimeline` prop `toolbar`): ↶ ↷ · ✂ Tách (Ctrl+B, chia câu ở vạch thời gian, chữ chia theo tỉ lệ thời gian — `cues.splitText`) · ⤝ Gộp với câu sau · ＋ Thêm câu (ở khoảng trống) · 🗑 Xoá (Delete giờ **xoá hẳn** câu, trước là để trống chữ). Số câu đổi → xuất gửi **`cues`** (cả danh sách `{start, end, text, src, look}`) → `dub.apply_cues` thay `job.segments` (cùng luật kẹp của `apply_timings`, gắn lại `line` của chỗ nhấn) — `RenderBody.cues`; lồng tiếng thì đọc lại giọng. Khi vừa tách / gộp mà chưa xuất: đổi ngôn ngữ phụ đề + AI rà tên riêng bị chặn (chúng làm theo số thứ tự câu của bản đã lưu). File nền (ảnh / video của Khung xuất) không có trên máy → hiện màu nền + nhãn "⚠ Không thấy file nền trên máy này" thay vì ảnh vỡ. CSS: khối "CapCut-style layout" cuối `editor.css` (biến `--dx-*`). Test `test_dub_editor.py` (+1).
## Lộ trình (chốt với người dùng 30/10) — làm theo thứ tự A → B, C chạy song song khi cần
Mục tiêu cuối: **bán DFlow** cho người làm affiliate (2 gói **Pro** / **Premium**), dạng **app desktop Tauri 2** — mọi thao tác trong app,
Chrome chỉ để cài extension và mở tab Flow đúng project. Người dùng nói rõ: không cần bàn chuyện đúng sai pháp lý, họ tự chịu trách nhiệm.

### Phase A — 🤖 Trợ lý AI "làm hết từ một câu" (tính năng Premium, làm TRƯỚC app)
- **Ý tưởng**: một khung chat (trang riêng `/assistant` + nút nổi mở được ở mọi trang). Người dùng gõ kiểu *"làm cho tao 1 clip quảng cáo sản phẩm này"*
  kèm link Shopee / TikTok và / hoặc ảnh, có thể thêm *"đăng lên page X tối nay"* → AI hỏi lại **chỉ khi thật cần** (ví dụ ngành / giới tính người
  mẫu không đoán được), báo **ước tính credit + thời gian, chờ một câu "ok"**, rồi **chạy ngầm làm hết**: đọc link → lưu sản phẩm (+ ảnh) → chọn kiểu
  clip hợp ngành → kịch bản viết theo sản phẩm → người mẫu (+ kiểm tra Flow) → ảnh cảnh → video → ghép + giọng → (tuỳ chọn) bài Facebook + lên lịch.
  Tiến độ hiện trong chat (từng bước, ảnh / video vừa xong) và ở nút "việc đang chạy"; rời trang / tắt máy giữa chừng vẫn chạy tiếp hoặc chạy lại đúng chỗ.
- **Kiến trúc dự kiến**:
  - **Bộ điều phối phía agent** (mới, ví dụ `services/autopilot.py`): chuyển logic `store/quicktool.ts runAuto` (đang chạy trên trình duyệt) về backend
    thành job có trạng thái lưu DB (bảng mới, ví dụ `AutoRun`: board, bước, request ids, lỗi, credit đã dùng), gửi request vào hàng worker có sẵn
    (`gen_image`, `gen_video_omni`, `export_video`), poll kết quả, tự thử lại khi Flow bỏ lượt, tự sống lại sau restart (`after_activate`).
  - **AI gọi công cụ**: LLM (Gemini, có sẵn pool key) đọc chat + ngữ cảnh (sản phẩm, kênh, mẫu clip, credit Flow) → trả JSON gọi công cụ, tái dùng các
    hàm đã có: `product_link.extract_product` / `tab_import`, `products`, `templates_for_category`, `create_board_from_template(tailor=True)`,
    `model_mode`, `bundle.make`, `post_writer.write_post`, `scheduler.create`. Có thể học cách `chat_agent.py` (chat Canvas cũ, ~1.000 dòng, đã có
    tool-calling cho node / ảnh / video / ghép) nhưng chat mới làm ở mức **"việc" (clip, bài, lịch)**, không ở mức node.
  - **Chat lưu DB** (hội thoại + tin nhắn, nhiều cuộc), ảnh người dùng dán / kéo thả vào chat → Asset.
- **A0 — bản demo (xong 30/10)**: khung chat + việc nền đầu tiên `create_model` (tạo người mẫu AI → lưu thư viện). Xem "Chỗ cần biết" → "🤖 Trợ lý AI".
- **A0+ (xong 30/10)**: kế hoạch nhiều bước + 5 kỹ năng (người mẫu, thêm sản phẩm từ link, viết bài / tập tiếp của loạt kèm ảnh, lên lịch, tạo clip có
  kịch bản), hiểu tên gõ sai, chờ "✅ Làm luôn" khi tự đăng công khai. **Còn thiếu cho Phase A**: chạy ngầm ảnh + video của clip (A1, đang phải mở clip bấm
  "⚡ Tạo video tự động"), video 8 s cho bài, sửa bài / lịch có sẵn qua chat, xem số liệu Facebook qua chat.
- **Mốc**: A1 bộ điều phối backend chạy được một clip từ sản phẩm có sẵn (thay `runAuto`) → A2 khung chat + AI hiểu yêu cầu, gọi công cụ, hỏi lại /
  xác nhận credit → A3 từ link / ảnh lạ đến clip ghép xong → A4 thêm bài viết + lịch đăng + nhiều clip một lần ("làm 3 clip cho 3 sản phẩm này") →
  A5 khoá Premium. Mỗi mốc chạy thật một clip qua Flow trước khi sang mốc sau.

### Phase B — App desktop **Tauri 2** (sau A) — **bản đầu đã làm 7/11** (xem "Chỗ cần biết" → "App desktop"; người dùng bảo làm app trước web)
- **Đã chọn Tauri 2** (Electron quá nặng). Vỏ dùng WebView2 có sẵn trên Windows (~5–10 MB, ~100 MB RAM); **agent Python chạy làm sidecar** (đóng gói
  PyInstaller / Nuitka, Tauri tự bật / tắt cùng app); cửa sổ app mở `http://127.0.0.1:8434` do agent phục vụ bản frontend đã build (cookie đăng nhập
  chạy như cũ, khách không cần Node). Bộ cài NSIS / MSI, tự cập nhật có chữ ký (plugin updater), icon khay, chặn mở 2 lần, ký mã Windows (tránh cảnh báo
  SmartScreen). Build bộ cài bằng **GitHub Actions** (máy Windows) — phát hành được từ máy Linux. Ước tính bộ cài ~120–180 MB (phần nặng là Python +
  ffmpeg, không phải vỏ); **gói lồng tiếng** (Whisper + torch CUDA ~2–3 GB) tải riêng khi cần, chỉ Premium.
- **"Mọi thứ trong app"**: Chrome chỉ còn extension + tab `flow.google.com` đúng project — app tự phát hiện extension chưa cài / chưa kết nối / tab sai
  project và mở đúng tab (`open_flow_tab` có sẵn), có màn hình cài đặt lần đầu (ffmpeg, extension, tài khoản Flow, Gemini key) hướng dẫn từng bước.
  Remotion: gói kèm Node hoặc để sau.

### Phase C — Chuẩn bị bán (song song, phần lớn trước khi phát hành B)
- **Xong 8/11 khuya (bản 1.7.0)**: app đăng nhập qua API của dflow.io.vn, mỗi tài khoản một role Postgres chỉ thấy schema của nó, kho file qua link ký sẵn, đăng ký
  trên web (xem "Chỗ cần biết" → "Phase C"). Tài khoản tạo sẵn đã bỏ ở bản cài (8/11 tối). **Còn**: bỏ phụ thuộc Claude CLI (gói Max của người dùng) → khách dùng Gemini
  key của họ; đường dẫn cứng `D:\codes\pyvideotrans` → gói tải thêm.
- **Gói Pro / Premium** (đề xuất 30/10, chưa chốt): Pro = làm tay một shop / một page (wizard clip đầy đủ, giọng Edge, bài viết 1 bài, lịch nhắc, sản phẩm /
  người mẫu / prompt, xoá chữ khoanh vùng; giới hạn 1 kênh, 1 Page, 1 tài khoản Flow, 1 máy). Premium = tự động + số lượng + tăng trưởng + đồ nặng:
  **Trợ lý AI (Phase A)**, tạo video tự động / hàng đợi / N clip, giọng Gemini, viết nhiều bài / loạt / A/B, **tự đăng Page + đồng bộ & số liệu**, định
  hướng kênh / đánh giá page / mẫu hot / gói 1 chạm, **lồng tiếng đầy đủ**, **Edit auto CapCut**, xoá phụ đề AI, nhiều kênh / tài khoản Flow / máy.
  Nên giới hạn số lượng thay vì khoá cứng (ví dụ lồng tiếng thử 3 video / tháng). Cơ chế: trường `plan` + hạn dùng trên tài khoản, kiểm tra ở server, cho
  offline vài ngày, giới hạn số máy.
- Server bản quyền nhỏ (trên Neon có sẵn), domain + trang giới thiệu (Cloudflare Pages / Vercel), thanh toán QR + webhook (SePay / Casso / PayOS), Sentry,
  nhóm hỗ trợ, video hướng dẫn, beta 10–30 khách quen trước.
- Rủi ro đã nói với người dùng: Flow đổi API là tool chết tới khi ra bản sửa (cần tự cập nhật nhanh); app Meta phải qua duyệt thì khách mới tự đăng được;
  Python / JS dễ bị đọc → phần quan trọng phải dựa vào server; giấy phép MIT bản gốc cho bán nhưng cần file `NOTICE` ghi nguồn; extension có thể bị
  Chrome Web Store từ chối → giữ cách cài tay kèm video.

## Việc đang dở / chưa kiểm chứng
- **Trình chỉnh sửa kiểu CapCut — còn lại sau đợt 1 (10/11)**: chưa có âm lượng từng lớp (giọng / nhạc nền / tiếng gốc — `BGM_VOLUME` đang cố định 0,6), tốc độ video, cắt / xoá một đoạn video trên timeline (hiện chỉ cắt thành nhiều clip ở tab ✂️ Cắt), chuyển cảnh, bộ lọc màu, chữ / sticker tự do nhiều lớp, lớp có thời lượng riêng (vùng mờ / nhân vật vẫn cả clip), hút mốc khi kéo khối, chọn nhiều khối, kéo đổi bề rộng 3 cột. Xuất sau khi tách / gộp câu mới có test đơn vị, chưa chạy thật.
- **Gói lồng tiếng (9/11, bản 1.8.1)**: bước tự cài Visual C++ Runtime (10/11) mới thử bằng test giả — chưa chạy UAC thật trên máy thiếu runtime (máy nhà có sẵn; chờ bạn người dùng cài lại ở bản mới). Chưa thử trên máy không có card NVIDIA (CPU) và trên máy bạn người dùng (driver / mạng của họ). Gói không tự cập nhật khi đổi `PACKAGES` / `ADDON_VERSION` (phải Gỡ rồi Cài lại); VieDub có trên máy thì luôn thắng add-on. Xoá chữ AI không có trong gói. Linux: code có nhánh nhưng chưa thử.
- **✂️ Cắt video (8/11 khuya, từ bản 1.8.0)**: bảng gói đã ký chưa bật `cut` cho gói nào (quản trị tick ở 📦 Gói & tính năng). Chưa thử với link thật (mới thử file trên máy), video dài 30–60 phút, máy không có Whisper (bản cài của khách: chỉ chia đều — có thể thêm Gemini xem video để chọn đoạn). Phần đang xuất dùng chung hàng đợi với lồng tiếng (chờ sau một video lồng tiếng dài); từ 1.8.2 phần cắt ra có mẫu / kiểu riêng thì tự xuất ngay sau khi cắt (mỗi phần một lượt ffmpeg). Session chỉ nằm trên máy đã cắt (phần cắt = clip thì có ở mọi máy). Clip `cut_part` vẫn hiện Bước 1–4 vô nghĩa (như `dub_part`).
- **BẢO MẬT — sau Phase C (8/11 khuya, bản 1.7.0)**: bạn bè cài app **không cần và không nhận dòng Neon** nữa — đăng ký / đăng nhập qua dflow.io.vn, app chỉ cầm
  role Postgres của chính tài khoản (đọc / ghi đúng schema của mình) + token API; key B2 nằm trên máy chủ web; key AI / token Page của mỗi người đi qua API (chỉ chủ
  tài khoản đọc được). Quyền dùng vẫn ký số (hướng B). **Còn mở**: (1) máy nào còn dòng Neon (máy nhà) vẫn toàn quyền — đừng đưa dòng đó cho ai; dòng đó từng nằm ở máy
  nào khác thì đổi mật khẩu Neon (Neon Console → Roles → Reset password) rồi cập nhật cả `.env` máy nhà lẫn `DATABASE_URL` trên Vercel; (2) phát lại giấy phép cũ của chính
  mình (chỉ có tác dụng trên máy đó, máy chủ web kiểm khoá / hạn khi đăng nhập và mỗi 10 phút); (3) người có mã nguồn (Cách 2) bỏ được kiểm tra trên máy họ; (4) máy chủ
  dflow-web giữ khoá web + dòng owner — bị chiếm là mất hết (Vercel: bật 2FA tài khoản); (5) **B2 đã đầy 10 GB miễn phí** → đẩy file đang lỗi (xem Bẫy). Chưa có: nút
  nâng `min_app`.
- **App desktop (7/11)**: vỏ Tauri **chưa build được trên máy** (không có Rust) — chỉ CI build; phần Rust chưa chạy thử thật (khay, đóng-ẩn, mở link ra trình duyệt,
  khởi động lại mã 75, tự thoát theo tiến trình cha) tới khi người dùng cài bộ cài. **Tự cập nhật đã chạy thật** (8/11 khuya: 1.6.0 → 1.7.0 bằng nút trong app, người dùng
  xác nhận) — capability + lệnh Rust + cài passive đều đúng. Chưa có: ký số, Remotion, nút "Chọn thư mục" (đang gõ đường dẫn), chuyển dữ liệu cũ khi đổi thư mục, Phase C (bán cho khách).
- **Tên riêng khi lồng tiếng (7/11)**: chưa nghe giọng VieNeu / Edge đọc các cách đọc AI ghi ("Anh xtanh", "Prốc xi ma Xen tau ri") — có thể phải sửa tay ở khung
  "🔤 Tên riêng"; gợi ý `hotwords` cho Whisper chưa chạy thật trên video mới (job cũ đã nhận dạng rồi — dùng nút "✨ AI rà tên riêng" trong trình chỉnh sửa rồi Xuất lại);
  nút "▶ Nghe câu" của trình chỉnh sửa vẫn đọc chữ phụ đề (chưa theo bảng tên); Edit auto CapCut lồng tiếng trước dùng chung luồng dub nên có rà tên, còn phụ đề video
  tải lên (Whisper riêng) thì không.
- **Clip quay như người thật + Không lời (7/11)**: **chưa tạo ảnh / video thật qua Flow** với prompt mới (mới thử AI viết kịch bản bằng chữ cho áo điều hoà #5,
  có lời 23 s / không lời 28 s — ra công trường, chạy xe, bấm nút quạt, tiếng quạt chạy) — cần xem Flow có giữ đúng sản phẩm khi cảnh "đời thường" hơn, prompt dài
  hơn, góc chụp gương che mặt. Chưa thử "Theo link sản phẩm" / "Theo video mẫu" với prompt mới (dùng chung luật). Chưa xem giao diện bằng mắt (tsc sạch, Vite biên
  dịch được; người dùng tự test). Clip đã tạo trước 7/11 vẫn giữ prompt cũ — bấm "✨ Viết lại kịch bản theo sản phẩm" ở Bước 2 để viết lại theo luật mới.
  Tiếng thật của clip không lời phụ thuộc Flow (Omni có tạo âm thanh theo `Audio:`; chưa nghe thử).
- **Tự động đăng theo lịch (7/11)**: chưa để một khung chạy tới giờ và đăng thật lên Page (vòng đăng là `scheduler.tick` có sẵn, đã đăng thật nhiều lần; phần mới mới thử tới bước "chờ tới giờ đăng"). Ảnh Flow trong lần thử lỗi `CAPTCHA_FAILED: grecaptcha not available` ngay sau khi khởi động lại agent — xem tab Flow / reload extension; ảnh lỗi thì bài đăng không ảnh. **Máy phải bật + agent chạy**: agent chạy từ phiên Claude Code chết theo phiên — nên tự khởi động agent khi đăng nhập Windows (chưa làm). Chưa có: video / Reel tự động (clip từ sản phẩm, video lồng tiếng thư viện link), học từ số liệu Facebook (bài nhiều view → kiểu đó), giới hạn số bài / ngày toàn kênh, lịch tự động cho YouTube (người dùng bảo chỉ FB).
- **Rà soát 30/10 — lỗi & cải thiện CHƯA SỬA** (người dùng bảo chỉ log; quét 20 trang bằng Playwright + đo API + cả bộ test; ưu tiên từ trên xuống):
  **Mục 1–4 ĐÃ SỬA 30/10** (xem Nhật ký; 5–15 còn đó). Ảnh hỏng cũ trên máy cty chỉ tự lành khi máy nhà (bản ảnh lành) chạy `repair_images` đẩy lại lên B2.
  1. **Bài bị đăng 2 lần lên Page**: bài #39 "Tập 7 | Hành tinh lăn nghiêng…" — lịch #18 "Đăng ngay từ trang Bài viết" 11:22 30/10 + lịch #17 tự đăng 12:00
     (trợ lý lên lịch) → 2 bài trên Page (`…_122120111967493254`, `…_122120121951493254`). Không có gì chặn: `scheduler.create` / `publish` / `tick` không xem
     bài đã có lịch `posted` / `planned` trên cùng page, "Đăng ngay" không nhắc lịch đang chờ. Hướng: đăng xong thì lịch `planned` khác của cùng bài + cùng page
     → `skipped` (như `fb_sync` làm với bài đăng tay); `tick` bỏ qua bài đã đăng lên page đó; hộp / thanh "Đăng ngay" cảnh báo "bài này đã có lịch hh:mm".
  2. **Hai máy cùng mở agent có thể đăng trùng**: `scheduler.run_loop` chạy ở mọi máy nối Neon, `tick` đọc slot `planned` rồi `publish` mà không giữ chỗ →
     cần "claim" nguyên tử (`UPDATE … SET status='posting' WHERE id=… AND status='planned'`, chỉ máy giành được mới đăng) hoặc chỉ một máy chạy vòng tự đăng.
  3. **5 ảnh trong media bị cụt đuôi** (máy cty, quét 251 ảnh bằng PIL: "image file is truncated", thiếu 4–53 byte cuối): `214da01e…` = ảnh bài #21 "Hệ Mặt
     Trời - Tập 1" (nửa dưới thành mảng màu, thẻ Bài đã lưu + Lịch đăng chỉ thấy một dải), `53e2eb81`, `9c62d344`, `bcd436c1`, `ff895e4b` (ảnh lịch sử). Tải về
     máy này 27/10 09:20 (ảnh làm ở máy nhà 26/10). Chưa rõ gốc — nghi: `media.fetch_and_cache` / `ingest_inline_bytes` ghi thẳng `path.write_bytes` (không qua
     file tạm + `os.replace`), hoặc file bị đẩy lên B2 khi đang ghi (hook xoá logo Gemini ghi lại file sau khi Asset có) rồi máy kia tải bản cụt. Cần so kích thước
     với file máy nhà + bản trên B2 (script ngoài app bị B2 trả 403 — dùng `file_store` khi agent đã đăng nhập). Chưa biết ảnh đã lên Facebook có hỏng không.
     Nên thêm: kiểm ảnh tải về / trước khi đăng (PIL `load()`), hỏng thì tải lại.
  4. **"Mở" ở Bài đã lưu như không làm gì**: bài mở ở khung trên nhưng trang vẫn đứng ở danh sách (trình duyệt giữ chỗ cuộn, `.qt-content` scrollTop
     1032 → 1887) → cuộn lên khung bài khi mở (`PostsPage` `open()`).
  5. **Đồng bộ Facebook ~10 s và làm đứng mọi request ~0,5–0,9 s** lúc bắt đầu và lúc ghi: `fb_sync.sync_channel` là `async` nhưng đọc / ghi Neon đồng bộ
     ngay trong event loop (đo `/api/health` 0,85 s và 0,47 s trong lúc sync, bình thường 1 ms). Trang Bài viết / Lịch đăng gọi sync khi mở (`max_age 600`).
     Hướng: phần DB qua `asyncio.to_thread`; Graph chậm vì field `insights` + `video_reels` (~9 s cho 64 bài). `scheduler.publish` (mỗi phút) cùng kiểu.
  6. **Mở trang gọi API trùng, chậm khi gọi đồng loạt**: Lịch đăng ~18 request một lúc, mỗi cái 1,2–2,4 s (pool DB 5+5, Neon ~44 ms/câu); `/api/running`
     2–3 lần mỗi trang (0,35 s khi gọi riêng — `dub.load_jobs()` đọc lại job.json mỗi lần), `/api/channels` 3 lần ở trang Bài viết (0,56–1,4 s cho 1 kênh — đọc
     token FB ở kho trung tâm), `/api/posts` 0,7–1 s cho 11 bài, `/api/auth/me` 2 lần, `/api/schedule` 2 lần. Hướng: gộp / cache ngắn.
  7. **Clip lồng tiếng / CapCut vẫn hiện Bước 1–4** vô nghĩa: Bước 1 "Mẫu này không có node sản phẩm. Thêm trong Canvas nếu cần" (Canvas đã ẩn khỏi menu), nút
     "⚡ Tạo video tự động" vẫn bật → nên chỉ có Bước 5. Tiêu đề wizard "CÔNG CỤ NHANH · CLIP" (`QuicktoolApp.tsx:608`, tên cũ) → tên clip. `StepSetup.tsx:550`
     "Đổi model ảnh/video trong ⚙ Settings (góc dưới trái)" → giờ là "Cài đặt" ở menu Nâng cao.
  8. **Form Sản phẩm** (`ProductsPanel.tsx:714`): "tối đa 2 ảnh phụ" (Bước 1 nhận 4 ảnh); mẹo "ảnh người cầm sản phẩm… hoặc để cạnh người" ngược với bài học
     Flow bỏ video khi có mặt người mẫu thật → "bàn tay cầm, tránh mặt người".
  9. **Trang Bài viết**: chỉ có 1 kênh vẫn phải chọn tay → tự chọn. Thẻ Bài đã lưu (lưới 4 cột, 1400 px): hàng nút Mở / Copy / 📅 / Xoá chật, chữ rớt dưới icon;
     chip số liệu xuống 2 hàng.
  10. **Lịch đăng**: lịch đã đăng của bài đã xoá chỉ còn "(đã xoá)" (nên lưu tên bài vào `result` lúc đăng); lịch đã đăng vẫn có "Đổi giờ / kênh" (backend từ
      chối đổi giờ); tiêu đề "Chủ nhật 01-11" xuống 2 dòng; khung chi tiết bên phải chiếm ~340 px làm 7 cột hẹp, tên bài cắt còn 2 chữ.
  11. **Hôm nay**: mục "Đã ghép xong, chưa tải về" — nút "Mở" rớt xuống dòng riêng dưới ảnh.
  12. **Sidebar**: credit Flow hiện 2 lần (chip "862 credit" + khối Tài khoản Flow "ULTRA 862"); cửa sổ cao 700 px thì mục "Cài đặt" bị khuất (thanh cuộn ẩn).
  13. **Cài đặt**: Google Flow — chip "Gói Ultra" (theo `.env`) nhưng hàng tài khoản ghi "PRO" (lệch); Tạo ảnh & video — mô tả model "Khuyên dùng: Veo 3.1 Lite
      hiện bị Flow nhận rồi huỷ…" (câu khuyên thành cảnh báo), hiện mã nội bộ "GEM_PIX_2"; tab Thông tin chỉ có số phiên bản.
  14. **Kiểm tra bản mới** (`api/github.ts`) gọi `api.github.com/repos/hoangduytn1703/flowboard/releases/latest` → 404 hai lần mỗi lần mở Hôm nay (repo chưa có
      Release / riêng tư) → im lặng khi 404, hoặc bỏ tới khi có kênh phát hành (Tauri updater).
  15. Mỗi lần mở app ghi lại `ui_prefs` (PUT `/api/account/prefs`) dù không đổi (một setter chạy lúc khởi động, `store/settings.ts persist`); xem lướt 5 bước
      wizard ghi `PATCH /api/boards/{id}` 5 lần (lưu `step`) — chấp nhận được.
  Không thấy: lỗi trang trắng / pageerror, trang tràn ngang (1400 và 1024 px), ảnh vỡ link. Test backend 1178 pass / 1 fail có sẵn (`test_chat_agent` veo) / 2 skip
  (Postgres), 16 phút trên máy Linux; `tsc` sạch. Không thử: lồng tiếng (theo lời người dùng), tạo ảnh / video Flow, viết bài AI, đăng thật.
- **Nền tuỳ chỉnh / Chỉ phụ đề / Cắt clip (31/10)**: Remotion đã chạy thật với nền video và nền lưới + Cắt 4:3 (nền màu / ảnh mới thử bằng ffmpeg + xem trước); phụ đề Thái / Hàn chưa thử qua Remotion;
  clip phần (`dub_part`) vẫn hiện Bước 1–4 + nút "Tạo video tự động" vô nghĩa (giống mục 7 rà soát); cắt chỉ cắt bản đã xuất — sửa phụ đề thì Xuất lại rồi
  Cắt lại; chưa cắt được cả loạt video một lần; **chưa dạy trợ lý AI** (trợ lý chưa có kỹ năng lồng tiếng nào — nên thêm cả cụm: lồng tiếng / chỉ phụ đề /
  cắt theo link).
- **Xoá logo video còn lại (7/11)**: clip **Veo** có chữ "Veo" nhỏ sát góc phải dưới — chưa xoá (logo khác hẳn, cần mẫu riêng); sao rất mờ trên nền gần trắng
  không dò ra (37449e62, 81601a94 — mắt cũng khó thấy); vết "V" ở đầu nhọn logo Flow trên mép tối–sáng đã giảm nhờ đọc độ đậm theo cặp điểm (cảnh 2 áo khoác),
  nền quá rối (< 30 % cặp sạch) vẫn đọc kiểu cũ — **chưa xem lại bằng mắt trên các clip khác sau đổi này** (người dùng tự test 7/11);
  sao nhấp nháy mà cảnh chuyển động liên tục (không có mảnh nền khớp) thì lấp từ xung quanh — mịn nhưng hơi nhoè trên nền nhiều vân. Video cũ của clip #67 phải ghép
  lại mới hết sao (bộ nhớ đệm đã đổi phiên bản nên lần ghép sau tự xoá lại).
- **Xoá logo video (1/11)**: clip cỡ khác 720×1280 / 1280×720 chưa thử (vị trí tính theo tỉ lệ `k`); "Xoá trên ảnh đã có" ở Cài đặt chưa quét video. Phụ đề Remotion cho clip: chưa có kéo vị trí / cỡ (luôn y 0,84), chưa có nhấn chữ quan trọng như lồng tiếng.
- **Thư viện link lồng tiếng (30/10)**: hàng đợi thư viện mới chạy thật với 2 link lỗi nhanh (example.com — trước khi chặn link không phải video), chưa lồng tiếng trọn một video thật từ thư viện, chưa chạy nhiều link liền nhau qua nhiều giờ. Chưa có: tách link theo file (lọc theo file nguồn), sắp xếp, ưu tiên / đổi thứ tự trong hàng đợi, giới hạn số video mỗi ngày, tự lấy tiêu đề video trước khi lồng tiếng.
- **Edit auto CapCut (28/10)**: dự án ghi ra **chưa mở thử trong CapCut thật** (cấu trúc chép từ dự án người dùng tạo bằng CapCut 9.5.0, kiểm bằng
  đọc lại file + Playwright). Cần người dùng mở CapCut xem dự án "Flowboard thử — Lao xuống Enceladus…": video nền, giọng + nhạc, phụ đề, chữ nhấn mạnh,
  zoom, tiếng hiệu ứng có hiện đúng không, rồi xuất một bản và thả về (bước ④). Chưa có: chỉnh màu riêng cho cụm từ trong phụ đề (karaoke), chữ "Tiêu đề"
  chưa dùng, tách chỗ nói vấp (lặp câu) cho video tự quay, máy không có pyvideotrans thì clip / video tải lên không có phụ đề.
  **Phase tiếp theo đã bàn với người dùng (28/10, chưa làm, chờ họ mở thử dự án trong CapCut trước):**
  1. **Chỉnh màu / cỡ / viền / nền chữ ngay trong Flowboard** từ một kiểu chữ đã học (chỉ là con số trong material: `text_color`, `font_size`,
     `border_*`, `background_*`, và `styles[0]` trong `content`) — vd. chữ nhấn mạnh vàng, to 1,5×, viền đen — người dùng khỏi làm mẫu từng kiểu.
  2. **Học thêm từ dự án của người dùng + tự đặt**: sticker (mũi tên / ngón tay cạnh chữ nhấn mạnh, nhất là chỗ nói giá), chuyển cảnh (giữa cảnh
     clip theo bước, chỗ cắt khoảng lặng), bộ lọc / hiệu ứng hình (cả video hoặc nháy ở chữ quan trọng), nhạc nền cho video tự quay. Người dùng
     chọn loại nào muốn dùng rồi mới làm. Hiệu ứng chữ (vào/ra) đã đi theo kiểu chữ (refs `material_animations` được chép).
  3. **Luôn quét dự án tên "Kho mẫu"** dù cũ hơn 12 dự án gần nhất (hướng dẫn người dùng dựng một dự án mẫu: video, 1–2 font mỗi font một dòng
     "Phụ đề" / "Nhấn mạnh" / "Tiêu đề", 5–10 tiếng hiệu ứng ngắn, tránh đồ Pro).
  4. **Nhận diện đồ Pro** lúc học: `key_value.json` của mỗi dự án có `is_vip` theo id tài nguyên (4 tiếng của người dùng = "0"; font không có cờ)
     → nhãn PRO, không tự dùng. Dự án có đồ Pro vẫn mở được, chỉ lúc Xuất CapCut hỏi bỏ đi hay nâng cấp.
  5. **Thử template của kho Mẫu CapCut** (người dùng dùng một template miễn phí rồi đóng CapCut) → xem dự án tạo từ template có đọc được / bị
     khoá không, học được font + hiệu ứng của nó không.
  6. **Học phong cách từ một video mp4 mẫu** (AI xem video như `reference_video` / Mẫu đang hot): vị trí, cỡ, màu phụ đề, số chữ một dòng, nhịp
     zoom / chữ nhấn mạnh / tiếng — chỉnh thông số, vẫn dùng font / âm thanh trong CapCut của người dùng (mp4 không chứa font / mã hiệu ứng).
  8. **Đồ "Yêu thích" (⭐) của CapCut** (dò 28/10): CapCut có bảng `favorite_effect` (`mid`, `effect_type`) trong SQLite `User Data\Cache\ressdk_db\<hash>\rp.db` (+ `-wal`; chép ra rồi mới đọc) — **đang trống** trên máy nhà (người dùng chưa thả tim, hoặc CapCut chỉ ghi khi mở tab Yêu thích; danh sách gốc ở tài khoản). Tên / loại / link của tài nguyên nằm trong `http_cache.response_body` (JSON của `get_panel_info…`, `get_resources_by_category_id…`); file chỉ có khi CapCut đã tải (`Cache\effect\<id>\<md5>\…` — 217 cái, `Cache\music\*.mp3` — 10 cái). Ý tưởng: font / tiếng yêu thích thay vào khuôn chữ / khuôn âm thanh đã học (cần file đã tải); hiệu ứng / sticker / chuyển cảnh vẫn cần một mẫu mỗi loại trong dự án. **Đã thử 28/10: không dùng được** — người dùng lưu "một mớ" tiếng hiệu ứng (dự án "test"), `favorite_effect` vẫn 0 dòng ở cả 3 `rp.db`, và CapCut **không tải** tiếng chỉ được lưu (Cache\music vẫn 5 mp3: 4 cũ + 1 tiếng kéo vào timeline). Tool chỉ học được đồ đã nằm trên timeline của một dự án — hướng dẫn người dùng kéo các tiếng đã lưu vào dự án "test" (đặt đâu cũng được) rồi Học lại.
  7. Hướng khó, chưa chọn: danh mục mã hiệu ứng / chuyển cảnh cộng đồng dò sẵn (pyJianYingDraft và bản cho CapCut) để dùng đồ người dùng chưa
     từng bấm — rủi ro mã cũ với CapCut 9.5, dễ dính Pro. Không điều khiển CapCut bằng chuột giả lập (chậm, dễ bấm nhầm Pro, chiếm máy người dùng).
- **Trình chỉnh sửa lồng tiếng (26/10)**: câu nào sát câu bên cạnh (Whisper thường để liền nhau) chỉ rút ngắn được, chưa dời được tới khi câu bên cạnh được rút lại; chưa có tách / gộp / thêm câu mới; lớp làm mờ / khung / nhân vật vẫn áp cả clip (chưa đặt theo khoảng thời gian); khối phụ đề video dài ở mức "Vừa khung" rất hẹp → phóng to mới bấm được.
- **Nhập từ tab đang mở** (`list_shop_tabs` / `read_tab` / `scrape_page` trong `extension/background.js`, bản 0.5.0) mới test bằng extension giả + UI giả lập, chưa chạy trên tab TikTok / Shopee thật. Trang chi tiết sản phẩm thì chỉ lấy sản phẩm chính (không lấy "sản phẩm liên quan").
- **Chưa thử thật (20/10)**: prompt 4 mẫu clip mới qua Flow; chế độ chỉ bàn tay qua Flow; tình huống hết credit → tự chuyển
  tài khoản; 2 Chrome profile cùng lúc; key OpenAI/xAI; nghe hội thoại nhiều giọng; hàng đợi nhiều clip với credit thật.
- Kịch bản khác nhau cho từng clip: đã có khi tạo từ sản phẩm (`variant`), chưa có với clip không gắn sản phẩm. Còn thiếu so với AI Dễ Ẹc (người dùng chưa chọn làm):
  upscale 2K/4K, storyboard lưới trong wizard ("storyboard 2"), trim / chèn chữ lên video thật.
- Còn trong báo cáo UX chưa sửa: Canvas chat dock quá to, toolbar Canvas tiếng Anh, "req ✗" không bấm được, thư viện tham chiếu cũ.
- Test `test_chat_agent.py::test_gen_video_renders_on_veo_only_when_asked` lỗi sẵn trên Linux (22/10, lỗi cả khi chưa có thay đổi mới), chưa xem nguyên nhân.
- **Người mẫu bị Flow chặn**: đã có nút kiểm tra; chưa tự kiểm tra khi tạo người mẫu mới (tốn ~12 credit/lần nên để người dùng bấm).
  Omni 4/6/10 s chưa thử lại (4 s bị bỏ 1 lần — có thể cũng do lỗi ghim nhầm project lúc đó).
- **Nhóm A (26/10) chưa thử thật**: đã kết nối Facebook Page (26/10, token người dùng dài hạn dán ở Kênh → Tự đăng lên Facebook Page, hết hạn
  ~25/12/2026 — nhớ gia hạn lại, xem Bẫy "Lấy token Facebook Page") nhưng **chưa đăng thử bài thật** (lên lịch một bài ngắn có ảnh + bình luận đầu, rồi một
  clip có video, để kiểm tra Graph API); Mẫu đang hot với link video / link Facebook thật; clip theo mẫu chưa render. TikTok / Instagram không tự đăng được (không có API công khai).
- **Máy Linux (cty) từ 26/10 nối Neon** (`FLOWBOARD_CENTRAL_DB_URL` trong `.env`, tài khoản akiragosho backend postgres — cùng dữ liệu
  máy nhà). Bản SQLite cục bộ 23/10 (gần như trống) còn ở `storage/accounts/akiragosho/` + `storage/accounts.db`, không dùng nữa.
  `.env` máy này `FLOWBOARD_PAYGATE_TIER=PAYGATE_TIER_TWO` (tài khoản Flow Ultra), máy nhà ghi `TIER_ONE` — mỗi máy theo tài khoản Flow của Chrome máy đó.
  **Lồng tiếng chưa dùng được trên máy Linux** (chưa có venv pyvideotrans: Whisper + spleeter; `FLOWBOARD_ERASE_PYTHON/ROOT` đang trỏ `D:\codes\…`); Remotion đã cài.
- **Bài viết Facebook** (24/10): chưa đăng thẳng lên Facebook (chỉ Copy + tải ảnh), chưa có lịch đăng; 2 bài thử (#1 có ảnh AI,
  #2 gắn clip Cơm cháy) để lại trong "Bài đã lưu" làm mẫu — xoá được. Prompt ảnh chưa lưu vào thư viện prompt.
- **Kênh** (24/10): kênh thử "Bếp Ăn Vặt Test" đã bị xoá trên UI ngay sau khi làm xong (bài #3–#5 còn, không gắn kênh); chưa có kênh
  thật nào. Xoá kênh giờ gỡ luôn `quicktool.channel_id` của clip (trước chỉ gỡ bài). Chưa có: brainstorm tự chạy khi gắn clip (chỉ chạy sau khi lưu bài), kịch bản clip chưa đọc định
  hướng kênh (mới có bài viết), chưa đăng thẳng lên nền tảng.
- **Lồng tiếng** (24/10): mới thử link YouTube + file upload; **chưa thử link Douyin / TikTok thật** (yt-dlp chung với reference-video
  đã chạy TikTok trước đây); chưa xoá chữ Trung in sẵn trên video (dùng "Xoá chữ / logo" trước rồi upload file); chế độ "xem lại
  bản dịch" mới test qua API; chưa chọn được font khác Arial; job đã sống qua restart (job.json) nhưng job đang chạy lúc tắt thì
  phải làm lại; vùng mờ chỉ là một hình chữ nhật cố định cả clip (chữ gốc đổi chỗ thì phải chọn vùng rộng hơn). Clip thử #7 "Dùng dầu massage
  đúng cách để ngừa rạn da" (từ YouTube) để lại làm mẫu — xoá được.
  Bài #7 #8 "Chuyện mình đi bán cơm cháy" (Tập 1–2, test chuỗi bài thật) để lại làm mẫu — xoá được. Clip hàng đợi thử #9 #10 đã xoá.
- **Dữ liệu trên Neon bị xoá gần hết tối 25/10 (20:41–20:43)**: log `storage/logs/start64.log` ghi các lệnh từ giao diện trên máy nhà:
  DELETE bài #8→#1, DELETE clip (board) 2, 7, 8, `POST /api/products/bulk-delete`, DELETE người mẫu #6 — không phải do code/test
  (agent không tự xoá; bộ test chạy trên SQLite tạm; e2e dọn lịch sử chỉ gửi `dry_run`). Hiện board/node/product/post/request = 0 dòng,
  còn 3 kênh, 43 prompt mẫu, 252 asset, 1 người mẫu. Nếu KHÔNG phải người dùng tự dọn: Neon có khôi phục theo thời điểm (branch restore,
  console.neon.tech → Restore, chọn trước 25/10 20:41 giờ VN = 13:41 UTC) — cửa sổ lưu lịch sử của gói free ngắn, làm sớm.
  Bản SQLite sao lưu trước khi lên cloud: `storage/accounts/akiragosho/flowboard.db` (22/10 12:58).
- **Muse (26/10)**: chưa thử với tài khoản Muse thật — cần xem Muse có giữ đúng thứ tự ảnh / video không, tên file video tải về từ Muse ra sao
  (nếu tên ngẫu nhiên thì tự xếp theo giờ tải về — tải đúng thứ tự Video 1, 2…), Muse có tự thêm nhạc/tiếng nói hay watermark nhìn thấy không,
  và chất lượng so với Flow. Tài khoản Muse người dùng hỏi lúc 26/10 vẫn báo **chưa có gói trả phí** (đã dùng 3 % hạn mức tuần, reset 6:26 1/11)
  dù người dùng nói đã mua → có thể gói gắn tài khoản Facebook khác.
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
- **22/10** — "Tạo lại…" ở bước 3/4 có ô nhập yêu cầu (tiếng Việt) + gợi ý nhanh: AI sửa prompt theo yêu cầu rồi tạo lại, nhớ yêu cầu lần trước, nút về prompt cũ. `POST /api/prompt/revise`. Thử thật cảnh 4 (ảnh): lần 1 AI làm mất tên áo → ra áo vest, đã sửa (giữ nguyên mô tả sản phẩm) → lần 2 đúng áo, đúng yêu cầu; sửa luôn lỗi F5 mất `lastRequest`. Video theo yêu cầu chưa thử với Flow (tốn credit). Test 42 pass. Chưa commit.
- **22/10** — Điều tra "timeout + tạo clip lâu": nguyên nhân là Flow lặng lẽ bỏ video có mặt người mẫu (bộ lọc người nổi tiếng, xác nhận bằng giao diện Flow; credit được hoàn) + worker chạy video nối đuôi (4 cảnh × 5–6 phút). Sửa: video chạy song song tối đa 3, lỗi ghi lên node, bước 4 báo "Flow bỏ lượt này" + gợi ý, giá Omni 8 s = 12 credit. Đã thử thật (3 video song song ~6 phút); test 837 pass (+1 lỗi 0600 có sẵn). Thử nút "vẽ lại không lộ mặt" thất bại nên đã bỏ; ảnh cảnh 1/3 của clip 1 đã trả về bản cũ. Chưa commit.
- **22/10** — Tìm ra thủ phạm video bị Flow bỏ: gương mặt người mẫu (thí nghiệm A–E + 2 probe, đổi từng yếu tố). Thêm "🎬 Kiểm tra với Flow" (Bước 1, lưu kết quả lên node + thư viện, huy hiệu ở /models), Bước 4 chỉ thẳng sang đổi người mẫu, prompt người mẫu mới tránh giống người nổi tiếng, worker nhận `max_wait_s`. Đã thử thật: người mẫu clip 1 → "chặn" (191 s), ảnh mẫu 10/10 → qua (68 s); phát hiện Omni 4 s bị bỏ. Chưa commit.
- **22/10 tối** — Sửa lỗi lớn: hàng tài khoản Flow coi `FLOW_DROPPED_JOB` ("refunded the credits") là hết credit → ghim project của tài khoản Google khác → mọi job rơi vào project lạ (`account_pool.is_credit_error`, `after_login`, `REVIVE_CREDITS`); "Tạo lại người mẫu" không làm gì khi đã có ảnh (`generateModel(force)`); kết luận kiểm tra Flow gắn với `mediaId`; gỡ câu "natural everyday look" khỏi prompt người mẫu (làm mặt giống ảnh thật hơn). Đã ghim lại `b5633a75`, credit thật 930. Test pool 11 pass. Thử nghiệm hôm nay tốn ~120 credit. Clip 1 vẫn chưa có video (người mẫu hiện tại bị chặn; người dùng sẽ tự tạo lại). Commit + push.
- **22/10 tối** — Sửa bug: chạy "Tạo video tự động" xong thì không bấm lại được bước 1–4 (luôn bị kéo về bước 5) — `QuicktoolApp.tsx` chỉ chuyển sang bước 5 một lần khi vừa xong. Kiểm tra bằng `tsc`; người dùng thử lại trên clip "Cơm cháy".
- **22/10 tối** — Sửa bug giọng Gemini đọc luôn "phong cách đọc" ở đầu mỗi clip: prompt TTS tách ghi chú / lời thoại (`tts.gemini_tts_prompt`), khoá cache có phiên bản (`GEMINI_PROMPT_VERSION = "v2"`) để ghép lại thì đọc mới. Thử thật với 3 câu của clip Cơm cháy + Gemini chép lại: cũ 2/3 câu đọc lẫn, mới 0/3. Test TTS pass.
- **22/10 tối** — Kịch bản clip viết theo mô tả + điểm bán của sản phẩm (`services/script_tailor.py`, gọi trong `POST /api/boards/from-template`): ảnh cảnh, chuyển động video, lời thoại; N clip/1 sản phẩm mỗi clip một góc, tạo song song. Thử thật với Cơm cháy: hết prompt burger, lời thoại nêu điểm bán, 15 s/clip (clip thử đã xoá). `conftest.py` không đọc key thật nữa. Cả bộ test 843 pass (+1 lỗi 0600 có sẵn). Commit + push (gộp sửa bước 1–4, giọng Gemini, kịch bản).
- **23/10** — Máy Linux: pull bước B + 2 commit mới, cài thư viện (`uv pip install -e ".[dev]"`), chạy với đăng nhập cục bộ (chưa có Neon URL); đăng nhập akiragosho thấy đủ dữ liệu cũ, trang Sản phẩm có nút "Nhập từ tab đang mở". Thử bằng API + Playwright.
- **23/10** — Người mẫu: nút **⧉ Nhân bản** (bản sao giống 100%, không bắt trùng, mở form sửa bản sao để đổi tên). `POST /api/references/{id}/clone`, `media_id` của `Reference` bỏ unique + migration. Test references/characters 20 pass (thêm test clone + migration), các test liên quan 177 pass (+1 lỗi có sẵn). Thử thật trên UI bằng mẫu tạm (đã xoá). Migration chạy thật trên SQLite máy Linux; **chưa chạy trên Postgres Neon** (máy nhà sẽ chạy khi khởi động).
- **23/10** — Màn hình đang tải và màn hình trống ở các trang (Sản phẩm, Người mẫu, Prompt, Lịch sử, Clip của tôi) chuyển ra giữa trang, có vòng xoay mới và nút hành động (`quicktool/PageState.tsx`); bỏ CSS `qt-empty-state` cũ. Đã chụp UI thật (trang Sản phẩm tải chậm giả lập, trống; Người mẫu, Clip trống).
- **23/10** — Prompt đã lưu theo ngành + loại cảnh: Bước 2 "📚 Chọn prompt" lọc/xếp theo ngành của sản phẩm và loại cảnh (hook, chi tiết, demo, chốt đơn…), ngành khác ẩn; "★ Lưu" tự gắn nhãn; trang `/prompts` lọc theo ngành / loại cảnh và sửa nhãn trên thẻ; lưu trùng text thì gộp nhãn. `quicktool/promptTags.ts`. Test prompt library 4 pass; thử thật trên UI với clip + sản phẩm thời trang tạm (đã xoá, đã đặt lại lượt dùng của mẫu). Commit + push gộp nhân bản người mẫu + màn tải/trống + prompt theo ngành.
- **24/10** — Kéo commit máy cty (`755e864`). Rà tốc độ Quicktool bằng Playwright + đo API: sửa proxy Vite sang `127.0.0.1` (bớt ~200 ms mỗi API), bỏ `pool_pre_ping` (ping khi kết nối ngồi yên), nhớ media thiếu 5 phút ở `/media`, ghép stream-copy có faststart. Test mới `test_db_idle_ping.py`, test media thêm 1; thử thật ghép 2 clip → faststart. Chưa commit.
- **24/10** — Nhóm "đỡ hỏng" (người dùng chọn): tự thử lại video bị Flow bỏ 1 lần, tự kiểm tra người mẫu đầu lượt tạo tự động, nút "Viết lại kịch bản theo sản phẩm" ở Bước 2 (`POST /api/boards/{id}/tailor`), đọc link lưu thêm chi tiết trang vào ghi chú sản phẩm. Thử thật: viết lại clip tạm (đã xoá), đọc link Shopee Cơm cháy. Test thêm cho cả 4 việc pass. Chưa commit.
- **24/10** — Bước 5: sắp xếp / bỏ / cắt từng cảnh và "Chữ trên video" (tên sản phẩm, giá, Freeship, bấm giỏ hàng, chữ tự gõ) — `ExportEditor.tsx`, `video_overlays.py`, `video_export(trims, overlays)`. Sửa luôn lỗi mất thay đổi khi PATCH cùng node chồng nhau (`patchNode` xếp hàng). Test ffmpeg thật pass; thử UI trên clip Cơm cháy (không ghép đè). Chưa commit.
- **24/10** — Trang "Hôm nay" (trang mở đầu: credit, đang chạy, cần xử lý, chưa tải, đang dở) + tải hàng loạt (.zip, tên theo sản phẩm + ngày, đánh dấu đã tải). `TodayPage.tsx`, `routes/exports.py`, summary board gộp 1 truy vấn. Thử thật trên UI + zip clip Cơm cháy. Chưa commit.
- **24/10** — **Bài viết Facebook**: trang `/posts` (điền mẫu hoặc chat với AI → bài kiếm tương tác, xem trước kiểu Facebook sửa trực tiếp, Copy, tạo ảnh Flow theo ảnh sản phẩm, lưu thư viện) + mục tuỳ chọn ở Bước 5 viết bài kèm clip theo lời thoại. `post_writer.py`, `routes/posts.py`, bảng `Post`, `PostsPage.tsx`, `PostEditor.tsx`, `ClipPost.tsx`. Test `test_posts.py` 5 pass, cả bộ 862 pass (+1 lỗi 0600 có sẵn), `tsc` sạch. Thử thật bằng Playwright: viết bài mẫu + sửa qua chat + lưu, viết bài ở Bước 5 clip Cơm cháy → mở ở /posts, tạo 1 ảnh Flow vuông có ảnh sản phẩm làm mẫu (27 s, đúng sản phẩm). Chưa commit.
- **24/10** — **Kênh của tôi**: bảng `Channel` + `Post.channel_id` + `quicktool.channel_id`; trang `/channels` (tạo/sửa kênh: nền tảng, ngành, mô tả, khán giả, mục tiêu; thống kê; bài + clip của kênh); **brainstorm** định hướng kênh (tự chạy sau khi lưu bài thứ 3, làm mới sau 5 bài, hoặc bấm tay) → bài viết sau bám PAGE DIRECTION + định dạng theo nền tảng; chọn kênh ở hộp Clip mới, Bước 1, trang Bài viết, Bước 5. `services/channels.py`, `routes/channels.py`, `ChannelsPage.tsx`, `ChannelPicker.tsx`, `ClipChannel.tsx`. Test `test_channels.py` 6 pass, cả bộ 869 pass (+1 lỗi 0600 có sẵn), `tsc` sạch. Thử thật bằng Playwright: tạo kênh → 3 bài → brainstorm (~20 s, định hướng đọc được, còn tự nhận xét "ba bài đầu khá giống nhau") → hộp Clip mới / Bước 1 / Bước 5 nhận kênh; viết thật 1 bài sau brainstorm. Chưa commit.
- **24/10** — **Lồng tiếng video** (`/tools/dub`): link/file → Whisper (venv pyvideotrans) → dịch LLM → TTS Việt vừa mốc câu → bỏ tiếng gốc (tuỳ chọn giữ nhạc nền bằng spleeter) → phụ đề hộp vàng → clip (board `dub`) có kênh + bài đăng Bước 5. `services/dub.py`, `dub_runner.py`, `routes/dub.py`, `DubPage.tsx`. Test `test_dub.py` 8 pass, cả bộ 877 pass (+1 lỗi 0600), `tsc` sạch. Thử thật: video giả 12,6 s (39 s, Whisper nghe lại đúng 4 câu đúng mốc) và YouTube tiếng Trung 69 s → 26 câu, 128 s; UI Playwright (trang, bảng câu, Bước 5, thư viện). Sửa lỗi track giọng dài gấp đôi (probe_clip với WAV) và chữ tràn khung (WrapStyle). Clip thử giả đã xoá, clip #7 từ YouTube giữ làm mẫu. Chưa commit.
- **25/10** — Sửa lồng tiếng với link Douyin: dán nguyên đoạn share vẫn nhận (`extract_url`), Douyin tải qua trang chia sẻ mobile thay vì yt-dlp (đòi cookie), báo rõ khi link là tuyển tập dài quá 10 phút; `/api/reference-video/fetch` dùng chung. `services/video_fetch.py`, test 5 pass (+ dub 8). Thử thật: link 合集 của người dùng → đọc được tiêu đề/thời lượng 55 phút trong 2,5 s → từ chối đúng; **chưa thử tải trọn một video Douyin lẻ** (cần link video đơn). Chưa commit.
- **25/10** — Lồng tiếng: **chỉnh vị trí phụ đề sau khi render** kiểu CapCut (kéo thả / mũi tên / slider / preset, cỡ chữ, kiểu) + **vùng làm mờ nhẹ chữ gốc** (kéo, đổi cỡ, độ mờ, tự tìm bằng OCR) → "Áp dụng" in lại ~27 s nhờ dùng lại giọng; job dub lưu `job.json` sống qua restart. `SubPositioner.tsx`, `dub.py` (`normalize_layout`, `blur_filter`, `video_filter`, `persist`/`load_jobs`). Test dub 12 pass, cả bộ pass, `tsc` sạch. Thử thật trên video Douyin 6:20 của người dùng (clip #8): job tải lại sau restart, in lại với phụ đề ở 72 % + dải mờ 60–67 % → đúng khung hình, rồi trả về bố cục mặc định; Playwright kéo hộp + bấm mũi tên đổi đúng %. Chưa commit.
- **25/10** — Lồng tiếng: sửa lỗi **nhạc nền còn nguyên giọng gốc** (đảo stem spleeter) và render lại clip #8 của người dùng; **hàng đợi** tối đa 5 video (dán nhiều link một lần, chạy lần lượt, "Gần đây" tự cập nhật); job đã lưu đĩa nên "lưu tạm" bản dịch (chế độ xem lại) cũng giữ. Bài viết: **câu chuyện nhiều kỳ** (`series`/`episode`, kiểu `serial`, AI đọc 3 tập trước, "Tiếp tục câu chuyện lần trước…", `GET /api/posts/series`) ở trang Bài viết + Bước 5. Test dub 14 + posts 7 pass, `tsc` sạch. Chưa commit.
- **25/10** — Đã làm rồi **bỏ theo yêu cầu**: provider "Claude (API key)" / "Gemini (API key)" cho `run_llm` (SDK anthropic, ô dán key, nút chọn một provider cho tất cả, mục AI provider trong Cài đặt Quicktool). Lý do: Claude CLI đã dùng gói Max của người dùng (không tốn tiền), API key không còn dùng được. Code đã revert hết (`git checkout` các file, xoá `claude_api.py` / `gemini_key.py`, gỡ `anthropic` khỏi venv). Nếu cần lại: mẫu còn trong lịch sử phiên 25/10, làm lại ~1 giờ.
- **25/10** — Bố trí lại hộp **Cài đặt**: tab bên trái (Tạo ảnh & video / Google Flow / Gemini key / Dữ liệu / Thông tin), các lựa chọn một-trong-nhiều thành select (Model video, Model ảnh, Nguồn tạo ảnh), hướng dẫn dài gập lại, nút tài khoản xếp ngang. `SettingsPanel.tsx`, `ImageProvidersSection.tsx`, `FlowAccountsSection.tsx`, `AccountPoolSection.tsx`, `styles.css`. `tsc` sạch; chụp Playwright cả 5 tab, chọn nguồn ảnh chưa có key → hiện ô key, không tự chuyển. Chưa commit.
- **25/10** — Kênh có **link page** + **"🔎 Xem & đánh giá kênh"**: extension 0.6.0 `read_channel` đọc trang qua Chrome của người dùng, AI chấm điểm / điểm mạnh / cần sửa / gợi ý / phong cách page thật, bài viết + brainstorm bám theo; tự đánh giá khi tạo kênh có link. `channel_page.py`, `routes/channels.py`, `extension/background.js` + `manifest.json`, `ChannelsPage.tsx`, `channels.css`. Test 18 pass (kênh + bài viết), `tsc` sạch. Thử thật: chữ trang "Bầu bì không khó" (lấy qua Chrome) → AI đánh giá 19 s, đúng ý (danh mục page sai ngành, nội dung lặp, ít CTA; phong cách câu ngắn gọi các ông chồng + 🥰); UI hiện thẻ đánh giá; với extension 0.5.0 báo đúng "cần Reload 0.6.0". **Chưa chạy `read_channel` thật** (người dùng cần Reload extension). Kênh thử #4 đã xoá. Sửa thêm nhãn nút "Xoá key" → "Lưu" khi nguồn ảnh chưa có key. Chưa commit.
- **25/10** — Trang Lịch sử có **🧹 Dọn lịch sử** (chỉ việc lỗi / cũ hơn 7 / 30 ngày / toàn bộ việc đã xong; đếm trước, bấm 2 lần mới xoá; không đụng việc đang chạy, ảnh/video, credit thật). `routes/history.py` `/clear`, `HistoryPage.tsx`, `history.css`. Test 9 pass, `tsc` sạch; Playwright mở popover đếm đúng (30 lỗi / 43 cũ hơn 7 ngày / 78 tất cả) và **không xoá dòng nào** của người dùng. Chưa commit.
- **25/10** — Sidebar làm lại cho bắt mắt: nhóm **Công cụ lên trên Thư viện** (`QuicktoolSidebar.tsx`); tên nhóm chữ trắng đậm 14px có gạch cam + đường kẻ; mục 15px, icon nằm trong ô vuông mờ, mục đang chọn nền gradient cam + icon cam + vạch cam bên trái, hover trượt nhẹ (`.qt-nav__*` trong `quicktool.css`). Chưa commit.
- **25/10** — Link kênh: tự chuẩn hoá (`channel_page.normalize_link`: thêm `https://` khi thiếu, `http` → `https`, lọc URL khỏi đoạn dán, bỏ `/` cuối) ở cả backend lẫn form — người dùng dán `http://tiktok.com/goodbOi95` từng bị từ chối. Test 13 pass. Chưa commit.
- **25/10** — Kênh: danh mục thành **chọn nhiều, tối đa 3** như tạo Trang Facebook (22 danh mục: bán gì + nói về gì), chip trong form, `channel_block` liệt kê cả 3 cho AI. `Channel.categories` + migration, `routes/channels.py`, `ChannelsPage.tsx`. Test 21 pass, `tsc` sạch. Chưa commit.
- **25/10** — Tiếp thị liên kết: sản phẩm có "Link tiếp thị liên kết" + "Shop đang hợp tác" (link aff trùng → 409, `GET /api/products/shops`), bài viết cho sản phẩm có aff sinh thêm **bình luận đầu tiên** (câu mời + link, link không vào bài) ở trang Bài viết + Bước 5, hộp sửa/Copy riêng. `test_affiliate.py` 5 pass, cả bộ 904 pass (+1 lỗi 0600 có sẵn), `tsc` sạch; thử thật UI (form, trùng, viết bài 13 s). Phát hiện dữ liệu Neon đã bị xoá qua UI lúc 20:41–20:43 (xem Việc đang dở). Chưa commit.
- **25/10** — Bài viết: chọn N ảnh → viết xong **tự tạo ảnh luôn** (không cần bấm "Tạo ảnh"), **viết lại bài mới thì bỏ ảnh cũ**, mỗi prompt có thumbnail + "↻ Tạo lại ảnh" (thay ảnh cũ) + "✨ Sửa theo yêu cầu" (AI sửa prompt từ câu tiếng Việt, `POST /api/posts/revise-image`). Áp cả Bước 5. Lỗi Flow không trả ảnh nay báo rõ là bộ lọc nội dung. Test posts 15 + flow_sdk 68 pass, `tsc` sạch; thử thật Playwright (ảnh tự ra 31 s, sửa prompt 9 s, viết lại bỏ ảnh cũ; ~4 ảnh Flow). Agent `start70`. Chưa commit.
- **25/10** — **Lồng tiếng: engine phụ đề Remotion** (lựa chọn riêng "Công nghệ phụ đề", ffmpeg/ASS giữ nguyên): 3 kiểu (hộp bo góc font Việt + emoji màu, bật sáng từng từ kiểu TikTok, chữ viền), xem trước bằng `<Player>` đúng y bản render trong khung chỉnh vị trí (kéo khung ghost, tua, vùng mờ). `frontend/src/remotion/*`, `frontend/remotion/render.mjs`, `services/dub_remotion.py`, nhánh `_render_remotion` + `engine` trong `dub.py`, route `/nosub`. Test `test_dub_remotion.py` 5 + dub 13 pass, `tsc` sạch; thử thật: job 12,6 s xong 101 s, in lại 18 s, khung hình đúng (karaoke, emoji, hộp vàng + dải mờ); Playwright kéo khung ghost → 65 %. Clip thử #11 "Remotion test" để lại làm mẫu — xoá được. Chưa commit.
- **26/10** — Máy Linux: pull `fff72da` (bài viết, kênh, lồng tiếng, Hôm nay…), `npm install --prefix frontend` (Remotion), thêm `FLOWBOARD_CENTRAL_DB_URL` vào `.env` → chạy trên Neon (đăng nhập akiragosho: 1 sản phẩm, 3 kênh, 2 bài, 43 prompt). Playwright mở 7 trang không lỗi. Lồng tiếng báo "chưa dùng được" (thiếu pyvideotrans). AI trên máy này: Claude CLI (`~/.nvm/.../bin/claude`, gói Max) + 7 key Gemini theo tài khoản; thử `POST /api/posts/write` 11 s ra bài (không lưu). Người dùng không cần lồng tiếng trên máy Linux. Bẫy: npm máy Linux viết lại `package-lock.json` (bỏ trường `libc`) → `git checkout frontend/package-lock.json` để khỏi commit nhiễu.
- **26/10** — Bài viết Facebook: kênh / page bắt buộc (nút viết khoá + backend 400, cả Bước 5), "Kêu gọi" thêm "Không kêu gọi — bài để đọc" làm mặc định, khối "🚀 Tăng view & tương tác" (câu mở đầu, trình bày, emoji, 6 cách kéo tương tác; cấm engagement bait), Bài đã lưu xem lưới / danh sách + phân trang. `post_writer.py`, `routes/posts.py`, `PostsPage.tsx`, `ClipPost.tsx`, `ChannelPicker.tsx`, `posts.css`. Test posts/channels/affiliate 30 pass; Playwright (khoá khi chưa chọn kênh, chip, lưới 12 + trang 3, danh sách 10 với 30 bài giả); viết thật 1 bài kênh "Mẹ bầu." 11 s đúng kiểu "5 điều…" + danh sách + không kêu gọi (không lưu).
- **26/10** — Rà lại toàn bộ nút Quicktool: nút thường sáng + viền rõ (hết đen mờ), cam có bóng, ghost/danger rõ ràng, cỡ chữ lớn hơn; nút chính trang Sản phẩm thành cam; Xoá dạng chữ → nút đỏ (Bài đã lưu, Prompt, prompt ảnh). Trang Bài viết: khung bài rộng 860 px chữ 16px, "＋ Bài mới" / "💾 Lưu" to và nổi, "✓ Đã lưu" khi đã lưu; ảnh thẻ Bài đã lưu cao 170 px. `quicktool.css`, `styles.css`, `posts.css`, `prompts.css`, `PostsPage.tsx`, `PostEditor.tsx`, `PromptsPage.tsx`. Chụp Playwright: Bài viết, Sản phẩm, Clip, Prompt. `tsc` sạch.
- **26/10** — Ẩn mục "Canvas (kéo thả node)" khỏi menu (`QuicktoolSidebar.tsx` cờ `CANVAS_IN_MENU = false`; route `/canvas` vẫn còn, đặt `true` để hiện lại). Trang Bài viết: cột form bên trái `position: sticky` theo khi cuộn bài dài bên phải (`posts.css`). `tsc` sạch.
- **26/10** — **Lịch đăng** (`/schedule`): tuần 7 cột, giờ vàng theo nền tảng, nhắc "Đến giờ đăng" ở Hôm nay, đánh dấu đã đăng / copy / tải clip; **tự đăng lên Facebook Page** qua Graph API khi kênh dán token (ảnh, video, bình luận đầu), vòng lặp 60 s. `services/scheduler.py`, `facebook_publish.py`, `routes/schedule.py`, `ScheduleDialog.tsx`, `SchedulePage.tsx`, `FacebookConnect.tsx`. Test 9 pass (+ channels/posts 17); Playwright: lên lịch → tuần → đổi về quá khứ → Hôm nay nhắc → Đã đăng; slot thử đã xoá. Chưa thử token Facebook thật.
- **26/10** — Câu mở đầu A/B: "✨ 5 câu mở đầu khác" ở khung bài viết (+ "⧉ Lưu thành bản sao") và cảnh 1 Bước 2. `services/hooks.py`, `routes/posts.py` (`/hooks`, `/clip-hooks`), `PostEditor.tsx`, `StepScript.tsx`. Test 4 pass; Playwright với AI thật (8 s, thay/hoàn tác đúng, board thử đã xoá).
- **26/10** — 🎁 Gói nội dung một chạm từ thẻ sản phẩm: clip (kịch bản riêng) + bài Facebook (link aff ở bình luận đầu) + caption TikTok, cùng kênh. `services/bundle.py`, `routes/bundles.py`, `BundleDialog.tsx`. Test 2 pass; thử thật 27 s (board + 2 bài thử đã xoá).
- **26/10** — 🔥 Mẫu đang hot (`/swipes`): dán link bài / video hoặc nội dung → AI phân tích vì sao chạy (câu mở đầu, các bước, cảm xúc, khung mẫu) → viết bài / tạo clip theo cấu trúc cho sản phẩm của mình. `services/swipes.py`, `routes/swipes.py`, `SwipesPage.tsx`; `write_post(extra=)`. Test 5 pass; thử thật với AI (phân tích 20 s, viết bài 15 s; bài + mẫu thử đã xoá). Nhóm A xong cả 4 mục, 97 test liên quan pass; chưa commit.
- **26/10** — Xoá logo Gemini ✦ góc ảnh: dựng hình sao có căn chỉnh từ 71 ảnh thật, dò vị trí + độ đậm từng ảnh, hoàn nguyên điểm ảnh gốc (không mờ), tự chạy khi ảnh về máy + nút quét ảnh cũ trong Cài đặt. `services/watermark.py`, `assets/gemini_star_alpha.png`, hook `media.py`, routes `media.py`, `GeminiMarkSection.tsx`; thêm numpy + opencv-headless. Test 5 pass; thử trên bản sao ảnh thật.
- **26/10** — Kết nối Facebook Page thật lần đầu (máy cty): tạo app Meta "Mẹ bầu hạnh phúc" (trường hợp sử dụng "Quản lý mọi thứ trên Trang", chưa nối hồ sơ doanh nghiệp), lấy token người dùng có đủ 4 quyền Page (`pages_show_list`, `pages_manage_posts`, `pages_read_engagement`, `pages_manage_engagement`), gia hạn thành token dài hạn (~60 ngày, hết ~25/12/2026), dán ở Kênh → Tự đăng lên Facebook Page → Kiểm tra token → Kết nối. Không đổi code. **Chưa lên lịch / đăng thử bài thật** (ảnh, video, bình luận đầu chưa kiểm chứng). Chưa commit — CLAUDE.md cần push để máy nhà thấy.
- **26/10 chiều** — Trang Bài viết gọn lại: trái 3 khối đánh số (tuỳ chỉnh ít dùng gập lại, kiểu bài thành ô chọn có mô tả, nút viết dính đáy), phải tách nút của bài (Lưu/Bản sao/Bài mới) và **thanh Đăng bài** (Copy / Lên lịch / 🚀 Đăng ngay lên Page đã kết nối). **Viết 1–5 bài một lúc** (`POST /api/posts/write-batch`): câu chuyện → các tập nối tiếp (tập sau đọc tập trước), không thì mỗi bài một kiểu mở đầu; khung "Loạt bài vừa viết" có 📅 từng bài + "Xếp lịch cả loạt". Test posts 11 pass; Playwright với AI thật (3 tập 31 s, mở từng tập, hộp lên lịch). **Chưa bấm Đăng ngay / Xếp lịch cả loạt thật** (sẽ đăng thật lên Page). 3 bài thử đã xoá; brainstorm tự chạy của kênh "Mẹ bầu." lúc thử đã lấy theo bài thử (chưa đặt lại được — người dùng bấm "Brainstorm lại" ở trang Kênh).
- **26/10 chiều** — Đăng / lên lịch bài có ảnh: khoá nút khi ảnh đang tạo (trước đó bấm lúc đang tạo là bài lên không ảnh), ảnh vừa tạo / bỏ trên bài đã lưu được lưu ngay (PATCH `images`), thanh đăng ghi số ảnh kèm. `PostsPage.tsx`, `PostEditor.tsx`. `tsc` sạch; chưa đăng thật.
- **26/10 tối** — Bài viết **kèm video 8 s thay ảnh** (Flow Omni ~12 credit, ảnh của bài làm nguyên liệu; ô "Kèm theo" → "🎬 1 video" tự làm sau khi viết; đăng lên Page dạng video), **Lịch đăng kéo thả** (lưới thẻ "Chưa lên lịch", kéo vào ngày → chỉ hỏi giờ, kéo lịch sang ngày khác để dời, chặn ngày/giờ đã qua cả UI lẫn backend), sửa bài đã đăng vẫn hiện "Chưa lên lịch", cột form Bài viết rộng hơn / khung bài hẹp ~10%. `Post.video` + migration, `generateStandaloneVideo`, `PostEditor` (hộp video), `DropTimeDialog.tsx`, `scheduler.check_future`. Test schedule + posts 20 pass, `tsc` sạch. Thử thật: video từ ảnh bài #10 ra trong 56 s (8 s, 720×1280, có tiếng nền — không gắn vào bài, tốn ~12 credit); Playwright kéo thả (ngày qua không nhận, thả thứ Năm → hỏi giờ, kéo sang thứ Sáu giữ 20:00; lịch thử đã xoá). **Chưa đăng thật một bài video lên Page.**
- **26/10 tối** — Loạt truyện: chọn loạt có sẵn / tạo loạt mới, nút "⚡ Viết nhanh Tập N+1" (ở form) và "✍️ Viết Tập N+1" (trên đầu mỗi loạt trong Bài đã lưu), Bài đã lưu gom theo loạt (tập theo thứ tự) + "Bài lẻ". `PostsPage.tsx`, `posts.css`, `write-batch` nhận `n = 1`. Theo yêu cầu đã **viết thật Tập 4 của "Những ngày đầu có thai"** bằng nút mới: 13 s, bài #18 (kênh Mẹ bầu., kèm 1 ảnh Flow tự tạo, nối mạch "ông xã" từ cuối Tập 3, kết móc Tập 5) — **chưa đăng / chưa lên lịch**. Test posts 11 pass, `tsc` sạch.
- **26/10 tối** — Sidebar hết thanh cuộn: mục menu thấp hơn (padding 5px, icon 26px), nhóm sát hơn, logo / credit / tài khoản gọn lại; màn thấp ≤ 900 px và ≤ 760 px thu nhỏ thêm; `.qt-nav` ẩn thanh cuộn (`scrollbar-width: none`, vẫn cuộn được bằng chuột nếu cửa sổ quá thấp). Khối CSS cuối `quicktool.css`. Đo Playwright: vừa khít ở cao 1000 / 900 / 800 / 720 px.
- **26/10** — Sửa bug clip tạo từ 🎁 Gói (hoặc phía agent) không mở được từ "Clip của tôi" (giật rồi về thư viện): tải lại danh sách clip một lần và chờ xong mới kết luận link cũ. `QuicktoolApp.tsx`, `store/board.ts refreshBoards`. Playwright: tạo clip qua API → sang Bài viết → về Clip của tôi → bấm → vào Bước 1. Board thử #16–18 đã xoá. `tsc` sạch.
- **26/10 tối** — Tìm hiểu nguồn video thay Flow (không code): Seedance 1.5 Pro 480p ~$0,012/s (rẻ nhất, mờ), Hailuo 02 6 s 768p ~$0,28, Kling 2.5 Turbo ~$0,07/s (qua fal.ai, một key), Seedance 2.0 chặn hẳn mặt người thật, bản free (Kling/Dreamina/PixVerse) không có API + watermark, muse2api (đã có `services/muse2api.py`) là v0.1 chưa thử với tài khoản thật + lái web bằng cookie. Flow Omni 8 s ≈ $0,24 vẫn rẻ. **Người dùng chọn giữ Flow** (chưa muốn tốn tiền) → làm prompt Flow thông minh + nhanh hơn. Nếu sau này cần: thêm "Nguồn tạo video" fal.ai làm dự phòng khi Flow bỏ lượt.
- **26/10 tối** — Flow nhanh hơn / ít bị bỏ lượt (người dùng chọn giữ Flow, không tốn tiền): đo nhịp poll thật (clip giữ: vào danh sách ~10 s, xong ~33 s), phát hiện lượt "không vào danh sách" sau 90 s thay vì 5 phút, ảnh cảnh chạy 2 cái một lúc, tạo tự động chạy kiểm tra người mẫu song song + video theo từng ảnh xong; tìm ra ảnh shop có mặt người mẫu thật làm Flow bỏ video → cảnh báo + "✨ Tạo ảnh chỉ có sản phẩm" ở Bước 1 (`face_check.py`, `ProductFaceCheck.tsx`); preset người mẫu bỏ chữ "idol/flawless", thêm nét riêng; kịch bản tránh cận mặt; che token FB trong log. Thử thật cả lượt: ~4,5 phút cho clip 4 cảnh (clip #19). Commit `0dcbe0b`.
- **26/10 tối** — 🎬 Làm video bằng Muse khi Flow chậm / bỏ lượt (Bước 4): khung 3 bước (chọn cảnh → copy một tin nhắn + tải/copy ảnh cảnh theo thứ tự → thả video Muse, tự xếp vào cảnh), dừng lượt Flow đang chạy khi gắn video Muse, đồng hồ "Flow đã chạy m:ss" + nút Muse ở cảnh chậm (≥ 150 s) và cảnh bị bỏ, nhãn Muse/Video của bạn giữ qua F5; ghép clip khác kích thước (fit 720×1280, viền đen cho video vuông/ngang) + sửa lỗi ffmpeg với clip câm. `steps/MuseBridge.tsx`, `quicktool/muse.ts`, `store/quicktool.attachMuseVideo`, `video_export.common_size/fit_filter`. Test 167 pass (thêm 2 test ghép), `tsc` sạch; Playwright trên clip thử (đã xoá) + ghép thật 38 s. Chưa thử với Muse thật. Commit + push.
- **26/10** — Trang Hôm nay thiết kế lại (tiêu đề + ngày, 5 thẻ KPI có icon, 2 cột ưu tiên, khối trống thu một dòng, icon SVG). `TodayPage.tsx`, `today.css`. `tsc` sạch; Playwright 2 cỡ màn hình + kiểm tra trang Lịch đăng không vỡ. Chưa commit.
- **26/10** — Lồng tiếng: tăng giới hạn video lên **30 phút** (người dùng gặp video Douyin 11 phút bị chặn), nâng các timeout theo (Whisper/spleeter, ffmpeg, Remotion), dịch chia đợt 60 câu có ngữ cảnh, bỏ gợi ý "tuyển tập" sai cho video chỉ hơi dài. `dub.py`, `dub_remotion.py`, `video_fetch.py`, `DubPage.tsx`. Test dub/remotion/fetch 26 pass (thêm 3), `tsc` sạch; agent `start74` báo `max_minutes 30`. Chưa thử thật video dài. Chưa commit.
- **26/10** — Bài viết: ô Loạt truyện chỉ hiện loạt của kênh đang chọn, đổi kênh thì tự bỏ loạt của kênh cũ, nhãn ghi tên kênh; backend liệt kê loạt theo (tên, kênh). `PostsPage.tsx`, `routes/posts.py`. Test posts 12 pass, `tsc` sạch; Playwright trên dữ liệu thật (Mẹ bầu → chỉ "Những ngày đầu có thai", đổi sang Chúng ta hay tò mò → chỉ "hệ mặt trời", loạt đã chọn bị bỏ). **Agent chưa khởi động lại** (đang có job lồng tiếng chạy) → phần backend gom theo kênh có hiệu lực sau lần restart tới. Chưa commit.
- **26/10** — Sửa gấp: giọng Gemini thỉnh thoảng đọc to cả câu lệnh tiếng Anh trước câu thoại (8/41 câu của video "Bài tập vai cổ cho mẹ bầu…"). `tts.py`: đo độ dài so với số chữ, đọc lại tối đa 3 lần (lần cuối chỉ gửi câu thoại), kiểm cả file cache. Test 19 TTS pass. Render lại job `00b00026da64` của người dùng (`voice.wav` cũ đổi tên `voice.leaked.wav`). Agent `start75` (kèm route `/api/running` mới, chưa gắn giao diện). Chưa commit.
- **26/10** — Nút "việc đang chạy" nổi góc dưới phải trên mọi trang (lồng tiếng, xoá chữ AI, ảnh/video/ghép Flow theo clip), bấm về đúng màn hình, báo xong/lỗi khi kết thúc; Lồng tiếng + Xoá chữ mở lại việc qua `?job=`. `routes/running.py`, `BackgroundTasks.tsx`, `DubPage.tsx`, `CleanToolPage.tsx`, `api/client.ts`. Test running 4 pass, `tsc` sạch; thử thật với job lồng tiếng 12,6 s (nút hiện ở trang khác kèm %, bấm về `/tools/dub?job=…`, ẩn ở chính trang đó, xong → "✓ xong") + giả lập trạng thái lỗi. Lần thử đầu job lỗi vì Edge TTS chập chờn ("No audio was received" kể cả với 4 lần thử lại, edge-tts 7.3.1 là bản mới nhất) — lần sau chạy bình thường. Clip/job thử đã xoá. Agent `start76`. Chưa commit.
- **26/10** — Sửa lỗi lồng tiếng video ngang: khung chỉnh vị trí phụ đề luôn dọc 9:16 nên vị trí chỉnh không khớp video thật; giờ khung theo đúng tỉ lệ video (job.width/height hoặc metadata của video), video ngang khung rộng 720 px. `SubPositioner.tsx`, `DubPage.tsx`, `dub.css`. `tsc` sạch; Playwright trên job ngang 1280×720 của người dùng: khung 720×405 (16:9), hộp phụ đề ở 0,67 khớp layout y=0,665. Chưa commit.
- **26/10** — Clip lồng tiếng: Bước 5 có thẻ riêng dẫn về trang Lồng tiếng để chỉnh phụ đề / giọng / bản dịch (trước đó chỉ hiện nút Ghép lại bị khoá). `StepExport.tsx`, `QuicktoolApp.tsx`, `quicktool.css`. `tsc` sạch; Playwright trên clip #21 của người dùng: thẻ hiện, bấm → `/tools/dub?job=00b00026da64` có khung chỉnh. Chưa commit.
- **26/10** — Đăng bài của clip giờ luôn kèm video clip (trang Bài viết lẫn Bước 5), clip chưa ghép thì báo lỗi thay vì đăng chữ không; Bước 5 thêm nút "🚀 Đăng ngay (kèm video)". `scheduler.py`, `routes/posts.py`, `PostsPage.tsx`, `ClipPost.tsx`, `api/posts.ts`. Test schedule + posts 22 pass, `tsc` sạch; Playwright chỉ xem (không đăng thật): bài #26 (clip #21 đã ghép) ghi "kèm video của clip", bài #19 (clip #15 chưa ghép) cảnh báo + khoá nút, Bước 5 clip #21 có nút mới. Agent `start77`. Chưa commit.
- **26/10** — Nút "việc đang chạy" phủ thêm mọi thao tác dài trong trang (~30 loại: viết bài, gói nội dung, đánh giá kênh, đọc link sản phẩm, viết kịch bản, ảnh bìa, OCR, đăng Facebook, đồng bộ…) bằng middleware `_track_long_ops` + `services/op_tracker.py`; trang Bài viết tự mở lại bài AI viết xong khi bạn quay lại. Test running 7 + posts pass, `tsc` sạch; thử thật Playwright với AI thật: bấm viết rồi sang Sản phẩm → nút "AI đang viết bài" → "✓ … xong" → bấm về /posts, bài được mở lại (chưa lưu, không tạo bài thừa). Agent `start78`. Chưa commit.
- **26/10** — Lồng tiếng: thêm **khung video** (thu nhỏ vào giữa, nền mờ/màu, viền) và **nhân vật nhún nhảy** (người mẫu đã lưu hoặc ảnh/GIF tải lên, tròn viền trắng hoặc giữ nguyên, nhún nhảy/nhún/lắc lư, kéo thả) ở khung chỉnh phụ đề, in chung lượt Áp dụng, cả 2 engine. `dub_decor.py`, `dub.py`, `routes/dub.py`, `dub_remotion.py`, `render.mjs`, `DubSubtitles.tsx`, `DecorControls.tsx`, `SubPositioner.tsx`, `DubPage.tsx`. Test dub 26 pass (thêm 5), `tsc` sạch; thử thật trên video thử (in lại 12 s, khung hình đúng) + Playwright (điều khiển, kéo nhân vật). Video thử đã xoá. Agent `start79`. Chưa commit.
- **26/10** — Khung/nhân vật lồng tiếng: thêm **chat với AI** (chỉ làm khung + nhân vật, hiểu mẫu đã lưu; vẽ nền khung và nhân vật bằng Flow, tự tách nền nhân vật), **khung nền ảnh** (AI vẽ hoặc tải lên), **★ Mẫu đã lưu** (lưu / dùng lại / xoá, đồng bộ Neon). `decor_ai.py`, `dub_decor.py` (`cutout`, `local_media`, nền ảnh), bảng `DecorPreset`, `routes/dub.py` (`/decor/*`), `DecorControls.tsx`, `DubSubtitles.tsx`, `render.mjs`. Test decor 10 + dub pass, `tsc` sạch; thử thật với AI + Flow trên trang chỉnh video của người dùng (chỉ xem, không Áp dụng): 44 s, ~2 ảnh Flow. Agent `start81`. Chưa commit.
- **26/10** — Lồng tiếng: thay khung chỉnh cuộn dài bằng **trình chỉnh sửa kiểu CapCut** một màn hình (video ở giữa phát kèm giọng Việt, sửa / kéo phụ đề ngay trên hình, bảng thuộc tính 5 tab, **timeline** `@xzdarcy/react-timeline-editor` với dải hình, khối từng câu kéo / kéo mép, sóng âm giọng, lớp làm mờ / khung / nhân vật; hoàn tác, phím tắt). Backend nhận mốc giờ mới từng câu (`apply_timings`, `voice_key` có mốc giờ) + routes voice/bgm/filmstrip/wave. `dub/editor/*`, `DubPage.tsx`, `dub.py`, `routes/dub.py`; bỏ `SubPositioner.tsx`. Test 978 pass (+1 lỗi 0600 có sẵn), `tsc` sạch. Thử thật Playwright (Chrome): video ngang 10:37 của người dùng — phát 2 s giọng lệch < 0,05 s, chọn câu, sửa trên hình, rút mép câu, kéo phụ đề, hoàn tác về đúng như cũ (**không xuất**); clip mẫu "Remotion test" — sửa chữ + rút câu 2 + chuyển phụ đề lên giữa → xuất 64 s, job lưu đúng chữ / mốc giờ / vị trí, sóng âm vẽ lại. Agent `start83`. Chưa commit.
- **27/10** — Trình chỉnh sửa lồng tiếng: kéo mép phụ đề giờ đổi **độ rộng** (nền dài ra, nhiều chữ hơn một dòng), cỡ chữ chỉ ở thanh Cỡ chữ; **chỉnh riêng từng câu** (vị trí / cỡ / độ rộng) + nút **"⇪ Áp cho tất cả câu"** và "Đồng bộ tất cả theo kiểu chung"; sửa luôn lỗi Remotion gãy câu ngắn thành 3 dòng. `dub.py` (`layout.w`, `Segment.look`, `normalize_look`, `effective_layout`, ASS theo từng câu), `dub_remotion.py`, `DubSubtitles.tsx`, `dub/editor/*`. Test dub 38 pass, `tsc` sạch. Thử thật Playwright (Chrome) trên clip mẫu "Hàng đợi test 1": kéo rộng câu 1 → 96 %, Áp cho tất cả, câu 2 kéo lên riêng → xuất 5 s (giữ giọng), khung hình in đúng: câu 1 dưới, câu 2 ở 53 %; clip mẫu "Remotion test" chỉ xem (không xuất): câu ngắn nằm một dòng. Agent `start85`. Chưa commit.
- **27/10** — Bài viết Facebook: (1) bài đã lên lịch / đã đăng / đến giờ / đăng lỗi có **nhãn ở góc trên phải** thẻ trong "Bài đã lưu" (+ chế độ danh sách, đầu bài đang mở), bấm → Lịch đăng; (2) **"Câu chuyện nhiều kỳ" tách khỏi Kiểu bài** thành 2 radio Không / Có — kiểu bài nào cũng viết thành loạt được (tập vẫn đúng kiểu Mẹo / Review…, không lặp nội dung tập trước). Sửa luôn ô chọn loạt hiện 2 dòng trùng khi loạt có tập chưa gắn kênh. `routes/posts.py` (`_post_schedules`, options bỏ `serial`), `post_writer.py` (`_series_block(kind)`), `PostsPage.tsx`, `ClipPost.tsx`, `posts.css`, `api/posts.ts`. Test posts + schedule + bundle + swipes + hooks 35 pass (thêm 2), `tsc` sạch. Thử Playwright trên dữ liệu thật (chỉ xem, không viết / đăng): nhãn đúng 10 bài có lịch, bài #28 mở ra radio "Có" + nhãn ở đầu. Máy Linux: cài thêm `@xzdarcy/react-timeline-editor` (npm), `package-lock.json` đã trả về. Commit `61560da`.
- **27/10 chiều** — Sửa lỗi viết tiếp loạt truyện bị lẫn sang page khác (Tập 6 loạt hệ mặt trời thành chuyện mẹ bầu): nút viết tập tiếp chỉ dùng cài đặt + sản phẩm của tập cuối (không lấy ý chính / mong muốn ảnh / người đọc trên form), chọn loạt ở form nạp cài đặt của loạt, "Bài đã lưu" tách loạt theo page; prompt thêm luật mỗi page riêng, loạt bám chủ đề + mạch tập trước, bỏ chi tiết lạc đề, mong muốn ảnh chỉ lấy phần hợp page. `post_writer.py`, `PostsPage.tsx`. Test 43 pass, `tsc` sạch. Thử AI thật qua `/api/posts/write` (không lưu, đã claim kết quả để trang không mở lại): 4 lần, lần cuối bài + ảnh Tập 7 đúng Sao Thổ dù brief dính "mẹ bầu". Bài #31 (Tập 6 lạc đề) **vẫn còn** — chờ người dùng quyết xoá / viết lại. Commit `6e08d89`.
- **27/10 tối** — Lồng tiếng, 3 việc người dùng báo: (1) **key Gemini không xoay**: nguyên nhân là quota TTS miễn phí 10 lượt/ngày/key tính theo
  từng model, code nghỉ cả key và không thử model dự phòng → sửa `gemini_api` nghỉ theo (key, model), TTS thử mọi key trên model chính rồi model
  lite, chờ giới hạn phút thay vì lỗi, thông báo rõ số key / lý do / giờ hồi; Cài đặt → Gemini key hiện "hết quota: <model> (10/ngày) · còn X giờ"
  thay vì "tạm nghỉ"; lỗi job ghi "N câu đầu đã đọc xong, render lại chỉ đọc phần còn thiếu". (2) **mỗi link một ô**, dán nhiều link tự tách ô.
  (3) **loạt video**: chờ cả loạt xong mới mở trình chỉnh sửa, select chọn clip, "⇪ Áp cho cả loạt" (kiểu chữ, vị trí, vùng mờ, khung, nhân vật).
  `gemini_api.py`, `tts`/`dub.py`, `routes/dub.py` (`batch_id`, `?batch=`), `running.py`, `DubPage.tsx`, `DubEditor.tsx`, `dub.css`, `editor.css`,
  `GeminiKeysSection.tsx`. Test gemini_api +3 (11), cả bộ 986 pass (+1 lỗi 0600 có sẵn), `tsc` sạch; Playwright loạt 2 clip thật (Edge, đã xoá).
  **Chưa render lại 5 job vũ trụ (giọng Orus) của người dùng** — 1 job lỗi ở câu 42/100, 4 job ở trạng thái chờ sửa: render giờ sẽ dùng model lite
  (10 lượt/ngày/key) cho phần còn thiếu, không đủ cho ~60 + 4×99 câu trong hôm nay; đợi quota hồi (~13 giờ) hoặc đổi giọng Edge. Agent `start87`. Chưa commit.
- **27/10 tối** — Làm giống VieDub phần giọng đọc để khỏi tốn quota Gemini: thêm **VieNeu** (25 giọng Việt miễn phí chạy trên máy qua venv
  pyvideotrans, nhiều câu một lượt nạp model) và **FPT.AI** (cần key, ô dán ở Cài đặt → Gemini key) vào mọi ô chọn giọng (trang Lồng tiếng, Bước 2,
  Bước 5, Người mẫu); ô chọn giọng giờ lấy danh sách từ agent kèm "dùng được / vì sao không". `dub_runner.py` (mode `vieneu`), `tts.py`, `dub.py`,
  `routes/llm.py` (`/fpt-key`), `client.ts`, `VoiceField.tsx`, `StepExport.tsx`, `StepScript.tsx`, `GeminiKeysSection.tsx`. Test tts/dub/llm 84 pass,
  cả bộ 986 pass (+1 lỗi 0600 có sẵn), `tsc` sạch; thử thật: nghe thử VieNeu 23 s, lồng tiếng clip mẫu giọng VieNeu 53 s (clip thử đã xoá), Cài đặt
  hiện ô key FPT. Agent `start88`. Chưa commit.
- **28/10** — Lồng tiếng: **mở lại video đã làm để chỉnh tiếp** (thả file video đã tải từ tool vào trang hoặc chọn ở ô "📂 Chỉnh lại video đã làm" → mở đúng dự án trong trình chỉnh sửa; clip wizard thì sang Bước 5): dấu `flowboard-dub:<id>` trong mp4, dấu vân tay từng lần xuất, so file cũ với video cuối của clip; dự án lưu bản sao lên clip (Neon) nên mất thư mục trên máy vẫn mở lại được, clip cũ tự bù bản sao; chọn file mới mà là video cũ thì gợi ý mở lại; "Gần đây" có "Xem tất cả". `dub.py` (`identify`, `read_tag`, `_tag_file`, `snapshot`, `restore_from_board`, `find_job`, `backfill_snapshots`, `_job_from_dict`), `routes/dub.py` (`/identify`, `?all`), `DubPage.tsx`, `api/dub.ts`, `dub.css`. Test reopen 5 + dub 37, cả bộ 991 pass (+1 lỗi 0600 có sẵn), `tsc` sạch. Thử thật: video cũ "Bài tập vai cổ…" (chưa có dấu) nhận ra bằng vân tay; snapshot 41 câu đã bù lên clip #21; in lại clip mẫu "Hàng đợi test 1" 4 s → file có dấu, nhận ra bằng dấu; Playwright (Chrome): chọn file → mở, thả lên trang → mở (41 câu), chọn làm file mới → hiện gợi ý → mở, video lạ → báo không nhận ra, "Xem tất cả" 14 video. Agent `start89`. Chưa commit.
- **28/10** — Lồng tiếng: ô "Gần đây" chỉ hiện 5 video mới nhất, "Xem tất cả (N)" mở hộp thoại danh sách đầy đủ (tìm kiếm, lọc theo trạng thái có số đếm, bảng tên / trạng thái / thời lượng / số câu / ngày làm, phân trang 10 dòng). `DubJobsDialog.tsx`, `DubPage.tsx`, `dub.css`, `api/dub.ts`, `routes/dub.py` (`brief`, `limit`), `dub.py` (`started_at` trong `public()`). Test reopen 6 + dub 16 pass, `tsc` sạch; Playwright (Chrome) trên dữ liệu thật: thẻ 5 dòng, hộp 10 + 4 dòng 2 trang, lọc Xong 6, tìm "vai cổ" 1 → Mở vào trình chỉnh sửa 41 câu, Esc đóng. Agent `start90`. Chưa commit.
- **28/10** — Hộp "Xem tất cả" của Lồng tiếng có **xoá khỏi danh sách** (từng dòng 🗑, chọn nhiều / cả trang / cả mục đang lọc, thanh xác nhận): chỉ xoá dòng + thư mục làm việc tạm, video đã xuất, video gốc và clip giữ nguyên; video vẫn mở lại được bằng cách thả vào trang. `dub.delete_jobs`, `POST /api/dub/jobs/delete`, `DubJobsDialog.tsx`, `DubPage.tsx`, `api/dub.ts`, `dub.css`. Test reopen 7 (thêm 1: xoá giữ video + clip, job đang chạy bị từ chối, vẫn mở lại được), `tsc` sạch. Playwright (Chrome) trên 3 mục thử tạo riêng (đã xoá hết qua UI): 🗑 một dòng → Huỷ → xoá; chọn cả trang → xoá 2; 14 mục thật không đổi. Agent `start91`. Chưa commit.
- **28/10** — Sửa lỗi lồng tiếng link Douyin chết giữa chừng vì giọng Edge từ chối ngẫu nhiên + tăng tốc: thử lại nhanh 10 lần, đọc 8 câu một lúc, câu vẫn trượt thì chờ 30 s đọc lại (3 vòng), khớp độ dài song song, tách nhạc nền chạy cùng lúc với bước giọng. Dọn các video lồng tiếng lỗi theo yêu cầu (job Enceladus lỗi Edge, job đã dừng, job thử của mình — chỉ thư mục làm việc; video gốc 35 MB tải 2 lần còn trong media, một bản được dùng lại). `tts.py` (`ATTEMPTS`, chờ), `dub.py` (`_prefetch_edge`, `EDGE_PARALLEL`, `VOICE_ROUNDS`, `fit` song song, `_separate_bgm` + luồng), test `test_dub_editor.py` (+2), cả bộ 995 pass (+1 lỗi 0600 có sẵn), `tsc` sạch. Thử thật bằng Playwright đúng đoạn share Douyin người dùng dán: **156 s từ lúc bấm đến khi mở trình chỉnh sửa**, 89 câu, không lỗi, clip #30 "Lao xuống Enceladus - mặt trăng băng của Sao Thổ" (để lại cho người dùng). Agent `start94`. Chưa commit.
- **28/10** — Sửa phụ đề chạy trước giọng (trễ TB 3 s, tối đa 5,7 s ở video Enceladus): phụ đề theo đúng chỗ giọng trên track (`follow_voice`), cắt im lặng Edge đệm ở đầu/cuối câu, câu được dùng cả khoảng lặng sau nó trước khi phải tăng tốc (`line_window`), bản dịch có giới hạn từ mỗi câu (`word_budget`). `dub.py`, test `test_dub_editor.py` (+3), cả bộ 998 pass (+1 lỗi 0600 có sẵn). In lại video Enceladus của người dùng (clip #30, 22 s, không gọi Edge lại — giọng cũ để ở `voice.before-sync.wav` trong thư mục job): phụ đề–giọng lệch 0,00 s, giọng so với lời gốc trễ 0 s. Thử dịch có giới hạn ở chế độ xem lại (job thử đã xoá). Agent `start95`. Chưa commit.
- **28/10** — Cài công cụ cho skill JunOps (`junops-edit-capcut` / `-youtube`: faster-whisper, `av==16.0.1`, bỏ alias python của Windows Store), học kiểu chữ + 4 tiếng từ CapCut của người dùng. Rồi làm menu **✂️ Edit auto CapCut** (`/tools/capcut`): video lồng tiếng / clip đã ghép / video tải lên → dự án CapCut thật (video nền không phụ đề, giọng + nhạc track riêng, phụ đề kiểu TikTok theo kiểu chữ của người dùng, AI chọn chữ quan trọng → chữ nhấn mạnh + zoom + tiếng hiệu ứng, cắt khoảng lặng cho video tự quay), khối Yêu cầu + Hướng dẫn, danh sách dự án + đưa video đã xuất từ CapCut về clip. `services/capcut_draft.py`, `services/capcut_auto.py`, `routes/capcut.py`, `dub.render_clean_video`, `dub_runner transcribe … words`, `running._capcut_items`, `api/capcut.ts`, `pages/CapcutPage.tsx`, `capcut.css`, sidebar + route. Test `test_capcut.py` 10, cả bộ 1008 pass (+1 lỗi 0600 có sẵn), `tsc` sạch. Thử thật bằng Playwright (Chrome): học kiểu chữ (đúng vai Phụ đề / chữ nhấn mạnh / Title), tạo dự án từ video Enceladus 3:35 trong 28–32 s (216 phụ đề, 15 chữ nhấn mạnh + zoom + tiếng, 4 tiếng xoay vòng, giọng + nhạc); sửa 3 lỗi lúc thử (tiếng hiệu ứng chỉ lấy tiếng < 2,5 s nên lặp một tiếng, một dòng phụ đề rơi sang track chữ nhấn mạnh, ngày làm video lồng tiếng hiện sai). Dự án **"Flowboard thử — Lao xuống Enceladus…"** để trong CapCut cho người dùng mở xem — **chưa mở trong CapCut thật**. Agent `start100`. Chưa commit.
- **28/10** — Ghi kế hoạch phase sau của Edit auto CapCut vào Việc đang dở (7 mục). Sửa lỗi đăng bài #33 lên page "Chúng ta hay tò mò" bị Facebook từ chối: không phải token hết hạn mà video clip 152 MB gửi một lần → 413; video > 20 MB giờ tải chia nhỏ (start / transfer / finish), thông báo 413 rõ ràng. `facebook_publish.py`, test schedule +2 (13 pass). Theo tài liệu Graph API Page videos (upload_phase vẫn còn). Agent `start101`. Chưa đăng lại thật. Chưa commit.
- **28/10** — Đăng lên Facebook chọn được **Bài viết hoặc Reel** (`Schedule.fb_format`, `publish_reel` qua `video_reels` + rupload, `reel_problem` 3–90 s, `/api/schedule/reel-check`, `FormatPicker` ở hộp lên lịch / kéo thả / Đăng ngay trang Bài viết + Bước 5, nhãn 🎬 Reel ở Lịch đăng). Test schedule 15 + posts/bundle/channels/capcut pass, `tsc` sạch; Playwright: bài #33 (clip 3:34) → chọn được Reel, hiện lời nhắc "tài liệu API ghi tối đa 90 giây" (lúc đầu chặn cứng > 90 s, người dùng chỉ ra app Facebook đăng được Reel 3:00 → đổi thành nhắc), nút thành "🚀 Đăng Reel ngay" (không đăng gì). Migration chạy trên Neon. Agent `start103`. Chưa đăng Reel thật — chưa biết API có nhận Reel > 90 s không. Chưa commit.
- **28/10** — Edit auto CapCut: người dùng đã tự dùng trang (22:44 dự án từ video lồng tiếng Enceladus, 22:46 dự án "download" từ video tải lên — Whisper nghe tiếng Trung nên phụ đề tiếng Trung) và đã mở + sửa dự án tool tạo trong CapCut (đổi phụ đề thành chữ đen nền vàng) → CapCut mở được dự án do tool ghi. Sửa `capcut_auto.learn`: giữ kiểu chữ đã chọn theo **nhãn** (font · cỡ · màu) chứ không theo số t1, t2… (kiểu mới trong dự án mới hơn làm xê dịch số). Test `test_capcut.py` 11. Đồ "Yêu thích" của CapCut không học được (xem Việc đang dở mục 8). Agent `start104`. Chưa commit.
- **28/10** — Edit auto CapCut: **lồng tiếng trước (tuỳ chọn)** ngay trong trang (video mới → Bước ③ giọng + nhạc nền → lồng tiếng như menu Lồng tiếng rồi tự tạo dự án CapCut), **lấy video theo link** (`/api/capcut/fetch`), **"— Không dùng —"** cho 3 ô kiểu chữ. `capcut_auto.py` (`_start_dub`, `_wait_dub`, `fetch_link`), `routes/capcut.py` (`DubSpec`, `/fetch`), `CapcutPage.tsx` (`DubCard`, ô link, tab Video mới), `api/capcut.ts`, `capcut.css`. Test 14 pass, `tsc` sạch. Thử thật Playwright (Chrome): 25 s đầu video tiếng Trung của người dùng → lồng tiếng giọng Hoài My + giữ nhạc → dự án CapCut trong **135 s** (Whisper 12 s, dịch 12 s, giọng Edge ~97 s cho 10 câu — Edge lại từ chối nhiều, ghép 3 s, AI chọn chữ 6 s): 25 phụ đề, 2 chỗ nhấn, giọng + nhạc 2 track; dự án / job / clip #31 thử đã xoá. Agent `start105`. Chưa commit.
- **28/10** — Edit auto CapCut: **xuất phụ đề .srt** (đọc từ dự án CapCut, có chữ đã sửa) + tuỳ chọn **chỉ tạo .srt** để nhập bằng Captions → Import (phụ đề thật: kéo 1 câu cả loạt đi theo — chữ thường do tool ghi thì không). `capcut_draft.read_subtitles/to_srt`, `capcut_auto.project_srt`, `GET /api/capcut/projects/{id}/srt`, `CapcutPage.tsx`. Test 15 pass, `tsc` sạch; tải thật .srt của dự án "test edit auto capcut" (202 dòng) qua API và nút trên giao diện (Playwright). Chưa thử Import trong CapCut. Agent `start106`. Chưa commit.
- **28/10** — Lồng tiếng có **✨ Nhấn chữ quan trọng** (chữ to bật lên + zoom nhẹ + tiếng hiệu ứng ở chỗ AI chọn, ~1 chỗ / 12 s; tab mới trong editor, hàng timeline, xem trước, chọn lại / thêm / dời / xoá từng chỗ, áp cho cả loạt) — ý từ đường CapCut đưa vào thẳng công cụ lồng tiếng để video hàng loạt cũng có. `services/key_moments.py` (tách từ `capcut_auto`), `services/sfx.py` (tiếng tổng hợp bằng ffmpeg), `dub.py` (`highlights`, `Emph` ASS, `zoompan`, `audio_mix`), `dub_remotion.py` + `DubSubtitles.tsx` + `render.mjs`, `routes/dub.py` (`/highlights/pick`), editor (`Inspector` tab ✨, `EditorStage`, `EditorTimeline`, `DubEditor`, `DubPage` áp loạt), `api/dub.ts`. Test `test_dub_highlights.py` 8, cả bộ 1025 pass (+1 lỗi 0600 có sẵn), `tsc` sạch. Thử thật Playwright (Chrome) trên bản lồng tiếng 25 s của video tiếng Trung người dùng: AI chọn 2 chỗ (6 s), thêm 1 chỗ, xuất ffmpeg 9 s (giữ giọng) → khung hình có chữ vàng "DIMETHYL SULFIDE" trên phụ đề, hình zoom, tiếng to hơn 4 dB tại chỗ nhấn; Remotion 24 s cũng ra (sửa 2 lỗi: fade câu ngắn, chữ dài bị cắt). Job / clip thử đã xoá. Agent `start107`. Chưa commit.
- **28/10** — Commit `e693e41` + push: mọi việc 27–28/10 chưa commit ở trên (mở lại video lồng tiếng, hộp Xem tất cả + xoá, Edge ổn định / nhanh, phụ đề khớp giọng, VieNeu + FPT, quota Gemini, Edit auto CapCut + lồng tiếng trước + .srt, Facebook chia nhỏ video + Reel, nhấn chữ quan trọng). Skill JunOps vào `.claude/skills/` (bỏ `__pycache__` + `du_lieu/` trong .gitignore).
- **29/10** — Nhận bản cập nhật skill `junops-edit-capcut` từ tác giả (người dùng dán vào trên máy Linux): gộp luôn phần YouTube (mục B + `youtube_junops.py`, `PHONG_CACH_YOUTUBE.md`), dẫn dắt 6 chặng, luật cắt ghép mới `references/LUAT_CAT_GHEP.md` (mốc cắt từ sóng âm, nghỉ 0,01 / 0,05 / 0,1 s — YouTube 0,5 s, phụ đề tắt lúc im và ở chỗ ghép, tăng giọng, chữ nhấn không đè mặt), script mới `song_am.py`, `quet_dau_vao.py`, `mg_junops.py` (4 mẫu motion graphic vẽ bằng code). File dán từ Windows có CRLF → đổi về LF (`junops_capcut.py` thật ra không đổi nội dung) + `.gitattributes` `.claude/skills/** text=auto eol=lf` để lần dán sau không ra diff cả file. **Chưa làm**: xoá `junops-edit-youtube` (trùng, luật nghỉ cũ 0,3 s — chờ người dùng quyết); mang luật mới vào Edit auto CapCut của Flowboard (cắt bằng sóng âm, phụ đề tắt lúc im, tăng giọng, chữ nhấn né mặt bằng YuNet) — người dùng hẹn làm ở máy nhà. Đã commit + push (29/10, máy Linux).
- **29/10** — Màn "Clip của tôi": chọn từng clip / **Chọn tất cả** / **🗑 Xoá N clip đã chọn** (bấm 2 lần, toast kết quả); trước đó chỉ clip chưa ghép mới tick được (nên nút "⬇ Tải N clip đã ghép" không bao giờ hiện). `QuicktoolApp.tsx` (`Library`: `toggleAll`, `deletePicked`), `quicktool.css` (`.qt-clip-bulk`). `tsc` sạch; Playwright (Chrome) với 2 clip tạm: chọn tất cả → "đã chọn 5", bỏ chọn, tick 2 clip tạm → xoá 2 lần bấm → còn đúng 3 clip thật. Chưa commit.
- **29/10** — Trang Lồng tiếng: khung tiến độ của một video đổi thành **vòng tròn tiến độ to ở giữa** quanh logo ⚡ (`quicktool/dub/ProgressRing.tsx` + khối `.qt-dubring` trong `dub.css`, dùng ở `DubPage.tsx`): cung tăng theo %, màu đi theo % cam → xanh lá (50 %) → xanh dương (100 %) bằng hue HSL 20° → 142° → 217° (`ringColor`), chờ đến lượt = cung quay, lỗi = vòng + logo đỏ kèm câu lỗi, nút Dừng giữ nguyên. Chỉ frontend — không động agent / job đang chạy. Bảng loạt nhiều video vẫn là danh sách thanh ngang (chưa đổi). Lỗi chỉ hiện vòng đỏ khi job chưa có câu nào (có câu thì mở trình chỉnh sửa như cũ). `tsc` sạch; Playwright (Chrome) đọc job đang chạy thật + giả lập 8/35/66/97 %, chờ, lỗi trong trình duyệt của mình (không POST). Chưa commit.
- **29/10** — Sửa lồng tiếng đứng mãi ở 71 % (job "Tù túng trong Hệ Mặt Trời…", 332 câu): 8 lượt gọi Edge treo không hạn → mỗi lượt có hạn giờ (`tts.edge_attempt_timeout`, `asyncio.wait_for`), lưu bản dịch ra `job.json` ngay khi dịch xong, job bị cắt ngang mà có câu thì mở lại để "Xuất lại". `tts.py`, `dub.py` (`_prepare`, `_job_from_dict`). Test TTS + dub 49 pass (thêm 3). Cứu job của người dùng: chép 332 câu từ agent đang chạy vào `job.json` (bản cũ để ở `job.before-hang.json`), restart (người dùng đồng ý) → `start109` → `POST …/render`: qua được giọng đọc (330/330) nhưng chết ở ghép giọng vì WinError 206 (xem Bẫy) → ghép theo nhóm 48 câu (`TIMELINE_CHUNK`, `_timeline_part`), test +1, restart `start110`, xuất lại: **xong trong ~1 phút** (giọng lấy hết từ cache), video 651 s 1280×720, tiếng đều ~−17 dB ở phút 0:30 / 5:00 / 10:00. Chưa commit.
- **29/10** — Lồng tiếng: **nhiều vùng mờ** (thêm / chọn / xoá từng vùng, OCR đặt một vùng cho mỗi dải chữ gốc) + **"Khung xuất"** (Gốc / 9:16 / 16:9 / 4:3 / 3:4 / 1:1 / 4:5 × nền mờ / viền đen / cắt cho đầy) — sân khấu đổi ngay theo khung, xuất ra đúng định dạng (ffmpeg + Remotion). `dub.py` (`blurs`, `canvas`, `canvas_size`, `canvas_filter`, `video_filter(source=)`), `dub_remotion.build_spec`, `DubSubtitles.tsx`, `api/dub.ts`, `dub/editor/FormatBar.tsx` (mới), `EditorStage`, `Inspector`, `EditorTimeline`, `DubEditor`, `editor.css`. Test `test_dub_canvas.py` 8 + dub/remotion pass, `tsc` sạch. Thử thật Playwright (Chrome) trên job tạm từ clip mẫu 25 s 576×1024: 2 vùng mờ, sân khấu đúng tỉ lệ (1:1 = 1,000, 4:3 = 1,335, 16:9), xuất ffmpeg 16:9 nền mờ ra 1024×576 (4 s, ảnh khớp xem trước); Remotion 4 s ra 1024×576 nền mờ + 2 vùng mờ (lần đầu ra nền đen vì `build_spec` bỏ khoá — đã sửa). Job + clip tạm đã xoá. Agent `start112`. Chưa commit.
- **29/10** — Lồng tiếng: **"📱 Xem trên"** — xem video sau khi xuất trong màn hình mô phỏng của TikTok / Reels / Shorts / bảng tin Facebook / Instagram / YouTube (video vừa khung hay bị cắt 4:5, nút / mô tả của app che chỗ nào) + cảnh báo phụ đề / nhân vật bị che hoặc bị cắt. `platforms.ts`, `DeviceChrome.tsx` (mới), `EditorStage.tsx`, `FormatBar.tsx`, `DubEditor.tsx`, `editor.css`. `tsc` sạch. Thử Playwright (Chrome) trên clip "Lao xuống hành tinh K218B" của người dùng (chỉ xem, không xuất): TikTok / FB bảng tin / YouTube / Shorts, đổi khung 16:9 trên TikTok ("video ngang nhỏ ở giữa"), kéo phụ đề sát đáy → báo bị phần mô tả che. Không đổi backend. Chưa commit.
- **29/10** — Sửa lỗi Bước 5 của clip lồng tiếng hiện + tải video cũ sau khi "Xuất lại" (người dùng báo phụ đề / vùng mờ lệch giữa màn chỉnh và file tải về — file mới thật ra đúng, trang clip giữ dữ liệu cũ): mở lại clip đang là clip hiện tại thì đọc lại từ agent. `QuicktoolApp.tsx`. `tsc` sạch; Playwright (chỉ xem): Bước 5 clip #38 → trang chỉnh → "Mở clip →" đọc lại clip, video = `c22a7c…` (bản 22:06, khung hình đã kiểm: phụ đề sát đáy, vùng mờ che chữ Trung). Chưa commit.
- **29/10** — Bước 5: hàng nút "📅 Lên lịch đăng" + **"✍️ Viết bài & đăng"** (khác màu) — nút sau mở trang Bài viết Facebook với clip gắn sẵn (`/posts?clip=`: video clip, kênh, sản phẩm điền sẵn; mở bài cũ của clip nếu có) để dùng đủ tuỳ chọn rồi Đăng ngay / Reel / Lên lịch. Lúc đầu làm hộp "🚀 Đăng ngay" (`ScheduleDialog mode="now"`), người dùng muốn đủ tuỳ chọn nên đổi. `StepExport.tsx`, `PostsPage.tsx`, `PostEditor.tsx`, `ScheduleDialog.tsx`, CSS. `tsc` sạch; Playwright (clip #38, chỉ xem): sang `/posts`, kênh "Chúng ta hay tò mò" tự chọn, video = bản xuất mới nhất `6cb4f3…`, 0 lệnh ghi. **Chưa đăng thật.** Chưa commit.
- **29/10** — Git: gỡ remote `upstream` (repo gốc), xoá nhánh `worktree/brave-forest-5ad8`, `worktree/calm-field-8091` (đã nằm trong main) và `worktree-agent-aad8…` (4 commit FB-001/004/007/008 đã có trong main qua `4fbcc11`; hash cũ `c085e13` nếu cần lấy lại). Còn `main` ↔ `origin/main`. Cập nhật bảng repo ở `D:\codes\CLAUDE.md` (máy kia cần sửa tay file đó — không nằm trong git; máy kia cũng tự `git remote remove upstream`).
- **29/10** — Rà + test trong lúc người dùng bận: quét 16 trang chính bằng Playwright → sửa **vòng render vô hạn** ở trình chỉnh sửa lồng tiếng (do phần "📱 Xem trên" vừa làm, `EditorStage.tsx`); **Lịch đăng nhanh hơn** (`scheduler._decorate` đọc token Facebook một lần mỗi kênh thay vì mỗi lịch: list 2 s → 0,55 s, trang 11 s → 5,6 s); trang Bài viết khi gắn clip: ô "Kèm theo" khoá + ghi "(đã có video clip)", brief về 0 ảnh (video clip được đăng, ảnh AI vô ích). Cả bộ test: 1142 pass, 9 lỗi môi trường đã biết (test_auth tier, test_llm_gemini agy, test_llm_secrets 0600, test_muse2api / test_provider_jobs file://). Trình chỉnh sửa job 10:51 "mở" ~19 s theo Playwright là do trình duyệt tải trước video 370 MB + WAV (API đều 10–130 ms) — chưa đổi. Agent `start113`. Chưa commit.
- **29/10** — Trang Bài viết: lựa chọn **"Đăng dạng: Bài viết / Reel" lên form** (khối ①, khi bài có video) — Reel thì AI viết chú thích Reel ngắn (`post_writer.REEL_CAPTION`, `brief.fb_format`) và thanh đăng chọn sẵn Reel. `post_writer.py`, `PostsPage.tsx`, `api/posts.ts`, test `test_posts.py` (+1, 14 pass). Playwright với AI thật trên clip #38 (không lưu, không đăng, đã claim kết quả). Agent `start114`. Chưa commit.
- **29/10** — Người dùng **đăng Reel thật thành công** (clip 10:51 → facebook.com/reel/…, slot #16): bỏ lời nhắc "API ghi tối đa 90 giây" (`facebook_publish.reel_warning`, `FormatPicker`). Trang Bài viết dọn theo góp ý: dạng Bài viết / Reel một nguồn (`brief.fb_format`) + một chỗ chọn (khối ①) — sửa lỗi sau khi đăng Reel trang nhảy về "Bài viết"; thanh đăng gọn hơn (một dòng tóm tắt, sau khi đăng ưu tiên "Xem Reel trên Facebook ↗"); Lên lịch nhận sẵn dạng đã chọn. `PostsPage.tsx`, `FormatPicker.tsx`, `ScheduleDialog.tsx`, `facebook_publish.py`, test schedule + posts 29 pass, `tsc` sạch. Agent `start115`. Chưa commit.
- **29/10** — Lồng tiếng: **"★ Mẫu chỉnh sửa"** — lưu toàn bộ kiểu (phụ đề, vùng mờ, khung xuất, khung, nhân vật, nhấn chữ) thành mẫu có tên, áp cho clip khác một bấm, đặt mẫu mặc định để video lồng tiếng mới dùng luôn (ô chọn ở trang Lồng tiếng). `dub.py` (`normalize_look_preset`, `start_job(layout=, highlights=)`), `routes/dub.py` (kind look, `/decor/presets/default`, `look_preset_id`), `LookPresets.tsx` (mới), `DubEditor.tsx`, `DubPage.tsx`, `api/dub.ts`, `editor.css`. Test `test_dub_look_presets.py` 2 + dub 34 pass, `tsc` sạch; Playwright (Chrome) trên clip K218B: lưu mẫu → thành mặc định → áp lại → form chọn sẵn; mẫu thử đã xoá. Agent `start116`. Chưa commit.
- **29/10** — Giấu nút "Viết Tập N+1" của loạt truyện (`NEXT_EPISODE_BUTTONS = false`, `PostsPage.tsx`; lúc đầu giấu luôn ô "Câu chuyện nhiều kỳ" — người dùng muốn giữ, đã trả lại). `tsc` sạch. Commit + push toàn bộ việc 29/10 (`931913b`, rồi commit sửa này).
- **30/10** — Lồng tiếng: **"📚 Import từ thư viện"** — thả / chọn file .txt / .md (nội dung gì cũng được) → lấy ra mọi link, lưu thư viện (bảng `DubLink`), mỗi link biết đã lồng tiếng chưa (khớp job + clip cũ theo khoá video, cả link rút gọn v.douyin.com), tick rồi "🎙 Lồng tiếng N link" → hàng đợi thư viện tự đẩy từng video vào hàng đợi lồng tiếng (một chạy + một chờ). `services/dub_links.py`, `routes/dub.py` (`/links*`), `dub.FEEDER` trong `_pump`, `routes/running.py`, `main.py`, `DubLinksDialog.tsx`, `DubPage.tsx`, `api/dub.ts`, `dub.css`. Test `test_dub_links.py` 7 + các bộ dub / running / capcut 100 pass, `tsc` sạch. Thử thật Playwright (Chrome) với file .md 7 link: nhận đúng 2 link đã lồng tiếng (K2-18b, Enceladus qua link rút gọn), 2 link mới tick sẵn, hỏi khi chọn link đã làm, 2 link example.com xếp hàng → feeder chạy lần lượt (lỗi tải, đúng như dự kiến) → sau đó chặn hẳn link không phải TikTok / Douyin / YouTube / IG / FB / X (trạng thái "Không phải video"). Link + job thử đã xoá, thư viện trống. Cài lại Playwright vào scratchpad (bản cũ đã mất). Agent `start119`. Commit + push 30/10.
- **30/10** — **🔄 Đồng bộ từ Facebook** (mục 1–4 người dùng chọn): đọc lại bài của Page đã kết nối (30 ngày) → bài đăng tay hiện trên Lịch đăng (thẻ "🌐", chỉ xem), bài tool tự đăng không bị lặp, bài trong "Bài đã lưu" mà đã đăng tay có nhãn "🌐 Đăng tay trên FB" và mở ra chỉ xem (không sửa), lịch chưa đăng của bài đó trên cùng page tự bỏ qua; tự đồng bộ 30 phút / khi mở trang / nút bấm. `services/fb_sync.py`, bảng `FbPost`, `routes/schedule.py`, `routes/posts.py` (`fb_manual`), `main.py`, `SchedulePage.tsx`, `PostsPage.tsx`, `PostEditor.tsx` (`readOnly`), `api/schedule.ts`, `api/posts.ts`, CSS. Test `test_fb_sync.py` 3 + schedule / posts / channels / bundle / running 49 pass, `tsc` sạch. Thử thật (Graph API chỉ đọc, page "Chúng ta hay tò mò"): 61 bài / 30 ngày, 7 bài tool tự đăng nhận đúng, 54 bài đăng tay hiện trên lịch; Playwright: thẻ + khung chi tiết, nút đồng bộ; bài thử #38 (cùng chữ với bài đăng tay, lùi ngày tạo) → nhãn + chỉ xem đúng, rồi đã xoá và đồng bộ lại (không còn liên kết). Commit + push 30/10.
- **30/10** — Kênh "Chúng ta hay tò mò" kết nối lại bằng token mới có thêm **`read_insights`** (token người dùng của app "Chúng ta hay tò mò", không hết hạn, quyền đọc dữ liệu tới 28/01/2027; thấy 3 page: Chúng ta hay tò mò, Tạm hóa chú hai Đù, Dev). Dò thật tên số liệu bài / Reel đọc được (ghi ở mục Đồng bộ từ Facebook). Chưa làm phần hiển thị số liệu. Không đổi code.
- **30/10** — **Số liệu Facebook (mục 5)**: mỗi lần đồng bộ đọc thêm lượt xem / người xem / lượt bấm / ❤ / 💬 / ↗ của mọi bài và lượt phát / thời gian xem / tỉ lệ còn xem của Reel (2 lệnh gọi mỗi page), hiện trên thẻ Lịch đăng (cả bài tool tự đăng lẫn bài đăng tay), thẻ / dòng "Bài đã lưu", và khung chi tiết (ô số liệu + biểu đồ "Còn bao nhiêu % người xem" cho Reel, rê chuột xem từng điểm, bảng). `fb_sync.py` (`_item`, `_reel_stats`, `stats_for_*`), cột `FbPost.stats` + migration, `scheduler.row(stats)`, `routes/posts.py` (`fb_stats`), `FbStats.tsx`, `SchedulePage.tsx`, `PostsPage.tsx`, `api/*`, CSS. Test `test_fb_sync.py` 4 + liên quan 50 pass, `tsc` sạch. Thử thật: K2-18b Reel 33 lượt phát, xem TB 15,5 s, ở 6 s còn 82 %; Tập 4 bài ảnh 17 lượt xem; Playwright thẻ + khung chi tiết + biểu đồ + Bài đã lưu, không lỗi console. Commit + push 30/10.
- **30/10** — Dòng số liệu Facebook to + nổi hơn theo góp ý ("chìm quá"): mỗi số thành chip 14px chữ sáng, emoji màu, số chính nền xanh ngọc; trên lịch chip nhỏ hơn và ẩn số 0 phụ. `FbStats.tsx`, `schedule.css`, `SchedulePage.tsx`. `tsc` sạch, Playwright xem lịch + Bài đã lưu. Commit + push 30/10.
- **30/10** — Thẻ clip chỉ có video (lồng tiếng, CapCut, tải lên) giờ có ảnh: cắt một khung gần đầu video đã ghép (`services/poster.py`, `GET /api/media/{id}/poster`, `clipThumbUrl`) ở thư viện, Hôm nay, Kênh, Lịch đăng; "Clip của tôi" phân trang tối đa 3 hàng (số cột đo theo màn hình); tiêu đề trang to gấp 3, màu cam. Test `test_poster.py` 2 + boards / media 25 pass, `tsc` sạch. Thử thật: poster 2 clip lồng tiếng (17–38 KB, đúng khung hình); Playwright với 20 clip giả (chặn API trong trình duyệt thử): 6 cột → trang 1 = 17 clip + "Clip mới", 3 cột → 8 clip / trang; tiêu đề 39px cam ở Clip / Bài viết / Lịch đăng. Commit + push 30/10.
- **30/10** — Tiêu đề trang về 18px (39px quá to, tên clip dài xuống 2 dòng), một dòng có "…" khi dài; `.dx` lồng tiếng `100vh − 106px`. `quicktool.css`, `editor.css`. Commit + push 30/10.
- **30/10** — Dọn dấu vết tác giả gốc + đổi tên **DFlow**: xoá `.github/FUNDING.yml`, `.omc/` (ghi chú / quy trình phát hành gốc), `docs/release-notes/`, `docs/assets/` (logo, ảnh / video quảng bá, **QR tài trợ**), `SponsorDialog.tsx` + 427 dòng CSS tài trợ, link nhóm Facebook ở Cài đặt → Thông tin, link `crisng95` trong comment / docs; README gốc (1.000+ dòng) thay bằng README ngắn tiếng Việt; kiểm tra bản mới trỏ `hoangduytn1703/flowboard`. Git: chỉ `origin` = repo của người dùng, chỉ `main`, không tag / stash / worktree. Đổi tên hiển thị: tab trình duyệt, sidebar (logo + "DFLOW"), đăng nhập, màn hình tải, thông báo, extension "DFlow Bridge" (manifest, popup — **cần Reload extension**), câu báo lỗi backend; favicon + `frontend/public/` (logo 256, favicon.ico 16–64, 32, 180, 192 cắt từ logo người dùng gửi); "© 2026 DFlow · Dev DuyNH" trên dòng phiên bản. `tsc` sạch, test tab-import / shopee / channel-page / capcut / flow-sdk / products / tiktok 150 pass; Playwright: đăng nhập, sidebar, favicon 200, tab Thông tin. Commit + push 30/10.
- **30/10** — Sidebar: bỏ nhãn "Quicktool" cạnh DFLOW; chân sidebar gom vào `.qt-sidebar__foot` (credit + tài khoản / Quét extension / © + phiên bản chung một khối, có padding trên dưới, thu nhỏ ở màn ≤ 860 / 760 px); mục "Bài viết Facebook" dùng icon chữ f trắng nền xanh Facebook (`.qt-nav__icon--fb`, SVG). `QuicktoolSidebar.tsx`, `quicktool.css`. Đo Playwright: menu không bị cắt ở cao 1000 / 900 / 800 / 720 px. Commit + push 30/10.
- **30/10** — Sửa tiêu đề trang mất dấu chồng ("VIẾT" → "VIÊT"): do `overflow: hidden` + `line-height: 1.3`, không phải font; giờ `line-height: 1.6` + đệm 3px trên. `.dx` lồng tiếng `100vh − 116px`. Dò 8 trang bằng Playwright: không còn chữ dấu chồng nào bị cắt. Commit + push 30/10.
- **30/10** — Chốt lộ trình với người dùng, ghi mục **Lộ trình** ở trên: Phase A trợ lý AI "làm hết từ một câu" (Premium) → Phase B app desktop Tauri 2 (agent Python sidecar, Chrome chỉ còn extension + tab Flow) → Phase C chuẩn bị bán (API cho kho trung tâm, gói Pro / Premium, bản quyền, thanh toán). Chưa code.
- **30/10** — **Phase A, bản demo A0: 🤖 Trợ lý AI** — nút chat tròn kéo thả góc dưới phải (tránh nút "việc đang chạy"), chat lưu DB, AI hiểu yêu cầu và chạy việc nền `create_model` (Flow vẽ chân dung → lưu Người mẫu đã lưu), không vẽ mặt người thật. `services/assistant.py`, `routes/assistant.py`, bảng `AssistantMessage` / `AssistantTask`, `routes/running.py`, `AssistantWidget.tsx`, `assistant.css`, `api/assistant.ts`. Test assistant 4 + running 7 pass, `tsc` sạch. Thử thật bằng Playwright + Flow: người mẫu "Bảo Ngọc" (#9) tạo + lưu trong 40 s. Commit + push 30/10.
- **30/10** — Trợ lý AI: chặn câu ngoài lề / chào hỏi bằng code trước khi gọi AI (không tốn token) + dặn AI chỉ đáp một câu với câu lọt qua. `assistant.quick_reply`. Test assistant 6 + running 7 pass. Commit + push 30/10.
- **30/10** — Trợ lý AI thêm kỹ năng + kế hoạch nhiều bước: thêm sản phẩm từ link, viết bài / tập tiếp của loạt (kèm ảnh AI), lên lịch / tự đăng, tạo clip có kịch bản, tạo người mẫu; hiểu tên kênh / loạt / sản phẩm gõ sai; hỏi lại khi thiếu / giờ đã qua; việc tự đăng công khai chờ "✅ Làm luôn". `services/assistant.py` (viết lại), `routes/assistant.py` (confirm / cancel), `routes/running.py`, `AssistantWidget.tsx`, `api/assistant.ts`, `assistant.css`. Test assistant 9 + running / posts / schedule / fb_sync / products 48 pass, `tsc` sạch. Thử thật bằng câu của người dùng (không bấm xác nhận). Commit + push 30/10.
- **30/10** — Trợ lý AI: nút ở tin nhắn kết quả (Mở bài viết / Mở Lịch đăng…) nằm một hàng dưới ảnh, nhỏ (12,5px, bo tròn), xen màu cam / xanh (`.dfa-link--a|b`), bỏ mũi tên. Người dùng đã bấm "✅ Làm luôn" cho kế hoạch #2: Tập 7 "Hành tinh lăn nghiêng trên quỹ đạo" đã viết (kèm ảnh) + lên lịch 12:00 30/10 tự đăng. `AssistantWidget.tsx`, `assistant.css`. Commit + push 30/10.
- **30/10** — **📲 Thêm vào tin** khi đăng bài / Reel / clip lên Page (tin ảnh hoặc video, video dài tự cắt 60 giây đầu, tin lỗi không ảnh hưởng bài), lựa chọn ở hộp Lên lịch, hộp kéo thả, Đăng ngay, thanh đăng trang Bài viết; trợ lý AI hiểu "thêm vào tin". Sửa lỗi app dựng các trang hai lần lúc khởi động (mất `?post=`, `?assistant=`… và thao tác vừa bấm). Quy ước mới: tính năng hợp thì dạy luôn cho trợ lý. `facebook_publish.publish_story`, `scheduler._story`, `Schedule.fb_story` + migration, `routes/schedule.py`, `assistant.py`, `FormatPicker.tsx` (`StoryToggle`), `ScheduleDialog.tsx`, `DropTimeDialog.tsx`, `PostsPage.tsx`, `SchedulePage.tsx`, `App.tsx`. Test schedule / assistant / fb_sync / posts / running / channels 59 pass, `tsc` sạch; Playwright: chip + hộp lên lịch (không đăng thật). Commit + push 30/10.
- **30/10** — Tin cho bài chỉ có chữ (người dùng hỏi: Facebook cho đăng tin chữ mà): API Page không có tin chữ nên tool vẽ ảnh tin 9:16 từ đoạn mở đầu (`services/story_card.py`, `scheduler._story(message, page_name)`), mở khoá chip ở trang Bài viết. Test `test_schedule.py` (+1, sửa 1) + assistant 27 pass, `tsc` sạch; xem 2 ảnh mẫu (dấu tiếng Việt đúng). Chưa đăng thật. Commit + push 30/10.
- **30/10** — Rà soát một vòng (trừ lồng tiếng), chỉ log không sửa: 15 mục ở đầu "Việc đang dở" — nặng nhất là bài #39 bị đăng 2 lần lên Page (Đăng ngay + lịch tự đăng), 2 máy cùng chạy có thể đăng trùng, 5 ảnh media bị cụt đuôi (có ảnh bài Tập 1), "Mở" bài đã lưu không cuộn lên, đồng bộ Facebook làm đứng request. Playwright 20 trang ở 1400 / 1024 px + đo API; test backend 1178 pass / 1 fail có sẵn. Chưa commit.
- **30/10** — Sửa 4 mục nặng của rà soát: (1) không đăng trùng — đăng xong thì lịch `planned` khác của cùng bài + cùng page → `skipped` (`scheduler._skip_twins`), vòng tự đăng không đăng lại bài đã lên page (`publish(auto=True)` + `_already_posted`); (2) giữ chỗ lịch nguyên tử `_claim` (status `posting`, `UPDATE … WHERE status IN planned/failed/skipped`) để 2 máy không cùng đăng, `posting` quá 60 phút → failed; (3) ảnh cụt trên B2 (xem Bẫy); (4) "Mở" bài đã lưu cuộn lên đầu. Frontend: trạng thái "đang đăng…". Test schedule / file_store / media / watermark / fb_sync / assistant / posts 70 pass, `tsc` sạch. Chưa viết test riêng cho claim / twins / repair_images. Commit + push 30/10.
- **30/10** — Sửa lồng tiếng hàng loạt chết ở bước dịch ("claude CLI exited 1", người dùng hỏi có phải dùng quota Claude không — đúng: dịch đi qua AI của Cài đặt = Claude CLI gói Max, hết lượt là lỗi): thêm **dịch bằng Google miễn phí như VieDub** làm mặc định (Google gtx → Microsoft dự phòng), AI thành lựa chọn và lỗi thì tự chuyển Google; lỗi Claude CLI giờ ghi rõ lý do. `services/free_translate.py`, `dub.py`, `routes/dub.py`, `dub_links.py`, `claude_cli.py`, `DubPage.tsx`, `api/dub.ts`. Test `test_free_translate.py` 9 + các bộ dub / links / running / capcut / video_fetch 136 pass, `tsc` sạch. Thử thật: 185 câu của video lỗi c27a1c… dịch bằng Google 10,5 s. Lỗi Douyin "không trả dữ liệu" là do Douyin chập chờn (cùng link lúc được lúc không) — không làm đường trình duyệt ẩn vượt chặn như VieDub. Agent `start120`. Commit + push 2/11.
- **31/10** — Lồng tiếng, 3 việc người dùng xin: (1) **nền tuỳ chỉnh** cho Khung xuất (màu, lưới kiểu khung sọc như ảnh mẫu, ảnh hoặc video tải lên — video nền tự lặp; cỡ + vị trí video) ở trình chỉnh sửa, cả ffmpeg lẫn Remotion; (2) **✂️ Cắt** video đã xuất thành nhiều clip (thủ công start–end, chia đều theo độ dài, hoặc AI gợi ý đoạn trọn ý + tiêu đề), mỗi phần là một clip có Bước 5; (3) **"💬 Chỉ chèn phụ đề"** — giữ tiếng gốc, bỏ đọc giọng / tách nhạc: video 25 s xong 17,6 s. Sửa luôn lỗi wizard đẩy về `/clips` khi mở clip vừa tạo phía agent (ref thay state). `dub.py`, `dub_split.py` (mới), `dub_remotion.py`, `routes/dub.py`, `routes/running.py`, `dub_links.py`, `canvasGeom.ts` (mới), `DubSubtitles.tsx`, `render.mjs`, `FormatBar.tsx`, `EditorStage.tsx`, `CutPane.tsx` (mới), `Inspector.tsx`, `DubEditor.tsx`, `DubPage.tsx`, `QuicktoolApp.tsx`, `StepExport.tsx`, `api/dub.ts`, CSS. Test `test_dub_bg_sub_split.py` 18, cả bộ 1196 pass (9 lỗi môi trường Windows đã biết: auth tier, agy, 0600, muse), `tsc` sạch; Playwright + Remotion + AI thật (xem Chỗ cần biết). Agent `start122`. Commit + push 2/11.
- **31/10 tối** — Sửa 2 ý người dùng báo: (1) nền giờ thay đúng **phần đen ngoài video trên TikTok** — khung xuất có hàng "Video" (Phủ kín / Nguyên hình / Cắt 4:3…), chọn nền khi đang "Phủ kín khung 4:3" thì video giữ hình 4:3, đặt giữa khung 9:16 trên nền đó (`canvas.inner` / `cut`, `inner_crop`, `FormatBar` 3 hàng); (2) chỉ chèn phụ đề **chọn ngôn ngữ**: tiếng Việt, đúng lời gốc (video tiếng Anh → phụ đề tiếng Anh) hoặc 11 thứ tiếng khác, đổi được ngay trong trình chỉnh sửa (`sub_lang`, `POST …/subtitles`), cắt câu chữ Hán đúng chiều rộng. `dub.py`, `free_translate.py`, `routes/dub.py`, `dub_links.py`, `canvasGeom.ts`, `DubSubtitles.tsx`, `FormatBar.tsx`, `EditorStage.tsx`, `Inspector.tsx`, `DubEditor.tsx`, `cues.ts`, `platforms.ts`, `DubPage.tsx`, `api/dub.ts`, `editor.css`. Test lồng tiếng 101 pass (+8 mới), `tsc` sạch; Playwright + ffmpeg + Remotion thật (xem Chỗ cần biết). Job / clip thử đã xoá. Agent `start123`. Commit + push 2/11.
- **1/11** — Lồng tiếng: giọng chọn lần cuối thành **giọng mặc định** theo tài khoản (`dubVoice`, cả trang Lồng tiếng, Edit auto CapCut) + chọn giọng ngay trong hộp **Thư viện link** trước khi "🎙 Lồng tiếng N link". `store/settings.ts`, `DubPage.tsx`, `DubLinksDialog.tsx`, `CapcutPage.tsx`, `dub.css`. Chỉ frontend (không khởi động lại agent — đang có video lồng tiếng chạy). `tsc` sạch; Playwright: chọn Hải Đăng trong hộp → form đổi theo, prefs tài khoản lưu `vieneu:Hải Đăng`, trình duyệt mới (xoá localStorage) mở ra vẫn Hải Đăng. Commit + push 2/11.
- **1/11** — Sửa: chuyển clip "chỉ phụ đề" (câu đang là tiếng gốc) sang "Lồng tiếng Việt" thì nút Xuất lại video bị khoá chờ người dùng tự bấm "Dịch sang tiếng Việt" → giờ tự dịch ngay khi chuyển (toast "Đã dịch N câu…"), nút xuất mở luôn; trang Lồng tiếng luôn mở ở "Lồng tiếng Việt" (bỏ nhớ `flowboard.dub.mode`). `DubEditor.tsx`, `DubPage.tsx`. `tsc` sạch; Playwright trên clip 25465e5804d3 của người dùng (chỉ chuyển, không xuất — gọi `POST …/subtitles`, không lưu gì): 234 câu dịch xong, nút "✓ Xuất lại video (đọc lại giọng)" bấm được; form mở ở Lồng tiếng dù localStorage cũ ghi "sub". Commit + push 2/11.
- **1/11** — Bước 4 có khung **"🎙 Giọng đọc & phụ đề khi ghép"** (giọng + nghe thử; phụ đề: Không / ffmpeg 3 kiểu / Remotion 3 kiểu — Bước 5 cùng ô chọn, "⚡ Tạo video tự động" dùng luôn; giọng mặc định = giọng yêu thích); **xoá logo Gemini ✦ trên video** chạy ngầm khi video Flow về máy + lúc ghép (cả sao sót từ ảnh cảnh); sửa Remotion lỗi khi cổng 3000 bị app khác chiếm. `video_watermark.py` (mới), `media.py`, `video_export.py`, `tts.py`, `processor.py`, `render.mjs`, `JoinOptions.tsx` (mới), `StepMedia.tsx`, `StepExport.tsx`, `generation.ts`, `board.ts`, `GeminiMarkSection.tsx`, CSS. Test `test_clip_stamp_subs.py` 6, cả bộ 1211 pass (9 lỗi môi trường Windows đã biết), `tsc` sạch. Thử thật: 4 clip của clip #61 sạch logo (ảnh so trước / sau), ghép thử bằng request riêng (không đụng clip #61) với Hải Đăng + Remotion: 60 s, khung hình không còn sao, phụ đề hộp vàng; Playwright Bước 4 / 5 không lỗi. Agent `start125`. Commit + push 2/11.
- **7/11** — Tìm lý do clip áo khoác có quạt (link → video) mất hơn 30 phút: ghép 60 fps chạy một nhân trên cả clip ghép (8 phút 49 s), giọng VieNeu nạp model mỗi cảnh, nút Ghép bấm 2 lần chạy 2 lượt, agent chết theo phiên Claude Code. Sửa: 60 fps từng clip song song + lưu lại, đọc giọng trước một lượt, không đọc lại VieNeu, chặn export trùng (agent + nút). `video_export.py`, `routes/requests.py`, `store/quicktool.ts`, `StepExport.tsx`. Test `test_export_speed.py` 6 + export / tts / requests / drama 87 pass, `tsc` sạch. Đo thật bằng request riêng (không gắn clip #67): 179 s → ghép lại 29 s (trước 618 s). Agent `start130`. Commit 7/11.
- **7/11** — **🤖 Tự động đăng theo lịch** cho Facebook Page trong trang Bài viết: đặt ngày + giờ cố định, agent tự soạn trước (Claude CLI mặc định, lỗi thì Gemini), vẽ ảnh Flow, lên lịch tự đăng; tới giờ chưa có bài thì bỏ khung; máy tắt lúc tới giờ thì bỏ lỡ (không đăng bù); tạm dừng huỷ bài chưa đăng; nút lấy cài đặt từ form viết; trợ lý AI có kỹ năng `auto_post`. `services/autopilot.py`, `routes/autopilot.py`, bảng `AutoPlan` / `AutoRun`, `llm/registry.use_ai`, `main.py`, `routes/running.py`, `assistant.py`, `api/autopilot.ts`, `posts/AutoPilot.tsx`, `autopilot.css`, `PostsPage.tsx`. Test autopilot 10 + assistant / running / posts / schedule / fb_sync / llm 200+ pass, `tsc` sạch. Thử thật an toàn (khung 6 ngày sau, đã dừng + xoá lịch, bài, slot thử). Agent `start131`. Commit 7/11.
- **7/11** — Commit `9ef7dae` (tốc độ ghép + tự động đăng). Rồi theo yêu cầu "làm kỹ, cần hiệu quả": **xoá logo video làm lại** (sao ảnh cảnh nhấp nháy — đo độ đậm + cỡ từng khung, dán mảnh nền sạch từ khung sao tắt; sao gốc ghim, không dò lệch; logo Flow đọc từng khung ở vị trí cố định khi mép cảnh che; màu trừ theo hình nhoè; bộ nhớ đệm có phiên bản) — đo trên 20 clip Omni thật + ảnh phóng to, 4 clip nhấp nháy từ 8–53 % khung còn sao trắng → 0 %, clip áo khoác cảnh 4 hết bỏ sót logo; thử rồi bỏ khớp hình theo clip và màu W ≠ 255. **60 fps làm ngầm khi từng cảnh về** (`smooth_prewarm.py`, hook worker, routes `/api/boards/{id}/smooth60`, pref `smooth60`, ô ở Bước 4 + 5 có dòng trạng thái). `video_watermark.py`, `video_export.py`, `worker/processor.py`, `routes/export_extras.py`, `store/settings.ts`, `store/quicktool.ts`, `JoinOptions.tsx`, `StepExport.tsx`, `api/client.ts`, CSS. Test mới `test_video_watermark_twinkle.py` 6 + `test_smooth_prewarm.py` 5, test cũ xoá logo / ghép / media pass, `tsc` sạch. Chưa commit.
- **7/11 khuya** — Xoá logo: kiểm video ghép cuối của clip áo khoác (4 cảnh, 60 fps, ghép 10,5 s khi đã làm mượt sẵn; làm mượt ngầm 217 s): sao nhấp nháy hết, còn vết chữ V sẫm ở đầu nhọn logo Flow cảnh 2 (sàn tối / tường sáng) do đọc độ đậm 0,347 thay vì ~0,31 → thêm `_pair_alpha` (đọc theo cặp điểm hai bên viền, chỉ cho logo Flow), `CLEAN_VERSION` 4. Đo cặp điểm trên ~30 clip; ép tay 0,28/0,30/0,32 trên cảnh 2 để chọn. Test xoá logo + làm mượt 22 pass. Người dùng bảo dừng test, tự test.
- **7/11 tối** — Clip review **quay như người thật** + lựa chọn **🔇 Không lời**: tìm hiểu cách viết prompt UGC cho Veo / Flow (hướng dẫn Veo 3.1 của Google, các bộ prompt UGC, cách làm video TikTok Shop / review không lời) → `services/clip_style.py` (luật chung), viết lại 8 mẫu clip + gợi ý bối cảnh, `script_tailor` (biết giới tính, nơi dùng thật, không lời), `product_link` / `reference_video` / `narration` theo cùng luật, "Viết lại chuẩn" / "Tạo lại theo yêu cầu" giữ kiểu điện thoại; sửa người mẫu nam bị trang điểm kiểu nữ (`character.ts` thêm bản `male`) và chân dung tham chiếu bỏ "studio". Không lời: ô chọn ở hộp Clip mới, `quicktool.voiceless`, Bước 2 bật / tắt, Bước 4–5 ẩn giọng / phụ đề, tạo tự động bỏ viết lời, trợ lý AI `create_clip {voiceless}`. Test `test_clip_style.py` 8, cả bộ 1109 pass / 2 skip (bỏ 5 file lỗi môi trường Windows đã biết), `tsc` sạch. Thử AI thật (chữ, không lưu) cho áo điều hoà: có lời / không lời. **Chưa chạy qua Flow; agent của người dùng (cửa sổ của họ) cần khởi động lại để có backend mới.**
- **7/11 khuya** — Lồng tiếng: **tên riêng bị Google dịch sai / đọc sai** (người dùng báo "Anyinstein"): Whisper nhận tiêu đề video làm `hotwords`, sau khi Google dịch một lượt Gemini (key miễn phí) sửa tên riêng trong câu + ghi cách đọc tiếng Việt, giọng đọc theo bảng tên (phụ đề vẫn ghi tên gốc), trình chỉnh sửa có khung "🔤 Tên riêng" + nút "✨ AI rà tên riêng" cho clip đã làm. `services/dub_names.py`, `dub.py` (`speech`, `voice_key`, `_check_names`, `needs_name_check`, `Job.names`), `dub_runner.py` (hotwords), `routes/dub.py` (`/jobs/{id}/names`, `RenderBody.names`), `op_tracker`, `api/dub.ts`, `dub/editor/NamesPanel.tsx`, `DubEditor`, `Inspector`, `cues.ts`, `editor.css`. Test `test_dub_names.py` 8 + mọi test lồng tiếng 162 pass, `tsc` sạch. Thử AI thật read-only trên clip "Chương cuối cùng…" (813 câu, 43 s, 28 câu sửa). Agent của người dùng cần khởi động lại.
- **7/11 khuya** — README viết lại: bảng "Cần gì cho nhu cầu nào" (lõi / clip Flow / AI CLI / Gemini key / giọng đọc / Remotion / yt-dlp / lồng tiếng + xoá phụ đề AI (pyvideotrans) / CapCut / Facebook Page / tự động đăng / cloud), cài phần lõi Windows (`start.ps1 -FlowProjectId -Plan`) và Linux, cài thêm theo nhu cầu (đường dẫn model Whisper / spleeter / LaMa / VieNeu, `FLOWBOARD_ERASE_*`), lỗi hay gặp. Commit + push toàn bộ việc 7/11.
- **7/11 khuya** — README: uv là bước cài khuyên dùng (tự tải Python 3.11, lệnh `winget install` từng gói), cách đặt `UV_CACHE_DIR` sang ổ khác (máy nhà: cache uv 10,7 GB ở `%LOCALAPPDATA%\uv\cache` trên ổ C chỉ còn 13 GB trống; venv của agent và pyvideotrans nằm ổ D nên uv đã phải chép file thay vì hardlink — cache trên C chỉ là bản thừa, xoá được; Python do uv tải ở `%APPDATA%\uv\python` (0,13 GB) là `home` của cả 2 venv — đừng dời). Đã làm trên máy nhà: `UV_CACHE_DIR=D:\uv-cache` (biến môi trường User), `uv cache clean` xoá 10,7 GB (ổ C 13 → 22,6 GB trống), 2 venv vẫn chạy. Máy khác chưa đặt.
- **7/11 khuya** — README viết lại cho người không rành công nghệ (người dùng: "đối tượng dùng không phải ai cũng rành công nghệ, dev"): mục lục, DFlow làm được gì, chuẩn bị tài khoản (GitHub được mời vào kho riêng tư, Flow Pro / Ultra, Claude, Gemini key, tên đăng nhập DFlow), bảng nhu cầu → cần cài gì, 9 bước cài Windows có "gõ gì / sẽ thấy gì" (mở PowerShell, `winget install -e --id … --accept-*`, dời cache uv, Claude Code, `gh auth login` + `gh repo clone … D:\DFlow`, lấy mã project Flow, `powershell -ExecutionPolicy Bypass -File .\start.ps1 -FlowProjectId … -Plan …`, nạp extension, đăng nhập + chọn AI + Gemini key), lối tắt Desktop (WScript.Shell, icon favicon.ico), cập nhật (`git pull`), cài thêm theo nhu cầu (yt-dlp, VieDub, CapCut, token Page, dùng chung dữ liệu), bảng lỗi thường gặp, phần dev. Kèm: `config._load_dotenv` đọc `utf-8-sig` (Notepad cũ thêm BOM làm mất khoá đầu, test mới trong `test_config_dotenv.py`), `start.ps1` in "DFlow" / "DFlow Bridge" thay tên cũ, Cài đặt thêm tab 🤖 AI viết. `tsc` sạch.
- **7/11 khuya** — **App desktop bản đầu** (người dùng: "build app luôn, triển luôn"; chọn GitHub Actions + bản cho mình và người tin cậy): agent chế độ app (`config.HOME/APP_MODE/ENV_FILE`, `agent/packaging/dflow_agent.py` + `dflow-agent.spec`), agent tự phục vụ giao diện (`web_ui.py`), Cài đặt → 🖥 Máy này (`routes/app.py`, `services/app_env.py`, `MachineSection.tsx`: gói Flow áp ngay, dòng cloud, thư mục dữ liệu, VieDub, extension, mở thư mục, khởi động lại), vỏ Tauri `desktop/` (agent ngầm, trang chờ, khay, một instance, link ra trình duyệt), workflow `.github/workflows/desktop.yml`, README thêm "Cách 1 — file cài đặt". Test `test_app_mode.py` 5 pass, `tsc` sạch; bản PyInstaller chạy thật trên cổng phụ. Commit + push, chạy workflow trên GitHub.
- **7/11 khuya** — App desktop: dữ liệu mặc định **ngoài ổ C** (`D:\DFlowData` hoặc ổ cố định khác còn ≥ 5 GB, nhớ trong `home.txt`; máy chỉ có ổ C mới dùng `%LOCALAPPDATA%\DFlowData`), hồ sơ WebView2 theo cùng thư mục, trang chờ hiện đúng đường dẫn log. `desktop/src-tauri/src/main.rs`, `desktop/ui/index.html`, README. Chưa build thử (CI).
- **7/11 khuya** — **Bộ cài app đầu tiên build thành công** trên GitHub Actions (run 42378801551, 13 phút, sau 1 lần sửa E0597): `DFlow_0.1.0_x64-setup.exe` 185 MB, đã tải về máy nhà `D:\DFlow-Setup\`. Chưa cài thử (người dùng tự cài). Actions báo Node 20 bị ép lên Node 24 cho checkout / setup-node / upload-artifact / setup-uv v4–v6 — chỉ là cảnh báo.
- **7/11 khuya** — App 0.1.1: hộp hỏi riêng `components/Dialogs.tsx` thay 41 chỗ `window.confirm` / `window.prompt` (WebView2 của app không hiện hộp gốc → "Đăng ngay" không đăng được); `tsc` sạch. Phát hiện qua `agent.log` của app: cả phiên không có `POST /api/posts` / `/api/schedule`. Người dùng tự xoá 16 bài đã lưu trên Neon lúc 21:59 (cố ý). Ảnh cũ 404 = file chưa lên B2 (xem Bẫy). Build lại bộ cài qua `gh workflow run desktop.yml`.
- **7/11 khuya** — App tự cập nhật (0.1.2): updater plugin + 2 lệnh Rust, capability cho trang 127.0.0.1:8434, thanh "Có bản DFlow mới" + mục phiên bản ở 🖥 Máy này, repo công khai `dflow-releases` (đã tạo), workflow ký + đăng `latest.json` khi đẩy tag `v*`, khoá ký ở `%USERPROFILE%\.flowboard`. README cập nhật. `tsc` sạch. Người dùng tự chạy script đặt 3 secret (Claude bị chặn ghi secret); push `main` + tag `v0.1.2` → run 42395099764 lỗi (thiếu `serde_json`, xem Bẫy) → thêm vào `Cargo.toml`, gắn lại tag `v0.1.2` vào commit sửa. Run 42395718864 xong (~13 phút): release v0.1.2 trên dflow-releases có `DFlow_0.1.2_x64-setup.exe` (186 MB) + `latest.json` (chữ ký, 2 khoá platform); đã tải về `D:\DFlow-Setup\` cho người dùng cài tay.
- **8/11** — 👥 Quản lý tài khoản (chỉ akiragosho, vai trò `admin` trên kho trung tâm): tạo tài khoản (lên cloud ngay khi máy có Neon), đặt lại mật khẩu, khoá / mở khoá, ghi chú, đăng xuất mọi máy; mọi tài khoản có "Đổi mật khẩu" ở chân sidebar (đăng xuất các máy khác); bỏ đăng ký tự do. `accounts.py` (cột `role` / `disabled` / `note` + ALTER cho kho cũ), `routes/account_admin.py`, `routes/account.py`, `main.py`, `api/account.ts`, `ChangePasswordDialog.tsx`, `UserChip.tsx`, `AccountsPage.tsx`, `accounts.css`, `QuicktoolSidebar.tsx`, `QuicktoolApp.tsx`, `styles.css`. Test `test_account_admin.py` 7 + login / cloud / app / assistant / running 37 pass, cả bộ 1161 pass / 2 skip (bỏ các file lỗi môi trường Windows đã biết), `tsc` sạch; Playwright trên agent tách riêng (tạo, khoá → đăng nhập bị từ chối, mở khoá, tài khoản thường không thấy menu + đổi mật khẩu, đặt lại mật khẩu → bị đăng xuất). **Chưa chạy trên Neon thật** — lần đầu agent / app bản mới mở kho trung tâm sẽ ALTER thêm 3 cột (không mất gì). Commit + phát hành trong v1.5.0.
- **8/11** — Gộp số phiên bản (người dùng thấy sidebar ghi v1.4 mà app là 0.1.2): mọi chỗ thành **1.5.0** (`frontend/package.json` + lock, `agent/pyproject.toml`, `tauri.conf.json`, `Cargo.toml`, `desktop/package.json` + lock); workflow thêm bước "Version check (tags only)" ngay sau checkout. App 0.1.2 vẫn nhận 1.5.0 là bản mới. Commit `eb64292` + tag `v1.5.0` → run 42399834928 xong, release v1.5.0 trên dflow-releases (bộ cài 186 MB + `latest.json`). **Lần cập nhật thật đầu tiên** (app 0.1.2 → 1.5.0 bằng nút "Cập nhật ngay") chờ người dùng bấm thử.
- **8/11** — Nút cập nhật của app báo "Command dflow_check_update not allowed by ACL" (người dùng chụp màn hình trên 0.1.2): trang của agent là origin remote với Tauri, lệnh riêng phải có quyền khai báo → `desktop/src-tauri/build.rs` (`AppManifest::commands`) + `capabilities/ui.json` thêm `allow-dflow-check-update` / `allow-dflow-install-update`, gitignore `permissions/autogenerated/`; mọi số phiên bản lên **1.5.1**. 0.1.2 / 1.5.0 không tự cập nhật được → người dùng cài tay 1.5.1. Chỉ kiểm được trên CI + app thật (không có Rust trên máy). Commit `337b77e` + tag `v1.5.1` → run 42402033076 xong (build nhận quyền mới, không lỗi), release v1.5.1 trên dflow-releases; bộ cài tải về `D:\DFlow-Setup\` cho người dùng cài tay. Chờ người dùng xác nhận nút "Kiểm tra cập nhật" chạy.
- **8/11** — 1.5.2: trang đăng nhập có "🌐 Dán dòng kết nối trước" cho máy mới cài (tài khoản người quản lý tạo nằm trên Neon nên trước đó không đăng nhập được), `GET/POST /api/app/connect` (mở, chỉ khi chưa nối cloud, thử kết nối + kiểm có bảng tài khoản rồi mới lưu, app tự khởi động lại); README sửa trình tự cài app (dán dòng → đăng nhập → đổi mật khẩu), GitHub chỉ cần cho Cách 2, Claude Code không cần Node / Git (theo tài liệu chính thức), "trước 1.5.1 chưa tự cập nhật", Mục 6.6 cấp tài khoản, 3 dòng lỗi mới. Mọi số phiên bản 1.5.2. Test app_mode 7 + account 15 pass, `tsc` sạch; Playwright trên agent tách riêng (khung hiện, dòng sai báo lỗi không lộ mật khẩu, luồng khởi động lại giả lập phản hồi). Commit `8e99f48` + tag `v1.5.2` (người dùng: "up lên 1.5.2 đi") → run 42406327799 xong, release v1.5.2 trên dflow-releases. Lần cập nhật thật đầu tiên bằng nút: 1.5.1 → 1.5.2 — chờ người dùng bấm.
- **8/11** — Trang hướng dẫn cho người mới cài app: **https://hoangduytn1703.github.io/dflow-releases/** (GitHub Pages của kho công khai `dflow-releases`, nhánh main, `index.html`; người dùng không muốn dùng Claude Docs / artifact — artifact thử đã bị họ xoá). Bản gốc: `docs/cai-dat-dflow.html` trong repo này; sửa xong chép đè `index.html` của `dflow-releases` (clone `git@github.com:hoangduytn1703/dflow-releases.git`) rồi push. Nút tải tự lấy bản mới nhất qua API GitHub (`releases/latest`), mất mạng thì giữ link 1.5.2 ghi sẵn — phát hành bản mới **không cần sửa trang**. README của `dflow-releases` + đầu README repo này trỏ tới trang. Đã kiểm bằng Playwright: 1280 px sáng + 400 px tối, không tràn ngang (sửa lỗi `.extra div` ăn vào khung lệnh).
- **8/11** — 📦 Gói & tính năng (admin thêm / bớt / đổi tên gói, tick tính năng, gán gói từng tài khoản, gói mặc định) + ⬆ Nâng cấp bằng chuyển khoản (chip gói + nút nâng cấp ở sidebar, màn các gói có giá, QR VietQR tự dựng + nội dung mặc định "{username} - {plan}" + số tiền, "Tôi đã chuyển khoản" → yêu cầu chờ, admin duyệt thủ công → lên gói). Agent: `plans.py`, `billing.py` (bảng `account_upgrade`), cột `account_user.plan`, middleware chặn route theo gói, vòng tự đăng / tự động dừng khi mất quyền, routes `/api/admin/plans|billing`, `/api/account/upgrade*`. Frontend: `lib/features.ts`, `lib/qr.ts` (npm `qrcode` 1.5.4), `FeatureGate.tsx`, `UpgradeDialog.tsx`, `PlansEditor.tsx`, `BillingEditor.tsx`, ẩn nút theo gói ở sidebar / Bước 5 / Hôm nay / Kênh / Sản phẩm / Bài viết / clip tự động / trợ lý. Test `test_plans.py` 6 + `test_billing.py` 4 + account / app 22 pass, cả bộ 1173 pass / 2 skip (bỏ các file lỗi môi trường Windows đã biết), `tsc` sạch; Playwright trên agent tách riêng (VIP không thấy Lồng tiếng → nâng cấp Premium → QR đúng số tiền + nội dung → gửi yêu cầu → admin duyệt → có lại Lồng tiếng; bỏ tick Mẫu đang hot → người dùng mất mục đó). Chưa push (người dùng test trên web trước). **Chưa chạy trên Neon thật**: lần đầu agent mới mở kho trung tâm sẽ thêm cột `plan`, bảng `account_upgrade`, khoá `plans` (gói mặc định Premium = mọi tài khoản cũ giữ đủ tính năng). **Chưa quét QR bằng app ngân hàng thật** — người dùng quét thử QR mẫu sau khi cài. Người dùng test trên web (start.ps1, start135.log) báo bấm tick / thêm gói làm cả trang cuộn + lộ nền đen → sửa (xem Bẫy), kiểm lại bằng Playwright: thêm 3 gói + tick 4 ô, trang không cuộn.
- **8/11 tối** — Theo góp ý chip sidebar xấu: **trang "Tài khoản của tôi"** (`/account`: gói + hạn dùng thử + ⬆ Nâng cấp gói, tính năng của gói, thông tin cá nhân / tên hiển thị, đổi mật khẩu, lịch sử giao dịch, đăng xuất máy khác / Thoát), chip sidebar chỉ còn avatar + tên + gói (bấm mở trang) và nút **Thoát**; **gói Dùng thử** có sẵn (luôn đầu, mặc định cho tài khoản mới, không bán, hạn 3 / 7 / 14 / 30 ngày, hết hạn = không đăng nhập được, admin bấm **Gia hạn**); **đổi thứ tự gói** (◀ ▶). `accounts.py` (cột `plan_expires`, `profile`, `expired`, `set_profile`, `fill_null_plans`), `plans.py`, `billing.py`, `routes/account.py`, `routes/account_admin.py`, `AccountPage.tsx` + `account.css`, `UserChip.tsx`, `PlansEditor.tsx`, `AccountsPage.tsx`, `UpgradeDialog.tsx`, `api/account.ts`, `QuicktoolApp.tsx`, CSS; bỏ `ChangePasswordDialog.tsx`; README + `docs/cai-dat-dflow.html` chỉ chỗ đổi mật khẩu mới (bản trên dflow-releases chưa cập nhật — chép khi push). Test `test_plans.py` 10 + billing / account / app / running / assistant / schedule / autopilot 80 pass / 2 skip, `tsc` sạch; Playwright trên agent tách riêng (xem Chỗ cần biết). Khởi động lại agent web (`start136.log`) — lần đầu mở Neon sẽ thêm 2 cột + thêm gói Dùng thử vào `plans` đã lưu (tài khoản cũ giữ gói đang có). Chưa push (chờ người dùng test trên web).
- **8/11 tối** — **Thời hạn gói + bảng giá có giá gốc**: mỗi gói trả phí bán nhiều thời hạn (1 / 3 / 6 tháng, 1 / 2 năm, vĩnh viễn) với giá bán + giá gốc gạch ngang (khách thấy -%, giá / tháng, "Tiết kiệm nhất", ngày hết hạn trước khi chuyển khoản); gia hạn cộng nối tiếp thời gian còn lại; quản trị gán gói + thời hạn cho từng tài khoản ở hộp "Gói & thời hạn"; gói trả phí hết hạn cũng không đăng nhập được. `plans.py` (`TERM_MONTHS`, `plan_end`, `add_months`, `term_label`), `billing.py` (`terms`, `normalize_terms`, `account_upgrade.months`), `accounts.py`, `routes/account.py`, `routes/account_admin.py`, `UpgradeDialog.tsx`, `BillingEditor.tsx`, `PlanAssignDialog.tsx` (mới), `AccountsPage.tsx`, `AccountPage.tsx`, `UserChip.tsx`, `api/account.ts`, CSS. Test billing 6 + plans / account / app / running / assistant / schedule / autopilot 82 pass / 2 skip, `tsc` sạch; Playwright trên agent tách riêng (xem Chỗ cần biết). Khởi động lại agent web (`start137.log`). Chưa push (chờ người dùng test trên web).
- **8/11 tối** — Sửa theo ý người dùng: **thời hạn + giá là một phần của gói** (VIP 1 tháng 49k · 1 năm 490k · Vĩnh viễn 980k), sửa ở "📦 Gói & tính năng" và lưu chung nút Lưu gói (trước đó tôi để bảng giá ở khung Thanh toán); giá đã nhập ở settings thanh toán tự dời vào gói; hạn từng tài khoản giữ nguyên (theo thời hạn đã mua) — hộp "Gói & thời hạn" giờ liệt kê thời hạn gói bán kèm giá, thời hạn khác, và **📅 chọn ngày hết hạn bất kỳ** (`expires_on`). `plans.py` (`terms`, `clean_terms`, `normalize_terms`, di trú), `billing.py`, `routes/account_admin.py` (`expires_on`, `_end_of_day`), `TermsEditor.tsx` (mới), `PlansEditor.tsx`, `BillingEditor.tsx`, `PlanAssignDialog.tsx`, `AccountsPage.tsx`, `api/account.ts`, CSS. Test billing 7 + liên quan 83 pass, `tsc` sạch; Playwright trên agent tách riêng. Khởi động lại agent web (`start138.log`). Chưa push.
- **8/11 tối** — Trang Quản lý tài khoản + Tài khoản của tôi **dàn hết bề rộng** (bỏ `max-width`); quét layout bằng Playwright 14 cỡ cửa sổ (1920 → 600 px) × 4 màn (quản lý, hộp gói & thời hạn, tài khoản của tôi, màn nâng cấp) → sửa 3 bảng tràn khung (tài khoản ~1366 px, giá ~1024 px, lịch sử ~1024 px) bằng container query + cột thao tác 350 px (nút không xuống dòng, cột thẳng hàng); lần cuối 56/56 sạch, không lỗi console. Rồi **rà bảo mật** (người dùng: "đảm bảo crack app không dễ"): vá ngay bản cài luôn bắt đăng nhập + không tạo admin mật khẩu mặc định (`config.PACKAGED`), phiên đăng nhập lưu băm SHA-256, CORS chỉ cho trang của app + extension + chặn lệnh ghi từ trang web lạ; ghi lỗ lớn còn mở (dòng Neon = toàn quyền) + 2 hướng B / C vào Việc đang dở. `accounts.css`, `account.css`, `config.py`, `accounts.py`, `main.py`, test `test_security.py` (3). Khởi động lại agent web (`start139.log`) — phiên cũ hết hiệu lực, phải đăng nhập lại. Chưa push.
- **8/11 khuya** — **Hướng B: chữ ký số quyền dùng + agent dịch Nuitka** (người dùng: "làm B luôn đi", sau khi rà bảo mật; miễn phí): `licensing.py` (Ed25519; khoá riêng chỉ ở máy nhà `%USERPROFILE%\.flowboard\dflow-license.key` — **người dùng cần sao lưu**), giấy phép từng tài khoản (`account_user.license`) + bảng gói / thanh toán / `min_app` ký số và kiểm đúng bản đã lưu, kho ký lần đầu khi agent có khoá khởi động (quản trị trước), chỉ máy có khoá đổi quyền (403 ở máy khác), băm mật khẩu có pepper (`dflow2`, gắn tên), phiên HMAC gắn id, chặn duyệt nâng cấp sai giá, khách chỉ thấy QR khi STK + bảng giá đã ký, `__version__`; CI dịch `flowboard` bằng Nuitka thành `.pyd` + chạy thử agent; trang quản trị có banner 🔑 / 🔒 + chip "chưa ký / chữ ký sai / bị sửa tay". `licensing.py` (mới), `accounts.py`, `plans.py`, `billing.py`, `routes/account.py`, `routes/account_admin.py`, `main.py`, `config.py`, `__init__.py`, `pyproject.toml` (cryptography), `dflow-agent.spec`, `desktop.yml`, `api/account.ts`, `AccountsPage.tsx`, `PlansEditor.tsx`, `BillingEditor.tsx`, CSS, README (Mục 6.6 khoá ký + bảng lỗi). Test `test_licensing.py` 11 + licence / thanh toán / gói / tài khoản / app / lịch / tự động 97 pass / 2 skip; cả bộ 1161 pass / 2 skip (trước lần đổi cách kiểm tài liệu ký; bỏ các file lỗi môi trường Windows đã biết); `tsc` sạch. Bản dịch Nuitka + PyInstaller chạy thật trên cổng phụ 8534 (sửa tay dòng không lên quyền, trang lạ 403). Khởi động lại agent web (`start140.log`) → **kho Neon ký lần đầu: 2 tài khoản** (akiragosho quản trị, tranngan VIP tới 08/12/2026; cả hai giữ băm cũ đã ghim nên mật khẩu không đổi, app 1.5.2 vẫn đăng nhập được), bảng gói / thanh toán / `min_app` 1.5.2 đã ký. Mọi người phải đăng nhập lại (đổi kiểu phiên). Push + phát hành 1.6.0 ngay sau (dòng dưới).
- **8/11 khuya** — **Khoá ký riêng cho website** (người dùng làm web chạy quảng cáo, quản lý tài khoản / gói song song, hỏi cho web là ngoại lệ chữ ký số): web không bỏ được chữ ký (ai có dòng Neon cũng giả được) nên có khoá Ed25519 riêng mà app tin như khoá quản trị — `licensing.WEB_PUBLIC_KEY_B64`, `_trusted()`, `status().web_fingerprint`; khoá riêng `%USERPROFILE%\.flowboard\dflow-web-license.key`. Sửa bên `dflow-web` (repo chưa có remote, không commit): `licensing.ts` tin cả hai khoá + ký được bằng khoá web + mang `lh`, `accounts.ts` / `password.ts` không lưu mật khẩu thiếu pepper trên kho đã ký, `.env.example`, `CLAUDE.md`; `.env.local` thêm `DFLOW_LICENSE_KEY_FILE` → khoá web (web ký ngay, không chờ job). Test licence 12 + account / billing / plans / app 53 pass, `npm run typecheck` web sạch, thử chéo node → Python đạt. Khởi động lại agent web DFlow (`start141.log`) để tin khoá web.
- **8/11 khuya** — **Phát hành 1.6.0** (người dùng: "push hết code lên thành 1 bản update app mới"): gộp mọi việc 8/11 tối–khuya ở trên — gói & tính năng, nâng cấp bằng chuyển khoản, thời hạn + giá gốc, gói Dùng thử, trang Tài khoản của tôi, dàn hết bề rộng + container query, vá bảo mật, chữ ký số quyền dùng + agent dịch Nuitka + khoá ký của website (dòng trên). Số phiên bản 1.6.0 ở 8 file (`__init__.py`, `pyproject.toml`, `tauri.conf.json`, `Cargo.toml`, `frontend` + `desktop` package.json + lock). Commit `b600917` + push `main`, tag `v1.6.0` → run 42455598766 xong (~24 phút; bước Nuitka + chạy thử agent đóng gói đạt), release v1.6.0 trên dflow-releases (bộ cài 182 MB + `latest.json`), tải về `D:\DFlow-Setup\`; trang hướng dẫn (`docs/cai-dat-dflow.html` → `index.html` của dflow-releases) trỏ 1.6.0 + 3 dòng lỗi mới (gói hết hạn / chưa được cấp quyền / bản app cũ). Cả bộ test trên commit phát hành 1163 pass / 2 skip. **App 1.5.2 trên máy nhà không đăng nhập được akiragosho** (mật khẩu đã đổi trên bản mới → băm `dflow2`) và màn đăng nhập của 1.5.2 không có thanh cập nhật → cài tay bộ cài 1.6.0 (bạn bè chưa đổi mật khẩu thì vào 1.5.2 rồi cập nhật bằng nút).
- **8/11 khuya** — **dflow-web lên GitHub riêng tư** `hoangduytn1703/dflow-web` (commit đầu 72 file; đã rà khoá ký, pepper, chuỗi Neon, `.env.local` — không lọt). Bản web DFlow (start.ps1) đã tắt để người dùng chạy app. **Hosting web bán gói**: người dùng muốn miễn phí như các web trước → **Vercel Hobby** (CLI máy nhà đã đăng nhập hoangduytn1703): project `dflow-web` (vùng `sin1` cạnh Neon — `vercel.json`; `.vercelignore` chặn `.env*`; **đã nối GitHub: mỗi lần push `main` của dflow-web là deploy production** — người dùng cấp quyền repo cho Vercel GitHub App, rồi `vercel git connect`). Lệnh đẩy bí mật lên Vercel bị chặn quyền ("Data Exfiltration") → người dùng tự chạy script đặt env production (DATABASE_URL, DFLOW_PEPPER, WEB_SYNC_SECRET, CRON_SECRET, SESSION_SECRET mới, DFLOW_LICENSE_KEY = khoá web). Đã thử Cloudflare Workers (OpenNext 1.20.16): build chết trên Windows (`EPERM symlink` — cần Developer Mode hoặc WSL, máy chưa có) + cần Workers Paid (băm pbkdf2 vượt 10 ms CPU gói free, giới hạn 3 MiB) + R2 / Durable Objects cho cache giá → bỏ. Tên miền: `toptoplive.io.vn` đã chuyển nameserver sang Cloudflare (đã kiểm DNS); người dùng muốn **`dflow.io.vn`** (chưa ai đăng ký, sẽ mua ở tenten.vn rồi thêm vào Cloudflare như trên).
- **8/11 khuya** — **Phase C: app đăng nhập qua dflow.io.vn, không cầm dòng Neon** (người dùng: "bạn toàn quyền, triển hướng C đi, làm hết"): web thêm API cho app
  (`dflow-web/src/app/api/app/*`, `lib/appapi.ts`, `lib/dbrole.ts`, `lib/media.ts`, `accounts.setDisabled` khoá role), agent thêm `cloud_api.py` + chế độ đăng nhập qua web
  (`accounts.py`, `file_store._ApiBucket`, `billing.py`, `routes/account.py`, `account_admin.py`, `cloud.py`, `app.py`, `db/session.py`), giao diện (trang đăng nhập có link đăng
  ký, menu quản trị mở web, Cài đặt → Dữ liệu). Test `test_cloud_api.py` 10 + cả bộ (xem dòng phát hành); **thử thật trên Neon + web dev 3030 + agent phụ cổng 8534**:
  tài khoản thử `phasec-test` (đã xoá: role, schema, tài khoản) — cách ly đúng, tạo clip vào schema riêng, hồ sơ / nâng cấp qua web, khoá / mở khoá. Phát hiện B2 đầy 10 GB
  miễn phí (đẩy file lỗi từ trước — xem Bẫy). Vá kèm: `/api/cloud/s3` trước đây tài khoản thường nào cũng ghi đè được key kho file → giờ chỉ admin.
- **8/11 khuya** — **Phát hành 1.7.0** (Phase C): CI chết 2 lần vì github.com release download trả 504 (xem Bẫy) → commit `a81b7bf` (ffmpeg nguồn 2 gyan.dev + thử lại, Tauri thử 3 lần) và `32a90d6` (tải NSIS qua API asset), dời tag v1.7.0 sang `32a90d6` (chưa phát hành nên không ảnh hưởng ai) → run 42471485411 xong, release v1.7.0 trên dflow-releases (bộ cài 191 MB + `latest.json`), tải về `D:\DFlow-Setup\`. Trang hướng dẫn (`docs/cai-dat-dflow.html` → `index.html` dflow-releases, commit `0ee01e2`) trỏ 1.7.0 + bước "Có tài khoản DFlow" (đăng ký trên dflow.io.vn) thay bước dán dòng kết nối. dflow-web `8054b3c`: trang Tài khoản + FAQ bỏ hướng dẫn dán dòng (tự deploy Vercel). Người dùng báo app đã lên 1.7.
- **8/11 khuya** — Người dùng xác nhận đã lên 1.7.0 **bằng nút cập nhật trong app** (từ 1.6.0) → lần tự cập nhật thật đầu tiên chạy được. Sửa dòng "Tự cập nhật chưa chạy thật" ở Việc đang dở.
- **8/11 khuya** — **✂️ Cắt video — menu riêng** (không lồng tiếng): link / file → Whisper → AI chọn đoạn theo yêu cầu (hoặc tự chọn / chia đều) → cắt thành nhiều video, mỗi video một clip + dự án chỉnh sửa (trình chỉnh sửa lồng tiếng ở chế độ phụ đề tuỳ chọn, chỉnh từng video hoặc áp cho cả loạt); trang Lồng tiếng lấy video từ "Clip của tôi"; trợ lý AI `cut_video`; tính năng gói `cut`. `services/video_cut.py`, `routes/cut.py`, `dub.py` (kind cut, `sub_lang none`), `plans.py`, `running.py`, `op_tracker.py`, `assistant.py`, `capcut_auto.py`, `routes/dub.py`, `api/cut.ts`, `pages/CutPage.tsx`, `cut.css`, `DubEditor` / `Inspector` / `EditorStage` / `CutPane`, `dub/ClipPickDialog.tsx`, `DubPage.tsx`, `StepExport.tsx`, `QuicktoolApp.tsx`, `QuicktoolSidebar.tsx`, `BackgroundTasks.tsx`, `lib/features.ts`; web `catalog.ts`, `FeatureIcon.tsx`. Test `test_video_cut.py` 9 + liên quan (dub / assistant / plans / running / capcut / licensing / billing…) 161 pass, `tsc` + web typecheck sạch; thử thật trên agent phụ 8534 (xem Chỗ cần biết). Phát hành trong 1.8.0 (người dùng: "ok phát hành 1.8.0 luôn đi").
- **9/11** — Phát hành 1.8.0 xong: run 42501297995 thành công (bản watcher báo "exit 4" chỉ là lỗi của `gh run watch`), release v1.8.0 trên dflow-releases (bộ cài 191 MB + `latest.json`), tải về `D:\DFlow-Setup\`, trang hướng dẫn trỏ 1.8.0 (dflow-releases `5e3c7d0`). Bạn người dùng cài 1.8.0 → lồng tiếng báo thiếu pyvideotrans (xem Việc đang dở).
- **9/11** — **🎙 Gói lồng tiếng** (người dùng: bạn họ cài 1.8.0, máy có card NVIDIA mà lồng tiếng báo thiếu pyvideotrans; "làm luôn", card NVIDIA): nút "⬇ Cài gói lồng tiếng" tự tải uv + Python 3.11 + faster-whisper / sherpa-onnx / VieNeu / RapidOCR (+ cuBLAS / cuDNN khi có card NVIDIA) + mô hình Whisper / spleeter / VieNeu vào `<DFlowData>\addons\dub`, kiểm Whisper chạy trên card rồi mới bật; lồng tiếng, chỉ phụ đề, cắt video theo lời, giọng VieNeu, tự tìm chữ gốc chạy bằng gói đó trên máy không có VieDub. `services/dub_addon.py`, `dub_runner.py` (CUDA không cần torch, rơi về CPU, `check`, `detect`), `dub.py`, `tts.py`, `video_clean.py`, `routes/dub.py`, `routes/video_clean.py`, `routes/running.py`, `plans.py`, `DubAddonCard.tsx`, `DubPage.tsx`, `MachineSection.tsx`, `CutPage.tsx`, `CapcutPage.tsx`, `BackgroundTasks.tsx`, `api/dub.ts`, `dub.css`, README, `docs/cai-dat-dflow.html`, `.gitignore` (`/addons/`). Test `test_dub_addon.py` 9 + liên quan pass, `tsc` sạch. trên máy nhà (RTX 3060 Laptop, driver 616) bằng agent phụ 8534 giấu VieDub (`FLOWBOARD_ERASE_ROOT` trỏ chỗ không có, gói ở `D:\dflow-addon-test`): bấm nút trên giao diện → cài xong **3 phút 30 giây** (mạng nhanh: cuBLAS + cuDNN 1,3 GB ~50 s, Whisper 1,6 GB ~45 s, VieNeu ~45 s), `check` báo Whisper chạy trên card (cuda), gói chiếm 4,8 GB; lồng tiếng thật phần video Enceladus 46 s tiếng Trung giọng VieNeu Hải Đăng + giữ nhạc nền: 20 câu, Google dịch, AI rà tên riêng, xong ~1,5 phút; "Tự tìm chữ gốc" 17 s ra đúng 3 dải (phụ đề 75–81 %, watermark trôi giữa, chữ trên cùng). Playwright: thẻ chưa cài / đang cài / nút việc đang chạy / đã cài ở Cài đặt → 🖥 Máy này, 760 px không tràn, không lỗi console. Cả bộ test 1191 pass / 2 skip.
- **9/11** — Phát hành 1.8.1 (gói lồng tiếng): tag v1.8.1 (người dùng tự bảo "đẩy tag đi" — lệnh đẩy tag của Claude bị chặn quyền lần đầu vì tạo bản phát hành công khai), run 42629695083 thành công (~26 phút), release v1.8.1 trên dflow-releases (bộ cài 191 MB + `latest.json`), tải về `D:\DFlow-Setup\`, trang hướng dẫn trỏ 1.8.1 (dflow-releases `87bc2d7`). Gói cài thử còn ở `D:\dflow-addon-test` (4,8 GB, xoá được).
- **9/11** — ★ Mẫu chỉnh sửa áp được như ý (người dùng: chỉnh 1 video 16:9 → 9:16 + nền + logo, lưu mẫu, các clip sau "add mẫu đó vào nó ko apply đúng"): nguyên nhân = nút áp mẫu là "bấm vào tên" nên họ chỉ bấm "Mặc định" (log không có lần `/use` nào), và mẫu mặc định không vào các video của ✂️ Cắt video. Sửa: nút "✓ Áp dụng" từng mẫu + tooltip / dòng gợi ý rõ "Mặc định = video mới"; trang Cắt video có ô "Mẫu chỉnh sửa cho các video cắt ra" (chọn sẵn mẫu mặc định) → phần cắt ra được áp mẫu và xuất ngay (cả khi cắt lại giữ kiểu riêng). `dub.look_preset` / `default_look_id` / `apply_look`, `video_cut.Session.look` + `needs_render`, `routes/cut.py`, `LookPresets.tsx`, `CutPage.tsx`, `api/cut.ts`, `editor.css`. Test video_cut 11 + look presets 2 + 110 test lồng tiếng / cắt / running / capcut pass, `tsc` sạch; Playwright trên agent phụ 8534: lưu mẫu 9:16 lưới ở phần 1 → phần 2 bấm ✓ Áp dụng → khung 9:16 + lưới hiện, form Cắt video chọn sẵn mẫu. Phát hành **1.8.2** (người dùng: "push lên hết để thành 1 bản mới, t sẽ test sau").
- **10/11** — Máy Linux: pull (đã ở v1.8.2), `npm install --prefix frontend` (gói `qrcode` mới; `package-lock.json` trả về như cũ). Sửa lỗi bạn người dùng báo: cài gói lồng tiếng xong bị "Could not find module …ctranslate2.dll" = máy thiếu Microsoft Visual C++ Runtime → gói tự kiểm runtime trong System32, tự tải + kiểm chữ ký + cài bộ vc_redist của Microsoft (một hộp UAC), nạp thử thư viện ngay sau bước pip (trước khi tải Whisper), câu lỗi có link bấm được. `dub_addon.py`, `DubAddonCard.tsx`, `dub.css`, test `test_dub_addon.py` 15 (+6) + dub / video_clean 43 pass, `tsc` sạch. Chưa chạy UAC thật (máy Linux). Phát hành **1.8.3** (commit + tag `v1.8.3`).
- **10/11** — Phát hành **1.8.3** xong: CI build + đăng lên dflow-releases lúc 09:28 (bộ cài `DFlow_1.8.3_x64-setup.exe` 191 MB, `latest.json` có chữ ký); trang hướng dẫn (`docs/cai-dat-dflow.html` → `index.html` dflow-releases) trỏ 1.8.3 + dòng lỗi "Could not find module …ctranslate2.dll" (trang này trước đó vẫn ở 1.8.1 — bản 1.8.2 chưa cập nhật trang), README Mục 6.2 + bảng lỗi. Máy Linux: `gh` đăng nhập tài khoản công ty `gmo-duynh` không xem được Actions của repo riêng — theo dõi bằng API công khai của dflow-releases.
- **10/11** — Hai việc người dùng báo trên bản cài: Cắt video link YouTube lỗi "yt-dlp không có trên máy" → agent tự tải yt-dlp chính thức (kiểm SHA-256) vào thư mục dữ liệu + tự cập nhật 3 ngày/lần, đưa node cho YouTube; bỏ giới hạn 200 MB (chọn file ghi thẳng ra đĩa, tải theo link không giới hạn cỡ, lọc theo thời lượng, chờ tối đa 30 phút), file tạm của app nằm trong `DFlowData\tmp`. `services/ytdlp.py`, `routes/reference_video.py`, `video_fetch.py`, `dub.py`, `dflow_agent.py`, frontend (MuseBridge, CleanToolPage, NewClipDialog, StepMedia, api/clean). Test `test_ytdlp.py` 7 + liên quan 82 pass, `tsc` sạch. Chưa chạy thật trên Windows (máy Linux; không cho chạy file yt-dlp vừa tải về ở đây). README Mục 6.1 + trang hướng dẫn: app tự tải yt-dlp, không cần winget. Phát hành **1.8.4** (commit + tag `v1.8.4`).
- **10/11** — Phát hành **1.8.4** xong: CI đăng lên dflow-releases lúc 11:15 (bộ cài `DFlow_1.8.4_x64-setup.exe` 191 MB, `latest.json` có chữ ký); trang hướng dẫn (`docs/cai-dat-dflow.html` → `index.html` dflow-releases `1076e8b`) trỏ 1.8.4 + mục "Tải video từ link" không còn lệnh winget. Tag do người dùng tự đẩy (lệnh đẩy tag của Claude bị chặn quyền vì tạo bản phát hành công khai). Chưa thử trên Windows thật: tự tải yt-dlp, bỏ 200 MB.
- **10/11** — Ba chỉnh theo góp ý: (1) **thanh kéo có nấc** trong trình chỉnh sửa lồng tiếng (`components/TickRange.tsx`: vạch nhỏ theo bước tròn + vạch lớn ở mốc, kéo chuột thì hút vào mốc trong 2 % khoảng, phím mũi tên vẫn đi từng bước) — áp cho Khung xuất (vị trí cắt / vị trí video / cỡ video / ô lưới), tab Phụ đề (cỡ chữ, độ rộng, ngang, dọc), Làm mờ (5 thanh), Nhấn (vị trí chữ to), Trang trí (cỡ video trong khung, viền, cỡ nhân vật); thanh zoom timeline giữ nguyên; (2) **thumbnail cho ★ Mẫu** (`dub/editor/LookThumb.tsx`): hình nhỏ vẽ từ chính dữ liệu mẫu (tỉ lệ khung xuất, nền màu / lưới / ảnh, chỗ video, khung + viền, vùng mờ, nhân vật, thanh phụ đề theo kiểu) nên mẫu cũ cũng có hình; mẫu không có gì để vẽ ra hình mặc định 9:16 tối + thanh phụ đề; không phải ảnh chụp thật; (3) toast xuống góc dưới trái, 1,5 s. `tsc` sạch; **chưa xem bằng mắt** (không có dev server lúc làm) — cần mở trình chỉnh sửa kiểm vạch nấc và hình mẫu.
- **10/11** — ✂️ Cắt video thông minh hơn (người dùng dán prompt mẫu của tool cutYoutube): prompt cắt **lưu theo tài khoản, sửa / đổi tên / xoá được** (có sẵn một prompt mẫu), prompt dài nhiều dòng giữ nguyên, AI viết **tiêu đề từng đoạn theo luật trong prompt** + **một tiêu đề chung (Name)**, chọn **ngôn ngữ tiêu đề**, copy cả dòng Name | start | end | title_bottom; ẩn các chip gợi ý. `video_cut.py`, `routes/cut.py`, `api/cut.ts`, `cut/PromptBox.tsx` (mới), `CutPage.tsx`, `cut.css`. Test video_cut 13 + assistant / plans / running 37 pass, `tsc` sạch. **Chưa thử với AI thật và chưa xem giao diện bằng mắt** (không có agent / dev server chạy lúc làm). Agent cần khởi động lại để có route mới. Chưa commit.
- **10/11** — Sửa lỗi không tải được video theo link (bộ lọc thời lượng của yt-dlp sai cú pháp, xem Bẫy; `reference_video.py`, `test_ytdlp.py`). Cắt video "Theo yêu cầu": **bỏ ô "Mỗi video ngắn dài" + "Số video tối đa"** (mâu thuẫn với prompt) ở form và khung Gợi ý lại — độ dài / số đoạn do prompt quyết, prompt không nói thì 30–180 giây (`video_cut.ai_prompt`); hai ô vẫn còn cho "AI tự chọn" và "Chia đều". Test cắt video / yt-dlp / video_fetch / reference_video 26 pass, `tsc` sạch. Agent chạy lại `start143.log`. Chưa commit.
- **10/11 tối** — Ba việc người dùng giao (tối ưu tool): (1) **trình chỉnh sửa kiểu CapCut đợt 1**: bố cục 3 cột (công cụ trái / màn xem giữa / chi tiết phải), thanh công cụ timeline có ✂ Tách (Ctrl+B) / ⤝ Gộp / ＋ Thêm câu / 🗑 Xoá + hoàn tác, backend nhận cả danh sách câu khi số câu đổi (`dub.apply_cues`), nhãn thay ảnh nền vỡ; (2) **rà như người mới cài**: AI tự dùng Gemini key khi chưa chọn AI / AI đã chọn không có trên máy / AI lỗi (trước là lỗi tiếng Anh ở mọi tính năng AI); thử thật trên Windows máy "sạch": tool tự tải yt-dlp 1,6 s rồi tải video YouTube 8 s (phần 1.8.4 chưa từng chạy thật), sửa video dài quá giới hạn báo "yt-dlp exited 0"; tốc độ: `/api/running` 370 → ~130 ms (4 nguồn đọc DB chạy song song), `/api/posts` 494 → ~270 ms (4 lượt tra song song), `/api/channels` 496 → ~370 ms (nhớ "kênh đã nối Page" 2 phút — `facebook_publish.has_token`); (3) **kiểm tra card màn hình một lần rồi nhớ** (`services/machine.py`, xem Chỗ cần biết). File: `machine.py` (mới), `registry.py`, `running.py`, `posts.py`, `channels.py`, `facebook_publish.py`, `reference_video.py`, `dub.py`, `routes/dub.py`, `routes/app.py`, `video_clean.py`, `video_cut.py`, `main.py`, `DubEditor.tsx`, `Inspector.tsx`, `EditorTimeline.tsx`, `EditorStage.tsx`, `cues.ts`, `editor.css`, `MachineSection.tsx`, `DubPage.tsx`, `CutPage.tsx`, `api/dub.ts`, `api/cut.ts`, `styles.css`. Đã xem bằng Chrome thật (phiên của người dùng, chỉ xem): bố cục mới, tách câu 13 → 14, nhãn thiếu file nền; **chưa xuất thật một video sau khi tách / gộp** (không đụng dự án của người dùng), chưa xem thẻ "Card màn hình" ở Cài đặt bằng mắt, chưa thử trên máy không có card. Cả bộ test 1245 pass / 2 skip / 1 lỗi có sẵn trên Windows (`test_llm_secrets` 0600), bỏ 4 file lỗi môi trường đã biết; `tsc` sạch. Agent chạy `start144.log`. Chưa commit.
- **10/11 khuya** — ✂️ Cắt video: **"Chia đều" → "Tự cắt"** (nhập bắt đầu / kết thúc / tên đoạn bắt buộc / tiêu đề phụ không bắt buộc, kiểm lỗi từng đoạn ở cả giao diện lẫn agent, không gọi AI, đoạn quá cuối video tự rút về). `video_cut.py`, `dub_split.py`, `routes/cut.py`, `cut/ManualRows.tsx` (mới), `CutPage.tsx`, `api/cut.ts`, `api/dub.ts`, `cut.css`. Test cắt video 39 pass, `tsc` sạch. Thử thật bằng Chrome trên web (`start145.log`): kiểm lỗi khi gõ / khi bấm Cắt, tự điền giờ bắt đầu, video YouTube 19 s với đoạn 2 đến 0:40 → rút về 0:19 + ghi chú, bảng xem lại có tiêu đề phụ; phiên thử ở chế độ xem lại nên không tạo clip, đã xoá. Chưa commit.
- **10/11 khuya** — ✂️ Cắt video làm lại theo góp ý: **phân tích trước** (dán nhiều link → 🔍 Phân tích → video nào xong thì chọn đoạn cho video đó, đã biết độ dài), ô giờ **phút : giây** không phải gõ dấu `:`, **bỏ trống giờ kết thúc = tới đoạn sau / hết video**, dải đoạn + ⏱ + tổng thời lượng, AI chọn đoạn thành tuỳ chọn điền vào cùng bảng (cho một hoặc mọi video đang chờ). `video_cut.py` (`ask`, `start(analyze)`, `cut(how)`), `routes/cut.py`, `cut/MinSec.tsx` + `cut/PartsTable.tsx` (mới), `CutPage.tsx`, `api/cut.ts`, `cut.css`. Test cắt video pass, `tsc` sạch. Thử thật bằng Chrome (`start146.log`): phân tích video YouTube 19 s → bảng hiện; 3 đoạn với đoạn 2 + 3 bỏ trống kết thúc → 0:12 và 0:19.1; gõ 40 giây → báo quá cuối video; 90 giây → 1:30. **Chưa bấm Cắt thật trong luồng mới** (không tạo clip vào thư viện của người dùng; phần cắt có test), chưa thử AI chọn đoạn và nhiều video cùng lúc trên giao diện. Phiên thử đã xoá. Chưa commit.
- **10/11 khuya** — Commit + phát hành **1.8.5** (gộp cả đợt 10/11: sửa không tải được video theo link (bộ lọc yt-dlp), trình chỉnh sửa kiểu CapCut + tách / gộp câu, AI dự phòng bằng Gemini key, kiểm tra card màn hình một lần, tăng tốc `/api/running` / `posts` / `channels`, Cắt video phân tích trước + nhập phút:giây + prompt đã lưu, thanh kéo có nấc, thumbnail mẫu, toast góc dưới trái). Số phiên bản 1.8.5 ở 8 file; tag `v1.8.5` do người dùng tự đẩy (lệnh đẩy tag của Claude bị chặn quyền). Sau khi CI xong: cập nhật `docs/cai-dat-dflow.html` + `index.html` của dflow-releases trỏ 1.8.5.
- **10/11 khuya** — Phát hành **1.8.5** xong: CI (run 42853592236) đăng lên dflow-releases (bộ cài `DFlow_1.8.5_x64-setup.exe` 182 MB, `latest.json`); trang hướng dẫn (`docs/cai-dat-dflow.html` → `index.html` dflow-releases) trỏ 1.8.5. Bản 1.8.4 hỏng tải video theo link (bộ lọc yt-dlp) — ai đang ở 1.8.4 cập nhật bằng nút trong app.
