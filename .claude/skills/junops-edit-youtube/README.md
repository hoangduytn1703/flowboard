# Skill JunOps — bản YouTube (junops-edit-youtube)

Skill để **Claude edit video ngang dài trong CapCut**: cắt ghép, phụ đề theo câu, zoom ở chỗ cắt cảnh, zoom vào chỗ nói quan trọng, chữ quan trọng không đè mặt, SFX.

👉 **Hướng dẫn cài đặt và sử dụng đầy đủ nằm ở file `HUONG_DAN_CAI_DAT_VA_SU_DUNG` (đi kèm trong gói).** Đọc file đó trước.

Tóm tắt rất ngắn:
1. Chép **cả hai** thư mục `junops-edit-capcut` và `junops-edit-youtube` vào `.claude\skills\` trong thư mục làm việc của Claude.
2. Nhắn Claude: "cài giúp mình các công cụ cần cho skill junops-edit-capcut và junops-edit-youtube".
3. Mỗi video: tạo dự án CapCut + kéo video thô vào + đóng CapCut + nhắn Claude "edit video YouTube này, dự án <tên>".

Bên trong:
```
junops-edit-youtube/
  SKILL.md          hướng dẫn cho Claude
  README.md         file này
  LICENSE
  references/PHONG_CACH_YOUTUBE.md   gợi ý phong cách
  scripts/youtube_junops.py          phu-de-cau · zoom-noi · zoom-chu · chu-quan-trong · kiem
```
Skill dùng chung công cụ cắt/ghi/chép lời của `junops-edit-capcut` (phải nằm cạnh).
