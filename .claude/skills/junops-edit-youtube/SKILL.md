---
name: junops-edit-youtube
description: Skill JunOps bản YOUTUBE — để Claude edit VIDEO NGANG DÀI (16:9) ngay trong CapCut bản máy tính (Windows). Cắt ghép chỗ nói vấp và khoảng lặng, phụ đề theo từng CÂU (chữ trắng), phóng to/thu nhỏ xen kẽ ở các chỗ cắt cảnh, zoom vào những chỗ nói quan trọng, chữ quan trọng hiện lên KHÔNG đè mặt, SFX nhỏ xoay vòng. Dùng chung công cụ chép lời/cắt/ghi của skill junops-edit-capcut. Dùng khi người dùng nói "edit video YouTube", "video dài", "video ngang", "phụ đề cả câu", "zoom khi cắt cảnh", "chữ quan trọng không đè mặt". KHÔNG dùng cho video dọc TikTok/Shorts — đó là skill junops-edit-capcut.
---

# Chào mừng bạn đã sử dụng skill JunOps — bản YouTube

Giống bản TikTok nhưng cho **video ngang dài**. Mọi thứ ghi thẳng vào dự án CapCut thật nên bạn mở CapCut lên vẫn kéo, cắt, đổi chữ, xoá được.

**Có gì khác bản TikTok:**
- Phụ đề mỗi lần hiện **cả một câu** (dài quá thì tách 2 lần hiện), chữ **trắng** — không cắt vụn 4 chữ.
- **Zoom ở chỗ cắt cảnh:** các đoạn kề nhau xen kẽ cỡ khung (vd 100% → 112% → 100% → 122%) để chỗ cắt trông như đổi góc máy.
- **Zoom vào chỗ nói quan trọng:** phóng nhẹ rồi trả về, tính theo cỡ khung của đoạn đó.
- **Chữ quan trọng** đặt ở phía đối diện khuôn mặt, không đè lên mặt.

**Không kèm sẵn** font, SFX, nhạc, hình nào — skill dùng đồ có sẵn trong CapCut của bạn. Không tách nền, không motion graphic.

**Cần skill `junops-edit-capcut` nằm cạnh** (dùng chung công cụ):
```
<thư mục làm việc>\.claude\skills\junops-edit-capcut\
<thư mục làm việc>\.claude\skills\junops-edit-youtube\
```

## Lần đầu dùng
Làm đúng phần "Lần đầu dùng" của skill `junops-edit-capcut` (cài công cụ; mở CapCut thêm 1–2 dòng chữ + vài SFX rồi đóng CapCut; chạy `hoc`). Skill này không cần cài thêm gì.

## Mỗi video (Claude làm theo thứ tự — luôn `--dry-run` xem trước, người dùng đồng ý mới ghi)

0. **Xác nhận đầu vào:** tên dự án CapCut (đã kéo video thô vào dòng thời gian), dòng thời gian được phép sửa (dòng trống/bản sao, KHÔNG sửa bản đã chốt), có kịch bản không. Nhắc người dùng **đóng hẳn CapCut**.
1. **Chép lời + cắt ghép** như skill `junops-edit-capcut` (`chep_loi.py` → chọn đoạn giữ → `junops_capcut.py cat`). Với YouTube **giữ nhịp thở tự nhiên**: chỉ bỏ khoảng lặng dài và lần nói vấp; nghỉ ~0,3 giây ở cuối mỗi ý, nối sát giữa câu; mỗi câu chọn lần nói trơn nhất (thường là lần sau cùng). Cho người dùng xem danh sách giữ/bỏ và chờ duyệt.
2. **Phụ đề theo câu:**
   `python scripts/youtube_junops.py phu-de-cau "<dự án>" --loi <file_loi.json> --ban-do ban_do_cat.json --dry-run` → xem vài dòng mẫu → bỏ `--dry-run`.
   Chữ trắng mặc định; muốn giữ màu kiểu chữ đã học: `--mau-chu giu`. Độ dài tối đa: `--toi-da 64`.
3. **Zoom ở chỗ cắt cảnh:** `python scripts/youtube_junops.py zoom-noi "<dự án>"` (đổi vòng cỡ khung bằng `--muc 1.0,1.12,1.0,1.22`). **Làm bước này trước bước 4.**
4. **Zoom vào chỗ nói quan trọng:** đổi giây trong lời sang giây dòng thời gian bằng `doi_moc.py`, rồi
   `python scripts/youtube_junops.py zoom-chu "<dự án>" --diem 12.5,31.0,58.2` (mặc định phóng thêm 12%, vào 0,3s, giữ 1s, ra 0,4s; tối đa 1,5 lần). Không zoom liên tục: tối đa ~4–5 chỗ mỗi phút, cách nhau ít nhất 5 giây.
5. **Chữ quan trọng không đè mặt:**
   - **Xem mặt người nói nằm ở đâu trong khung:** lấy một khung hình từ video thô (`ffmpeg -ss 5 -i "<video>" -frames:v 1 khung.jpg`) rồi mở ảnh xem; hoặc **hỏi người dùng** "bạn ngồi bên trái, giữa hay bên phải khung hình?".
   - Viết `chu.json`: `[{"at": 12.5, "dur": 1.5, "text": "TỪ QUAN TRỌNG"}]` (mỗi chữ tối đa 1–4 từ).
   - `python scripts/youtube_junops.py chu-quan-trong "<dự án>" --chu chu.json --mat trai|giua|phai` — `--mat` là phía **mặt đang ở**; chữ tự đặt phía đối diện (mặt ở giữa thì chữ luân phiên trái/phải). Có thể ghi đè từng chữ bằng `x`, `y` trong json.
   - Chỉ nhấn 1–2 từ quan trọng nhất của câu, không lạm dụng.
6. **SFX:** dùng `junops_capcut.py apply` như bản TikTok (plan.json, op `sfx` để `mau` tự xoay vòng). Mỗi lúc một tiếng, nhỏ (volume ~0,3), đặt ở chỗ cắt cảnh/chữ hiện.
7. **Kiểm tra:** `python scripts/youtube_junops.py kiem "<dự án>"`. Người dùng mở CapCut xem, sửa tay, xuất; sau đó `python ..\junops-edit-capcut\scripts\kiem_tra.py <video.mp4>` (khung đen/đứng hình).

Thứ tự chạy: **cắt → phụ đề → zoom-noi → zoom-chu → chữ quan trọng → SFX → kiểm tra.** Không chạy lại `zoom-noi` sau khi đã `zoom-chu` (phải khôi phục backup rồi làm lại theo thứ tự).

## Luật an toàn (bắt buộc)
1. **Đóng hẳn CapCut khi ghi** (công cụ từ chối ghi nếu CapCut đang mở).
2. Luôn **backup** trong `<dự án>/_backup_junops/<giờ>_<việc>`; lỗi thì chép file trong đó đè lại.
3. Lần đầu thử trên **dự án nháp / bản sao**. Người dùng sửa tay xong phải **đóng CapCut** trước khi Claude ghi tiếp; Claude đọc lại file hiện tại, không dựng đè lên phần người dùng đã sửa.

## Giới hạn cần nói thẳng
- Chỉ **CapCut bản máy tính trên Windows** đã thử; CapCut cập nhật lớn có thể đổi cách lưu file.
- Chép lời có thể nghe sai tên riêng/chữ tiếng Anh → xem lại phụ đề; mốc chữ chỉ gần đúng.
- Vị trí "không đè mặt" là **ước lượng theo phía mặt đang ở** — luôn xem lại trong CapCut, kéo chữ nếu cần.
- `zoom-noi` đổi cỡ khung của TỪNG đoạn video chính; nếu bạn đã chỉnh cỡ khung thủ công thì nó sẽ đè lên (có backup).
- Claude **không nghe được âm thanh**; mọi quyết định về lời nói dựa vào bản chép lời. Luôn xem lại video bằng mắt trước khi đăng.
