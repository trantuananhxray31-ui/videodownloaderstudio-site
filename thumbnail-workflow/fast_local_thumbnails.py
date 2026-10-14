"""Local-first VDS thumbnail maker. Two approved templates, no AI, no per-file cloud worker.

Usage:
  python fast_local_thumbnails.py --config film.json
  python fast_local_thumbnails.py --config film.json --sync --remote "drive:THUMBNAILS"
  python fast_local_thumbnails.py --jobs-dir jobs --sync --remote "drive:THUMBNAILS"

The video folder and each approved image template must belong to the SAME film.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SIZES = {"16x9": (1920, 1080), "9x16": (1080, 1920)}
EXTS = {".mp4", ".mkv", ".mov", ".webm", ".m4v"}
EP_PATTERN = re.compile(r"(?:tập|tap|episode|ep)[ _.\-]*(\d{1,3})(?!\d)|第[ _.\-]*(\d{1,3})集", re.I)
PART_PATTERN = re.compile(r"(?:phần|phan|part)[ _.\-]*(\d{1,3})(?!\d)", re.I)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def safe_name(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    if not value or value != value.strip() or value.endswith(".") or re.search(r'[<>:"/\\|?*\x00-\x1f]', value):
        raise ValueError("Unsafe movie folder name")
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", value):
        raise ValueError("Reserved movie folder name")
    return value


def path_from(config_dir: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return (p if p.is_absolute() else config_dir / p).resolve()


def inventory(video_dir: Path) -> tuple[list[tuple[int, int]], list[int]]:
    if not video_dir.is_dir():
        raise ValueError(f"Video folder missing: {video_dir}")
    videos = sorted(p for p in video_dir.iterdir() if p.is_file() and p.suffix.lower() in EXTS)
    if not videos:
        raise ValueError(f"No videos in {video_dir}")
    numbers: dict[tuple[int, int], str] = {}
    unresolved = []
    for p in videos:
        m = EP_PATTERN.search(unicodedata.normalize("NFC", p.stem))
        if not m:
            unresolved.append(p.name)
            continue
        n = int(next(x for x in m.groups() if x is not None))
        part_match = PART_PATTERN.search(p.stem)
        part = int(part_match.group(1)) if part_match else 0
        if not (1 <= n <= 999 and 0 <= part <= 999):
            unresolved.append(p.name)
            continue
        key = (n, part)
        if key in numbers:
            raise ValueError(f"Duplicate episode/part {key}: {numbers[key]} vs {p.name}")
        numbers[key] = p.name
    if unresolved:
        raise ValueError("Unresolved video episode names: " + ", ".join(unresolved[:10]))
    keys = sorted(numbers)
    missing = sorted(set(range(1, max(k[0] for k in keys) + 1)) - {k[0] for k in keys})
    return keys, missing


def target_name(episode: int, part: int, ratio: str) -> str:
    return f"TAP_{episode:03d}" + (f"_PHAN_{part:03d}" if part else "") + f"_{ratio}.jpg"


def read_job(config_path: Path) -> dict:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    safe_name(data["series_folder"])
    if data.get("source_verified") is not True or data.get("approved_templates") is not True:
        raise ValueError("Source and both film-specific templates must be human verified/approved")
    root = config_path.resolve().parent
    data["_videos"] = path_from(root, data["video_folder"])
    data["_output"] = path_from(root, data["output_root"])
    data["_font"] = path_from(root, data["font"])
    if not data["_font"].is_file():
        raise ValueError("Vietnamese bold font file missing")
    for ratio, size in SIZES.items():
        spec = data["templates"][ratio]
        spec["_path"] = path_from(root, spec["path"])
        with Image.open(spec["_path"]) as im:
            if im.size != size:
                raise ValueError(f"{ratio} template dimensions incorrect: {im.size}")
        x, y, w, h = spec["badge_box"]
        if not (0 <= x < x + w <= 1 and 0 <= y < y + h <= 1):
            raise ValueError("Badge coordinates outside template")
    return data


def encode_episode(base: Image.Image, badge: list, font_path: str, episode: int, part: int, cache: dict) -> bytes:
    canvas = base.copy()
    draw = ImageDraw.Draw(canvas)
    w, h = canvas.size
    x, y, bw, bh = badge
    rect = tuple(round(v) for v in (x * w, y * h, (x + bw) * w, (y + bh) * h))
    label = f"TẬP {episode:03d}" + (f" • P{part:03d}" if part else "")
    for size in range(int(bh * h * .65), 17, -1):
        font = cache.setdefault(size, ImageFont.truetype(font_path, size))
        stroke = max(2, size // 18)
        bounds = draw.textbbox((0, 0), label, font=font, stroke_width=stroke)
        if bounds[2] - bounds[0] <= (rect[2] - rect[0]) * .88 and bounds[3] - bounds[1] <= (rect[3] - rect[1]) * .8:
            break
    else:
        raise ValueError("Episode label does not fit approved badge")
    draw.rounded_rectangle(rect, radius=max(8, int(bh * h * .15)), fill="#d91921", outline="#090909", width=4)
    tx = (rect[0] + rect[2] - (bounds[2] - bounds[0])) / 2 - bounds[0]
    ty = (rect[1] + rect[3] - (bounds[3] - bounds[1])) / 2 - bounds[1]
    draw.text((tx, ty), label, font=font, fill="#ffef2d", stroke_width=stroke, stroke_fill="#090909")
    from io import BytesIO
    buffer = BytesIO()
    canvas.save(buffer, "JPEG", quality=92, optimize=True)
    return buffer.getvalue()


def immutable_write(dest: Path, raw: bytes) -> str:
    """Create atomically; existing files are verified, never overwritten."""
    digest = md5(raw)
    if dest.exists():
        if md5(dest.read_bytes()) != digest:
            raise FileExistsError(f"Existing image differs; not overwritten: {dest}")
        return "skipped"
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=".vds-", suffix=".tmp")
    temp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(temp_path, dest)  # exclusive even on POSIX: never replaces dest
        except FileExistsError:
            if md5(dest.read_bytes()) != digest:
                raise
            return "skipped"
        except OSError:
            # Filesystems without hard-link support: use exclusive create.
            with dest.open("xb") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
        return "created"
    finally:
        temp_path.unlink(missing_ok=True)


def check_jpeg(path: Path, size: tuple[int, int]) -> None:
    if path.stat().st_size > 2_000_000:
        raise ValueError(f"JPEG over 2 MB: {path}")
    with Image.open(path) as im:
        im.load()
        if im.format != "JPEG" or im.mode != "RGB" or im.size != size:
            raise ValueError(f"Bad JPEG dimensions/format: {path}")


def render(config_path: Path) -> dict:
    job = read_job(config_path)
    keys, missing_episodes = inventory(job["_videos"])
    folder = job["_output"] / job["series_folder"]
    folder.mkdir(parents=True, exist_ok=True)
    assets = {}
    base = {}
    for ratio in SIZES:
        with Image.open(job["templates"][ratio]["_path"]) as im:
            base[ratio] = im.convert("RGB")
    cache = {}
    count_created = count_skipped = 0
    for ratio in SIZES:
        import io
        output = io.BytesIO()
        base[ratio].save(output, "JPEG", quality=92, optimize=True)
        name = f"PHIM_{ratio}.jpg"
        action = immutable_write(folder / name, output.getvalue())
        check_jpeg(folder / name, SIZES[ratio])
        assets[name] = {"md5": md5((folder / name).read_bytes()), "bytes": (folder / name).stat().st_size}
        count_created += action == "created"
        count_skipped += action == "skipped"
    for episode, part in keys:
        for ratio in SIZES:
            name = target_name(episode, part, ratio)
            raw = encode_episode(base[ratio], job["templates"][ratio]["badge_box"], str(job["_font"]), episode, part, cache)
            action = immutable_write(folder / name, raw)
            check_jpeg(folder / name, SIZES[ratio])
            assets[name] = {"md5": md5(raw), "bytes": len(raw)}
            count_created += action == "created"
            count_skipped += action == "skipped"
    # No video is assigned an inferred episode number. Gaps are reported only.
    result = {"series_folder": job["series_folder"], "video_count": len(keys), "missing_video_episode_numbers": missing_episodes,
              "expected_jpegs": len(keys) * 2 + 2, "created": count_created,
              "verified_existing": count_skipped, "files": assets, "output_folder": str(folder)}
    state = job["_output"] / ".thumbnail-state"
    state.mkdir(exist_ok=True)
    state_path = state / (hashlib.sha256(job["series_folder"].encode("utf-8")).hexdigest()[:20] + ".json")
    fd, temp = tempfile.mkstemp(dir=state, prefix=".manifest-", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        os.replace(temp, state_path)  # only our metadata; never image files
    finally:
        Path(temp).unlink(missing_ok=True)
    return result


def remote_files(remote: str) -> dict:
    command = ["rclone", "lsjson", "--files-only", "--hash", remote]
    output = subprocess.check_output(command, text=True)
    result = {}
    for entry in json.loads(output):
        name = entry["Path"]
        if name in result:
            raise FileExistsError("Duplicate Drive file name: " + name)
        result[name] = entry
    return result


def sync_with_rclone(result: dict, remote_root: str) -> dict:
    """Preflight by MD5, upload only absent files, and verify every Drive MD5."""
    if not remote_root or ":" not in remote_root:
        raise ValueError("Use an explicit rclone remote such as drive:THUMBNAILS")
    local_dir = Path(result["output_folder"])
    target = remote_root.rstrip("/") + "/" + result["series_folder"]
    expected = result["files"]
    existing = remote_files(target)  # failure stops; never assume a missing/unreadable folder is empty
    for name, spec in expected.items():
        if name not in existing:
            continue
        item = existing[name]
        checksum = (item.get("Hashes") or {}).get("MD5")
        if not checksum or checksum.lower() != spec["md5"].lower() or int(item["Size"]) != spec["bytes"]:
            raise FileExistsError("Remote MD5/size conflict: " + name)
    subprocess.run(["rclone", "copy", str(local_dir), target, "--ignore-existing", "--checksum"], check=True)
    verified = remote_files(target)
    for name, spec in expected.items():
        if name not in verified:
            raise RuntimeError("Missing after Drive sync: " + name)
        item = verified[name]
        checksum = (item.get("Hashes") or {}).get("MD5")
        if not checksum or checksum.lower() != spec["md5"].lower() or int(item["Size"]) != spec["bytes"]:
            raise RuntimeError("Drive readback MD5/size mismatch: " + name)
    return {"remote": target, "verified": len(expected)}


def main() -> None:
    parser = argparse.ArgumentParser(description="VDS bulk thumbnails from two approved templates")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", type=Path, help="One movie JSON configuration")
    source.add_argument("--jobs-dir", type=Path, help="Directory of approved movie JSON configurations")
    parser.add_argument("--sync", action="store_true", help="Upload missing files with preflight and Drive checksum readback")
    parser.add_argument("--remote", help='Explicit rclone folder, e.g. "drive:THUMBNAILS"')
    args = parser.parse_args()
    if args.sync and not args.remote:
        parser.error("--sync requires --remote")
    jobs = [args.config] if args.config else sorted(args.jobs_dir.glob("*.json"))
    if not jobs:
        parser.error("No movie configurations found")
    for config in jobs:
        result = render(config)
        print(json.dumps({k: v for k, v in result.items() if k != "files"}, ensure_ascii=False))
        if args.sync:
            print(json.dumps(sync_with_rclone(result, args.remote), ensure_ascii=False))


if __name__ == "__main__":
    main()
