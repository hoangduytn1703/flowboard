# DFlow

**DFlow** giúp người làm affiliate (TikTok Shop, Shopee…) làm nội dung nhanh hơn, ngay trên máy tính của mình:

- Từ **ảnh / link sản phẩm** → AI viết kịch bản → tạo ảnh và video bằng Google Flow → ghép thành **clip quảng cáo có giọng đọc tiếng Việt**.
- **Lồng tiếng** video nước ngoài (Douyin, TikTok, YouTube…) sang tiếng Việt, có phụ đề.
- **Viết bài Facebook**, **lên lịch** và **tự đăng** lên Facebook Page.

> **Người mới chỉ cần cài app?** Gửi họ trang hướng dẫn ngắn: **https://hoangduytn1703.github.io/dflow-releases/** (không cần tài khoản GitHub).

DFlow chạy trên máy của bạn (không phải trang web có sẵn), nên cần cài một lần theo hướng dẫn dưới đây. Làm lần lượt từng bước, mỗi bước
đều ghi rõ **phải gõ gì** và **sẽ thấy gì**.

## Mục lục

1. [DFlow làm được gì](#1-dflow-làm-được-gì)
2. [Bạn cần chuẩn bị gì](#2-bạn-cần-chuẩn-bị-gì)
3. [Cài đặt lần đầu (Windows)](#3-cài-đặt-lần-đầu-windows) — [bằng file cài đặt](#cách-1--cài-bằng-file-dflow-setupexe-dễ-nhất) hoặc [từ mã nguồn](#cách-2--chạy-từ-mã-nguồn)
4. [Mỗi ngày dùng thế nào](#4-mỗi-ngày-dùng-thế-nào)
5. [Cập nhật bản mới](#5-cập-nhật-bản-mới)
6. [Cài thêm theo nhu cầu](#6-cài-thêm-theo-nhu-cầu)
7. [Gặp lỗi thì làm gì](#7-gặp-lỗi-thì-làm-gì)
8. [Dành cho dev](#8-dành-cho-dev)

---

## 1. DFlow làm được gì

| Mục trong app | Dùng để |
|---|---|
| **Hôm nay** | Xem việc cần làm, việc đang chạy, clip chưa tải về |
| **Clip của tôi** | Làm clip quảng cáo 5 bước: sản phẩm & người mẫu → kịch bản → ảnh → video → ghép + giọng đọc. Có kiểu **🔇 Không lời** (chỉ hình + tiếng động thật) |
| **Sản phẩm, Người mẫu, Prompt** | Lưu sản phẩm (nhập từ link Shopee / TikTok), người mẫu AI, câu lệnh hay dùng |
| **Lồng tiếng video** | Đổi video tiếng Trung / Anh… sang giọng Việt + phụ đề, chỉnh như CapCut |
| **Edit auto CapCut** | Tạo sẵn dự án CapCut có phụ đề, chữ nhấn, hiệu ứng (chỉ Windows) |
| **Bài viết Facebook, Kênh, Mẫu đang hot** | AI viết bài theo kênh / page của bạn, học theo bài đang hot |
| **Lịch đăng** | Lên lịch, tự đăng lên Facebook Page (bài / Reel / tin), tự động đăng theo giờ cố định |
| **🤖 Trợ lý AI** | Nút tròn góc dưới phải — gõ một câu, trợ lý làm giúp |

## 2. Bạn cần chuẩn bị gì

**Máy tính**: Windows 10 hoặc 11, RAM từ 8 GB, ổ cứng trống khoảng **10 GB** (cộng thêm ~15 GB nếu dùng lồng tiếng), có Internet.

**Tài khoản** (chuẩn bị trước khi cài):

| Cần gì | Để làm gì | Lấy ở đâu |
|---|---|---|
| Tài khoản Google có **Google Flow gói Pro hoặc Ultra** | Tạo ảnh và video | Đăng ký Google AI Pro / Ultra, vào flow.google.com |
| Tài khoản **Claude** (gói Pro hoặc Max) | AI viết kịch bản, bài viết, trợ lý | claude.ai |
| **Gemini API key** (miễn phí) | Đọc sản phẩm từ link, clip theo link, giọng Gemini, sửa tên riêng khi lồng tiếng | aistudio.google.com/apikey |
| **Tên đăng nhập DFlow** (+ dòng kết nối dữ liệu) | Đăng nhập vào app, dữ liệu của bạn nằm trên cloud | Người quản lý DFlow tạo và gửi cho bạn ([Mục 6.6](#66-cấp-tài-khoản-cho-người-khác-chỉ-người-quản-lý)) |
| Tài khoản **GitHub** được mời vào kho code | **Chỉ khi chạy từ mã nguồn** (Cách 2) — người cài bằng file không cần | Tạo ở github.com, rồi nhờ chủ DFlow mời vào kho `hoangduytn1703/flowboard` |

**Không phải ai cũng cần hết.** Bảng dưới cho biết tính năng nào cần cài thêm gì. Phần **Cơ bản** là bắt buộc, các dòng còn lại chỉ cài khi bạn dùng tới.

| Bạn muốn | Cần cài | Hướng dẫn |
|---|---|---|
| **Cơ bản**: mở app, làm clip quảng cáo, sản phẩm, bài viết, lịch đăng | File cài **DFlow-Setup.exe** + Chrome + Claude Code + extension DFlow Bridge (chạy từ mã nguồn thì thêm uv, Node.js, Git, ffmpeg) | [Mục 3](#3-cài-đặt-lần-đầu-windows) |
| Tải video từ link TikTok / YouTube / Instagram / Facebook | yt-dlp (Douyin không cần) | [Mục 6.1](#61-tải-video-từ-link) |
| **Lồng tiếng video**, xoá phụ đề có sẵn bằng AI, giọng VieNeu miễn phí | Bộ VieDub (pyvideotrans) — nặng, nên có card đồ hoạ NVIDIA | [Mục 6.2](#62-lồng-tiếng-video-xoá-phụ-đề-ai-giọng-vieneu) |
| Edit auto CapCut | CapCut bản máy tính | [Mục 6.3](#63-edit-auto-capcut) |
| Tự đăng lên Facebook Page, xem lượt xem | Mã truy cập (token) của Page | [Mục 6.4](#64-tự-đăng-facebook-page) |
| Dùng chung dữ liệu trên nhiều máy | Dòng kết nối cơ sở dữ liệu (chủ DFlow đưa) | [Mục 6.5](#65-dùng-chung-dữ-liệu-trên-nhiều-máy) |

> **Tự động đăng theo lịch** chỉ chạy khi máy đang bật và DFlow đang mở lúc tới giờ.

---

## 3. Cài đặt lần đầu (Windows)

Có 2 cách. **Cách 1 (file cài đặt)** dễ nhất — **không phải cài Python, Node, Git** (app đã có sẵn bên trong); app tự cập nhật.
**Cách 2 (mã nguồn)** dành cho người sửa code hoặc muốn luôn có bản mới nhất.

### Cách 1 — Cài bằng file DFlow-Setup.exe (dễ nhất)

1. **Lấy file cài đặt** `DFlow_..._x64-setup.exe` (~185 MB) ở trang **github.com/hoangduytn1703/dflow-releases/releases** (bản mới nhất ở
   trên cùng, mục Assets) — hoặc chủ DFlow gửi cho bạn.
2. **Chạy file đó.** Windows có thể hiện màn hình xanh *"Windows protected your PC"* (vì file chưa ký số) → bấm **More info** → **Run anyway**.
   Bấm Next / Install, không cần quyền quản trị. Ở trang **Choose Install Location** có thể đổi sang ổ khác (ví dụ `D:\DFlow`) cho đỡ tốn ổ C.
   Dữ liệu (ảnh, video, cài đặt, nhật ký) **tự để ngoài ổ C**: DFlow chọn ổ D (hoặc ổ khác còn trống trên 5 GB) và tạo thư mục `D:\DFlowData`;
   chỉ máy có mỗi ổ C mới để ở ổ C.
3. **Mở DFlow** từ menu Start (hoặc biểu tượng trên màn hình). Lần đầu mất 20–40 giây để khởi động.
   Đóng cửa sổ thì DFlow **vẫn chạy ngầm** ở khay hệ thống (góc dưới phải, cạnh đồng hồ) để lịch đăng bài vẫn chạy —
   muốn tắt hẳn: chuột phải biểu tượng DFlow → **Thoát DFlow**.
4. **Đăng nhập lần đầu** (theo đúng thứ tự):
   - Được gửi **dòng kết nối dữ liệu** (bắt đầu bằng `postgresql://…`)? Ở trang đăng nhập bấm **🌐 Dán dòng kết nối trước** → dán nguyên dòng →
     **Kết nối**. DFlow tự kiểm tra rồi khởi động lại (20–40 giây). Làm một lần trên mỗi máy. Chưa dán dòng này thì tài khoản được cấp sẽ báo
     *"Sai tên đăng nhập hoặc mật khẩu"*.
   - Đăng nhập bằng **tên + mật khẩu được cấp**.
   - Bấm **Đổi mật khẩu** (góc dưới trái, cạnh tên của bạn) để đặt mật khẩu riêng.
5. **Cài Claude Code** (AI viết kịch bản, bài viết) — mở PowerShell (bấm Start, gõ `powershell`) và dán:

   ```powershell
   irm https://claude.ai/install.ps1 | iex
   ```

   Xong gõ `claude` rồi Enter → trình duyệt mở ra để đăng nhập tài khoản Claude → quay lại gõ `/exit`.
   Claude Code cài thẳng, **không cần Node.js hay Git**. Cần gói Claude Pro / Max.
6. **Mở Google Flow**: vào **flow.google.com** trong Chrome, đăng nhập tài khoản có gói Pro / Ultra, tạo một project mới. Để tab này mở.
7. Trong DFlow, lần đầu sẽ hiện hộp **AI Providers**: chọn **Claude** cho cả ba mục → **Áp dụng thay đổi** (đổi sau ở **⚙ Cài đặt → 🤖 AI viết**).
8. Vào **⚙ Cài đặt → 🖥 Máy này**:
   - chọn gói **Pro** hoặc **Ultra** (giống gói Flow của bạn);
   - phần **Extension DFlow Bridge**: làm theo hướng dẫn hiện ở đó (mở `chrome://extensions` → bật Developer mode → Load unpacked → chọn
     thư mục DFlow chỉ cho, có nút 📂 mở sẵn thư mục), rồi F5 tab flow.google.com;
   - muốn để ảnh / video ở chỗ khác (ổ ngoài, ổ E…): đổi **Thư mục lưu ảnh, video** rồi bấm **↻ Khởi động lại DFlow**;
   - đổi dòng kết nối dữ liệu sau này: ô **Dùng chung dữ liệu** → Lưu → Khởi động lại.
9. **⚙ Cài đặt → 🔑 Gemini key**: dán Gemini key (lấy ở aistudio.google.com/apikey). **⚙ Cài đặt → ⚡ Google Flow**: chọn project Flow vừa tạo.

**Cập nhật bản mới**: app **tự báo** khi có bản mới (thanh "🎉 Có bản DFlow …" ở dưới màn hình, hoặc **⚙ Cài đặt → 🖥 Máy này → ↻ Kiểm tra
cập nhật**) → bấm **⬇ Cập nhật ngay**: app tự tải, đóng, cài và mở lại — dữ liệu, đăng nhập giữ nguyên, không phải gỡ ra cài lại. Sau đó vào
`chrome://extensions` bấm nút tải lại (↻) ở ô DFlow Bridge. File cài mới nhất luôn có ở **github.com/hoangduytn1703/dflow-releases/releases**
(bản **trước 1.5.1** chưa tự cập nhật được: tải file cài mới nhất về cài đè một lần, dữ liệu giữ nguyên).

> Bản app đã kèm sẵn ffmpeg. Lồng tiếng video vẫn cần bộ VieDub cài riêng ([Mục 6.2](#62-lồng-tiếng-video-xoá-phụ-đề-ai-giọng-vieneu)) —
> khai báo đường dẫn ở Cài đặt → 🖥 Máy này. Phụ đề kiểu Remotion chưa có trong bản app (dùng kiểu ffmpeg).

### Cách 2 — Chạy từ mã nguồn

Mất khoảng 20–30 phút, phần lớn là chờ tải.

#### Bước 1 — Mở PowerShell

Bấm nút **Start** (góc dưới trái) → gõ `powershell` → bấm **Windows PowerShell**. Một cửa sổ nền xanh / đen hiện ra — mọi lệnh bên dưới đều gõ ở đây.

- **Dán lệnh**: copy lệnh trong README (nút copy ở góc khung lệnh), rồi **bấm chuột phải** vào cửa sổ PowerShell để dán, bấm **Enter** để chạy.
- Chờ lệnh chạy xong (hiện lại dòng `PS C:\Users\...>`) rồi mới dán lệnh tiếp theo.

#### Bước 2 — Cài các phần mềm cần thiết

Dán cả khối này vào PowerShell (nó cài lần lượt từng phần mềm, mỗi cái 1–3 phút):

```powershell
winget install -e --id astral-sh.uv --accept-source-agreements --accept-package-agreements
winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements
winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
winget install -e --id GitHub.cli --accept-source-agreements --accept-package-agreements
winget install -e --id Google.Chrome --accept-source-agreements --accept-package-agreements
```

Các phần mềm này là gì:

| Phần mềm | Vai trò |
|---|---|
| **uv** | Cài phần lõi của DFlow (viết bằng Python). uv **tự tải Python** — bạn không cần cài Python riêng |
| **Node.js** | Chạy giao diện của DFlow |
| **Git** + **GitHub CLI** | Tải code DFlow về và cập nhật bản mới |
| **ffmpeg** | Ghép và xử lý video |
| **Chrome** | Trình duyệt để mở app và chạy Google Flow (đã có thì nó báo "already installed", không sao) |

Nếu cửa sổ hiện hộp hỏi quyền (User Account Control) thì bấm **Yes**.

**Sau khi cài xong: đóng PowerShell và mở lại** (Bước 1) — nếu không, máy chưa nhận các lệnh vừa cài.

> Báo `winget is not recognized`? Mở **Microsoft Store**, tìm **App Installer**, bấm Cập nhật / Cài đặt, rồi làm lại bước này.

#### Bước 3 — (Nên làm) Để dữ liệu tạm của uv sang ổ D

uv giữ một bản sao các thư viện đã tải, có thể lên tới hơn 10 GB nếu dùng lồng tiếng. Mặc định nó nằm ở ổ C. Nếu máy có ổ D, chạy lệnh này để nó
nằm ở ổ D (máy chỉ có ổ C thì bỏ qua bước này):

```powershell
[Environment]::SetEnvironmentVariable('UV_CACHE_DIR', 'D:\uv-cache', 'User')
```

Rồi **đóng PowerShell và mở lại**.

#### Bước 4 — Cài Claude Code (AI viết kịch bản, bài viết)

```powershell
npm install -g @anthropic-ai/claude-code
claude
```

Lệnh `claude` mở trình duyệt để đăng nhập tài khoản Claude. Đăng nhập xong quay lại PowerShell, gõ `/exit` rồi Enter để thoát.

> Đã quen dùng Gemini CLI (`agy`) hoặc Codex thì dùng cái đó cũng được — chọn trong app ở Bước 9 (hoặc Cài đặt → 🤖 AI viết).

#### Bước 5 — Đăng nhập GitHub và tải DFlow về

```powershell
gh auth login
```

Nó hỏi vài câu, dùng phím mũi tên để chọn và Enter:
`GitHub.com` → `HTTPS` → `Yes` → `Login with a web browser`. Nó hiện một **mã 8 ký tự** — copy mã đó, bấm Enter, trình duyệt mở trang GitHub, dán mã
và bấm **Authorize**.

Tải code về thư mục `D:\DFlow` (máy chỉ có ổ C thì đổi `D:` thành `C:` ở lệnh này và mọi lệnh sau):

```powershell
gh repo clone hoangduytn1703/flowboard D:\DFlow
cd D:\DFlow
```

> Báo `Could not resolve to a Repository`? Tài khoản GitHub của bạn chưa được mời vào kho — nhờ chủ DFlow mời, mở email bấm chấp nhận lời mời.

#### Bước 6 — Lấy mã project Google Flow

1. Mở Chrome, vào **flow.google.com**, đăng nhập đúng tài khoản Google có gói Pro / Ultra.
2. Bấm **tạo project mới** (New project).
3. Nhìn thanh địa chỉ: copy đoạn mã dài ngay sau chữ `/project/` — dạng `1a2b3c4d-1234-5678-9abc-1234567890ab`. Đó là **mã project**.
4. Xem gói của bạn là **Pro** hay **Ultra** (hiện ở góc trên phải trang Flow, bấm vào ảnh đại diện).

**Để tab Flow này mở** — DFlow cần nó để tạo ảnh và video.

#### Bước 7 — Chạy DFlow lần đầu

Trong PowerShell (đang ở `D:\DFlow`), dán lệnh sau, **thay** `MÃ-PROJECT` bằng mã ở Bước 6 và `Ultra` bằng `Pro` nếu gói của bạn là Pro:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -FlowProjectId MÃ-PROJECT -Plan Ultra
```

Lần đầu nó tự cài mọi thứ còn thiếu, mất **5–10 phút**. Xong sẽ thấy dòng chữ xanh **DFlow**, bên dưới có `App : http://localhost:5174`, và cuối cùng là
`Application startup complete`.

**Giữ nguyên cửa sổ này** (thu nhỏ được, đừng đóng) — đóng là DFlow tắt.

#### Bước 8 — Cài extension DFlow Bridge vào Chrome

Extension là "cầu nối" để DFlow điều khiển Google Flow trong Chrome của bạn.

1. Mở tab mới trong Chrome, gõ `chrome://extensions` rồi Enter.
2. Bật công tắc **Developer mode** (Chế độ nhà phát triển) ở góc trên phải.
3. Bấm **Load unpacked** (Tải tiện ích đã giải nén) → chọn thư mục **`D:\DFlow\extension`** → **Select Folder**.
4. Thấy ô **DFlow Bridge** hiện ra là được. Bấm biểu tượng mảnh ghép 🧩 trên thanh Chrome → ghim 📌 DFlow Bridge cho dễ thấy.
5. Quay lại tab **flow.google.com** và bấm **F5** để tải lại.

#### Bước 9 — Mở DFlow và cài đặt

1. Mở tab mới, vào **http://localhost:5174**.
2. Đăng nhập bằng tên + mật khẩu DFlow được cấp.
3. Lần đầu sẽ hiện hộp **AI Providers**: chọn **Claude** cho cả ba mục rồi bấm **Áp dụng thay đổi**. (Sau này muốn đổi AI: **⚙ Cài đặt → 🤖 AI viết**.)
4. Vào **⚙ Cài đặt** (cuối menu bên trái):
   - Tab **🔑 Gemini key**: vào aistudio.google.com/apikey → **Create API key** → copy → dán vào ô → Lưu. Có nhiều tài khoản Google thì tạo
     mỗi tài khoản một key và dán hết (key miễn phí có giới hạn lượt mỗi ngày).
   - Tab **⚡ Google Flow**: kiểm tra project đã đúng mã ở Bước 6.

**Xong!** Vào **Clip của tôi** → **Clip mới** để làm clip đầu tiên.

---

## 4. Mỗi ngày dùng thế nào

**Cài bằng file cài đặt (Cách 1)**: mở **DFlow** từ menu Start / màn hình, mở tab flow.google.com trong Chrome — vậy thôi.

**Chạy từ mã nguồn (Cách 2) — tạo lối tắt trên màn hình** (làm một lần) — dán lệnh này vào PowerShell (đổi `D:\DFlow` nếu bạn để chỗ khác):

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop') + '\DFlow.lnk')
$s.TargetPath = 'powershell.exe'
$s.Arguments = '-ExecutionPolicy Bypass -NoExit -File "D:\DFlow\start.ps1"'
$s.WorkingDirectory = 'D:\DFlow'
$s.IconLocation = 'D:\DFlow\frontend\public\favicon.ico'
$s.Save()
```

Từ đó mỗi ngày:

1. Bấm đúp biểu tượng **DFlow** trên màn hình → chờ tới dòng `Application startup complete`. Giữ cửa sổ đó mở.
2. Mở Chrome: một tab **flow.google.com** (đã đăng nhập) và một tab **http://localhost:5174**.
3. Dùng xong: đóng cửa sổ DFlow (hoặc bấm **Ctrl + C** trong cửa sổ đó).

## 5. Cập nhật bản mới

Khi được báo có bản mới: **tắt DFlow** (đóng cửa sổ), mở PowerShell rồi chạy:

```powershell
cd D:\DFlow
git pull
```

Rồi mở lại DFlow như bình thường — nó tự cài thêm những gì bản mới cần. Nếu cửa sổ DFlow có dòng vàng `Extension : changed`, vào `chrome://extensions`
bấm nút **tải lại** (↻) ở ô DFlow Bridge, rồi F5 tab Flow.

---

## 6. Cài thêm theo nhu cầu

### 6.1 Tải video từ link

Cho các ô dán link TikTok, YouTube, Instagram, Facebook (link Douyin chạy sẵn, không cần cài):

```powershell
winget install -e --id yt-dlp.yt-dlp --accept-source-agreements --accept-package-agreements
```

Rồi tắt DFlow và mở lại.

### 6.2 Lồng tiếng video, xoá phụ đề AI, giọng VieNeu

Phần này nặng (nhận dạng giọng nói, tách nhạc, xoá chữ bằng AI), chạy bằng bộ **VieDub (pyvideotrans)** cài riêng. **Nên có card đồ hoạ NVIDIA**
(không có vẫn chạy, nhưng chậm hơn nhiều) và thêm khoảng 15 GB ổ cứng. Nếu không rành, nhờ người cài DFlow làm giúp phần này.

1. Tải và cài VieDub (pyvideotrans) theo hướng dẫn trong kho VieDub, để ở `D:\codes\pyvideotrans`.
2. Mở VieDub, lồng tiếng thử **một** video để nó tự tải các mô hình về thư mục `models\`:
   - nhận dạng giọng nói Whisper `models--mobiuslabsgmbh--faster-whisper-large-v3-turbo` (bắt buộc, ~1,6 GB);
   - tách nhạc nền `onnx\vocals.fp16.onnx`, `onnx\accompaniment.fp16.onnx` (cho ô "Giữ nhạc nền");
   - xoá phụ đề `lama\big-lama.pt`;
   - giọng VieNeu: tự tải lần đầu dùng (~580 MB).
3. Nếu VieDub **không** nằm ở `D:\codes\pyvideotrans`: mở file cấu hình bằng `notepad D:\DFlow\.env`, thêm 2 dòng dưới cùng (thay đường dẫn cho đúng),
   lưu lại, tắt DFlow mở lại:

   ```
   FLOWBOARD_ERASE_ROOT=E:\VieDub
   FLOWBOARD_ERASE_PYTHON=E:\VieDub\.venv\Scripts\python.exe
   ```

Trang **Lồng tiếng video** tự báo còn thiếu gì. Không cài phần này thì các tính năng khác vẫn chạy bình thường.

### 6.3 Edit auto CapCut

1. Cài **CapCut bản máy tính** (capcut.com).
2. Mở một dự án CapCut, gõ vài dòng chữ theo kiểu bạn hay dùng: một dòng ghi **Phụ đề**, một dòng ghi **Nhấn mạnh**, một dòng ghi **Tiêu đề**, kéo vài
   hiệu ứng âm thanh vào. **Đóng CapCut**.
3. Trong DFlow vào **Edit auto CapCut** → bấm **Học** — DFlow học kiểu chữ và âm thanh của bạn.

### 6.4 Tự đăng Facebook Page

Cần một "mã truy cập" (token) của Page, lấy một lần từ trang dành cho nhà phát triển của Facebook (developers.facebook.com): tạo app → chọn
"Quản lý mọi thứ trên Trang" → lấy token có quyền `pages_show_list`, `pages_manage_posts`, `pages_read_engagement`, `pages_manage_engagement`
(thêm `read_insights` để xem lượt xem) → gia hạn thành token dài hạn → dán vào DFlow ở **Kênh của tôi → Tự đăng lên Facebook Page**.
Các bước này hơi rắc rối — nhờ người cài làm giúp. Chi tiết từng bước: [CLAUDE.md](CLAUDE.md), mục "Lấy token Facebook Page".

### 6.5 Dùng chung dữ liệu trên nhiều máy

Để mở DFlow ở máy nào cũng thấy cùng sản phẩm, clip, bài viết… (và để đăng nhập được bằng tài khoản người quản lý tạo): người quản lý gửi riêng
cho bạn một dòng bắt đầu bằng `postgresql://` hoặc `FLOWBOARD_CENTRAL_DB_URL=` (**giữ bí mật**, đừng đăng lên đâu).

- **Bản app (Cách 1)**: ở trang đăng nhập bấm **🌐 Dán dòng kết nối trước** → dán → **Kết nối** (app tự khởi động lại). Đã đăng nhập rồi thì đổi ở
  **⚙ Cài đặt → 🖥 Máy này → Dùng chung dữ liệu**.
- **Chạy từ mã nguồn (Cách 2)**: cũng dán ở trang đăng nhập được (xong tắt DFlow, chạy lại `start.ps1`), hoặc mở `notepad D:\DFlow\.env`, dán dòng
  đó xuống cuối, lưu, tắt DFlow mở lại rồi đăng nhập.

### 6.6 Cấp tài khoản cho người khác (chỉ người quản lý)

Chỉ tài khoản **quản trị** (`akiragosho`) thấy menu **👥 Quản lý tài khoản** (nhóm Nâng cao). Mỗi tài khoản có dữ liệu riêng — không ai thấy của ai.

1. **👥 Quản lý tài khoản → Tạo tài khoản cho người khác**: gõ tên đăng nhập (chữ không dấu, số, `.` `_` `-`), mật khẩu (🎲 tạo ngẫu nhiên),
   ghi chú (ai dùng, hết hạn khi nào) → **Tạo tài khoản** → **📋 Copy để gửi** (mật khẩu chỉ hiện lúc này).
2. Gửi cho họ: thông tin đăng nhập vừa copy + **dòng kết nối dữ liệu** (dòng `FLOWBOARD_CENTRAL_DB_URL=…` trong file `.env` của bạn) + link file cài
   **github.com/hoangduytn1703/dflow-releases/releases**.
3. Họ quên mật khẩu → **🔑 Đặt lại mật khẩu** (copy luôn thông tin mới để gửi). Ngừng cho dùng → **🔒 Khoá** (họ bị đăng xuất, không đăng nhập được;
   dữ liệu giữ nguyên, **🔓 Mở khoá** là dùng lại). **⎋ Đăng xuất mọi máy** khi nghi lộ mật khẩu.

Người khác chỉ đổi được mật khẩu của chính họ (nút **Đổi mật khẩu** ở góc dưới trái).

> **Lưu ý bảo mật**: dòng kết nối dữ liệu cho **toàn quyền** với cơ sở dữ liệu (người rành kỹ thuật đọc được dữ liệu của mọi tài khoản). Chỉ gửi
> cho người bạn tin. Đổi mật khẩu quản trị ngay sau khi cài (mật khẩu mặc định ghi trong mã nguồn).

---

## 7. Gặp lỗi thì làm gì

| Bạn thấy | Cách sửa |
|---|---|
| `winget is not recognized` | Cài / cập nhật **App Installer** trong Microsoft Store (Bước 2) |
| `uv` / `node` / `git` / `gh` `is not recognized` ngay sau khi cài | Đóng PowerShell, mở lại |
| `running scripts is disabled on this system` | Dùng đúng lệnh có `-ExecutionPolicy Bypass` như Bước 7, hoặc lối tắt ở Mục 4 |
| `Could not resolve to a Repository` khi tải code | Tài khoản GitHub chưa được mời vào kho (Bước 5) |
| Trang `localhost:5174` không mở được | Cửa sổ DFlow còn mở không? Lần đầu chờ cài xong (5–10 phút) rồi F5 |
| `Could not create agent\.venv` | uv chưa cài được — làm lại Bước 2, đóng mở lại PowerShell |
| `ffmpeg is not on PATH` | `winget install -e --id Gyan.FFmpeg`, rồi đóng mở lại PowerShell |
| Tài khoản được cấp báo *"Sai tên đăng nhập hoặc mật khẩu"* | Máy này chưa nối dữ liệu cloud: ở trang đăng nhập bấm **🌐 Dán dòng kết nối trước** (Mục 6.5) |
| *"Tài khoản này đã bị khoá"* | Hỏi người quản lý DFlow mở khoá |
| Quên mật khẩu | Nhờ người quản lý **🔑 Đặt lại mật khẩu** (Mục 6.6) |
| App báo **mất kết nối extension** | Kiểm tra DFlow Bridge đang bật ở `chrome://extensions` (bấm ↻ tải lại), tab flow.google.com còn mở, rồi F5 tab Flow |
| AI không viết được / báo lỗi AI | **⚙ Cài đặt → 🤖 AI viết** đã chọn Claude chưa; chạy `claude` trong PowerShell xem còn đăng nhập không, gói Claude còn lượt không |
| Tạo ảnh / video báo lỗi, "Flow bỏ lượt" | Tab Flow đúng tài khoản có gói Pro / Ultra; Cài đặt → Google Flow đúng project; ở Bước 1 của clip bấm "🎬 Kiểm tra với Flow" xem người mẫu có bị chặn không |
| Báo hết lượt Gemini | Thêm Gemini key từ tài khoản Google khác (Cài đặt → Gemini key) |
| Lồng tiếng báo "chưa dùng được" | Chưa cài bộ VieDub — xem Mục 6.2 |

Vẫn không được: chụp màn hình cửa sổ DFlow (PowerShell) và trang báo lỗi, gửi cho người hỗ trợ.

---

## 8. Dành cho dev

- Code: `agent/` (Python, FastAPI + SQLModel), `frontend/` (React + Vite), `extension/` (Chrome MV3), `desktop/` (vỏ app Tauri 2). Tên trong code vẫn là `flowboard`.
- App desktop: `agent/packaging/` (PyInstaller → `dflow-agent.exe`, agent tự phục vụ giao diện đã build qua `FLOWBOARD_WEB_DIR`), `desktop/src-tauri/` (chạy agent ngầm, khay hệ thống, một instance). Bộ cài build trên GitHub Actions (`.github/workflows/desktop.yml`): Actions → Desktop app → Run workflow, hoặc đẩy tag `v*` để có Release.
- Cổng cố định (đừng đổi — extension và Vite ghi cứng): giao diện **5174**, API **8434**, WebSocket extension **8355**. Chạy song song được với flowkit (5173 / 8100 / 9222).
- Linux / macOS:

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh   # uv vào ~/.local/bin, không cần sudo
  make install            # agent/.venv + frontend/node_modules
  cp .env.example .env    # FLOWBOARD_FLOW_PROJECT_ID, FLOWBOARD_PAYGATE_TIER (TIER_ONE = Pro, TIER_TWO = Ultra)
  make agent              # API :8434, WebSocket extension :8355
  make frontend           # giao diện :5174 (terminal khác)
  ```

- Test: `cd agent && .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests` (Windows; Linux `.venv/bin/python`). Typecheck: `cd frontend && npx tsc -b --noEmit`.
- Cấu hình máy nằm ở `.env` (không commit); bí mật của tài khoản (key AI, token Page, bucket) nằm trong kho trung tâm, nhập qua Cài đặt.
- Ghi chú đầy đủ cho người phát triển — cách chạy, cấu trúc code, các bẫy đã gặp, nhật ký thay đổi: **[CLAUDE.md](CLAUDE.md)**.

---

© 2026 DuyNH
