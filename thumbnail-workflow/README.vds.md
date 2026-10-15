# Workflow mới: ChatGPT thường → Drive → VDS

Entry point: `vds_batch.py` và `composio_drive.py`; yêu cầu chỉ `requirements.batch.txt` (Pillow). `workflow.py`/requirements.txt/config.example.json là bản API OCR/edit cũ, không chạy cho từng tập.

## Hai chế độ

* `have_original`: ảnh đính kèm hoặc Drive; xác minh đúng phim rồi thiết kế lại hai mẫu chung.
* `find_original`: tìm/tải ảnh trên mạng theo tên/mã phim, lưu nguồn và xác minh, rồi thiết kế lại.

Mẫu mới khác rõ ảnh gốc: hình tràn khung, nhân vật lớn, chữ Việt nhiều tầng vàng/trắng viền đen–đỏ theo tham chiếu người dùng. Giữ một vùng nhãn số tập. Người dùng đã chọn dùng ảnh chung cho mọi tập; chỉ nhãn tập/phần thay đổi. Không gọi AI cho từng ảnh. Tạo/chỉnh mẫu trong ChatGPT vẫn dùng hạn mức.

## Công cụ và cách chạy

Đọc [CHATGPT_HANDOFF.md](CHATGPT_HANDOFF.md) để biết từng tool, account và quy trình Drive. GitHub lưu code, không tự chạy code. Trong @1 Workbench tải hai module, mẫu và font tiếng Việt, cài Pillow. Linux dùng DejaVu Sans Bold/Noto Sans; Windows có Arial Bold.

`Drive(run_composio_tool, account='BRU Drive xray31')` dùng FIND_FILE có pagination, GET_FILE_METADATA, CREATE_FOLDER, UPLOAD_FROM_URL. Account này đã xác minh đọc được THUMBNAILS và có quyền thêm file; chat đích kiểm tra lại. Account “BRU source transport” không thấy đích này.

`Drive.scan_one_film(folder_id)` quét metadata từng bộ, đọc hết pagination; lưu checkpoint từng bộ. Không đếm SRT/TXT/cache thành tập, không trộn `file tải` với output `reup`. Nếu chỉ có episode folders nhưng chưa có video thì báo chưa sẵn sàng. Gaps chỉ báo, duplicate/unknown phải giải quyết; part clip cần mapping explicit. Copy job.vds.example.json thành job riêng; giữ tên bộ đúng VDS.

```text
python vds_batch.py scan --inventory inventory.json
python vds_batch.py prepare --job job.json --run runs/film-001
```

Prepare xuất review.html và nhãn mẫu đầu/giữa/cuối ở cả hai tỷ lệ. Chỉ sau human review rõ mẫu và vị trí số tập:

```text
python vds_batch.py approve --run runs/film-001 --reviewer HUMAN_NAME
python vds_batch.py render --run runs/film-001 --limit 40
python vds_batch.py verify --run runs/film-001
```

Lặp render đến `ready_to_upload`; một run/job/approval cho cả bộ. Checkpoint sau từng ảnh. Mẫu/font/job đổi phải prepare và duyệt lại. Có result.json, upload-plan.json, THUMBNAILS.zip. Lỗi trước khi tạo file thử tối đa 3 lần; lỗi có partial file giữ lại, không xóa/ghi đè.

Publish trong Workbench: `Drive.publish(run, upload_local_file, limit=20)`, lặp tới complete. Verify trước upload; preflight mọi tên đích, cùng MD5 skip, khác/trùng dừng xin phép. Write timeout không tự retry. Readback name/parent/MD5 và receipts giúp resume. Chạy một publisher mỗi phim; Drive không có unique-name transaction.

## Drive và nhận diện VDS

Đích: https://drive.google.com/drive/folders/1fvctF1zgqrGL6UNVtjBDH5RU_y_GfJ37

```text
THUMBNAILS_WORK/<tên bộ>/             # original, nguồn, mẫu, job
THUMBNAILS_REVIEW/<run>/<tên bộ>/     # samples chờ duyệt
THUMBNAILS/<tên bộ>/
  PHIM_16x9.jpg
  PHIM_9x16.jpg
  TAP_001_16x9.jpg
  TAP_001_9x16.jpg
  TAP_002_16x9.jpg
  TAP_002_9x16.jpg
  TAP_001_PHAN_001_16x9.jpg           # chỉ khi có video phần tương ứng
  TAP_001_PHAN_001_9x16.jpg
```

Tên bộ phải trùng folder bộ VDS nhận, giữ HG ID nếu có. JPEG RGB ngang1920×1080/dọc1080×1920, tối đa2MB. 100 tập chính=202 ảnh tính cảPHIM.

Google Drive for desktop: đánh dấu THUMBNAILS có sẵn ngoại tuyến, chọn đường dẫn trên máy trong VDS, bật quét folder con, tắt movie fallback, Kiểm tra ghép ảnh. Mã nguồn VDS tìm được ghép theo tên bộ+tập+phần+tỷ lệ, không đọc manifest riêng. Không mặc định dùng .vds-thumbnails.

Bản VDS cài hiện tại chưa xác minh. Thử video đầu/giữa/cuối và video phần trước production. Nếu parser không nhận “Tập …”, dừng, không rename video/sửa app ngoài scope. Website repo giữ nguyên.

## Tests và trạng thái

```text
python -m unittest -v test_workflow.py test_vds_batch.py test_composio_drive.py
```

Có batch thật202ảnh/100tập, approval/hash, resume, part, gaps/duplicates, pagination rỗng có token, conflict/error connector. Mẫu thật v2 chưa được duyệt: chưa xuất cả bộ thật hoặc upload JPEG cuối. Adapter publish cần smoke test live sau duyệt; chưa chứng minh Drive sync/VDS cài hiện tại hoạt động.
