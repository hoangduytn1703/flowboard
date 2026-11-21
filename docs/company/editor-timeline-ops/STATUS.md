# STATUS — editor-timeline-ops
- Phase: 1 (brief) viết xong, chờ G1.
- Decisions: chưa có — chờ director trả lời 3 câu ở cuối `01-brief.md` (ý nghĩa "lớp phủ", hướng kiến trúc A/B,
  làm cả 3 hay theo slice).
- Rà nhanh đã làm: `dub.Job` hiện là single-source (`src_path`), lớp phủ dựng bằng một `-filter_complex` duy nhất;
  "✂️ Cắt" tạo N job/clip riêng (không phải N đoạn trong 1 timeline); có sẵn `video_concat.concat_video_assets`
  (ffmpeg concat demuxer, dùng cho Bước 5 Quicktool) có thể tái dùng; timeline dùng `@xzdarcy/timeline-engine`,
  hàng phụ đề (cue) đã kéo/cắt được — khuôn mẫu UI cho khối video sau này.
- Chưa làm gì ở code. Không có demo nào đang chạy.
- Next: director duyệt G1 → phase 2 (PRD).
