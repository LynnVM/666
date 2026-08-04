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

    pack = sub.add_parser("study-pack-template", help="Create editable study pack template files for a case")
    pack.add_argument("--case", required=True, help="Case directory created by init")
    pack.add_argument("--force", action="store_true", help="Overwrite existing template files")
    pack.set_defaults(func=write_study_pack_template)

    args = parser.parse_args(argv)
    if hasattr(args, "language") and args.language == "":
        args.language = None
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
