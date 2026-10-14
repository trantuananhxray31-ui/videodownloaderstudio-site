# Quy trình VDS mới: tạo thumbnail hàng loạt trên máy gốc

**Bộ HG_7681305157576952857 đã hoàn tất:** Google Drive có 428/428 JPEG theo mẫu duyệt, xác minh 428 tên riêng biệt và checksum MD5 của 117 ảnh được bổ sung. Đây là kết quả vận hành ngày 15/10/2026, không phải một tính năng tự động chạy từ GitHub.

## Từ phim tiếp theo: tuyệt đối không dùng render/upload JPEG từng cái trong phiên @1

Entrypoint: `fast_local_thumbnails.py` (chỉ cần Pillow), không dùng `workflow.py` AI/OCR và không phụ thuộc dữ liệu tạm trong @1.

1. Duyệt từng thư mục phim trong `reup`, **đối chiếu video thật** (không lấy từ danh sách thumbnail) và giữ nguyên HG ID. Mỗi thư mục phim dùng cấu hình JSON riêng. Nếu có phần/tập trùng hoặc video không có số tập rõ ràng, dừng thay vì đoán.
2. Chọn **2 ảnh mẫu riêng của đúng bộ phim**, mẫu ngang 1920×1080 và dọc 1080×1920; có thể truy tìm ảnh gốc trong thư mục tải/ảnh gốc hoặc Drive. Kiểm tra poster khớp phim, xác nhận `source_verified` và `approved_templates` **chỉ sau khi thật sự duyệt**.
3. Trên **máy có lưu trữ bền vững**, chạy một chương trình Pillow nhân bản ảnh mẫu và ghi nhãn số tập. 100 tập → 202 JPG gồm 2 ảnh PHIM. Không gọi AI cho từng ảnh, không bắt buộc chia phiên 180 giây.
4. Lưu đầy đủ JPG theo tên `TAP_001_16x9.jpg`, `TAP_001_9x16.jpg`, `PHIM_16x9.jpg` và `PHIM_9x16.jpg` trong `THUMBNAILS/<tên phim>`. Manifest nằm ở `THUMBNAILS/.thumbnail-state`, **ngoài thư mục ảnh** để không làm VDS nhận nhầm. Khi chạy lại, cùng MD5 được bỏ qua; khác MD5 dừng, không tự ghi đè/xóa.
5. Đồng bộ trực tiếp **các JPG**, không tải ZIP lên Drive rồi coi như đã giải nén. Dùng **rclone** được cấu hình OAuth riêng tại máy chạy, kiểm tra MD5/size trước và sau khi tải. Không để token/OAuth vào GitHub hoặc chat. Chỉ chạy một worker đồng bộ cho mỗi bộ. Mặc định **không tự upload**.
6. Trước khi đánh dấu hoàn tất, kiểm tra số file trên Drive, trùng tên, checksum, và thử VDS ghép thumbnail với video đầu/giữa/cuối.

## Cài đặt (PowerShell)

```powershell
cd thumbnail-workflow
py -m pip install -r requirements.batch.txt
Copy-Item fast_local.example.json film-001.json
# Sửa đường dẫn video reup, ảnh mẫu ĐÚNG PHIM, font, output_root
# Chỉ khi mẫu thực sự được duyệt: bật source_verified / approved_templates = true
py fast_local_thumbnails.py --config film-001.json
```

Đồng bộ trực tiếp với Google Drive bằng rclone (chỉ khi remote `drive:` đã được xác thực trên máy, root đúng THUMBNAILS và quyền thư mục đã kiểm tra):

```powershell
rclone lsd drive:
py fast_local_thumbnails.py --config film-001.json --sync --remote "drive:THUMBNAILS"
```

Hoặc xử lý nhiều phim có job đã duyệt:

```powershell
py fast_local_thumbnails.py --jobs-dir jobs
py fast_local_thumbnails.py --jobs-dir jobs --sync --remote "drive:THUMBNAILS"
```

**Không chạy tự động với tất cả phim khi chưa có mẫu đã duyệt của từng phim.** Job sai có thể gán ảnh phim này cho phim khác.

## Khác biệt với luồng cũ

- `vds_batch.py` và `composio_drive.py` vẫn giữ để kiểm tra bộ cũ hoặc khôi phục có kiểm soát, nhưng **không phải mặc định cho phim tiếp theo**.
- `fast_local_thumbnails.py` dùng hệ thống tệp bền vững + Pillow, rclone Drive sync trực tiếp có checksum. Không nhận rclone remote là chứng cứ VDS trên máy đã đồng bộ; phải thử VDS sau khi sync.
- Phạm vi thay đổi GitHub chỉ trong `thumbnail-workflow/`; không tự merge PR #1, không tự bật lịch chạy và không thay đổi ứng dụng VDS trên máy gốc.
