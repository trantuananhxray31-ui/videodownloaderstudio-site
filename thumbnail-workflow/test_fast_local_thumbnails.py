import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
import fast_local_thumbnails as m


class FastLocalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        video = self.root / "video"
        video.mkdir()
        self.video = video
        self.job = {
            "series_folder": "Test Film [HG_123]",
            "source_verified": True,
            "approved_templates": True,
            "video_folder": str(video),
            "output_root": str(self.root / "output"),
            "font": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "templates": {}
        }
        for ratio, size in m.SIZES.items():
            path = self.root / (ratio + ".jpg")
            Image.new("RGB", size, "navy").save(path)
            self.job["templates"][ratio] = {
                "path": str(path),
                "badge_box": [.75, .025, .23, .13] if ratio == "16x9" else [.64, .02, .34, .075]
            }
        self.config = self.root / "job.json"
        self.save_job()

    def tearDown(self):
        self.tmp.cleanup()

    def save_job(self):
        self.config.write_text(json.dumps(self.job), encoding="utf-8")

    def test_render_all_and_resume(self):
        for ep in range(1, 4):
            (self.video / f"Tập {ep:03d}.mp4").write_bytes(b"video")
        result = m.render(self.config)
        self.assertEqual(result["expected_jpegs"], 8)
        self.assertEqual(result["created"], 8)
        self.assertEqual(m.render(self.config)["verified_existing"], 8)
        self.assertEqual(len(list(Path(result["output_folder"]).glob("*.jpg"))), 8)

    def test_original_file_conflict_stops_without_overwrite(self):
        (self.video / "Tập 001.mp4").write_bytes(b"x")
        result = m.render(self.config)
        p = Path(result["output_folder"]) / "TAP_001_16x9.jpg"
        p.write_bytes(b"corruption")
        with self.assertRaises(FileExistsError):
            m.render(self.config)
        self.assertEqual(p.read_bytes(), b"corruption")

    def test_duplicate_episode_stops(self):
        (self.video / "Tập 001 foo.mp4").write_bytes(b"x")
        (self.video / "ep 001 bar.mkv").write_bytes(b"x")
        with self.assertRaises(ValueError):
            m.render(self.config)

    def test_unresolved_file_stops(self):
        (self.video / "filename-without-episode.mp4").write_bytes(b"x")
        with self.assertRaises(ValueError):
            m.render(self.config)

    def test_template_approval_required(self):
        (self.video / "Tập 001.mp4").write_bytes(b"x")
        self.job["approved_templates"] = False
        self.save_job()
        with self.assertRaises(ValueError):
            m.render(self.config)

    def test_reup_nested_episode_folders_and_ignore_shorts(self):
        for n in (1, 2):
            folder = self.video / f"Tap_{n:03d}"
            folder.mkdir()
            (folder / f"Tap_{n:03d}_vi.mp4").write_bytes(b"video")
            shorts = folder / "Shorts"
            shorts.mkdir()
            (shorts / f"Tap_{n:03d}_clip.mp4").write_bytes(b"shorts")
        result = m.render(self.config)
        self.assertEqual(result["video_count"], 2)
        self.assertEqual(result["expected_jpegs"], 6)
        self.assertEqual(result["missing_video_episode_numbers"], [])
        self.assertEqual(m.render(self.config)["verified_existing"], 6)

    def test_subtitle_only_final_folder_reported_missing(self):
        for n in (1, 2):
            folder = self.video / f"Tập {n:03d}_hg_123"
            folder.mkdir()
            (folder / f"Tập {n:03d}_vi.mp4").write_bytes(b"video")
        pending = self.video / "Tập 003_hg_123"
        pending.mkdir()
        (pending / "Tập 003_vi.srt").write_text("subtitles")
        result = m.render(self.config)
        self.assertEqual(result["expected_jpegs"], 6)
        self.assertEqual(result["missing_video_episode_numbers"], [3])
        self.assertFalse((Path(result["output_folder"]) / "TAP_003_9x16.jpg").exists())

    def test_episode_parent_filename_mismatch_stops(self):
        folder = self.video / "Tap_001"
        folder.mkdir()
        (folder / "Tap_002_vi.mp4").write_bytes(b"bad")
        with self.assertRaises(ValueError):
            m.render(self.config)

    def test_unexpected_jpg_blocks_sync(self):
        (self.video / "Tập 001.mp4").write_bytes(b"x")
        result = m.render(self.config)
        (Path(result["output_folder"]) / "random.jpg").write_bytes(b"wrong")
        with self.assertRaises(ValueError):
            m.render(self.config)


if __name__ == "__main__":
    unittest.main()
