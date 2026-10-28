# Chào mừng bạn đã sử dụng skill JunOps

Skill giúp **Claude edit video ngay trong CapCut** (bản máy tính, Windows): cắt chỗ nói vấp, phụ đề, chữ nhấn mạnh, SFX, zoom in/out. Tất cả ghi thẳng vào dự án CapCut thật, bạn mở lên sửa lại được.

Font và SFX **không kèm theo**: skill dùng những gì có sẵn trong CapCut của bạn. Skill không tách nền.

## Cài đặt (làm một lần)

1. Cài **CapCut bản máy tính** và **ứng dụng Claude** trên máy. Đăng nhập cả hai.
2. Mở Claude, chọn **Claude Code**, chế độ **Local**, chọn một thư mục làm việc (ví dụ tên "EDIT VIDEO") và **cho phép** Claude đọc/ghi thư mục này.
3. Chép thư mục `junops-edit-capcut` (thư mục này) vào `.claude\skills\` bên trong thư mục làm việc vừa chọn. Cấu trúc đúng:
   ```
   EDIT VIDEO\.claude\skills\junops-edit-capcut\SKILL.md
   ```
4. Nhắn Claude: **"cài giúp mình các công cụ cần cho skill junops-edit-capcut"**. Claude sẽ kiểm tra Python, ffmpeg, faster-whisper và cài phần thiếu (lần đầu chạy sẽ tải mô hình chép lời tiếng Việt vài trăm MB).
5. Trong CapCut, dùng thử **1–2 dòng chữ** (đúng font/màu bạn thích) và **vài hiệu ứng âm thanh** trong bất kỳ dự án nào, rồi **đóng CapCut**. Claude sẽ quét những thứ này để làm theo phong cách của bạn.

## Mỗi video

1. Trong CapCut: tạo dự án mới, kéo **video thô** vào dòng thời gian, **đặt tên dự án**, rồi **đóng hẳn CapCut** (chờ vài chục giây).
2. Bỏ video thô (và kịch bản, nếu có) vào thư mục làm việc.
3. Nhắn Claude: **"edit video này"** kèm tên dự án CapCut.
4. Claude sẽ chép lời, đưa bạn danh sách đoạn giữ/bỏ để duyệt, rồi ghi vào CapCut: đoạn đã cắt, phụ đề, chữ nhấn mạnh, SFX, zoom.
5. Mở CapCut lên xem, sửa tay chỗ chưa ưng (nhớ **đóng CapCut** trước khi nhờ Claude ghi tiếp), rồi xuất file.

## Luật an toàn

- **Đóng hẳn CapCut mỗi khi Claude ghi vào dự án.** Nếu để mở, CapCut sẽ ghi đè phần Claude vừa làm.
- Claude luôn sao lưu vào thư mục `_backup_junops` trong dự án trước khi ghi.
- Lần đầu hãy thử trên một **dự án nháp**.

## Giới hạn

- Đã thử trên CapCut bản máy tính, Windows. CapCut cập nhật có thể làm công cụ cần chỉnh lại.
- Chép lời có thể nghe sai tên riêng, chữ tiếng Anh: bạn vẫn cần xem lại phụ đề.
- Bạn nên xem lại video bằng mắt trước khi đăng.

## Bên trong gói

```
junops-edit-capcut/
  SKILL.md            hướng dẫn cho Claude
  README.md           file này
  LICENSE
  references/         cách CapCut lưu dự án, gợi ý phong cách
  scripts/
    junops_capcut.py  đọc/ghi CapCut: list, analyze, hoc, mau, chon, cat, apply
    chep_loi.py       chép lời kèm mốc giây
    tao_edl_bo_lang.py  bỏ khoảng lặng
    tao_phu_de.py     phụ đề tự động
    doi_moc.py        đổi giây video thô sang giây dòng thời gian
    kiem_tra.py       kiểm tra khung đen / đứng hình
    cai_dat.py        kiểm tra và cài công cụ
```
