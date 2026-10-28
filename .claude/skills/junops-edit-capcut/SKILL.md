---
name: junops-edit-capcut
description: Skill JunOps — để Claude edit video ngay trong CapCut bản máy tính (Windows). Cắt chỗ nói vấp và khoảng lặng, thêm phụ đề, chữ nhấn mạnh, hiệu ứng âm thanh (SFX), zoom in/zoom out vào những chữ quan trọng. Mọi thứ được ghi thẳng vào dự án CapCut thật nên người dùng mở CapCut lên sửa lại được. Dùng khi người dùng nói "edit video này", "dựng video trong CapCut", "thêm phụ đề / chữ nhấn mạnh / SFX / zoom", "cắt chỗ nói vấp", "cắt khoảng lặng", "học phong cách edit của mình".
---

# Chào mừng bạn đã sử dụng skill JunOps

Skill này giúp Claude edit video trong **CapCut bản máy tính**: ghi thẳng vào file dự án CapCut, nên bạn mở CapCut lên vẫn kéo, cắt, đổi chữ, xoá được như video bình thường.

**Tính năng cơ bản:** cắt chỗ nói vấp và khoảng lặng · phụ đề · chữ nhấn mạnh · hiệu ứng âm thanh (SFX) · font · zoom in / zoom out.

**Không có sẵn:** font, SFX, nhạc, hay kiểu chữ nào kèm theo skill. Skill chỉ dùng những gì **đã có trong CapCut của chính bạn** (Claude tự quét và chọn, hoặc bạn chỉ định). Skill cũng **không tách nền**.

## Lần đầu dùng (làm một lần)

1. `python scripts/cai_dat.py` (thêm `--cai` để tự cài phần thiếu). Cần: Python 3.9+, CapCut bản máy tính, ffmpeg, faster-whisper.
2. Đảm bảo CapCut của bạn đã từng dùng ít nhất **1–2 dòng chữ** (đúng font/màu bạn thích) và **vài hiệu ứng âm thanh**. Chưa có thì mở CapCut, thêm vào bất kỳ dự án nào, rồi **đóng CapCut**.
3. `python scripts/junops_capcut.py hoc` để quét kiểu chữ + SFX trong CapCut của bạn, rồi `mau` để xem danh sách. Dùng `chon --phu-de t2 --nhan-manh t5` nếu muốn đổi kiểu chữ phụ đề / chữ nhấn mạnh.

## Mỗi video (Claude làm theo thứ tự)

0. **Xác nhận đầu vào với người dùng:** tên dự án CapCut (đã tạo, đã kéo video thô vào dòng thời gian), dòng thời gian được phép sửa (mặc định: dòng trống hoặc một bản sao, KHÔNG sửa bản đã chốt), có kịch bản không. Nhắc người dùng **đóng hẳn CapCut** (chờ vài chục giây).
1. **Chép lời:** `python scripts/chep_loi.py "<video thô>"` → đọc file `_loi.txt`.
2. **Chọn đoạn giữ lại:** mỗi câu chọn **lần nói trơn nhất (thường là lần nói sau cùng)**, bỏ lần nói vấp/hụt, bỏ khoảng lặng dài. Có thể bắt đầu bằng `python scripts/tao_edl_bo_lang.py <file_loi.json>` rồi sửa `edl.json` bằng tay. **Cho người dùng xem danh sách giữ/bỏ và chờ duyệt** trước khi ghi.
3. **Ghi các đoạn đã cắt:** `python scripts/junops_capcut.py cat "<dự án>" --edl edl.json --dry-run`, thấy ổn thì bỏ `--dry-run`. Lệnh này tạo `ban_do_cat.json` (giây video thô ↔ giây dòng thời gian).
4. **Phụ đề tự động:** `python scripts/tao_phu_de.py <file_loi.json> ban_do_cat.json` → `plan_phu_de.json`.
5. **Chữ nhấn mạnh, SFX, zoom:** tự viết `plan.json` (mẫu bên dưới). Mốc thời gian trong plan là **giây trên dòng thời gian SAU khi cắt**: đổi từ giây trong lời gốc bằng `python scripts/doi_moc.py ban_do_cat.json <giây thô>`.
6. **Ghi:** `python scripts/junops_capcut.py apply "<dự án>" --plan plan.json --dry-run` rồi chạy thật (gộp `plan_phu_de.json` vào `plan.json` hoặc chạy lần lượt).
7. **Người dùng mở CapCut xem, sửa tay nếu cần, rồi xuất.** Sau khi xuất: `python scripts/kiem_tra.py <video.mp4>`.

### Mẫu plan.json
```json
{"ops": [
  {"op": "chu", "mau": "nhan_manh", "start": 3.0, "dur": 1.2, "text": "TỪ QUAN TRỌNG"},
  {"op": "chu", "mau": "phu_de",    "start": 5.0, "dur": 2.0, "text": "câu phụ đề"},
  {"op": "sfx",  "at": 3.0},
  {"op": "sfx",  "at": 5.0, "mau": "s2", "volume": 0.25},
  {"op": "zoom", "at": 10.0, "muc": 1.15, "giu": 1.0, "vao": 0.3, "ra": 0.4}
]}
```
- `chu`: `mau` là `phu_de`, `nhan_manh`, `chu_to` hoặc id kiểu chữ (t1, t2…). Tuỳ chọn `x`, `y`, `scale`.
- `sfx`: `mau` bỏ trống/`auto` = tự lấy lần lượt trong kho SFX của người dùng (không lặp liền nhau); hoặc id (s1, s2…).
- `zoom`: phóng to rồi trả về cũ ở đoạn video chính đang chạy tại `at` (dạng đầy đủ: `points` = [[giây, tỉ lệ], …]).

## Gợi ý phong cách (mặc định, người dùng đổi tuỳ ý)

- **Phụ đề:** mỗi dòng **tối đa 4 chữ**, đặt giữa khung hình; một cụm quan trọng mỗi dòng nhấn màu khác.
- **Chữ nhấn mạnh:** chỉ dùng cho 1–2 từ quan trọng nhất của câu, không lạm dụng.
- **Zoom:** zoom vào đúng lúc người nói nhắc **chữ quan trọng**, mức 1,10–1,20; không zoom liên tục (người xem dễ chóng mặt).
- **SFX:** nhỏ (volume khoảng 0,2–0,35), mỗi lần một tiếng, không để nhiều tiếng giống nhau liền nhau.
- Chi tiết thêm: `references/PHONG_CACH_GOI_Y.md`.

## Luật an toàn (bắt buộc)

1. **Đóng hẳn CapCut khi ghi.** Công cụ từ chối ghi nếu CapCut đang mở (CapCut sẽ ghi đè phần vừa làm khi đóng).
2. **Luôn có backup** trong `<dự án>/_backup_junops/<giờ>_<việc>`; lỗi thì chép file trong đó đè lại.
3. `apply` chỉ **thêm** chữ/SFX/zoom, không xoá hay sửa đoạn có sẵn. `cat` thay các đoạn của track video chính bằng các đoạn đã cắt (cần backup, đã tự làm). Lần đầu hãy thử trên một dự án nháp hoặc bản sao.
4. Người dùng vừa sửa tay trong CapCut thì phải đóng CapCut trước khi Claude ghi tiếp.

## Giới hạn cần nói thẳng

- Chỉ **CapCut bản máy tính trên Windows** đã thử. CapCut cập nhật có thể đổi cách lưu file khiến công cụ cần chỉnh lại.
- Máy chép lời có thể **nghe sai tên riêng và chữ tiếng Anh**; mốc chữ chỉ gần đúng → vẫn cần nghe lại và xem lại phụ đề.
- `kiem_tra.py` chỉ bắt khung đen/đứng hình, **không** bắt được chữ sai chính tả, chữ đè lên mặt, hay cảnh không hợp lời nói → người dùng xem lại bằng mắt.
- `cat` chỉ cắt track video chính; track âm thanh/video khác (lồng tiếng, B-roll) không tự cắt theo.
- Claude **không nghe được âm thanh**; mọi quyết định về lời nói dựa vào bản chép lời.

## Học từ chỉnh sửa của người dùng

Khi người dùng sửa tay xong và **đóng CapCut**: dùng `python scripts/junops_capcut.py analyze "<dự án>"` để đọc lại, so với bản Claude làm, rồi ghi sở thích mới (cỡ chữ, vị trí, mức zoom, tiếng SFX bị bỏ…) vào `du_lieu/so_thich.md` để lần sau làm theo.
