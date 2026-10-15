import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import workflow as w


class FakeAI:
    def __init__(self, failures=0):
        self.failures = failures
        self.calls = 0

    def ocr(self, source, film):
        return {"original_text": "测试", "vietnamese_title": "Trở Về Bên Em", "confidence": .95, "notes": ""}

    def clean(self, source, target, feedback):
        Image.new("RGB", (900, 1200), "#576b88").save(target)

    def qc(self, *args):
        self.calls += 1
        return {"passed": self.calls > self.failures, "issues": [] if self.calls > self.failures else ["Chữ gốc còn sót"]}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "run"
        font = "C:/Windows/Fonts/arialbd.ttf"
        if not Path(font).exists():
            font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        self.cfg = {"font": font, "max_attempts": 3, "max_bytes": 2000000,
                    "output_folder_id": "target"}
        self.job = {"film": "Trở Về", "assets": [{"kind": "PHIM", "file_id": "poster"},
                    {"kind": "TAP", "episode": 1, "file_id": "still"}]}

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, ai=None):
        def download(drive, file_id, path):
            Image.new("RGB", (900, 1200), "navy").save(path)
            return {"id": file_id}
        with patch.object(w, "download", download):
            w.prepare(self.cfg, self.job, self.root, None, ai or FakeAI())

    def test_exact_names_dimensions_and_review(self):
        self.prepare()
        files = sorted(p.name for p in self.root.rglob("*.jpg"))
        self.assertEqual(files, ["PHIM_16x9.jpg", "PHIM_9x16.jpg", "TAP_001_16x9.jpg", "TAP_001_9x16.jpg"])
        for p in self.root.rglob("*.jpg"):
            ratio = "16x9" if "16x9" in p.name else "9x16"
            w.technical_qc(p, w.RATIOS[ratio], 2000000)
        self.assertTrue(list(self.root.glob("review-*.html")))

    def test_prepare_never_replaces_run(self):
        self.prepare()
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_retry_after_failed_qc(self):
        ai = FakeAI(failures=1)
        self.prepare(ai)
        self.assertEqual(w.latest(self.root)[0]["attempt"], 2)
        self.assertEqual(ai.calls, 3)

    def test_qc_exhaustion_blocks_approval(self):
        with self.assertRaises(ValueError):
            self.prepare(FakeAI(failures=100))
        with self.assertRaises(ValueError):
            w.approve(self.root, "Người duyệt")

    def test_no_approval_blocks_upload_before_drive_calls(self):
        self.prepare()
        with self.assertRaises(ValueError):
            w.upload(self.root, None)

    def test_changed_image_invalidates_approval(self):
        self.prepare()
        w.approve(self.root, "Người duyệt")
        path = next(self.root.rglob("*.jpg"))
        path.write_bytes(b"modified")
        with self.assertRaises(ValueError):
            w.snapshot(self.root)

    def test_revision_requires_new_approval(self):
        self.prepare()
        old, _ = w.snapshot(self.root)
        w.approve(self.root, "Người duyệt")
        asset = self.job["assets"][0]
        w.candidate(self.root, self.root / "PHIM/source.png", asset, "Trở Về", self.cfg, FakeAI(), 2,
                    title_override="Một Ngày Trở Lại")
        new, _ = w.snapshot(self.root)
        self.assertNotEqual(old, new)
        self.assertFalse((self.root / f"approval-{new}.json").exists())

    def test_metadata_change_requires_new_approval(self):
        self.prepare()
        w.approve(self.root, "Người duyệt")
        cfg = dict(self.cfg, output_folder_id="different")
        (self.root / "config.json").write_text(__import__("json").dumps(cfg))
        new, _ = w.snapshot(self.root)
        self.assertFalse((self.root / f"approval-{new}.json").exists())

    def test_path_and_episode_validation(self):
        for bad in ["../escape", "a/b", "CON", "nul.txt", "", "x."]:
            with self.assertRaises(ValueError):
                w.component(bad)
        for bad in [0, -1, 1000, True, "1"]:
            with self.assertRaises(ValueError):
                w.stem({"kind": "TAP", "episode": bad})

    def test_duplicate_assets(self):
        job = {"film": "Phim", "assets": [self.job["assets"][0]] * 2}
        with self.assertRaises(ValueError):
            w.validate_job(job)

    def test_drive_conflict_blocks_all_uploads(self):
        self.prepare()
        w.approve(self.root, "Người duyệt")
        class Request:
            def execute(self):
                return {"id": "target", "name": "THUMBNAILS", "mimeType": "application/vnd.google-apps.folder"}
        class Drive:
            def files(self): return self
            def get(self, **kwargs): return Request()
        with patch.object(w, "folder", return_value="film"), patch.object(w, "find", return_value=[{"id": "existing"}]):
            with self.assertRaises(FileExistsError):
                w.upload(self.root, Drive())


if __name__ == "__main__":
    unittest.main()
