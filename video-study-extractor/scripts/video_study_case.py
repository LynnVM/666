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
SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?", re.UNICODE)
CLAIM_HINT_RE = re.compile(
    r"(必须|一定|不会|不能|可以|应该|需要|导致|因为|所以|原理|定义|区别|优点|缺点|最好|唯一|always|never|must|should|because|therefore)",
    re.IGNORECASE,
)
STUDY_PACK_FILES = [
    "00_overview.md",
    "01_full_notes.md",
    "02_timeline.md",
    "03_key_knowledge.md",
    "04_corrections_and_supplements.md",
    "05_quiz.md",
    "06_flashcards.md",
    "07_guided_learning_plan.md",
    "08_practice_checklist.md",
]


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


def find_yt_dlp_cmd() -> list[str] | None:
    exe = which("yt-dlp") or which("yt_dlp")
    if exe:
        return [exe]
    code, _ = run_capture([sys.executable, "-m", "yt_dlp", "--version"], timeout=10)
    if code == 0:
        return [sys.executable, "-m", "yt_dlp"]
    return None


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
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_text_if_exists(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def ensure_case_dirs(case_dir: Path) -> None:
    for sub in ["transcript", "keyframes", "analysis", "reports", "study_pack"]:
        (case_dir / sub).mkdir(parents=True, exist_ok=True)


def build_case(args_input: str, out_dir: Path) -> Path:
    info = classify_input(args_input)
    fingerprint = sha256_text(args_input)[:12]
    base = safe_name(Path(info.get("path") or args_input).stem if info.get("path") else info.get("platform") or "input")
    case_dir = out_dir.resolve() / f"{base}-{fingerprint}"

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
    return case_dir


def create_case(args: argparse.Namespace) -> None:
    case_dir = build_case(args.input, Path(args.out))
    print(str(case_dir))


def create_folder_cases(args: argparse.Namespace) -> None:
    folder = Path(args.input).resolve()
    if not folder.exists() or not folder.is_dir():
        raise NotADirectoryError(str(folder))
    media = [
        p for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS | AUDIO_EXTS | SUBTITLE_EXTS
    ]
    media.sort()
    out_dir = Path(args.out)
    created = []
    for path in media:
        case_dir = build_case(str(path), out_dir)
        created.append({"input": str(path), "case": str(case_dir)})
    index = {"source_folder": str(folder), "count": len(created), "cases": created}
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir.resolve() / "folder_cases.json", index)
    print(str(out_dir.resolve() / "folder_cases.json"))


def acquire_url(args: argparse.Namespace) -> None:
    case_dir = Path(args.case).resolve()
    metadata_path = case_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata.json not found: {metadata_path}")
    metadata = read_json(metadata_path)
    input_info = metadata.get("input", {})
    if input_info.get("kind") not in {"url", "share_text"}:
        raise ValueError("acquire-url requires a url or share_text case")
    urls = input_info.get("urls") or []
    if not urls:
        raise ValueError("No URL found in case metadata")
    url = urls[0]
    ytdlp = find_yt_dlp_cmd()
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "platform": input_info.get("platform"),
        "yt_dlp": ytdlp,
        "dry_run": args.dry_run,
        "mode": "subtitles_only" if not args.download else "subtitles_and_media",
        "sub_langs": args.sub_langs,
        "subtitles": None,
        "media": None,
        "warnings": [],
    }
    if not ytdlp:
        report["warnings"].append("yt-dlp is not installed. Install yt-dlp or provide a local video/subtitle file.")
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(case_dir / "reports" / "acquire_url.json", report)
        metadata["acquire_url"] = report
        write_json(metadata_path, metadata)
        print(str(case_dir / "reports" / "acquire_url.json"))
        return

    subtitle_dir = case_dir / "transcript" / "subtitles"
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    subtitle_cmd = ytdlp + [
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        args.sub_langs,
        "--convert-subs",
        "srt",
        "--no-playlist",
        "--ignore-errors",
        "-o",
        str(subtitle_dir / "%(title).100s.%(ext)s"),
        url,
    ]
    report["subtitles"] = {"command": subtitle_cmd}
    if not args.dry_run:
        code, out = run_capture(subtitle_cmd, timeout=args.timeout)
        report["subtitles"].update({"returncode": code, "output_tail": out[-4000:]})
        report["subtitles"]["files"] = [str(p) for p in subtitle_dir.glob("*")]

    if args.download:
        media_dir = case_dir / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        media_cmd = ytdlp + [
            "-f",
            args.format,
            "--merge-output-format",
            "mp4",
            "--no-playlist",
            "--ignore-errors",
            "-o",
            str(media_dir / "source.%(ext)s"),
            url,
        ]
        report["media"] = {"command": media_cmd}
        if not args.dry_run:
            code, out = run_capture(media_cmd, timeout=args.timeout)
            files = [
                str(p) for p in media_dir.glob("source.*")
                if p.suffix.lower() in VIDEO_EXTS | AUDIO_EXTS
            ]
            report["media"].update({"returncode": code, "output_tail": out[-4000:], "files": files})
            if files:
                report["media_file"] = files[0]
                report["media_probe"] = probe_media(Path(files[0]))
                metadata["input"] = {
                    **input_info,
                    "acquired_media_path": files[0],
                    "acquired_media_kind": "local_video",
                }
            else:
                report["warnings"].append(
                    "No media file was acquired. Provide a local video/audio/subtitle file if the platform blocks access."
                )

    if not args.dry_run:
        subtitle_files = report.get("subtitles", {}).get("files") or []
        if not subtitle_files:
            report["warnings"].append(
                "No subtitle file was acquired. Try --download for permitted media, or provide a local subtitle/video file."
            )

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    metadata["acquire_url"] = report
    write_json(metadata_path, metadata)
    write_json(case_dir / "reports" / "acquire_url.json", report)
    print(str(case_dir / "reports" / "acquire_url.json"))


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


def extract_scene_keyframes(
    ffmpeg: str,
    source: Path,
    out_dir: Path,
    threshold: float,
    max_frames: int,
) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "scene_%03d.jpg"
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-vf",
        f"select='gt(scene,{threshold})',showinfo",
        "-vsync",
        "vfr",
        "-frames:v",
        str(max_frames),
        "-q:v",
        "2",
        str(pattern),
    ]
    p = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if p.returncode != 0:
        raise RuntimeError(f"Scene keyframe extraction failed:\n{p.stdout}")
    pts_times = [float(m.group(1)) for m in re.finditer(r"pts_time:([0-9.]+)", p.stdout)]
    files = sorted(out_dir.glob("scene_*.jpg"))
    index = []
    for idx, frame_path in enumerate(files[:max_frames], start=1):
        ts = pts_times[idx - 1] if idx - 1 < len(pts_times) else None
        if ts is not None:
            new_name = f"scene_{idx:03d}_{format_timestamp(ts).replace(':', '-').replace('.', '-')}.jpg"
            new_path = out_dir / new_name
            if new_path != frame_path:
                frame_path.rename(new_path)
                frame_path = new_path
        index.append({
            "index": idx,
            "timestamp_seconds": round(ts, 3) if ts is not None else None,
            "timestamp": format_timestamp(ts) if ts is not None else None,
            "file": str(frame_path),
            "reason": "scene_change",
            "threshold": threshold,
        })
    return index


def merge_keyframe_indexes(*indexes: list[dict]) -> list[dict]:
    merged = []
    seen_files = set()
    for index in indexes:
        for item in index:
            file_path = item.get("file")
            if file_path in seen_files:
                continue
            seen_files.add(file_path)
            merged.append(item)
    merged.sort(key=lambda item: (item.get("timestamp_seconds") is None, item.get("timestamp_seconds") or 0.0))
    for idx, item in enumerate(merged, start=1):
        item["merged_index"] = idx
    return merged


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
        uniform_keyframes = extract_uniform_keyframes(
            ffmpeg,
            source,
            duration,
            case_dir / "keyframes",
            args.keyframes,
        )
        scene_keyframes = []
        if args.scene_keyframes > 0:
            scene_keyframes = extract_scene_keyframes(
                ffmpeg,
                source,
                case_dir / "keyframes" / "scene",
                args.scene_threshold,
                args.scene_keyframes,
            )
        keyframes = merge_keyframe_indexes(uniform_keyframes, scene_keyframes)
        write_json(case_dir / "keyframes" / "keyframes.json", {
            "frames": keyframes,
            "uniform_count": len(uniform_keyframes),
            "scene_count": len(scene_keyframes),
        })
        process_report["keyframes"] = {
            "count": len(keyframes),
            "uniform_count": len(uniform_keyframes),
            "scene_count": len(scene_keyframes),
            "index": "keyframes/keyframes.json",
        }
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


def write_study_pack_template(args: argparse.Namespace) -> None:
    case_dir = Path(args.case).resolve()
    metadata_path = case_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata.json not found: {metadata_path}")
    metadata = read_json(metadata_path)
    study_pack = case_dir / "study_pack"
    study_pack.mkdir(parents=True, exist_ok=True)
    templates = {
        "00_overview.md": overview_template(metadata),
        "01_full_notes.md": full_notes_template(),
        "02_timeline.md": timeline_template(),
        "03_key_knowledge.md": key_knowledge_template(),
        "04_corrections_and_supplements.md": corrections_template(),
        "05_quiz.md": quiz_template(),
        "06_flashcards.md": flashcards_template(),
        "07_guided_learning_plan.md": guided_plan_template(),
        "08_practice_checklist.md": practice_template(),
    }
    for name, content in templates.items():
        path = study_pack / name
        if args.force or not path.exists():
            path.write_text(content, encoding="utf-8")
    print(str(study_pack))


def load_segments(case_dir: Path) -> list[dict[str, Any]]:
    clean_path = case_dir / "transcript" / "clean_segments.json"
    segments_path = case_dir / "transcript" / "segments.json"
    transcript_path = case_dir / "transcript" / "transcript.txt"
    for path in [clean_path, segments_path]:
        if path.exists():
            data = read_json(path)
            return normalize_segments(data.get("segments", []))
    text = read_text_if_exists(transcript_path).strip()
    if not text:
        return []
    segments = []
    for idx, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"\[([0-9:.]+)\s+-\s+([0-9:.]+)\]\s*(.*)", line)
        if m:
            segments.append({"start": parse_timestamp(m.group(1)), "end": parse_timestamp(m.group(2)), "text": m.group(3).strip()})
        else:
            segments.append({"start": float(idx * 30), "end": float((idx + 1) * 30), "text": line})
    return segments


def normalize_segments(raw_segments: list[Any]) -> list[dict[str, Any]]:
    segments = []
    for item in raw_segments:
        if not isinstance(item, dict):
            continue
        text = clean_caption_text(str(item.get("text", "")))
        if not text:
            continue
        start = safe_float(item.get("start", 0.0))
        end = safe_float(item.get("end", start + 1.0))
        if end < start:
            end = start
        segments.append({"start": start, "end": end, "text": text})
    segments.sort(key=lambda s: (float(s["start"]), float(s["end"])))
    return segments


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_caption_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\{\\.*?\}", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^\s*[-–—]\s*", "", text)
    return text.strip()


def parse_srt_or_vtt(text: str) -> list[dict[str, Any]]:
    text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n{2,}", text.strip())
    segments = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if lines[0].upper().startswith("WEBVTT"):
            lines = lines[1:]
        if lines and re.fullmatch(r"\d+", lines[0]):
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            continue
        start_text, end_text = [part.strip().split()[0] for part in lines[0].split("-->", 1)]
        caption = clean_caption_text(" ".join(lines[1:]))
        if caption:
            segments.append({
                "start": parse_timestamp(start_text),
                "end": parse_timestamp(end_text),
                "text": caption,
            })
    return normalize_segments(segments)


def find_transcript_source(case_dir: Path, metadata: dict[str, Any], explicit: str | None = None) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path.resolve() if path.exists() else None
    input_info = metadata.get("input", {})
    if input_info.get("kind") == "subtitle" and input_info.get("path"):
        path = Path(input_info["path"])
        if path.exists():
            return path
    for pattern in ["*.srt", "*.vtt", "*.txt"]:
        matches = sorted((case_dir / "transcript" / "subtitles").glob(pattern))
        if matches:
            return matches[0]
    for name in ["transcript.srt", "transcript.vtt", "transcript.txt"]:
        path = case_dir / "transcript" / name
        if path.exists():
            return path
    return None


def load_segments_from_source(source: Path) -> list[dict[str, Any]]:
    text = read_text_if_exists(source)
    if source.suffix.lower() in {".srt", ".vtt"} or "-->" in text:
        return parse_srt_or_vtt(text)
    segments = []
    for idx, line in enumerate(text.splitlines()):
        line = clean_caption_text(line)
        if not line:
            continue
        m = re.match(r"\[([0-9:.,]+)\s+-\s+([0-9:.,]+)\]\s*(.*)", line)
        if m:
            segments.append({"start": parse_timestamp(m.group(1)), "end": parse_timestamp(m.group(2)), "text": m.group(3)})
        else:
            segments.append({"start": idx * 30.0, "end": (idx + 1) * 30.0, "text": line})
    return normalize_segments(segments)


def merge_short_segments(
    segments: list[dict[str, Any]],
    max_gap: float,
    max_chars: int,
    max_duration: float,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for seg in normalize_segments(segments):
        if not merged:
            merged.append(dict(seg))
            continue
        prev = merged[-1]
        gap = float(seg["start"]) - float(prev["end"])
        combined = clean_caption_text(f"{prev['text']} {seg['text']}")
        duration = float(seg["end"]) - float(prev["start"])
        if gap <= max_gap and len(combined) <= max_chars and duration <= max_duration:
            prev["end"] = max(float(prev["end"]), float(seg["end"]))
            prev["text"] = combined
        else:
            merged.append(dict(seg))
    return merged


def clean_transcript(args: argparse.Namespace) -> None:
    case_dir = Path(args.case).resolve()
    metadata_path = case_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata.json not found: {metadata_path}")
    ensure_case_dirs(case_dir)
    metadata = read_json(metadata_path)
    source = find_transcript_source(case_dir, metadata, args.source)
    if source:
        raw_segments = load_segments_from_source(source)
    else:
        raw_segments = load_segments(case_dir)
    if not raw_segments:
        raise ValueError("No transcript or subtitle content found. Provide --source or run transcription first.")

    cleaned = merge_short_segments(
        raw_segments,
        max_gap=args.max_gap,
        max_chars=args.max_chars,
        max_duration=args.max_duration,
    )
    chapters = segment_chapters(cleaned, args.chapter_minutes)
    transcript_dir = case_dir / "transcript"
    write_json(transcript_dir / "clean_segments.json", {
        "source": str(source) if source else "existing transcript segments",
        "raw_count": len(raw_segments),
        "segments": cleaned,
    })
    write_segments_outputs(cleaned, transcript_dir)
    write_json(case_dir / "analysis" / "chapters.json", {"chapters": chapters})
    report = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source) if source else None,
        "raw_segments": len(raw_segments),
        "clean_segments": len(cleaned),
        "chapters": len(chapters),
        "outputs": [
            "transcript/clean_segments.json",
            "transcript/segments.json",
            "transcript/transcript.txt",
            "transcript/transcript.srt",
            "analysis/chapters.json",
        ],
    }
    metadata["clean_transcript"] = report
    write_json(metadata_path, metadata)
    write_json(case_dir / "reports" / "clean_transcript.json", report)
    print(str(case_dir / "reports" / "clean_transcript.json"))


def parse_timestamp(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except (TypeError, ValueError):
        return 0.0


def load_keyframes(case_dir: Path) -> list[dict[str, Any]]:
    path = case_dir / "keyframes" / "keyframes.json"
    if not path.exists():
        return []
    return read_json(path).get("frames", [])


def frame_notes(args: argparse.Namespace) -> None:
    case_dir = Path(args.case).resolve()
    metadata_path = case_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata.json not found: {metadata_path}")
    ensure_case_dirs(case_dir)
    keyframes = load_keyframes(case_dir)
    segments = load_segments(case_dir)
    out_path = case_dir / "analysis" / "frame_observations.md"
    lines = [
        "# Frame Observations",
        "",
        "Use this file as the visual evidence pass. Inspect each listed image with vision tools, then fill the fields.",
        "",
    ]
    if not keyframes:
        lines += [
            "No keyframes were found. Run `process-local` on a local video case first.",
            "",
        ]
    for frame in keyframes[: args.limit]:
        timestamp = str(frame.get("timestamp") or format_timestamp(safe_float(frame.get("timestamp_seconds"))))
        frame_file = str(frame.get("file") or "")
        nearby = nearest_segment_text(segments, safe_float(frame.get("timestamp_seconds")), args.context_seconds)
        lines += [
            f"## [{timestamp}] {Path(frame_file).name}",
            "",
            f"- File: `{frame_file}`",
            f"- Reason: {frame.get('reason') or 'keyframe'}",
            f"- Nearby transcript: {nearby or 'TODO'}",
            "- Visible text/OCR: TODO",
            "- Diagram/code/UI observation: TODO",
            "- Learning value: TODO",
            "- Possible mismatch with transcript: TODO",
            "",
        ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    report = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "frames_total": len(keyframes),
        "frames_written": min(len(keyframes), args.limit),
        "output": "analysis/frame_observations.md",
    }
    write_json(case_dir / "reports" / "frame_notes.json", report)
    print(str(out_path))


def nearest_segment_text(segments: list[dict[str, Any]], timestamp: float, window: float) -> str:
    nearby = [
        str(seg.get("text", ""))
        for seg in segments
        if abs(safe_float(seg.get("start")) - timestamp) <= window
        or safe_float(seg.get("start")) <= timestamp <= safe_float(seg.get("end"))
    ]
    return summarize_text(" ".join(nearby), 260)


def segment_chapters(segments: list[dict[str, Any]], chapter_minutes: int) -> list[dict[str, Any]]:
    if not segments:
        return []
    window = max(5, chapter_minutes) * 60
    chapters: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    start = float(segments[0]["start"])
    for seg in segments:
        if current and float(seg["start"]) - start >= window:
            chapters.append(make_chapter(current, len(chapters) + 1))
            current = []
            start = float(seg["start"])
        current.append(seg)
    if current:
        chapters.append(make_chapter(current, len(chapters) + 1))
    return chapters


def make_chapter(segments: list[dict[str, Any]], index: int) -> dict[str, Any]:
    text = normalize_space(" ".join(str(s["text"]) for s in segments))
    keywords = extract_keywords(text, 8)
    title = " / ".join(keywords[:3]) if keywords else f"Part {index}"
    return {
        "index": index,
        "start": float(segments[0]["start"]),
        "end": float(segments[-1]["end"]),
        "title": title,
        "segments": segments,
        "text": text,
        "keywords": keywords,
        "summary": summarize_text(text, 220),
    }


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str) -> list[str]:
    return [normalize_space(m.group(0)) for m in SENTENCE_RE.finditer(text) if normalize_space(m.group(0))]


def summarize_text(text: str, max_chars: int) -> str:
    sentences = split_sentences(text)
    if not sentences:
        return text[:max_chars]
    out = ""
    for sentence in sentences:
        if len(out) + len(sentence) > max_chars and out:
            break
        out += sentence
    return out[:max_chars].strip()


def extract_keywords(text: str, limit: int) -> list[str]:
    stop = {
        "然后", "这个", "就是", "我们", "你们", "他们", "如果", "因为", "所以", "但是", "一个", "这里",
        "可以", "没有", "进行", "时候", "需要", "the", "and", "that", "this", "with", "for", "you", "are",
    }
    words = re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}|[\u4e00-\u9fff]{2,8}", text)
    counts: dict[str, int] = {}
    for word in words:
        if word.lower() in stop or word in stop:
            continue
        counts[word] = counts.get(word, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def keyframes_near(keyframes: list[dict[str, Any]], start: float, end: float, limit: int = 5) -> list[dict[str, Any]]:
    frames = [
        f for f in keyframes
        if f.get("timestamp_seconds") is not None and start <= float(f["timestamp_seconds"]) <= end
    ]
    return frames[:limit]


def extract_claim_candidates(segments: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    claims = []
    for seg in segments:
        for sentence in split_sentences(str(seg["text"])):
            if len(sentence) < 10:
                continue
            if CLAIM_HINT_RE.search(sentence):
                claims.append({
                    "timestamp": format_timestamp(float(seg["start"])),
                    "start": float(seg["start"]),
                    "text": sentence,
                    "reason": "contains claim-like wording",
                    "status": "needs_fact_check",
                })
            if len(claims) >= limit:
                return claims
    return claims


def generate_study_pack(args: argparse.Namespace) -> None:
    case_dir = Path(args.case).resolve()
    metadata_path = case_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata.json not found: {metadata_path}")
    metadata = read_json(metadata_path)
    segments = load_segments(case_dir)
    keyframes = load_keyframes(case_dir)
    chapters = segment_chapters(segments, args.chapter_minutes)
    claims = extract_claim_candidates(segments, args.claims)
    study_pack = case_dir / "study_pack"
    study_pack.mkdir(parents=True, exist_ok=True)

    context = {
        "metadata": metadata,
        "segments": segments,
        "chapters": chapters,
        "keyframes": keyframes,
        "claims": claims,
    }
    write_json(case_dir / "analysis" / "study_pack_context.json", context)
    write_json(case_dir / "analysis" / "claim_candidates.json", {"claims": claims})

    outputs = {
        "00_overview.md": render_overview(context),
        "01_full_notes.md": render_full_notes(context),
        "02_timeline.md": render_timeline(context),
        "03_key_knowledge.md": render_key_knowledge(context),
        "04_corrections_and_supplements.md": render_corrections(context),
        "05_quiz.md": render_quiz(context),
        "06_flashcards.md": render_flashcards(context),
        "07_guided_learning_plan.md": render_guided_plan(context),
        "08_practice_checklist.md": render_practice_checklist(context),
    }
    for name, content in outputs.items():
        path = study_pack / name
        if args.force or not path.exists() or args.overwrite_generated:
            path.write_text(content, encoding="utf-8")
    print(str(study_pack))


def self_test(args: argparse.Namespace) -> None:
    out_dir = Path(args.out).resolve()
    case_dir = build_case("v0.6 self test subtitle", out_dir)
    sample = """1
00:00:00,000 --> 00:00:02,000
今天我们学习机器人建图。

2
00:00:02,200 --> 00:00:05,000
如果里程计方向错了，地图可能会旋转。

3
00:00:05,200 --> 00:00:08,000
所以必须检查 TF、雷达安装方向和坐标系。

4
00:00:15,000 --> 00:00:19,000
建图完成后应该保存地图并验证定位效果。
"""
    subtitle_path = case_dir / "transcript" / "sample.srt"
    subtitle_path.write_text(sample, encoding="utf-8")
    clean_args = argparse.Namespace(
        case=str(case_dir),
        source=str(subtitle_path),
        max_gap=1.0,
        max_chars=120,
        max_duration=12.0,
        chapter_minutes=5,
    )
    clean_transcript(clean_args)
    keyframes = [
        {"timestamp_seconds": 1.0, "timestamp": format_timestamp(1.0), "file": str(case_dir / "keyframes" / "frame_001.jpg"), "reason": "self-test"},
        {"timestamp_seconds": 6.0, "timestamp": format_timestamp(6.0), "file": str(case_dir / "keyframes" / "frame_002.jpg"), "reason": "self-test"},
    ]
    write_json(case_dir / "keyframes" / "keyframes.json", {"frames": keyframes})
    frame_notes(argparse.Namespace(case=str(case_dir), limit=20, context_seconds=10.0))
    generate_study_pack(argparse.Namespace(case=str(case_dir), chapter_minutes=5, claims=10, force=True, overwrite_generated=True))
    report = {
        "case": str(case_dir),
        "checks": [
            "transcript/clean_segments.json",
            "analysis/chapters.json",
            "analysis/frame_observations.md",
            "study_pack/00_overview.md",
        ],
    }
    write_json(case_dir / "reports" / "self_test.json", report)
    print(str(case_dir / "reports" / "self_test.json"))


def source_label(metadata: dict[str, Any]) -> str:
    input_info = metadata.get("input", {})
    return str(input_info.get("path") or input_info.get("raw_input") or "unknown")


def render_overview(context: dict[str, Any]) -> str:
    metadata = context["metadata"]
    chapters = context["chapters"]
    all_text = " ".join(ch.get("text", "") for ch in chapters)
    keywords = extract_keywords(all_text, 12)
    best = chapters[:5]
    return "\n".join([
        "# 一页速览",
        "",
        f"来源：`{source_label(metadata)}`",
        "",
        "## 视频主题",
        "",
        " / ".join(keywords[:5]) if keywords else "需要结合关键帧和转写进一步确认。",
        "",
        "## 核心收获",
        "",
        *[f"- {kw}" for kw in keywords[:7]],
        "",
        "## 最值得回看的时间点",
        "",
        *[f"- [{format_timestamp(ch['start'])}] {ch['title']}" for ch in best],
        "",
        "## 学习建议",
        "",
        "先按时间轴快速浏览，再逐章学习完整笔记。遇到 `04_corrections_and_supplements.md` 中的待核查点时，优先查官方资料后再记忆。",
        "",
    ])


def render_full_notes(context: dict[str, Any]) -> str:
    keyframes = context["keyframes"]
    lines = ["# 完整学习笔记", ""]
    if not context["chapters"]:
        return "# 完整学习笔记\n\n未找到转写内容。请先提供字幕或运行转写。\n"
    for ch in context["chapters"]:
        frames = keyframes_near(keyframes, ch["start"], ch["end"])
        lines += [
            f"## [{format_timestamp(ch['start'])}-{format_timestamp(ch['end'])}] {ch['title']}",
            "",
            "讲了什么：",
            "",
            ch["summary"] or "TODO",
            "",
            "关键知识：",
            "",
            *[f"- {kw}" for kw in ch.get("keywords", [])[:6]],
            "",
            "画面补充：",
            "",
        ]
        if frames:
            lines += [f"- [{f.get('timestamp')}] `{Path(str(f.get('file'))).name}` ({f.get('reason')})" for f in frames]
        else:
            lines += ["- TODO: 检查本章附近关键帧。"]
        lines += ["", "需要记住：", "", "- TODO: 由 AI 结合画面和事实核查补全。", ""]
    return "\n".join(lines)


def render_timeline(context: dict[str, Any]) -> str:
    lines = ["# 时间轴", ""]
    chapters = context["chapters"]
    if chapters:
        lines += [f"- [{format_timestamp(ch['start'])}] {ch['title']}：{ch['summary']}" for ch in chapters]
    else:
        lines += ["- TODO: 未找到转写内容。"]
    return "\n".join(lines) + "\n"


def render_key_knowledge(context: dict[str, Any]) -> str:
    text = " ".join(ch.get("text", "") for ch in context["chapters"])
    keywords = extract_keywords(text, 20)
    lines = ["# 关键知识点", ""]
    if not keywords:
        return "# 关键知识点\n\n未找到足够文本。请先转写或提供字幕。\n"
    for kw in keywords:
        related = [
            ch for ch in context["chapters"]
            if kw in ch.get("text", "")
        ][:3]
        lines += [
            f"## {kw}",
            "",
            "定义：TODO: 结合视频上下文和外部资料补全。",
            "",
            "为什么重要：TODO",
            "",
            "相关时间点：",
            "",
            *[f"- [{format_timestamp(ch['start'])}] {ch['title']}" for ch in related],
            "",
            "常见误区：TODO",
            "",
        ]
    return "\n".join(lines)


def render_corrections(context: dict[str, Any]) -> str:
    lines = ["# 视频纠错与补充", "", "以下是自动抽取的待核查断言候选。需要 AI 联网或查权威资料后填写核查结论。", ""]
    claims = context["claims"]
    if not claims:
        lines += ["暂无明显待核查断言。"]
        return "\n".join(lines) + "\n"
    for claim in claims:
        lines += [
            f"## [{claim['timestamp']}] 待核查说法",
            "",
            f"视频原说法：{claim['text']}",
            "",
            "核查结论：无法核查",
            "",
            "依据：TODO: 优先官方文档、标准、论文、教材或权威资料。",
            "",
            "建议学习者采用的说法：TODO",
            "",
        ]
    return "\n".join(lines)


def render_quiz(context: dict[str, Any]) -> str:
    keywords = extract_keywords(" ".join(ch.get("text", "") for ch in context["chapters"]), 10)
    lines = ["# 复习题", "", "## 基础题", ""]
    for idx, kw in enumerate(keywords[:5], start=1):
        lines.append(f"{idx}. 视频中 `{kw}` 主要指什么？")
    lines += ["", "## 理解题", ""]
    for idx, ch in enumerate(context["chapters"][:3], start=1):
        lines.append(f"{idx}. [{format_timestamp(ch['start'])}] 这一段的核心逻辑是什么？")
    lines += ["", "## 应用题", "", "1. 如果把视频里的方法用到自己的任务中，第一步应该做什么？", "", "## 答案", "", "TODO: 学习者作答后由 AI 结合笔记讲解。", ""]
    return "\n".join(lines)


def render_flashcards(context: dict[str, Any]) -> str:
    keywords = extract_keywords(" ".join(ch.get("text", "") for ch in context["chapters"]), 12)
    lines = ["# 闪卡", ""]
    for kw in keywords:
        related = next((ch for ch in context["chapters"] if kw in ch.get("text", "")), None)
        source = format_timestamp(related["start"]) if related else "00:00:00.000"
        lines += [f"Q: `{kw}` 是什么？", "", "A: TODO: 结合视频和核查资料补全。", "", f"Source: [{source}]", ""]
    return "\n".join(lines)


def render_guided_plan(context: dict[str, Any]) -> str:
    lines = ["# AI 导学路线", "", "## 学习顺序", ""]
    if context["chapters"]:
        lines += [f"{idx}. [{format_timestamp(ch['start'])}] {ch['title']}" for idx, ch in enumerate(context["chapters"], start=1)]
    else:
        lines += ["1. 先补充字幕或转写。"]
    lines += [
        "",
        "## 带学方式",
        "",
        "- 每次讲一个章节。",
        "- 每章讲完后问 1-3 个问题。",
        "- 学习者答错时，回到对应时间点解释。",
        "- 遇到待核查断言，先查资料再给确定结论。",
        "",
        "## 完成标准",
        "",
        "- 能复述每章核心观点。",
        "- 能回答复习题。",
        "- 能指出视频中待核查或可能错误的说法。",
        "",
    ]
    return "\n".join(lines)


def render_practice_checklist(context: dict[str, Any]) -> str:
    lines = ["# 实操清单", "", "## 环境准备", "", "- TODO: 从视频中提取工具、软件、数据、硬件要求。", "", "## 操作步骤", ""]
    for idx, ch in enumerate(context["chapters"], start=1):
        lines.append(f"{idx}. [{format_timestamp(ch['start'])}] 学习并复现：{ch['title']}")
    lines += ["", "## 验证方法", "", "- TODO: 从视频中提取成功现象、测试命令或检查标准。", "", "## 常见错误", "", "- TODO: 结合视频演示和评论/外部资料补全。", ""]
    return "\n".join(lines)


def overview_template(metadata: dict[str, Any]) -> str:
    source = metadata.get("input", {}).get("path") or metadata.get("input", {}).get("raw_input")
    return f"""# 一页速览

来源：`{source}`

## 视频主题

TODO

## 适合谁学

TODO

## 前置知识

TODO

## 核心收获

- TODO

## 最值得回看的时间点

- [00:00:00] TODO

## 学习建议

TODO
"""


def full_notes_template() -> str:
    return """# 完整学习笔记

## [00:00:00-00:00:00] 章节标题

讲了什么：

关键知识：

画面补充：

需要记住：

可操作步骤：
"""


def timeline_template() -> str:
    return """# 时间轴

- [00:00:00] TODO
"""


def key_knowledge_template() -> str:
    return """# 关键知识点

## 知识点

定义：

为什么重要：

视频证据：

相关时间点：

常见误区：
"""


def corrections_template() -> str:
    return """# 视频纠错与补充

## [00:00:00] 待核查说法

视频原说法：

核查结论：正确 / 基本正确但不完整 / 有争议 / 疑似错误 / 错误 / 无法核查

依据：

建议学习者采用的说法：
"""


def quiz_template() -> str:
    return """# 复习题

## 基础题

1. TODO

## 理解题

1. TODO

## 应用题

1. TODO

## 答案

1. TODO
"""


def flashcards_template() -> str:
    return """# 闪卡

Q: TODO

A: TODO

Source: [00:00:00]
"""


def guided_plan_template() -> str:
    return """# AI 导学路线

## 学习顺序

1. TODO

## 需要暂停练习的地方

- [00:00:00] TODO

## AI 应该如何带学

- TODO

## 完成标准

- TODO
"""


def practice_template() -> str:
    return """# 实操清单

## 环境准备

- TODO

## 操作步骤

1. TODO

## 验证方法

- TODO

## 常见错误

- TODO
"""


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
            "1. Run `acquire-url` to try public subtitles first.",
            "2. Use `acquire-url --download` only when media download is permitted and needed.",
            "3. If acquisition fails, ask the user for a local video/audio/subtitle file.",
            "4. Continue with transcript, keyframes, visual notes, fact checks, and study pack.",
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
    ]
    lines += [f"- `study_pack/{name}`" for name in STUDY_PACK_FILES]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="video_study_case.py")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create a case workspace")
    init.add_argument("--input", required=True, help="Video path, folder, URL, subtitle, or share text")
    init.add_argument("--out", required=True, help="Output directory for case workspaces")
    init.set_defaults(func=create_case)

    folder = sub.add_parser("init-folder", help="Create cases for every media/subtitle file in a folder")
    folder.add_argument("--input", required=True, help="Folder containing media files")
    folder.add_argument("--out", required=True, help="Output directory for case workspaces")
    folder.set_defaults(func=create_folder_cases)

    process = sub.add_parser("process-local", help="Extract audio/keyframes and optionally transcribe a local media case")
    process.add_argument("--case", required=True, help="Case directory created by init")
    process.add_argument("--keyframes", type=int, default=30, help="Number of uniform keyframes to extract")
    process.add_argument("--scene-keyframes", type=int, default=20, help="Maximum scene-change keyframes to extract")
    process.add_argument("--scene-threshold", type=float, default=0.35, help="FFmpeg scene-change threshold")
    process.add_argument("--transcribe", action="store_true", help="Transcribe extracted audio with faster-whisper")
    process.add_argument("--model", default="small", help="faster-whisper model size or local model path")
    process.add_argument("--language", default="zh", help="Transcription language, or empty string for auto")
    process.add_argument("--max-single-minutes", type=int, default=60, help="Warn when media exceeds this length")
    process.set_defaults(func=process_local)

    acquire = sub.add_parser("acquire-url", help="Acquire public subtitles and optionally media for a URL/share case")
    acquire.add_argument("--case", required=True, help="Case directory created by init")
    acquire.add_argument("--download", action="store_true", help="Also download permitted media with yt-dlp")
    acquire.add_argument("--dry-run", action="store_true", help="Write the acquisition plan without running yt-dlp")
    acquire.add_argument("--sub-langs", default="zh.*,en.*", help="yt-dlp subtitle language selector")
    acquire.add_argument("--format", default="bv*+ba/b", help="yt-dlp format selector used with --download")
    acquire.add_argument("--timeout", type=int, default=600, help="Timeout in seconds for each yt-dlp command")
    acquire.set_defaults(func=acquire_url)

    clean = sub.add_parser("clean-transcript", help="Clean subtitles/transcripts, merge short captions, and build chapters")
    clean.add_argument("--case", required=True, help="Case directory created by init")
    clean.add_argument("--source", help="Optional SRT/VTT/TXT transcript source")
    clean.add_argument("--max-gap", type=float, default=1.2, help="Maximum gap in seconds for merging adjacent captions")
    clean.add_argument("--max-chars", type=int, default=180, help="Maximum merged segment length")
    clean.add_argument("--max-duration", type=float, default=18.0, help="Maximum merged segment duration in seconds")
    clean.add_argument("--chapter-minutes", type=int, default=8, help="Approximate chapter size")
    clean.set_defaults(func=clean_transcript)

    frames = sub.add_parser("frame-notes", help="Create a visual observation worksheet from keyframes")
    frames.add_argument("--case", required=True, help="Case directory created by init")
    frames.add_argument("--limit", type=int, default=80, help="Maximum keyframes to include")
    frames.add_argument("--context-seconds", type=float, default=15.0, help="Transcript window around each frame")
    frames.set_defaults(func=frame_notes)

    pack = sub.add_parser("study-pack-template", help="Create editable study pack template files for a case")
    pack.add_argument("--case", required=True, help="Case directory created by init")
    pack.add_argument("--force", action="store_true", help="Overwrite existing template files")
    pack.set_defaults(func=write_study_pack_template)

    generate = sub.add_parser("generate-study-pack", help="Generate a draft study pack from transcript and keyframe indexes")
    generate.add_argument("--case", required=True, help="Case directory created by init")
    generate.add_argument("--chapter-minutes", type=int, default=8, help="Approximate chapter size for transcript grouping")
    generate.add_argument("--claims", type=int, default=30, help="Maximum claim candidates to extract")
    generate.add_argument("--force", action="store_true", help="Write files even if templates already exist")
    generate.add_argument("--overwrite-generated", action="store_true", help="Overwrite existing study_pack files")
    generate.set_defaults(func=generate_study_pack)

    test = sub.add_parser("self-test", help="Run a small offline pipeline test fixture")
    test.add_argument("--out", required=True, help="Output directory for the test case")
    test.set_defaults(func=self_test)

    args = parser.parse_args(argv)
    if hasattr(args, "language") and args.language == "":
        args.language = None
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
