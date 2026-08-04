#!/usr/bin/env python3
"""Create and inspect a video-study-extractor case workspace.

This script intentionally avoids heavyweight dependencies. It prepares a
repeatable workspace, classifies inputs, extracts URLs from share text, writes
metadata, and generates a concrete processing checklist for the agent/user.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}
SUBTITLE_EXTS = {".srt", ".vtt", ".ass", ".txt"}
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


def file_sha256(path: Path, limit_bytes: int | None = None) -> str:
    h = hashlib.sha256()
    read = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            if limit_bytes is not None and read + len(chunk) > limit_bytes:
                chunk = chunk[: max(0, limit_bytes - read)]
            if not chunk:
                break
            h.update(chunk)
            read += len(chunk)
            if limit_bytes is not None and read >= limit_bytes:
                break
    return h.hexdigest()


def safe_name(value: str) -> str:
    value = re.sub(r"^[a-zA-Z]:[\\/]", "", value)
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return value[:80] or "video-study-case"


def extract_urls(text: str) -> list[str]:
    return [m.group(0).rstrip(").,;]") for m in URL_RE.finditer(text)]


def classify_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "bilibili.com" in host or "b23.tv" in host:
        return "bilibili"
    if "douyin.com" in host or "iesdouyin.com" in host:
        return "douyin"
    if "xiaohongshu.com" in host or "xhslink.com" in host:
        return "xiaohongshu"
    if "kuaishou.com" in host:
        return "kuaishou"
    return "generic_url"


def classify_input(raw_input: str) -> dict:
    urls = extract_urls(raw_input)
    path = Path(raw_input.strip('"'))
    result = {
        "raw_input": raw_input,
        "urls": urls,
        "kind": "text",
        "platform": None,
        "path": None,
        "exists": False,
    }

    if path.exists():
        result["exists"] = True
        result["path"] = str(path.resolve())
        if path.is_dir():
            result["kind"] = "local_folder"
        else:
            ext = path.suffix.lower()
            if ext in VIDEO_EXTS:
                result["kind"] = "local_video"
            elif ext in AUDIO_EXTS:
                result["kind"] = "local_audio"
            elif ext in SUBTITLE_EXTS:
                result["kind"] = "subtitle"
            else:
                result["kind"] = "local_file"
        return result

    if urls:
        result["kind"] = "share_text" if raw_input.strip() != urls[0] else "url"
        result["platform"] = classify_url(urls[0])
        return result

    return result


def which(name: str) -> str | None:
    return shutil.which(name)


def run_capture(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return p.returncode, p.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def probe_media(path: Path) -> dict:
    probe = {"available": False}
    ffprobe = which("ffprobe")
    if not ffprobe:
        probe["error"] = "ffprobe not found"
        return probe
    code, out = run_capture([
        ffprobe,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ])
    if code != 0:
        probe["error"] = out
        return probe
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        probe["error"] = "ffprobe returned non-json output"
        return probe
    probe["available"] = True
    probe["format"] = data.get("format", {})
    probe["streams"] = data.get("streams", [])
    return probe


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def create_case(args: argparse.Namespace) -> None:
    info = classify_input(args.input)
    fingerprint = sha256_text(args.input)[:12]
    base = safe_name(Path(info.get("path") or args.input).stem if info.get("path") else info.get("platform") or "input")
    case_dir = Path(args.out).resolve() / f"{base}-{fingerprint}"

    for sub in [
        "input",
        "media",
        "audio",
        "transcript",
        "keyframes",
        "analysis",
        "reports",
        "study_pack",
        "logs",
    ]:
        (case_dir / sub).mkdir(parents=True, exist_ok=True)

    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input": info,
        "tools": {
            "ffmpeg": which("ffmpeg"),
            "ffprobe": which("ffprobe"),
            "yt_dlp": which("yt-dlp") or which("yt_dlp"),
            "python": sys.executable,
        },
        "policy": {
            "max_single_video_minutes": 60,
            "long_video_split_minutes": 25,
            "no_drm_bypass": True,
        },
    }

    if info.get("path") and Path(info["path"]).is_file():
        p = Path(info["path"])
        metadata["file"] = {
            "name": p.name,
            "size_bytes": p.stat().st_size,
            "sha256_first_64mb": file_sha256(p, 64 * 1024 * 1024),
        }
        if p.suffix.lower() in VIDEO_EXTS | AUDIO_EXTS:
            metadata["media_probe"] = probe_media(p)

    write_json(case_dir / "metadata.json", metadata)
    (case_dir / "study_plan.md").write_text(make_plan(metadata), encoding="utf-8")
    print(str(case_dir))


def make_plan(metadata: dict) -> str:
    kind = metadata["input"]["kind"]
    platform = metadata["input"].get("platform") or "n/a"
    lines = [
        "# Video Study Case Plan",
        "",
        f"- Input kind: `{kind}`",
        f"- Platform: `{platform}`",
        f"- Created: `{metadata['created_at']}`",
        "",
        "## Next Actions",
        "",
    ]
    if kind in {"local_video", "local_audio"}:
        lines += [
            "1. Extract or import transcript with timestamps.",
            "2. Extract keyframes using uniform + scene-change sampling.",
            "3. Inspect keyframes for text, code, diagrams, and UI states.",
            "4. Merge transcript and visual notes into `analysis/merged_context.md`.",
            "5. Fact-check important claims.",
            "6. Generate files under `study_pack/`.",
        ]
    elif kind in {"url", "share_text"}:
        lines += [
            "1. Try public subtitles or permitted downloader for the detected platform.",
            "2. If acquisition fails, ask the user for a local video/audio/subtitle file.",
            "3. Continue with transcript, keyframes, visual notes, fact checks, and study pack.",
        ]
    elif kind == "local_folder":
        lines += [
            "1. Enumerate videos and process each as a separate part.",
            "2. Generate per-video notes.",
            "3. Merge duplicate knowledge and produce a course-level study pack.",
        ]
    else:
        lines += [
            "1. Ask the user for a local media file, subtitle file, supported URL, or share text.",
        ]
    lines += [
        "",
        "## Required Outputs",
        "",
        "- `study_pack/00_overview.md`",
        "- `study_pack/01_full_notes.md`",
        "- `study_pack/02_timeline.md`",
        "- `study_pack/03_key_knowledge.md`",
        "- `study_pack/04_corrections_and_supplements.md`",
        "- `study_pack/05_quiz.md`",
        "- `study_pack/06_flashcards.md`",
        "- `study_pack/07_guided_learning_plan.md`",
        "- `study_pack/08_practice_checklist.md`",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="video_study_case.py")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create a case workspace")
    init.add_argument("--input", required=True, help="Video path, folder, URL, subtitle, or share text")
    init.add_argument("--out", required=True, help="Output directory for case workspaces")
    init.set_defaults(func=create_case)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
