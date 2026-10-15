# Thumbnail phim tiếng Việt

> **Workflow hiện hành đã đổi:** dùng [README.vds.md](README.vds.md) và [CHATGPT_HANDOFF.md](CHATGPT_HANDOFF.md). Thiết kế mẫu chung rồi dùng code thay số tập, không AI từng ảnh. Phần bên dưới là tài liệu legacy API OCR/edit, giữ để tham khảo; không phải entrypoint mới.

Workflow riêng cho `videodownloaderstudio-site`, không sửa website. GitHub lưu code/skill; ChatGPT điều phối và hỗ trợ duyệt; worker Python dùng OpenAI API và Google Drive OAuth để chạy pipeline. Đăng nhập ChatGPT/Drive connector không tự cấp API key hay token cho worker.

## Đầu ra

```text
THUMBNAILS/
└── Tên bộ phim/
    ├── PHIM_16x9.jpg       # 1920 × 1080
    ├── PHIM_9x16.jpg       # 1080 × 1920
    ├── TAP_001_16x9.jpg
    └── TAP_001_9x16.jpg
```

Thư mục đích đã tạo: https://drive.google.com/drive/folders/1fvctF1zgqrGL6UNVtjBDH5RU_y_GfJ37
Các thư mục `.vds-thumbnails` và `03_THUMBNAIL_CONCEPTS` hiện có được giữ nguyên.

## Cài đặt

Python 3.11 trở lên. Trong thư mục `thumbnail-workflow`:

```powershell
python -m venv .venv
.venv/Scripts/Activate.ps1
python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
Copy-Item job.example.json job.json
```

Tạo Google Cloud project, bật Drive API, cấu hình OAuth consent screen và Desktop OAuth client. Tải client secret về máy ngoài Git hoặc file bị ignore. Chỉ tài khoản được thêm vào OAuth test users mới đăng nhập được khi ứng dụng ở chế độ testing. Token testing có thể hết hạn; xác thực lại bằng file token mới, không ghi đè token cũ.

```powershell
python workflow.py auth --client-secret client_secret.json --token token.json
$env:GOOGLE_TOKEN_FILE = 'token.json'
$env:OPENAI_API_KEY = '<nhập key trong phiên terminal riêng>'
```

Không gửi key trong chat; không commit credentials. Drive scope đầy đủ được dùng để đọc ảnh/thư mục có sẵn và tải file mới; code upload chỉ dùng create, không update/delete. OAuth cần sự đồng ý riêng của người dùng. Giữ run data ngoài Git; public repo không chứa ảnh nguồn, dịch OCR hay file review.

## Chọn nguồn và chạy

```powershell
python workflow.py discover --folder '<Drive folder ID nguồn>'
python workflow.py prepare --config config.json --job job.json --run runs/phim-001
python workflow.py review --run runs/phim-001
```

Thay `file_id` trong job bằng ID ảnh poster/tập đã đọc metadata, ghi episode rõ ràng. Chỉ JPEG/PNG/WebP; không tự suy luận tập theo thứ tự Drive. `source_folder_id` chỉ là gợi ý discovery; job explicit là nguồn chuẩn. Chưa chọn mặc định thư mục nguồn vì các thư mục tìm thấy chưa chứng minh có poster/tập phù hợp. Video MP4 cần xuất still trước; CLI không trích frame.

Pipeline tự tải ảnh → OCR/dịch title → AI xóa chữ quảng cáo gốc và phục hồi nền → đặt chữ Việt bằng font → render hai tỷ lệ → QC kỹ thuật và QC hình ảnh. Có lưu `original_text`, confidence và notes. Confidence dưới 0.8 dừng để người dùng sửa title; không bịa chữ khó đọc. Logo/watermark được bảo tồn, chữ tiêu đề/caption mới là mục tiêu xóa.

Mở file `review-*.html` được in ra; đọc `ocr.json`, xem `clean.png` và ảnh hai tỷ lệ. Người duyệt kiểm tra bản dịch, dấu tiếng Việt, khuôn mặt, phục hồi nền, bố cục, chữ sót và thông tin tập. QC máy không chứng minh hoàn hảo; chữ/nhân vật bị AI thay đổi phải reject.

Nếu reject, sửa bằng feedback và tùy chọn title đã xác nhận:

```powershell
python workflow.py revise --run runs/phim-001 --asset PHIM --feedback 'Chữ gốc còn ở góc trái' --title 'Tên phim tiếng Việt đã kiểm tra'
```

Nếu người duyệt đồng ý bản hiện tại:

```powershell
python workflow.py approve --run runs/phim-001 --reviewer 'Tên người duyệt'
python workflow.py upload --run runs/phim-001
```

`approve` là xác nhận của người điều hành, không có xác thực danh tính doanh nghiệp; ChatGPT không được tự chạy trước khi người dùng duyệt. Approval gắn với hashes, metadata và thư mục đích; bất kỳ sửa ảnh/metadata/lần thử mới đều yêu cầu duyệt lại. Upload chỉ sau QC pass và approval đúng hash.

## Mặc định và retry

* Vision: `gpt-4.1-mini`; chỉnh được. Edit: `gpt-image-1`; chỉnh được. Kiểm tra quyền truy cập model trên tài khoản trước khi chạy live.
* 16:9 1920×1080; 9:16 1080×1920; JPEG RGB quality 92, tối đa 2 MB/file.
* Font Arial Bold Windows hỗ trợ tiếng Việt. Linux đặt font thành `/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf` hoặc Noto Sans đã cài.
* Nền blur, ảnh chính contain để giữ mặt; chữ vàng/nền tối ở vùng dưới. Hai bố cục cùng title; tập thêm `Tập 001`.
* Tối đa 3 candidate/asset, bao gồm revise thủ công. QC hình ảnh fail tự thử lại với issues; hết lượt dừng. Transport/auth/API exceptions dừng candidate, không tạo vòng gọi trả phí vô hạn. SDK chỉ retry transient tối đa 2 lần; mỗi image call timeout 240 giây.
* Mỗi prepare dùng run folder mới. Local file mở chế độ exclusive. Không overwrite Drive, không có tùy chọn force. Trùng tên dừng cả preflight trước khi upload.
* Upload gián đoạn có receipts và checksum để tiếp tục những file đã tạo. Nếu server tạo file nhưng client không nhận response/receipt, dừng conflict khi chạy lại và xử lý thủ công; không tự tạo bản trùng.
* Drive không có unique-name transaction: chạy một uploader cho mỗi phim. Race giữa hai máy có thể tạo tên trùng dù không ghi đè; không hỗ trợ concurrent production workers.

Không kích hoạt lịch chạy/GitHub production job khi chưa có OAuth/API key/nguồn thật và chưa kiểm thử end-to-end. CI trong PR chỉ chạy tests bằng mock, không dùng secrets. Để tự động nhận nguồn mới, hệ thống hiện tại gọi `prepare` với job manifest sau khi ảnh đã tải xong; vẫn phải dừng ở human review. Không tự upload chỉ vì ảnh được thả vào folder.

## Skill

Skill entrypoint: `skill/thumbnail-vietnam/SKILL.md`. Dùng trực tiếp với Codex cùng thư mục workflow. Khi cài riêng, giữ nguyên cấu trúc thư mục chứa README/CLI hoặc sửa đường dẫn tương ứng. Chưa cài vào global skills vì đây là phần bổ sung repo có thể review.

## Kiểm thử

```powershell
python -m unittest -v test_workflow.py
```

Tests không tốn API: kích thước/tên ảnh, path safety, không ghi đè local/Drive, bounded QC retry, chặn upload chưa duyệt, ảnh/metadata/revision làm mất approval. FakeAI chỉ xác minh orchestration và render; không xác minh OCR/edit/translation thực tế. Live smoke test cần một ảnh thật, OAuth Drive worker và API key.

Tài liệu API đã tham khảo: [Responses structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [image edits](https://developers.openai.com/api/docs/guides/image-generation), [Drive uploads](https://developers.google.com/workspace/drive/api/guides/manage-uploads).
