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
from typing import Any
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


def find_python_module_binary(module: str, attr: str) -> str | None:
    try:
        mod = __import__(module, fromlist=[attr])
        func = getattr(mod, attr)
        value = func()
        return str(value) if value else None
    except Exception:  # noqa: BLE001
        return None


def find_ffmpeg() -> str | None:
    return which("ffmpeg") or find_python_module_binary("imageio_ffmpeg", "get_ffmpeg_exe")


def find_ffprobe() -> str | None:
    return which("ffprobe")


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


def run_checked(cmd: list[str], timeout: int | None = None) -> None:
    p = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if p.returncode != 0:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(cmd)}\n{p.stdout}")


def probe_media(path: Path) -> dict:
    probe = {"available": False}
    ffprobe = find_ffprobe()
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


def media_duration_seconds(probe: dict) -> float | None:
    try:
        duration = probe.get("format", {}).get("duration")
        return float(duration) if duration is not None else None
    except (TypeError, ValueError):
        return None


def has_audio_stream(probe: dict) -> bool:
    return any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))


def has_video_stream(probe: dict) -> bool:
    return any(stream.get("codec_type") == "video" for stream in probe.get("streams", []))


def format_timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def srt_timestamp(seconds: float) -> str:
    return format_timestamp(seconds).replace(".", ",")


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
            "ffmpeg": find_ffmpeg(),
            "ffprobe": find_ffprobe(),
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


def extract_audio(ffmpeg: str, source: Path, out_wav: Path) -> None:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    run_checked([
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(out_wav),
    ])


def extract_uniform_keyframes(ffmpeg: str, source: Path, duration: float, out_dir: Path, count: int) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if duration <= 0:
        duration = float(count)
    frame_count = max(1, count)
    if frame_count == 1:
        times = [min(duration / 2, duration)]
    else:
        step = duration / frame_count
        times = [min(duration - 0.2, step * i + step / 2) for i in range(frame_count)]
    index = []
    for idx, ts in enumerate(times, start=1):
        ts = max(0.0, ts)
        label = format_timestamp(ts).replace(":", "-").replace(".", "-")
        frame_name = f"frame_{idx:03d}_{label}.jpg"
        frame_path = out_dir / frame_name
        run_checked([
            ffmpeg,
            "-y",
            "-ss",
            f"{ts:.3f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(frame_path),
        ])
        index.append({
            "index": idx,
            "timestamp_seconds": round(ts, 3),
            "timestamp": format_timestamp(ts),
            "file": str(frame_path),
            "reason": "uniform_sample",
        })
    return index


def write_segments_outputs(segments: list[dict], transcript_dir: Path) -> None:
    transcript_dir.mkdir(parents=True, exist_ok=True)
    write_json(transcript_dir / "segments.json", {"segments": segments})
    text_lines = []
    srt_lines = []
    for i, seg in enumerate(segments, start=1):
        start = float(seg["start"])
        end = float(seg["end"])
        text = str(seg["text"]).strip()
        text_lines.append(f"[{format_timestamp(start)} - {format_timestamp(end)}] {text}")
        srt_lines.extend([str(i), f"{srt_timestamp(start)} --> {srt_timestamp(end)}", text, ""])
    (transcript_dir / "transcript.txt").write_text("\n".join(text_lines) + "\n", encoding="utf-8")
    (transcript_dir / "transcript.srt").write_text("\n".join(srt_lines), encoding="utf-8")


def transcribe_audio(audio_path: Path, transcript_dir: Path, model_size: str, language: str | None) -> dict:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "error": f"faster-whisper unavailable: {exc}",
            "next_step": "Install faster-whisper or provide an existing subtitle file.",
        }
    model = WhisperModel(model_size, device="auto", compute_type="auto")
    segments_iter, info = model.transcribe(str(audio_path), language=language)
    segments = [
        {"start": seg.start, "end": seg.end, "text": seg.text}
        for seg in segments_iter
    ]
    write_segments_outputs(segments, transcript_dir)
    return {
        "available": True,
        "model_size": model_size,
        "language": getattr(info, "language", language),
        "language_probability": getattr(info, "language_probability", None),
        "segments": len(segments),
    }


def process_local(args: argparse.Namespace) -> None:
    case_dir = Path(args.case).resolve()
    metadata_path = case_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata.json not found: {metadata_path}")
    metadata = read_json(metadata_path)
    input_info = metadata.get("input", {})
    if input_info.get("kind") not in {"local_video", "local_audio"}:
        raise ValueError("process-local requires a local_video or local_audio case")
    source = Path(input_info["path"])
    if not source.exists():
        raise FileNotFoundError(str(source))

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found. Install ffmpeg or install imageio-ffmpeg in this Python environment.")

    probe = metadata.get("media_probe")
    if not probe or not probe.get("available"):
        probe = probe_media(source)
        metadata["media_probe"] = probe
    duration = media_duration_seconds(probe) or 0.0

    process_report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "duration_seconds": duration,
        "ffmpeg": ffmpeg,
        "audio": None,
        "keyframes": None,
        "transcription": None,
        "warnings": [],
    }

    if duration > args.max_single_minutes * 60:
        process_report["warnings"].append(
            f"Video is longer than {args.max_single_minutes} minutes; split before final study-pack generation."
        )

    audio_path = case_dir / "audio" / "audio_16k_mono.wav"
    if input_info.get("kind") == "local_audio":
        audio_path = source
        process_report["audio"] = {"mode": "source_audio", "file": str(audio_path)}
    elif has_audio_stream(probe):
        extract_audio(ffmpeg, source, audio_path)
        process_report["audio"] = {"mode": "extracted", "file": str(audio_path)}
    else:
        process_report["warnings"].append("No audio stream found; transcription skipped.")

    if input_info.get("kind") == "local_video" and has_video_stream(probe):
        keyframes = extract_uniform_keyframes(
            ffmpeg,
            source,
            duration,
            case_dir / "keyframes",
            args.keyframes,
        )
        write_json(case_dir / "keyframes" / "keyframes.json", {"frames": keyframes})
        process_report["keyframes"] = {"count": len(keyframes), "index": "keyframes/keyframes.json"}
    else:
        process_report["warnings"].append("No video stream found; keyframe extraction skipped.")

    if args.transcribe and process_report.get("audio"):
        process_report["transcription"] = transcribe_audio(
            audio_path,
            case_dir / "transcript",
            args.model,
            args.language,
        )
    elif process_report.get("audio"):
        process_report["transcription"] = {
            "available": False,
            "skipped": True,
            "next_step": "Run again with --transcribe, or provide subtitle files.",
        }

    process_report["finished_at"] = datetime.now(timezone.utc).isoformat()
    metadata["process_local"] = process_report
    write_json(metadata_path, metadata)
    write_json(case_dir / "reports" / "process_local.json", process_report)
    (case_dir / "analysis" / "next_agent_steps.md").write_text(make_next_agent_steps(process_report), encoding="utf-8")
    print(str(case_dir / "reports" / "process_local.json"))


def make_next_agent_steps(report: dict[str, Any]) -> str:
    lines = [
        "# Next Agent Steps",
        "",
        "1. Read `metadata.json` and `reports/process_local.json`.",
        "2. If `transcript/transcript.txt` exists, use it as the main speech evidence.",
        "3. Inspect images listed in `keyframes/keyframes.json` with vision tools.",
        "4. Align visual notes with transcript timestamps.",
        "5. Extract factual claims and fact-check important ones.",
        "6. Generate the required `study_pack/` files.",
        "",
        "## Processing Summary",
        "",
        f"- Source: `{report.get('source')}`",
        f"- Duration seconds: `{report.get('duration_seconds')}`",
        f"- Audio: `{report.get('audio')}`",
        f"- Keyframes: `{report.get('keyframes')}`",
        f"- Transcription: `{report.get('transcription')}`",
    ]
    warnings = report.get("warnings") or []
    if warnings:
        lines += ["", "## Warnings", ""]
        lines += [f"- {warning}" for warning in warnings]
    return "\n".join(lines) + "\n"


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

    process = sub.add_parser("process-local", help="Extract audio/keyframes and optionally transcribe a local media case")
    process.add_argument("--case", required=True, help="Case directory created by init")
    process.add_argument("--keyframes", type=int, default=30, help="Number of uniform keyframes to extract")
    process.add_argument("--transcribe", action="store_true", help="Transcribe extracted audio with faster-whisper")
    process.add_argument("--model", default="small", help="faster-whisper model size or local model path")
    process.add_argument("--language", default="zh", help="Transcription language, or empty string for auto")
    process.add_argument("--max-single-minutes", type=int, default=60, help="Warn when media exceeds this length")
    process.set_defaults(func=process_local)

    args = parser.parse_args(argv)
    if hasattr(args, "language") and args.language == "":
        args.language = None
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
