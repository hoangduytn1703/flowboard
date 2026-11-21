# Brief — editor-timeline-ops

## Hiện trạng code (rà nhanh trước khi viết brief)

- Trình chỉnh sửa kiểu CapCut (trang 🎞 Chỉnh sửa video / Cắt video / Lồng tiếng dùng chung: `DubEditor.tsx`) đang
  vận hành trên **MỘT** `dub.Job` = **MỘT** video nguồn (`Job.src_path` / `source_media_id`, số ít). Mọi thứ khác
  (phụ đề `Segment` — tên trùng với "đoạn", nhưng thực ra là CÂU phụ đề có mốc giờ; vùng mờ, khung, nhân vật, chữ,
  nhấn chữ quan trọng) là **lớp phủ lên trên một luồng video duy nhất**, dựng bằng một `-filter_complex` ffmpeg:
  `[0:v]` → sáng/tối → zoom → khung xuất (canvas) → khung trang trí (frame) → vùng mờ → nhân vật (mascot) → phụ đề
  (ass). Vùng mờ / khung / nhân vật áp **cả clip**, không theo mốc giờ; chỉ phụ đề và chỗ nhấn chữ có mốc giờ riêng.
- Timeline dùng `@xzdarcy/timeline-engine` (`EditorTimeline.tsx`): hàng "Video" hiện tại chỉ là **một dải phim nền
  tĩnh, không kéo/cắt được** (`movable: false, flexible: false`); hàng phụ đề (cue) **đã** kéo/cắt/resize được
  (`onActionResizeEnd`, `onTiming`) — đây là khuôn mẫu UI có sẵn để tái dùng cho khối video.
- "✂️ Cắt video" (`dub_split.py`, `video_cut.py`) cắt MỘT video thành **N video RIÊNG BIỆT** (N `dub.Job` + N clip
  khác nhau trong thư viện) — không phải N đoạn trong CÙNG một timeline có thể sửa qua lại.
- Có sẵn logic ghép nhiều clip khác nhau thành MỘT video liên tục ở nơi khác: `video_concat.concat_video_assets`
  (ffmpeg concat demuxer, `-c copy` khi hợp cỡ, re-encode khi lệch tỉ lệ qua `fit_filter`/`common_size`) — dùng cho
  Bước 5 Quicktool (ghép các cảnh), **không** dùng cho trình chỉnh sửa CapCut-style. Đây là nền có thể tái dùng.
- Việc này đã được ghi nhận thiếu từ đợt 1 (10/11) trong CLAUDE.md → "Việc đang dở": *"cắt / xoá một đoạn video
  trên timeline (hiện chỉ cắt thành nhiều clip ở tab ✂️ Cắt)"* + *"chữ / sticker tự do nhiều lớp"* + *"lớp có thời
  lượng riêng (vùng mờ / nhân vật vẫn cả clip)"*.

## Mục tiêu

Cho trình chỉnh sửa video của DFlow khả năng sửa **thân video** như CapCut, không chỉ sửa lớp phủ trên một video có
sẵn:
1. **Xoá một đoạn** trong video đang chỉnh (ripple delete — xoá xong phần sau dồn lên, không để khoảng trống).
2. **Chèn một đoạn video khác** vào giữa timeline (từ máy, từ Clip của tôi, hoặc từ một video đã tải khác) — phần
   sau bị đẩy lùi lại đúng bằng độ dài đoạn chèn.
3. **Lớp phủ** (overlay) — cần director xác nhận ý chính xác (xem mục "Cần bạn quyết" ở cuối), nhưng hướng hiểu mặc
   định: thêm một video/ảnh nhỏ nổi lên trên video chính (kiểu picture-in-picture / sticker) ở MỘT KHOẢNG THỜI
   GIAN nhất định, kéo được vị trí/cỡ như nhân vật hiện có nhưng có **thời điểm bắt đầu/kết thúc riêng** (khác với
   nhân vật hiện tại vốn áp cả clip).

## Người dùng

Chính director (admin/akiragosho) và các tài khoản VIP/Pro/Premium dùng trang Lồng tiếng / Cắt video / Chỉnh sửa
video để biên tập clip trước khi đăng — cùng nhóm người dùng của menu "🎞 Chỉnh sửa video" đã có.

## Ràng buộc

- **Không rewrite kiến trúc hiện có** trừ khi được duyệt ở G3: giữ `dub.Job` là đơn vị chỉnh sửa, giữ render
  pipeline ffmpeg hiện tại cho mọi lớp phủ đã có (phụ đề, vùng mờ, khung, nhân vật, chữ, nhấn chữ) — chỉ thêm khả
  năng sửa THÂN video, không viết lại các lớp phủ.
- Mọi thứ có mốc giờ hiện có (câu phụ đề, điểm nhấn chữ, "secs" của lớp chữ) phải **tự dời/tự xoá đúng** khi thân
  video bị xoá/chèn đoạn — không được để lệch thời gian sau khi sửa (đây là phần khó nhất, cần thiết kế kỹ ở G3).
- Dùng lại hạ tầng đã có khi hợp lý: `video_concat` (ghép/concat), khuôn mẫu kéo-resize của hàng "cue" trên
  timeline, cơ chế lưu tạm khi đổi clip (`DRAFTS` trong `DubEditor.tsx`).
- Test thật bằng ffmpeg (dựng file, đo bằng ffprobe/Pillow) như quy ước của dự án — không chỉ test đơn vị so chuỗi.
- Port cố định của dự án (flowboard UI 5174 / API 8434 / WS 8355) không được đổi.
- Không commit/push/deploy, không đụng dữ liệu thật của director — demo chạy trên agent riêng (cổng phụ, dữ liệu
  tạm) như các phase build trước.

## Thước đo thành công

- Mở một video bất kỳ trong trình chỉnh sửa → xoá được 1 đoạn giữa clip → xuất ra, đoạn đó biến mất, phần sau dồn
  liền mạch (không giật hình, không lệch tiếng), **phụ đề / chỗ nhấn chữ sau đoạn xoá vẫn đúng câu đúng lúc**.
- Chèn được 1 video khác vào giữa timeline → xuất ra, video mới nằm đúng chỗ, phần cũ sau điểm chèn lùi lại đúng
  bằng độ dài đoạn mới, phụ đề/chỗ nhấn vẫn đúng.
- Thêm được ít nhất 1 lớp phủ (hình/video nhỏ) có thời điểm bắt đầu/kết thúc riêng, kéo được vị trí/cỡ, xuất ra
  đúng như xem trước.
- Toàn bộ qua được bằng ffmpeg thật (dựng file → đo pixel/khung hình), không có clip nào xuất ra bị lệch tiếng
  hoặc gãy khung hình.

## 2-3 hướng tiếp cận (cân nhắc ở G3, không cần quyết ngay)

**A. "Vật liệu hoá" (materialize) mỗi lần sửa thân video — rủi ro thấp nhất, tái dùng nhiều nhất**
Mỗi lần xoá/chèn đoạn, dựng một file nguồn MỚI bằng `video_concat`/ffmpeg concat (mảnh giữ lại của nguồn cũ + đoạn
chèn, nếu có) rồi gán làm `src_path` mới của job — y hệt cách clip ghép của Quicktool đã làm. Toàn bộ pipeline lớp
phủ (`video_filter`, ASS, vùng mờ, khung, nhân vật...) **giữ nguyên 100 %**, chỉ nhận một nguồn khác dài khác. Dời
mốc giờ của câu phụ đề / chỗ nhấn / "secs" chữ theo kiểu cộng/trừ offset tại điểm sửa (giống `_timeline_cues` đã
làm khi ghép nhiều clip ở Quicktool). *Ưu:* an toàn, không đụng filter_complex hiện có, dễ kiểm bằng ffmpeg thật.
*Nhược:* mỗi lần sửa thân video phải dựng lại file trung gian (chờ vài giây), không "preview tức thời" trong
trình duyệt như kéo thả phụ đề hiện nay — xem trước trong editor phải tạm chấp nhận độ trễ hoặc dùng cách B cho
riêng phần xem trước.

**B. Danh sách "clip" trong `Job`, dựng timeline multi-input lúc xuất, xem trước ghép nối trên trình duyệt**
Thêm `Job.clips: [{source_media_id, trim_in, trim_out}]` thay cho `src_path` đơn; lúc xuất, `video_filter` nhận N
input video + `concat` filter (hoặc vẫn pre-concat như A nhưng chỉ ở bước xuất, không ở mỗi lần sửa) dựng lại một
luồng `[0:v]` ảo cho các bước phía sau dùng tiếp. Phía trình duyệt: `EditorStage` phát nối tiếp nhiều `<video>`/
nguồn theo clip list thay vì 1 file — xem trước mượt hơn A, không phải dựng file trung gian khi kéo/xoá/chèn.
*Ưu:* trải nghiệm sửa mượt hơn, đúng kiểu CapCut thật. *Nhược:* đổi mô hình dữ liệu cốt lõi của `Job`, đổi cả
`EditorStage` (phát video) lẫn phần dựng ffmpeg lúc xuất — nhiều rủi ro hơn, nhiều file phải sửa hơn (ảnh hưởng cả
Lồng tiếng / Cắt video / Chỉnh sửa video vì dùng chung `dub.Job`).

**C. Làm trước ở phạm vi hẹp: chỉ "xoá đoạn" (không chèn, không overlay) bằng cách B nhưng rút gọn**
Nếu muốn thấy kết quả nhanh trước khi cam kết kiến trúc lớn: làm "xoá đoạn" trước (dễ nhất — xoá là ghép 2 mảnh
còn lại, không cần "chèn nguồn ngoài"), theo hướng A. "Chèn đoạn" + "lớp phủ" làm sau, mỗi cái một slice riêng.
*Khuyến nghị của em*: làm theo thứ tự C → A, tức **slice 1 = xoá đoạn (hướng A)**, **slice 2 = chèn đoạn (hướng
A, mở rộng)**, **slice 3 = lớp phủ** (tách biệt, không phụ thuộc A/B vì lớp phủ không đổi thân video — chỉ cần
thêm time-range cho mascot-như hiện có). Việc "xem trước mượt như CapCut thật" (hướng B) để sau, khi director đã
thấy A chạy ổn và muốn đầu tư thêm.

## Cần bạn quyết (G1)

1. **"Lớp phủ" là gì chính xác?** Em hiểu mặc định = thêm 1 ảnh/video nhỏ đè lên video chính trong MỘT khoảng thời
   gian (kéo vị trí/cỡ, có start/end riêng) — khác nhân vật hiện có (luôn cả clip). Đúng ý anh không, hay anh
   muốn khác (ví dụ: nhiều lớp chữ/sticker time-range như CapCut, không phải video/ảnh)?
2. **Chọn hướng kiến trúc**: em khuyến nghị **hướng A** (vật liệu hoá, tái dùng `video_concat`, ít rủi ro, xem
   trước có thể hơi trễ 1-2 giây sau mỗi lần sửa) thay vì hướng B (mô hình multi-clip đầy đủ như CapCut thật,
   rủi ro cao hơn, sửa nhiều hơn) — có cần làm ngay hướng B để xem trước mượt như CapCut, hay chấp nhận A trước?
3. **Phạm vi đợt này**: làm cả 3 (xoá / chèn / lớp phủ) hay làm theo từng slice có demo riêng (C → A, như khuyến
   nghị ở trên) rồi anh duyệt tiếp từng bước?

## Rủi ro / chưa kiểm chứng ở bước này

- Dời mốc giờ của mọi lớp có "thời điểm" (câu phụ đề, điểm nhấn chữ quan trọng, "secs" của lớp chữ 🔤) khi xoá/
  chèn đoạn là phần dễ sai nhất — cần thiết kế kỹ thuật cụ thể ở G3, có test ffmpeg thật kèm theo.
- Chưa rõ performance khi video dài (vài phút, hàng trăm câu phụ đề) — dựng lại nguồn mỗi lần sửa (hướng A) có
  thể chậm nếu không cache đúng, cần đo thật ở phase 4.
