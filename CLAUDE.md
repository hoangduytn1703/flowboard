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
- `make install` (cần `python3-venv`; không có thì dùng `uv venv` + `uv pip install -e ".[dev]"` trong `agent/` — `[dev]` có pytest + moto cho test; chạy lại sau mỗi lần `pyproject.toml` đổi), `cp .env.example .env`.
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
- **Đăng video lớn lên Facebook Page bị "413 Request Entity Too Large"** (28/10, người dùng tưởng token hết hạn): bài #33 gắn clip #30 (lồng tiếng 3:35, file 152 MB) → `facebook_publish` gửi cả file trong một request `source` tới `graph-video …/{page}/videos` → Facebook từ chối 413, thông báo cũ chỉ ghi "Facebook từ chối (413): " (rỗng). Token hết hạn là mã **190**. Giờ video > `CHUNKED_ABOVE` (20 MB) đi đường chia nhỏ `_upload_video_chunked`: `upload_phase=start` (`file_size`) → `transfer` đúng khoảng byte Facebook trả về (`start_offset`/`end_offset`, `video_file_chunk`, thử lại 3 lần khi rớt mạng) → `finish` (`description`), tối đa 1,75 GB / 45 phút; 413 báo "file gửi lên quá lớn". Test `test_a_big_video_goes_up_in_pieces`. Chưa đăng lại bài #33 (để người dùng tự bấm).
- **Remotion `interpolate` ném lỗi khi câu phụ đề ngắn hơn 0,2 s** (28/10, "inputRange must be strictly monotonically increasing"): fade của `DubSubtitles` dùng mốc `start+0,12` và `end−0,08` → câu 0,16 s làm mốc đảo thứ tự, cả lượt render Remotion lỗi. Giờ kẹp hai mốc về giữa câu. Bug có sẵn, lộ ra khi test nhấn chữ với câu ngắn.
- **Zoom theo thời gian trong ffmpeg**: `crop` không đổi được w/h theo khung, `scale eval=frame` đổi cỡ khung làm link filter đổi kích thước — dùng `zoompan` với `d=1`, biểu thức theo `in_time`, `s=` đúng cỡ nguồn và `fps=` đúng r_frame_rate (sai fps thì lệch tiếng dần). Nhanh (6 s video 0,5 s).
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
- **Hộp Cài đặt = tab bên trái** (25/10, thay bố cục 2 cột dài ~2.700 px): `SettingsPanel.tsx` `TABS` — 🎬 Tạo ảnh & video (Model
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
  Lưu ý: file trên B2 vẫn có logo (file_store chỉ đẩy khi tạo Asset) → máy kia mở ảnh thì hook xoá lại; **video Veo chưa xử lý**.
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
- **Đăng dạng Bài viết hay Reel** (28/10, người dùng: "muốn chia ra reel và post"): `Schedule.fb_format` "post" | "reel" (migration `db.ensure_schedule_format_column`, đã chạy trên Neon). Reel qua API theo developers.facebook.com/docs/video-api/guides/reels-publishing: `facebook_publish.publish_reel` = `POST /{page}/video_reels upload_phase=start` → file lên `upload_url` (rupload.facebook.com, header `Authorization: OAuth`, `offset`, `file_size`; rớt mạng thì đọc `status.uploading_phase.bytes_transfered` để gửi tiếp) → `upload_phase=finish video_state=PUBLISHED description` → chờ `status.video_status` ready ≤ 120 s → bình luận đầu → `permalink_url`. `reel_problem(video)` chỉ chặn video < 3 s / không đọc được; `reel_warning` chỉ **nhắc** (dài hơn 90 s mà tài liệu API ghi, ngang hơn 16:9, cạnh ngắn < 540 px) — người dùng chỉ ra app Facebook đăng được Reel 3:00 (đăng tay), nên không chặn, để Facebook quyết; từ chối thì báo lỗi, đăng lại dạng bài viết (giới hạn API: 30 bài / 24 giờ / Page). `scheduler.reel_check` + `GET /api/schedule/reel-check?kind&post_id|board_id` → `{has_video, ok, reason}`; `create/update(fb_format=)` từ chối Reel khi không có video / video sai chuẩn (clip chưa ghép thì để lúc đăng kiểm). Đường "post" như cũ (`publish_post`: `/videos`, chia nhỏ khi > 20 MB). UI `schedule/FormatPicker.tsx` ("📰 Bài viết / 🎬 Reel", Reel khoá + lý do khi không hợp, khoá trong lúc đang kiểm ~0,8 s; không có video thì ẩn) ở `ScheduleDialog`, `DropTimeDialog`, thanh Đăng bài trang Bài viết (compact, chỉ khi bài có video / gắn clip) và Bước 5 `ClipPost` ("🚀 Đăng Reel ngay"); Lịch đăng ghi "🎬 Reel" trên ô lịch + khung chi tiết "Dạng". Test `test_schedule.py` (+2: chuẩn Reel bằng ffmpeg thật, cả luồng Reel với Graph giả). **Chưa đăng Reel thật.**
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
  video không phải 9:16 / > 200 MB / 2 video một cảnh → "✓ Gắn N video vào cảnh" = `store/quicktool.attachMuseVideo` (cảnh đang chạy Flow
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
- **Đăng xuất Flow phải bấm 2 lần** (21/10, `SettingsPanel.tsx`): lần đầu nút đổi thành "Bấm lần nữa để đăng xuất…" + "Huỷ",
  tự quay lại sau 5 s / khi đóng hộp; xong có toast (`AccountPanel.handleLogout`). Nút chỉ có ở hộp Cài đặt mở từ ⚙ cạnh tài khoản.

## Việc đang dở / chưa kiểm chứng
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
