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

ZH_NORMALIZATION_MAP = str.maketrans({
    "這": "这", "個": "个", "裡": "里", "裏": "里", "會": "会", "時": "时", "候": "候",
    "種": "种", "憑": "凭", "現": "现", "點": "点", "實": "实", "掃": "扫", "描": "描",
    "礙": "碍", "斷": "断", "數": "数", "據": "据", "齡": "龄", "傳": "传", "過": "过",
    "程": "程", "見": "见", "象": "象", "為": "为", "導": "导", "致": "致", "圍": "围",
    "區": "区", "標": "标", "於": "于", "內": "内", "徑": "径", "規": "规", "劃": "划",
    "敗": "败", "終": "终", "端": "端", "啟": "启", "動": "动", "濾": "滤", "說": "说",
    "紅": "红", "黃": "黄", "經": "经", "從": "从", "圖": "图", "產": "产", "響": "响",
    "開": "开", "將": "将", "稱": "称", "檔": "档", "參": "参", "歡": "欢", "樂": "乐",
    "學": "学", "習": "习", "問": "问", "題": "题", "認": "认", "證": "证", "錯": "错",
    "誤": "误", "語": "语", "記": "记", "錄": "录", "體": "体", "優": "优", "級": "级",
    "擇": "择", "網": "网", "點": "点", "頻": "频", "視": "视", "資": "资", "料": "料",
    "權": "权", "威": "威", "補": "补", "齊": "齐", "寫": "写", "舊": "旧", "進": "进",
    "來": "来", "後": "后", "處": "处", "對": "对", "頂": "顶", "評": "评", "論": "论",
    "麼": "么", "條": "条", "編": "编", "譯": "译", "還": "还", "覺": "觉", "顯": "显",
    "與": "与", "應": "应", "該": "该", "實": "实", "驗": "验", "產": "产", "響": "响",
})

TERM_NORMALIZATION_REPLACEMENTS = [
    ("GEOF传染器", "GEOF传感器"),
    ("GEOF傳染器", "GEOF传感器"),
    ("数据年龄", "数据拖影"),
    ("數據年齡", "数据拖影"),
    ("進行区", "禁行区"),
    ("进行区", "禁行区"),
    ("進行區", "禁行区"),
    ("中端", "终端"),
    ("代价地图里踢除了", "代价地图里剔除了"),
    ("被踢除", "被剔除"),
    ("撤去点", "测距点"),
    ("撤去點", "测距点"),
    ("SRC字幕录", "src 目录"),
    ("SRC字目录", "src 目录"),
    ("滤波解点的原代码", "滤波节点的源代码"),
    ("原代码", "源代码"),
    ("浪誓文件", "launch 文件"),
    ("下代价地图参数", "代价地图参数"),
    ("Scan Filter", "scan_filtered"),
    ("激光雷達", "激光雷达"),
    ("濾波", "滤波"),
    ("導航", "导航"),
    ("路徑規劃", "路径规划"),
    ("代價地圖", "代价地图"),
    ("傳感器", "传感器"),
    ("啟動", "启动"),
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


def find_windows_tool_link(name: str) -> str | None:
    candidates = [
        Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links" / f"{name}.EXE",
        Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links" / f"{name}.exe",
    ]
    for path in candidates:
        try:
            if path.exists():
                if path.stat().st_size == 0:
                    continue
                return str(path)
        except PermissionError:
            continue
    return None


def find_ffmpeg() -> str | None:
    return which("ffmpeg") or find_python_module_binary("imageio_ffmpeg", "get_ffmpeg_exe") or find_windows_tool_link("ffmpeg")


def find_ffprobe() -> str | None:
    return which("ffprobe") or find_windows_tool_link("ffprobe")


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
        return probe_media_with_ffmpeg(path, "ffprobe not found")
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
        return probe_media_with_ffmpeg(path, out)
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        probe["error"] = "ffprobe returned non-json output"
        return probe
    probe["available"] = True
    probe["format"] = data.get("format", {})
    probe["streams"] = data.get("streams", [])
    return probe


def probe_media_with_ffmpeg(path: Path, previous_error: str | None = None) -> dict:
    ffmpeg = find_ffmpeg()
    probe: dict[str, Any] = {"available": False, "format": {}, "streams": []}
    if previous_error:
        probe["ffprobe_error"] = previous_error
    if not ffmpeg:
        probe["error"] = "ffmpeg fallback not available"
        return probe
    code, out = run_capture([ffmpeg, "-hide_banner", "-i", str(path)], timeout=30)
    if code not in {0, 1}:
        probe["error"] = out
        return probe
    duration = parse_ffmpeg_duration(out)
    if duration is not None:
        probe["format"]["duration"] = str(duration)
    if re.search(r"Stream #\d+:\d+.*Video:", out):
        probe["streams"].append({"codec_type": "video", "source": "ffmpeg"})
    if re.search(r"Stream #\d+:\d+.*Audio:", out):
        probe["streams"].append({"codec_type": "audio", "source": "ffmpeg"})
    probe["available"] = bool(probe["streams"] or duration is not None)
    if not probe["available"]:
        probe["error"] = out[-2000:]
    return probe


def parse_ffmpeg_duration(output: str) -> float | None:
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


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


def write_markdown(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8-sig")


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


def study_url(args: argparse.Namespace) -> None:
    out_dir = Path(args.out).resolve()
    url_case = build_case(args.input, out_dir)
    acquire_url(argparse.Namespace(
        case=str(url_case),
        download=args.download,
        dry_run=False,
        sub_langs=args.sub_langs,
        format=args.format,
        timeout=args.timeout,
        write_subs=args.write_subs,
    ))
    acquire_report_path = url_case / "reports" / "acquire_url.json"
    acquire_report = read_json(acquire_report_path) if acquire_report_path.exists() else {}
    media_file = acquire_report.get("media_file")
    active_case = url_case

    if media_file and Path(media_file).exists():
        active_case = build_case(media_file, out_dir)
        run_pipeline(argparse.Namespace(
            case=str(active_case),
            dry_run=False,
            keep_going=args.keep_going,
            process_local=True,
            transcribe=args.transcribe,
            model=args.model,
            language=args.language,
            device=args.device,
            compute_type=args.compute_type,
            keyframes=args.keyframes,
            scene_keyframes=args.scene_keyframes,
            scene_threshold=args.scene_threshold,
            max_single_minutes=args.max_single_minutes,
            chapter_minutes=args.chapter_minutes,
            claims=args.claims,
            frame_limit=args.frame_limit,
            overwrite_generated=True,
            download=False,
            write_subs=False,
            sub_langs=args.sub_langs,
            format=args.format,
            timeout=args.timeout,
        ))
    else:
        run_pipeline(argparse.Namespace(
            case=str(active_case),
            dry_run=False,
            keep_going=args.keep_going,
            process_local=False,
            transcribe=False,
            model=args.model,
            language=args.language,
            device=args.device,
            compute_type=args.compute_type,
            keyframes=args.keyframes,
            scene_keyframes=args.scene_keyframes,
            scene_threshold=args.scene_threshold,
            max_single_minutes=args.max_single_minutes,
            chapter_minutes=args.chapter_minutes,
            claims=args.claims,
            frame_limit=args.frame_limit,
            overwrite_generated=True,
            download=False,
            write_subs=False,
            sub_langs=args.sub_langs,
            format=args.format,
            timeout=args.timeout,
        ))

    run_report_path = active_case / "reports" / "run_pipeline.json"
    run_report = read_json(run_report_path) if run_report_path.exists() else {}
    study_session = active_case / "study_pack" / "09_study_session.md"
    study_pack_files = [active_case / "study_pack" / name for name in STUDY_PACK_FILES]
    warnings = list(acquire_report.get("warnings") or [])
    failed_steps = [
        step for step in run_report.get("steps", [])
        if step.get("status") == "failed"
    ]
    errors = [f"{step.get('name')}: {step.get('error')}" for step in failed_steps]
    evidence_ready = bool(media_file) or any([
        (active_case / "transcript" / "segments.json").exists(),
        (active_case / "transcript" / "transcript.txt").exists(),
        (active_case / "transcript" / "clean_segments.json").exists(),
        any((active_case / "transcript" / "subtitles").glob(pattern) for pattern in ["*.srt", "*.vtt", "*.txt"]),
    ])
    complete = (
        evidence_ready
        and not failed_steps
        and study_session.exists()
        and all(path.exists() for path in study_pack_files)
    )
    final_report = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "input": args.input,
        "url_case": str(url_case),
        "case": str(active_case),
        "study_pack": str(active_case / "study_pack"),
        "study_session": str(study_session),
        "downloaded_media": media_file,
        "complete": complete,
        "warnings": warnings,
        "errors": errors,
    }
    write_json(active_case / "reports" / "study_url.json", final_report)
    print(render_study_url_summary(final_report))
    if not complete:
        raise SystemExit(2)


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
        "mode": "media_for_asr" if args.download else "metadata_only",
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

    if args.write_subs:
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

    if not args.dry_run and args.write_subs:
        subtitle_files = report.get("subtitles", {}).get("files") or []
        if not subtitle_files:
            report["warnings"].append(
                "No subtitle file was acquired. The normal workflow should still use downloaded media plus ASR transcription."
            )
    if not args.dry_run and args.download and not report.get("media_file"):
        report["warnings"].append(
            "No media file was acquired, so speech-to-text transcription cannot start."
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
    for old_frame in out_dir.glob("scene_*.jpg"):
        old_frame.unlink()
    pattern = out_dir / "scene_%03d.jpg"
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-vf",
        f"select='gt(scene,{threshold})',showinfo",
        "-fps_mode",
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
        files = sorted(out_dir.glob("scene_*.jpg"))
        if not files:
            return []
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


def transcribe_audio(
    audio_path: Path,
    transcript_dir: Path,
    model_size: str,
    language: str | None,
    device: str,
    compute_type: str,
) -> dict:
    requested_device = device
    requested_compute_type = compute_type
    device, compute_type, runtime_note = resolve_transcription_runtime(device, compute_type)
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "error": f"faster-whisper unavailable: {exc}",
            "next_step": "Install faster-whisper or provide an existing subtitle file.",
        }
    attempts = [(device, compute_type, runtime_note)]
    allow_cpu_fallback = requested_device == "auto" or device == "cuda"
    if allow_cpu_fallback and (device, compute_type) != ("cpu", "int8"):
        attempts.append(("cpu", "int8", f"fallback after {device}/{compute_type} failure"))
    errors = []
    for attempt_device, attempt_compute_type, attempt_note in attempts:
        try:
            model = WhisperModel(model_size, device=attempt_device, compute_type=attempt_compute_type)
            segments_iter, info = model.transcribe(str(audio_path), language=language)
            segments = [
                {"start": seg.start, "end": seg.end, "text": seg.text}
                for seg in segments_iter
            ]
            write_segments_outputs(segments, transcript_dir)
            return {
                "available": True,
                "model_size": model_size,
                "requested_device": requested_device,
                "requested_compute_type": requested_compute_type,
                "device": attempt_device,
                "compute_type": attempt_compute_type,
                "runtime_note": attempt_note,
                "fallback_errors": errors,
                "language": getattr(info, "language", language),
                "language_probability": getattr(info, "language_probability", None),
                "segments": len(segments),
            }
        except Exception as exc:  # noqa: BLE001
            errors.append({
                "device": attempt_device,
                "compute_type": attempt_compute_type,
                "error": str(exc),
            })
    return {
        "available": False,
        "error": f"faster-whisper transcription failed after {len(attempts)} attempt(s): {errors[-1]['error'] if errors else 'unknown error'}",
        "model_size": model_size,
        "requested_device": requested_device,
        "requested_compute_type": requested_compute_type,
        "device": attempts[-1][0],
        "compute_type": attempts[-1][1],
        "fallback_errors": errors,
        "next_step": "Retry with --device cpu --compute-type int8, clear a broken model cache, use another model size, or provide a subtitle file.",
    }


def resolve_transcription_runtime(device: str, compute_type: str) -> tuple[str, str, str]:
    requested = f"{device}/{compute_type}"
    if device != "auto" and compute_type != "auto":
        return device, compute_type, f"explicit runtime: {requested}"
    cuda = detect_ctranslate2_cuda()
    resolved_device = device
    resolved_compute_type = compute_type
    if device == "auto":
        resolved_device = "cuda" if cuda.get("available") else "cpu"
    if compute_type == "auto":
        resolved_compute_type = "float16" if resolved_device == "cuda" else "int8"
    return resolved_device, resolved_compute_type, f"auto runtime {requested} -> {resolved_device}/{resolved_compute_type}"


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
            f"Video is longer than {args.max_single_minutes} minutes; run split-media before final study-pack generation."
        )
        process_report["split_media_next_step"] = (
            f"python <skill>/scripts/video_study_case.py split-media --case \"{case_dir}\" --part-minutes 25"
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
            try:
                scene_keyframes = extract_scene_keyframes(
                    ffmpeg,
                    source,
                    case_dir / "keyframes" / "scene",
                    args.scene_threshold,
                    args.scene_keyframes,
                )
            except RuntimeError as exc:
                process_report["warnings"].append(
                    f"Scene keyframe extraction failed; continuing with uniform keyframes only. {str(exc)[:600]}"
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
            args.device,
            args.compute_type,
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


def build_split_plan(duration: float, part_minutes: int, overlap_seconds: float) -> list[dict[str, Any]]:
    part_seconds = max(5, part_minutes) * 60.0
    overlap = min(max(0.0, overlap_seconds), part_seconds - 1.0)
    if duration <= 0:
        return []
    parts = []
    start = 0.0
    index = 1
    while start < duration:
        end = min(duration, start + part_seconds)
        parts.append({
            "index": index,
            "start": start,
            "end": end,
            "duration": max(0.0, end - start),
            "timestamp_start": format_timestamp(start),
            "timestamp_end": format_timestamp(end),
        })
        if end >= duration:
            break
        next_start = max(0.0, end - overlap)
        if next_start <= start:
            next_start = end
        start = next_start
        index += 1
    return parts


def split_media(args: argparse.Namespace) -> None:
    case_dir = Path(args.case).resolve()
    metadata_path = case_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata.json not found: {metadata_path}")
    ensure_case_dirs(case_dir)
    metadata = read_json(metadata_path)
    input_info = metadata.get("input", {})
    if input_info.get("kind") not in {"local_video", "local_audio"}:
        raise ValueError("split-media requires a local_video or local_audio case")
    source = Path(input_info["path"])
    if not source.exists():
        raise FileNotFoundError(str(source))

    probe = metadata.get("media_probe")
    if not probe or not probe.get("available"):
        probe = probe_media(source)
        metadata["media_probe"] = probe
    duration = media_duration_seconds(probe) or 0.0
    parts = build_split_plan(duration, args.part_minutes, args.overlap_seconds)
    split_dir = case_dir / "media" / "parts"
    out_cases_dir = case_dir / "parts"
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "duration_seconds": duration,
        "part_minutes": args.part_minutes,
        "overlap_seconds": args.overlap_seconds,
        "execute": args.execute,
        "copy_codecs": args.copy_codecs,
        "parts": parts,
        "part_cases": [],
        "warnings": [],
    }
    if not parts:
        report["warnings"].append("Could not determine media duration. Check ffprobe or provide valid media.")

    ffmpeg = find_ffmpeg()
    if args.execute and not ffmpeg:
        raise RuntimeError("ffmpeg not found. Install ffmpeg or install imageio-ffmpeg in this Python environment.")

    if args.execute:
        split_dir.mkdir(parents=True, exist_ok=True)
        out_cases_dir.mkdir(parents=True, exist_ok=True)
        ext = source.suffix.lower() or ".mp4"
        for part in parts:
            part_path = split_dir / f"part_{part['index']:03d}_{int(part['start']):06d}_{int(part['end']):06d}{ext}"
            cmd = [
                ffmpeg,
                "-y",
                "-ss",
                str(part["start"]),
                "-i",
                str(source),
                "-t",
                str(part["duration"]),
            ]
            if args.copy_codecs:
                cmd += ["-c", "copy"]
            else:
                cmd += ["-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart"]
            cmd.append(str(part_path))
            code, out = run_capture(cmd, timeout=args.timeout)
            part["file"] = str(part_path)
            part["ffmpeg_returncode"] = code
            part["ffmpeg_output_tail"] = out[-2000:]
            if code != 0:
                report["warnings"].append(f"Part {part['index']} split failed.")
                continue
            part_case = build_case(str(part_path), out_cases_dir)
            part_metadata_path = part_case / "metadata.json"
            part_metadata = read_json(part_metadata_path)
            part_metadata["parent_case"] = str(case_dir)
            part_metadata["parent_part"] = part
            write_json(part_metadata_path, part_metadata)
            report["part_cases"].append({
                "index": part["index"],
                "case": str(part_case),
                "file": str(part_path),
            })

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    metadata["split_media"] = report
    write_json(metadata_path, metadata)
    write_json(case_dir / "reports" / "split_media.json", report)
    write_split_readme(case_dir, report)
    print(str(case_dir / "reports" / "split_media.json"))


def write_split_readme(case_dir: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Split Media Plan",
        "",
        f"- Source: `{report.get('source')}`",
        f"- Duration seconds: `{report.get('duration_seconds')}`",
        f"- Execute: `{report.get('execute')}`",
        "",
        "## Parts",
        "",
    ]
    for part in report.get("parts", []):
        lines.append(
            f"- Part {part['index']:03d}: [{part['timestamp_start']} - {part['timestamp_end']}] "
            f"duration `{part['duration']:.1f}s`"
        )
    part_cases = report.get("part_cases") or []
    if part_cases:
        lines += ["", "## Part Cases", ""]
        lines += [f"- Part {item['index']:03d}: `{item['case']}`" for item in part_cases]
        lines += [
            "",
            "## Next Commands",
            "",
            "Process each part case independently. Use separate terminals if you want parallel processing.",
            "",
        ]
        for item in part_cases:
            lines.append(
                f"python <skill>/scripts/video_study_case.py process-local --case \"{item['case']}\" "
                "--keyframes 20 --scene-keyframes 12 --transcribe --model small --language zh"
            )
    warnings = report.get("warnings") or []
    if warnings:
        lines += ["", "## Warnings", ""]
        lines += [f"- {warning}" for warning in warnings]
    (case_dir / "analysis" / "split_media_plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def discover_part_cases(case_dir: Path) -> list[dict[str, Any]]:
    metadata_path = case_dir / "metadata.json"
    metadata = read_json(metadata_path) if metadata_path.exists() else {}
    split_report = metadata.get("split_media") or {}
    part_cases = list(split_report.get("part_cases") or [])
    report_path = case_dir / "reports" / "split_media.json"
    if report_path.exists():
        report = read_json(report_path)
        part_cases.extend(report.get("part_cases") or [])
    discovered = []
    for item in part_cases:
        path = Path(str(item.get("case", "")))
        if path.exists() and (path / "metadata.json").exists():
            discovered.append({
                "index": int(item.get("index", len(discovered) + 1)),
                "case": str(path),
                "file": item.get("file"),
            })
    for metadata_file in sorted((case_dir / "parts").glob("*/metadata.json")):
        path = metadata_file.parent
        if not any(Path(item["case"]) == path for item in discovered):
            part_metadata = read_json(metadata_file)
            parent_part = part_metadata.get("parent_part") or {}
            discovered.append({
                "index": int(parent_part.get("index", len(discovered) + 1)),
                "case": str(path),
                "file": parent_part.get("file"),
            })
    return sorted(discovered, key=lambda item: item["index"])


def read_study_pack_text(case_dir: Path, name: str) -> str:
    return read_text_if_exists(case_dir / "study_pack" / name).strip()


def merge_parts(args: argparse.Namespace) -> None:
    case_dir = Path(args.case).resolve()
    metadata_path = case_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata.json not found: {metadata_path}")
    ensure_case_dirs(case_dir)
    part_cases = discover_part_cases(case_dir)
    course_pack = case_dir / "course_study_pack"
    course_pack.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "parent_case": str(case_dir),
        "part_cases": part_cases,
        "outputs": [],
        "warnings": [],
    }
    if not part_cases:
        report["warnings"].append("No part cases found. Run split-media --execute first or provide generated part cases.")

    overview_lines = ["# Course Overview", ""]
    index_lines = ["# Part Index", ""]
    claims: list[dict[str, Any]] = []
    for item in part_cases:
        part_dir = Path(item["case"])
        part_title = f"Part {item['index']:03d}"
        overview = read_study_pack_text(part_dir, "00_overview.md")
        notes = read_study_pack_text(part_dir, "01_full_notes.md")
        timeline = read_study_pack_text(part_dir, "02_timeline.md")
        overview_lines += [
            f"## {part_title}",
            "",
            f"- Case: `{part_dir}`",
            f"- Media: `{item.get('file') or 'unknown'}`",
            "",
            summarize_text(overview or notes or timeline, args.summary_chars) or "TODO: Process this part case first.",
            "",
        ]
        index_lines += [
            f"## {part_title}",
            "",
            f"- Case: `{part_dir}`",
            f"- Media: `{item.get('file') or 'unknown'}`",
            f"- Overview: `{part_dir / 'study_pack' / '00_overview.md'}`",
            f"- Full notes: `{part_dir / 'study_pack' / '01_full_notes.md'}`",
            "",
        ]
        claim_path = part_dir / "analysis" / "claim_candidates.json"
        if claim_path.exists():
            for claim in read_json(claim_path).get("claims", []):
                if isinstance(claim, dict):
                    claims.append({**claim, "part_index": item["index"], "part_case": str(part_dir)})

    outputs = {
        "00_course_overview.md": "\n".join(overview_lines).strip() + "\n",
        "01_part_index.md": "\n".join(index_lines).strip() + "\n",
        "02_merged_claims.md": render_merged_claims(claims),
    }
    for name, content in outputs.items():
        path = course_pack / name
        if args.force or not path.exists():
            write_markdown(path, content)
            report["outputs"].append(str(path))
    write_json(case_dir / "analysis" / "merged_claims.json", {"claims": claims})
    write_json(case_dir / "reports" / "merge_parts.json", report)
    print(str(course_pack))


def render_merged_claims(claims: list[dict[str, Any]]) -> str:
    lines = [
        "# Merged Claim Candidates",
        "",
        "These claims are collected from part cases. Fact-check them before treating them as reliable knowledge.",
        "",
    ]
    if not claims:
        lines += ["No claim candidates found.", ""]
        return "\n".join(lines)
    for idx, claim in enumerate(claims, start=1):
        lines += [
            f"## Claim {idx}",
            "",
            f"- Part: `{claim.get('part_index', 'n/a')}`",
            f"- Timestamp: `{claim.get('timestamp', 'n/a')}`",
            f"- Text: {claim.get('text', '')}",
            f"- Status: `{claim.get('status', 'needs_fact_check')}`",
            "",
        ]
    return "\n".join(lines)


def fact_check_queue(args: argparse.Namespace) -> None:
    case_dir = Path(args.case).resolve()
    if not (case_dir / "metadata.json").exists():
        raise FileNotFoundError(f"metadata.json not found: {case_dir / 'metadata.json'}")
    ensure_case_dirs(case_dir)
    claims = collect_claims_for_queue(case_dir)
    queue = []
    seen = set()
    for claim in claims:
        text = normalize_space(str(claim.get("text", "")))
        if not text or text in seen:
            continue
        seen.add(text)
        queue.append({
            "id": f"claim-{len(queue) + 1:03d}",
            "priority": claim_priority(text),
            "text": text,
            "timestamp": claim.get("timestamp"),
            "source_case": claim.get("source_case"),
            "part_index": claim.get("part_index"),
            "status": "pending",
            "recommended_sources": recommended_fact_sources(text),
            "notes": "",
        })
        if len(queue) >= args.limit:
            break
    queue.sort(key=lambda item: (item["priority"], item["id"]))
    write_json(case_dir / "analysis" / "fact_check_queue.json", {"claims": queue})
    (case_dir / "analysis" / "fact_check_queue.md").write_text(render_fact_check_queue(queue), encoding="utf-8")
    report = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "claims": len(queue),
        "outputs": ["analysis/fact_check_queue.json", "analysis/fact_check_queue.md"],
    }
    write_json(case_dir / "reports" / "fact_check_queue.json", report)
    print(str(case_dir / "analysis" / "fact_check_queue.md"))


def collect_claims_for_queue(case_dir: Path) -> list[dict[str, Any]]:
    claims = []
    own_path = case_dir / "analysis" / "claim_candidates.json"
    if own_path.exists():
        for claim in read_json(own_path).get("claims", []):
            if isinstance(claim, dict):
                claims.append({**claim, "source_case": str(case_dir)})
    merged_path = case_dir / "analysis" / "merged_claims.json"
    if merged_path.exists():
        for claim in read_json(merged_path).get("claims", []):
            if isinstance(claim, dict):
                claims.append({**claim, "source_case": claim.get("part_case") or str(case_dir)})
    for item in discover_part_cases(case_dir):
        part_dir = Path(item["case"])
        path = part_dir / "analysis" / "claim_candidates.json"
        if not path.exists():
            continue
        for claim in read_json(path).get("claims", []):
            if isinstance(claim, dict):
                claims.append({**claim, "source_case": str(part_dir), "part_index": item["index"]})
    return claims


def claim_priority(text: str) -> int:
    lowered = text.lower()
    high = ["must", "never", "always", "安全", "危险", "错误", "必须", "不能", "一定"]
    medium = ["should", "because", "therefore", "原理", "定义", "导致", "建议"]
    if any(term in lowered or term in text for term in high):
        return 1
    if any(term in lowered or term in text for term in medium):
        return 2
    return 3


def recommended_fact_sources(text: str) -> list[str]:
    lowered = text.lower()
    if any(term in lowered for term in ["python", "pip", "openai", "api", "ffmpeg", "yt-dlp"]):
        return ["Official documentation", "Release notes", "Repository issue tracker"]
    if any(term in text for term in ["机器人", "雷达", "建图", "定位", "TF", "坐标系"]):
        return ["ROS documentation", "Sensor/vendor documentation", "SLAM package documentation"]
    return ["Official documentation", "Textbooks or papers", "Authoritative vendor/source material"]


def render_fact_check_queue(queue: list[dict[str, Any]]) -> str:
    lines = [
        "# Fact Check Queue",
        "",
        "Priority 1 means high-impact or likely-to-mislead claims. Verify those first.",
        "",
    ]
    if not queue:
        lines += ["No pending claims found.", ""]
        return "\n".join(lines)
    for item in queue:
        lines += [
            f"## {item['id']} - Priority {item['priority']}",
            "",
            f"- Claim: {item['text']}",
            f"- Timestamp: `{item.get('timestamp') or 'n/a'}`",
            f"- Source case: `{item.get('source_case') or 'n/a'}`",
            f"- Part: `{item.get('part_index') or 'n/a'}`",
            f"- Status: `{item['status']}`",
            "- Recommended sources:",
            *[f"  - {source}" for source in item["recommended_sources"]],
            "- Verification notes: TODO",
            "",
        ]
    return "\n".join(lines)


def module_available(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:  # noqa: BLE001
        return False


def detect_nvidia_smi() -> dict[str, Any]:
    cmd = which("nvidia-smi")
    if not cmd:
        return {
            "available": False,
            "value": None,
            "summary": "nvidia-smi not found",
        }
    code, out = run_capture([cmd, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"], timeout=10)
    if code != 0:
        return {
            "available": False,
            "value": cmd,
            "summary": out,
        }
    gpus = [line.strip() for line in out.splitlines() if line.strip()]
    return {
        "available": bool(gpus),
        "value": cmd,
        "summary": "; ".join(gpus) if gpus else "no GPU rows returned",
    }


def detect_ctranslate2_cuda() -> dict[str, Any]:
    try:
        import ctranslate2  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "value": None,
            "summary": f"ctranslate2 unavailable: {exc}",
            "recommended_device": "cpu",
            "recommended_compute_type": "int8",
        }
    try:
        cuda_count = int(ctranslate2.get_cuda_device_count())
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "value": getattr(ctranslate2, "__version__", None),
            "summary": f"could not query CUDA devices: {exc}",
            "recommended_device": "cpu",
            "recommended_compute_type": "int8",
        }
    return {
        "available": cuda_count > 0,
        "value": getattr(ctranslate2, "__version__", None),
        "summary": f"cuda device count: {cuda_count}",
        "recommended_device": "cuda" if cuda_count > 0 else "cpu",
        "recommended_compute_type": "float16" if cuda_count > 0 else "int8",
    }


def doctor(args: argparse.Namespace) -> None:
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    ytdlp = find_yt_dlp_cmd()
    bad_hf_files = find_zero_byte_hf_files()
    nvidia = detect_nvidia_smi()
    ct2_cuda = detect_ctranslate2_cuda()
    checks = [
        {
            "name": "python",
            "available": True,
            "value": sys.executable,
            "required_for": "all commands",
        },
        {
            "name": "ffmpeg",
            "available": bool(ffmpeg),
            "value": ffmpeg,
            "required_for": "audio extraction, keyframes, split-media --execute",
            "install_hint": "Install FFmpeg or run `pip install imageio-ffmpeg` for the ffmpeg fallback.",
        },
        {
            "name": "ffprobe",
            "available": bool(ffprobe),
            "value": ffprobe,
            "required_for": "media duration probing and split planning",
            "install_hint": "Install system FFmpeg so ffprobe is on PATH.",
        },
        {
            "name": "yt-dlp",
            "available": bool(ytdlp),
            "value": " ".join(ytdlp) if ytdlp else None,
            "required_for": "URL/share-link acquisition",
            "install_hint": "Run `pip install yt-dlp`.",
        },
        {
            "name": "faster-whisper",
            "available": module_available("faster_whisper"),
            "value": None,
            "required_for": "optional local transcription",
            "install_hint": "Run `pip install faster-whisper`.",
        },
        {
            "name": "nvidia-smi",
            "available": nvidia["available"],
            "value": nvidia["summary"],
            "required_for": "GPU transcription diagnostics",
            "install_hint": "Install/update the NVIDIA driver if you want GPU transcription.",
        },
        {
            "name": "ctranslate2-cuda",
            "available": ct2_cuda["available"],
            "value": ct2_cuda["summary"],
            "required_for": "faster-whisper GPU transcription",
            "install_hint": "Install a CUDA-capable ctranslate2/faster-whisper stack, or use `--device cpu --compute-type int8`.",
        },
        {
            "name": "imageio-ffmpeg",
            "available": module_available("imageio_ffmpeg"),
            "value": find_python_module_binary("imageio_ffmpeg", "get_ffmpeg_exe"),
            "required_for": "ffmpeg fallback when system ffmpeg is missing",
            "install_hint": "Run `pip install imageio-ffmpeg`.",
        },
        {
            "name": "huggingface-cache",
            "available": not bad_hf_files,
            "value": "; ".join(bad_hf_files[:5]) if bad_hf_files else "no zero-byte files detected",
            "required_for": "faster-whisper model loading",
            "install_hint": "Delete the broken model cache directory and rerun transcription, or use another model size.",
        },
    ]
    report = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "gpu_recommendation": {
            "device": ct2_cuda["recommended_device"],
            "compute_type": ct2_cuda["recommended_compute_type"],
        },
        "checks": checks,
        "warnings": [
            f"{item['name']} missing: {item.get('install_hint')}"
            for item in checks
            if not item["available"] and item["name"] in {"ffmpeg", "ffprobe", "huggingface-cache", "ctranslate2-cuda"}
        ],
    }
    if args.out:
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(out_path, report)
    print(render_doctor(report))


def render_doctor(report: dict[str, Any]) -> str:
    lines = ["# Video Study Extractor Doctor", ""]
    gpu = report.get("gpu_recommendation") or {}
    if gpu:
        lines += [
            "## Recommended Transcription Device",
            "",
            f"- Device: `{gpu.get('device')}`",
            f"- Compute type: `{gpu.get('compute_type')}`",
            "",
        ]
    for item in report["checks"]:
        status = "OK" if item["available"] else "MISSING"
        lines += [
            f"## {item['name']} - {status}",
            "",
            f"- Value: `{item.get('value')}`",
            f"- Required for: {item.get('required_for')}",
        ]
        if not item["available"] and item.get("install_hint"):
            lines.append(f"- Install hint: {item['install_hint']}")
        lines.append("")
    warnings = report.get("warnings") or []
    if warnings:
        lines += ["## Warnings", ""]
        lines += [f"- {warning}" for warning in warnings]
    return "\n".join(lines)


def find_zero_byte_hf_files(limit: int = 20) -> list[str]:
    roots = [
        Path(os.environ.get("HF_HOME", "")),
        Path.home() / ".cache" / "huggingface" / "hub",
    ]
    bad = []
    for root in roots:
        if not str(root) or not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.stat().st_size == 0:
                bad.append(str(path))
                if len(bad) >= limit:
                    return bad
    return bad


def next_steps(args: argparse.Namespace) -> None:
    case_dir = Path(args.case).resolve()
    metadata_path = case_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata.json not found: {metadata_path}")
    ensure_case_dirs(case_dir)
    metadata = read_json(metadata_path)
    steps = build_next_steps(case_dir, metadata)
    report = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "case": str(case_dir),
        "steps": steps,
    }
    write_json(case_dir / "reports" / "next_steps.json", report)
    (case_dir / "analysis" / "next_steps.md").write_text(render_next_steps(report), encoding="utf-8")
    print(str(case_dir / "analysis" / "next_steps.md"))


def build_next_steps(case_dir: Path, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    input_info = metadata.get("input", {})
    kind = input_info.get("kind")
    steps: list[dict[str, Any]] = []

    def add(priority: int, command: str, reason: str) -> None:
        steps.append({"priority": priority, "command": command, "reason": reason})

    script = "python <skill>/scripts/video_study_case.py"
    if kind in {"url", "share_text"} and not (case_dir / "reports" / "acquire_url.json").exists():
        add(1, f'{script} acquire-url --case "{case_dir}"', "Acquire public subtitles or permitted media from the URL/share text.")
    if kind in {"local_video", "local_audio"} and not (case_dir / "reports" / "process_local.json").exists():
        add(1, f'{script} process-local --case "{case_dir}" --keyframes 30 --scene-keyframes 20', "Extract audio and keyframes from local media.")

    duration = media_duration_seconds(metadata.get("media_probe") or {}) or 0.0
    if kind in {"local_video", "local_audio"} and duration > 3600 and not (case_dir / "reports" / "split_media.json").exists():
        add(1, f'{script} split-media --case "{case_dir}" --part-minutes 25', "Long media should be split or at least planned before final study-pack generation.")

    transcript_ready = (case_dir / "transcript" / "segments.json").exists() or (case_dir / "transcript" / "transcript.txt").exists()
    clean_ready = (case_dir / "transcript" / "clean_segments.json").exists()
    if transcript_ready and not clean_ready:
        add(2, f'{script} clean-transcript --case "{case_dir}" --chapter-minutes 8', "Clean fragmented transcript segments and build chapter JSON.")

    keyframes_ready = (case_dir / "keyframes" / "keyframes.json").exists()
    frame_notes_ready = (case_dir / "analysis" / "frame_observations.md").exists()
    if keyframes_ready and not frame_notes_ready:
        add(2, f'{script} frame-notes --case "{case_dir}"', "Prepare visual observation notes for keyframes.")

    study_pack_ready = all((case_dir / "study_pack" / name).exists() for name in STUDY_PACK_FILES)
    if (transcript_ready or clean_ready) and not study_pack_ready:
        add(3, f'{script} generate-study-pack --case "{case_dir}" --chapter-minutes 8 --claims 30 --force', "Generate the first-pass study pack.")

    claims_ready = (case_dir / "analysis" / "claim_candidates.json").exists() or (case_dir / "analysis" / "merged_claims.json").exists()
    queue_ready = (case_dir / "analysis" / "fact_check_queue.json").exists()
    if claims_ready and not queue_ready:
        add(4, f'{script} fact-check-queue --case "{case_dir}"', "Prioritize claims that need external verification.")

    part_cases = discover_part_cases(case_dir)
    course_ready = (case_dir / "course_study_pack" / "00_course_overview.md").exists()
    if part_cases and not course_ready:
        add(5, f'{script} merge-parts --case "{case_dir}" --force', "Merge processed part cases into a course-level scaffold.")

    if not steps:
        add(9, "Ask Codex to inspect the case and teach from the generated study pack.", "No obvious missing pipeline step was detected.")
    return sorted(steps, key=lambda item: item["priority"])


def render_next_steps(report: dict[str, Any]) -> str:
    lines = ["# Next Steps", "", f"Case: `{report['case']}`", ""]
    for step in report["steps"]:
        lines += [
            f"## Priority {step['priority']}",
            "",
            f"Reason: {step['reason']}",
            "",
            "```powershell",
            step["command"],
            "```",
            "",
        ]
    return "\n".join(lines)


def validate_case(args: argparse.Namespace) -> None:
    case_dir = Path(args.case).resolve()
    issues: list[dict[str, Any]] = []

    def issue(level: str, code: str, message: str, path: Path | None = None) -> None:
        issues.append({
            "level": level,
            "code": code,
            "message": message,
            "path": str(path) if path else None,
        })

    metadata_path = case_dir / "metadata.json"
    if not metadata_path.exists():
        issue("error", "missing_metadata", "metadata.json is required.", metadata_path)
        metadata: dict[str, Any] = {}
    else:
        metadata = read_json(metadata_path)
        input_info = metadata.get("input", {})
        if not input_info.get("kind"):
            issue("error", "missing_input_kind", "metadata.input.kind is missing.", metadata_path)
        if input_info.get("path") and not Path(input_info["path"]).exists():
            issue("warning", "missing_source_file", "The source path recorded in metadata does not exist.", Path(input_info["path"]))

    for sub in ["transcript", "keyframes", "analysis", "reports", "study_pack"]:
        path = case_dir / sub
        if not path.exists():
            issue("warning", f"missing_{sub}", f"Case subdirectory `{sub}` is missing.", path)

    transcript_files = [
        case_dir / "transcript" / "segments.json",
        case_dir / "transcript" / "transcript.txt",
        case_dir / "transcript" / "clean_segments.json",
    ]
    if not any(path.exists() for path in transcript_files):
        issue("warning", "missing_transcript", "No transcript segments or transcript text found.", case_dir / "transcript")

    keyframes_path = case_dir / "keyframes" / "keyframes.json"
    if keyframes_path.exists():
        frames = read_json(keyframes_path).get("frames", [])
        if not isinstance(frames, list):
            issue("error", "invalid_keyframes", "keyframes.json frames must be a list.", keyframes_path)
        elif not frames:
            issue("warning", "empty_keyframes", "keyframes.json has no frames.", keyframes_path)
    elif metadata.get("input", {}).get("kind") == "local_video":
        issue("warning", "missing_keyframes", "Local video case has no keyframes index.", keyframes_path)

    missing_pack = [name for name in STUDY_PACK_FILES if not (case_dir / "study_pack" / name).exists()]
    if missing_pack:
        issue("warning", "incomplete_study_pack", f"Missing study pack files: {', '.join(missing_pack)}", case_dir / "study_pack")

    claim_path = case_dir / "analysis" / "claim_candidates.json"
    queue_path = case_dir / "analysis" / "fact_check_queue.json"
    if claim_path.exists() and not queue_path.exists():
        issue("info", "fact_check_queue_missing", "Claim candidates exist but fact_check_queue.json has not been generated.", queue_path)

    next_steps_report = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "case": str(case_dir),
        "valid": not any(item["level"] == "error" for item in issues),
        "issues": issues,
        "next_steps": build_next_steps(case_dir, metadata) if metadata else [],
    }
    ensure_case_dirs(case_dir)
    write_json(case_dir / "reports" / "validate_case.json", next_steps_report)
    (case_dir / "analysis" / "validate_case.md").write_text(render_validate_case(next_steps_report), encoding="utf-8")
    print(str(case_dir / "reports" / "validate_case.json"))
    if args.strict and not next_steps_report["valid"]:
        raise SystemExit(1)


def export_study_session(args: argparse.Namespace) -> None:
    case_dir = Path(args.case).resolve()
    metadata_path = case_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata.json not found: {metadata_path}")
    ensure_case_dirs(case_dir)
    metadata = read_json(metadata_path)
    segments = load_segments(case_dir)
    chapters_path = case_dir / "analysis" / "chapters.json"
    chapters = read_json(chapters_path).get("chapters", []) if chapters_path.exists() else segment_chapters(segments, args.chapter_minutes)
    queue_path = case_dir / "analysis" / "fact_check_queue.json"
    queue = read_json(queue_path).get("claims", []) if queue_path.exists() else []
    keyframes = load_keyframes(case_dir)
    session = {
        "case": str(case_dir),
        "source": source_label(metadata),
        "metadata": metadata,
        "chapters": chapters,
        "fact_check_queue": queue,
        "keyframes": keyframes,
    }
    out_md = case_dir / "study_pack" / "09_study_session.md"
    out_json = case_dir / "analysis" / "study_session.json"
    write_json(out_json, session)
    write_markdown(out_md, render_study_session(session, args.questions_per_chapter))
    report = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "chapters": len(chapters),
        "fact_check_items": len(queue),
        "outputs": ["study_pack/09_study_session.md", "analysis/study_session.json"],
    }
    write_json(case_dir / "reports" / "export_study_session.json", report)
    print(str(out_md))


def run_pipeline(args: argparse.Namespace) -> None:
    case_dir = Path(args.case).resolve()
    metadata_path = case_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata.json not found: {metadata_path}")
    ensure_case_dirs(case_dir)
    metadata = read_json(metadata_path)
    steps = pipeline_steps(case_dir, metadata, args)
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "case": str(case_dir),
        "dry_run": args.dry_run,
        "steps": [],
    }
    for step in steps:
        enabled = bool(step["enabled"]() if callable(step["enabled"]) else step["enabled"])
        reason = step["reason"]() if callable(step["reason"]) else step["reason"]
        item = {"name": step["name"], "enabled": enabled, "reason": reason, "status": "skipped"}
        if not enabled:
            report["steps"].append(item)
            continue
        if args.dry_run:
            item["status"] = "planned"
            report["steps"].append(item)
            continue
        try:
            step["func"]()
            item["status"] = "done"
        except Exception as exc:  # noqa: BLE001
            item["status"] = "failed"
            item["error"] = str(exc)
            report["steps"].append(item)
            if not args.keep_going:
                break
            continue
        report["steps"].append(item)
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(case_dir / "reports" / "run_pipeline.json", report)
    (case_dir / "analysis" / "run_pipeline.md").write_text(render_run_pipeline(report), encoding="utf-8")
    print(str(case_dir / "reports" / "run_pipeline.json"))


def pipeline_steps(case_dir: Path, metadata: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    input_info = metadata.get("input", {})
    kind = input_info.get("kind")
    steps = []

    def add(name: str, enabled: Any, reason: Any, func: Any) -> None:
        steps.append({"name": name, "enabled": enabled, "reason": reason, "func": func})

    def transcript_ready() -> bool:
        return (case_dir / "transcript" / "segments.json").exists() or (case_dir / "transcript" / "transcript.txt").exists()

    def subtitle_ready() -> bool:
        return any((case_dir / "transcript" / "subtitles").glob(pattern) for pattern in ["*.srt", "*.vtt", "*.txt"])

    def clean_ready() -> bool:
        return (case_dir / "transcript" / "clean_segments.json").exists()

    def transcript_source_ready() -> bool:
        return transcript_ready() or subtitle_ready() or clean_ready()

    def keyframes_ready() -> bool:
        return (case_dir / "keyframes" / "keyframes.json").exists()

    def study_pack_ready() -> bool:
        return all((case_dir / "study_pack" / name).exists() for name in STUDY_PACK_FILES)

    def process_report_ready() -> bool:
        report_path = case_dir / "reports" / "process_local.json"
        if not report_path.exists():
            return False
        if args.transcribe and not transcript_ready():
            return False
        if args.keyframes and not keyframes_ready():
            return False
        return True

    add(
        "acquire-url",
        lambda: kind in {"url", "share_text"} and not (case_dir / "reports" / "acquire_url.json").exists(),
        "URL/share case has not been acquired.",
        lambda: acquire_url(argparse.Namespace(
            case=str(case_dir),
            download=args.download,
            dry_run=False,
            sub_langs=args.sub_langs,
            format=args.format,
            timeout=args.timeout,
            write_subs=args.write_subs,
        )),
    )
    add(
        "process-local",
        lambda: kind in {"local_video", "local_audio"} and args.process_local and not process_report_ready(),
        lambda: "Local media has not been processed." if not (case_dir / "reports" / "process_local.json").exists()
        else "Existing local processing outputs satisfy requested media, keyframe, and transcript settings." if process_report_ready()
        else "Existing local processing report is incomplete for requested outputs.",
        lambda: process_local(argparse.Namespace(
            case=str(case_dir),
            keyframes=args.keyframes,
            scene_keyframes=args.scene_keyframes,
            scene_threshold=args.scene_threshold,
            transcribe=args.transcribe,
            model=args.model,
            language=args.language,
            device=args.device,
            compute_type=args.compute_type,
            max_single_minutes=args.max_single_minutes,
        )),
    )
    add(
        "clean-transcript",
        lambda: (transcript_ready() or subtitle_ready()) and not clean_ready(),
        lambda: "Transcript has already been cleaned." if clean_ready() else "Transcript exists but has not been cleaned.",
        lambda: clean_transcript(argparse.Namespace(
            case=str(case_dir),
            source=None,
            max_gap=1.2,
            max_chars=180,
            max_duration=18.0,
            chapter_minutes=args.chapter_minutes,
        )),
    )
    add(
        "normalize-transcript",
        lambda: clean_ready() and not (case_dir / "reports" / "normalize_transcript.json").exists(),
        lambda: "Transcript has already been normalized." if (case_dir / "reports" / "normalize_transcript.json").exists() else "Transcript exists but has not been normalized to simplified Chinese/technical terms.",
        lambda: normalize_transcript_command(argparse.Namespace(
            case=str(case_dir),
            chapter_minutes=args.chapter_minutes,
        )),
    )
    add(
        "frame-notes",
        lambda: keyframes_ready() and not (case_dir / "analysis" / "frame_observations.md").exists(),
        lambda: "Frame observation worksheet already exists." if (case_dir / "analysis" / "frame_observations.md").exists() else "Keyframes exist but visual observation worksheet is missing.",
        lambda: frame_notes(argparse.Namespace(case=str(case_dir), limit=args.frame_limit, context_seconds=15.0)),
    )
    add(
        "generate-study-pack",
        lambda: transcript_source_ready() and (not study_pack_ready() or args.overwrite_generated),
        lambda: "Study pack will be regenerated because overwrite is enabled." if args.overwrite_generated else "Study pack has not been generated.",
        lambda: generate_study_pack(argparse.Namespace(
            case=str(case_dir),
            chapter_minutes=args.chapter_minutes,
            claims=args.claims,
            force=True,
            overwrite_generated=args.overwrite_generated,
        )),
    )
    add(
        "fact-check-queue",
        lambda: transcript_source_ready() and not (case_dir / "analysis" / "fact_check_queue.json").exists(),
        lambda: "Fact-check queue already exists." if (case_dir / "analysis" / "fact_check_queue.json").exists() else "Claim candidates exist but fact-check queue is missing.",
        lambda: fact_check_queue(argparse.Namespace(case=str(case_dir), limit=args.claims)),
    )
    add(
        "export-study-session",
        lambda: transcript_source_ready() and (
            not (case_dir / "study_pack" / "09_study_session.md").exists()
            or args.overwrite_generated
        ),
        lambda: "Interactive study session will be regenerated because overwrite is enabled." if args.overwrite_generated else "Study pack exists but interactive study session is missing.",
        lambda: export_study_session(argparse.Namespace(
            case=str(case_dir),
            chapter_minutes=args.chapter_minutes,
            questions_per_chapter=2,
        )),
    )
    add(
        "validate-case",
        True,
        "Validate final case state.",
        lambda: validate_case(argparse.Namespace(case=str(case_dir), strict=False)),
    )
    return steps


def render_run_pipeline(report: dict[str, Any]) -> str:
    lines = ["# Run Pipeline Report", "", f"Case: `{report['case']}`", f"Dry run: `{report['dry_run']}`", ""]
    for step in report.get("steps", []):
        lines += [
            f"- `{step['name']}`: `{step['status']}` - {step.get('reason', '')}",
        ]
        if step.get("error"):
            lines.append(f"  Error: {step['error']}")
    return "\n".join(lines) + "\n"


def render_study_url_summary(report: dict[str, Any]) -> str:
    complete = bool(report.get("complete"))
    lines = [
        "# 视频学习任务完成" if complete else "# 视频学习任务未完成",
        "",
        f"- 案例目录：`{report['case']}`",
        f"- 学习包：`{report['study_pack']}`",
        f"- AI带学脚本：`{report['study_session']}`",
    ]
    if report.get("downloaded_media"):
        lines.append(f"- 已下载媒体：`{report['downloaded_media']}`")
    if report.get("warnings"):
        lines += ["", "## 警告", ""]
        lines += [f"- {warning}" for warning in report["warnings"]]
    if report.get("errors"):
        lines += ["", "## 错误", ""]
        lines += [f"- {error}" for error in report["errors"]]
    if complete:
        lines += [
            "",
            "下一步不要把学习包直接丢给用户。先读 `09_study_session.md`，然后用对话方式开始带学复刻：先说明最终要复刻什么，再给第 1 步命令，等待用户输出后继续判断。",
        ]
    else:
        lines += [
            "",
            "这次没有拿到可解析的视频、字幕或转写内容。请提供本地视频文件，或在允许联网访问的平台环境中重试。",
        ]
    return "\n".join(lines)


def render_study_session(session: dict[str, Any], questions_per_chapter: int) -> str:
    context = {
        "metadata": session.get("metadata") or {"input": {"raw_input": session.get("source")}},
        "chapters": session.get("chapters", []),
        "keyframes": session.get("keyframes", []),
    }
    quality = transcript_quality([
        seg
        for chapter in session.get("chapters", [])
        for seg in chapter.get("segments", [])
        if isinstance(seg, dict)
    ])
    lines = [
        "# AI 视频带学复刻脚本",
        "",
        f"来源：`{session.get('source')}`",
        "",
        "用这个文件进行互动式学习和复刻。它不是给用户看的最终文档，而是 AI 的后台教案。AI 应先学懂视频，再像老师一样带用户一步一步复现。",
        "",
        f"转写质量：`{quality.get('level')}`，评分：`{quality.get('score')}`。如果本章转写不顺，以视频画面和官方资料为准。",
        "",
        "## 带学规则",
        "",
        "- 不要把本文件全文发给用户。",
        "- 不要只总结“视频讲了什么”。必须转成“怎么复刻、为什么这么做、你现在运行什么、我如何判断输出”。",
        "- 每次只推进一个小步骤，给出可执行命令或检查动作，等待用户输出后再继续。",
        "- 每个步骤都要解释原理：这一步验证了哪条数据链、错了会出现什么现象。",
        "- 如果某个说法出现在事实核查队列里，在查证前标为“待核查”。",
        "- 回答和纠错都要尽量回到时间戳、字幕和关键帧证据。",
        "",
        "## 对话开场模板",
        "",
        "先告诉用户：我已经学完视频，接下来不发文档，而是带你复刻。然后按下面格式开始：",
        "",
        "1. 这个视频最终要复刻什么。",
        "2. 需要哪些前置条件。",
        "3. 整体原理链路是什么。",
        "4. 第一步先做什么。",
        "5. 为什么先做它。",
        "6. 用户运行什么命令或做什么检查。",
        "7. 用户应该把什么结果发回来。",
        "",
        "## 复刻路线",
        "",
        *render_replication_route(session),
        "",
    ]
    chapters = session.get("chapters") or []
    if not chapters:
        lines += [
            "## 缺少章节",
            "",
            "没有找到章节。请先运行 `clean-transcript`，再导出带学脚本。",
            "",
        ]
    for chapter in chapters:
        start = format_timestamp(safe_float(chapter.get("start")))
        end = format_timestamp(safe_float(chapter.get("end")))
        points = chapter_teaching_points(chapter, context)
        lines += [
            f"## 第 {chapter.get('index', '?')} 章：{display_chapter_title(chapter, context)}",
            "",
            f"- 时间：[{start} - {end}]",
            f"- 可信摘要：{chapter_summary(chapter, context, 260)}",
            f"- 关键词：{', '.join(clean_keywords(chapter.get('keywords', []), 8)) or '关键词不足，需要回看画面确认'}",
            "",
            "### 本章目标",
            "",
            "- 先听懂这一段在解决什么问题。",
            "- 再把视频内容转换成可复刻步骤。",
            "- 找出画面中的命令、图示、RViz 状态或硬件连接证据。",
            "- 最后判断自己复现时要检查哪些条件。",
            "",
            "### 讲解",
            "",
            *[f"- {point}" for point in points],
            "",
            f"讲的时候不要照念转写。先把本章放进完整链路：{teaching_chain_hint(context)}。",
            "",
            "### 证据提醒",
            "",
            "- 语音转写可能有错字，专业术语不要直接背。",
            "- ROS、导航、雷达类视频要重点核对包名、话题名、launch 文件、参数名和命令行。",
            "",
            "### 提问",
            "",
        ]
        for idx, question in enumerate(build_chapter_questions(chapter, questions_per_chapter), start=1):
            lines.append(f"{idx}. {question}")
        lines += [
            "",
            "### 纠正",
            "",
            "学习者回答后，用本章时间戳、字幕证据、关键帧和事实核查队列来纠正。待核查内容不要当成确定事实。",
            "",
        ]
    queue = session.get("fact_check_queue") or []
    lines += ["## 背诵前必须核查", ""]
    if queue:
        for item in queue[:20]:
            lines += [
                f"- `{item.get('id', 'claim')}` 优先级 `{item.get('priority', 'n/a')}`：{normalize_zh_text(str(item.get('text', '')))}",
            ]
    else:
        lines += ["- 没有找到事实核查队列。如果已经有断言候选，请运行 `fact-check-queue`。"]
    lines += ["", "## 完成标准", "", "- 学习者能凭记忆复述每章核心内容。", "- 学习者能回答生成的问题。", "- 学习者知道哪些视频说法还需要核查。", ""]
    return "\n".join(lines)


def render_replication_route(session: dict[str, Any]) -> list[str]:
    text = " ".join(str(ch.get("text", "")) for ch in session.get("chapters", []))
    source = str(session.get("source") or "")
    if is_low_cost_ros_box_video(text + source):
        return [
            "- 第 1 关：确认目标板卡/盒子型号、CPU、内存、存储和启动方式。重点核对 S905L/S905L3A、2G 内存、16G eMMC/USB 启动等信息。",
            "- 第 2 关：确认镜像来源和刷机方式。准备 U 盘、写盘工具、短接/进入刷机模式的方法，先不要接机器人。",
            "- 第 3 关：第一次启动 Linux，确认能 SSH 登录板子，并记录板子的 IP、用户名、密码。",
            "- 第 4 关：确认 ROS2 环境。运行 `ros2 --version`、`ros2 topic list` 或启动一个最小 demo。",
            "- 第 5 关：把机器人小车相关包、Web 控制台或作者开源镜像部署到板子上。",
            "- 第 6 关：确认 Web 控制台能连接板子，能看到视频流、摇杆控制、线速度/角速度状态。",
            "- 第 7 关：启动建图，验证地图能显示并保存。",
            "- 第 8 关：加载已保存地图，启动导航，验证代价地图、目标点和机器人运动。",
            "- 第 9 关：如果卡顿或启动失败，按电源、存储、网络、ROS2 环境、驱动包、CPU/内存占用顺序排查。",
        ]
    if re.search(r"雷达|lidar|slam|nav2|rviz|scan|tf|odom", text + source, re.I):
        return [
            "- 第 1 关：确认雷达 `/scan` 正常发布。命令：`ros2 topic list`、`ros2 topic echo /scan --once`、`ros2 topic hz /scan`。",
            "- 第 2 关：确认 TF 坐标关系正确。重点看 `base_link` 到雷达 frame 的方向和位置。",
            "- 第 3 关：确认里程计 `/odom` 正常。机器人前进、后退、旋转时，里程计变化方向要符合真实运动。",
            "- 第 4 关：启动 SLAM Toolbox 建图。先小范围慢速移动，确认地图不旋转、不漂移、不重影。",
            "- 第 5 关：低速键盘遥控扫描环境。遇到急转、打滑、雷达遮挡要暂停排查。",
            "- 第 6 关：保存地图，确认生成地图图像和 YAML 配置。",
            "- 第 7 关：启动 Nav2，加载保存的地图和参数文件。",
            "- 第 8 关：在 RViz2 设置 `Nav2 Goal`，验证路径规划和底盘执行。",
            "- 第 9 关：出现地图歪、漂移、不贴墙时，按 `/scan`、TF、`/odom`、速度、RViz Fixed Frame 顺序排查。",
        ]
    return [
        "- 第 1 关：确认视频要复刻的最终成果。",
        "- 第 2 关：列出前置环境、工具、账号、硬件或数据。",
        "- 第 3 关：按视频时间轴拆成可执行步骤。",
        "- 第 4 关：先复现最小可验证步骤。",
        "- 第 5 关：让用户运行检查命令或完成操作，并根据输出继续纠错。",
    ]


def teaching_chain_hint(context: dict[str, Any]) -> str:
    theme = infer_video_theme(context)
    if is_low_cost_ros_box_context(context):
        return "硬件选型 -> 刷 Linux/ROS2 镜像 -> SSH 登录 -> ROS2 环境验证 -> Web 中控台 -> 建图/导航验证"
    if "ROS2" in theme and "激光雷达" in theme:
        return "硬件接入 -> ROS2 数据 -> SLAM 建图 -> 地图保存 -> Nav2 导航"
    return "目标确认 -> 前置条件 -> 最小复现 -> 结果验证 -> 问题排查"


def build_chapter_questions(chapter: dict[str, Any], count: int) -> list[str]:
    keywords = [str(item) for item in chapter.get("keywords", []) if str(item).strip()]
    start = format_timestamp(safe_float(chapter.get("start")))
    end = format_timestamp(safe_float(chapter.get("end")))
    summary = summarize_text(str(chapter.get("summary") or chapter.get("text") or ""), 120)
    topic = " / ".join(normalize_zh_text(item) for item in keywords[:3]) if keywords else "本章内容"
    candidates = [
        f"用你自己的话说，[{start} - {end}] 这一章主要在解决什么问题？",
        f"视频里有哪些画面或字幕证据能支持 `{topic}` 这个重点？",
        "这一章里最应该记住的操作、命令、参数或配置是什么？",
        "如果不核对字幕和视频画面，直接照抄这一步，可能会出什么问题？",
        "这一章有哪些专业术语需要查资料确认后再背？",
    ]
    if summary and not is_poor_text(summary):
        candidates.insert(1, f"用一句话概括这一章的逻辑：{normalize_zh_text(summary)}")
    return candidates[: max(1, count)]


def render_validate_case(report: dict[str, Any]) -> str:
    lines = [
        "# Case Validation",
        "",
        f"Case: `{report['case']}`",
        f"Valid: `{report['valid']}`",
        "",
        "## Issues",
        "",
    ]
    if report["issues"]:
        for item in report["issues"]:
            suffix = f" (`{item['path']}`)" if item.get("path") else ""
            lines.append(f"- `{item['level']}` `{item['code']}`: {item['message']}{suffix}")
    else:
        lines += ["- No issues detected."]
    lines += ["", "## Recommended Next Steps", ""]
    for step in report.get("next_steps", []):
        lines += [
            f"- Priority {step['priority']}: {step['reason']}",
            "",
            "```powershell",
            step["command"],
            "```",
            "",
        ]
    return "\n".join(lines)


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
            write_markdown(path, content)
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
    text = normalize_zh_text(text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^\s*[-–—]\s*", "", text)
    return text.strip()


def normalize_zh_text(text: str) -> str:
    text = text.translate(ZH_NORMALIZATION_MAP)
    for old, new in TERM_NORMALIZATION_REPLACEMENTS:
        text = text.replace(old, new)
    return text


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


def normalize_transcript_command(args: argparse.Namespace) -> None:
    case_dir = Path(args.case).resolve()
    raw_segments = load_segments(case_dir)
    if not raw_segments:
        raise ValueError("No transcript content found. Run transcription or provide subtitles first.")
    normalized = [
        {
            **seg,
            "text": normalize_zh_text(clean_caption_text(str(seg.get("text", "")))),
        }
        for seg in raw_segments
    ]
    normalized = [seg for seg in normalized if seg["text"]]
    transcript_dir = case_dir / "transcript"
    write_segments_outputs(normalized, transcript_dir)
    chapters = segment_chapters(normalized, args.chapter_minutes)
    write_json(case_dir / "analysis" / "chapters.json", {"chapters": chapters})
    report = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "segments": len(normalized),
        "chapters": len(chapters),
        "outputs": [
            "transcript/segments.json",
            "transcript/transcript.txt",
            "transcript/transcript.srt",
            "analysis/chapters.json",
        ],
    }
    write_json(case_dir / "reports" / "normalize_transcript.json", report)
    print(str(case_dir / "reports" / "normalize_transcript.json"))


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
    write_markdown(out_path, "\n".join(lines))
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
        "transcript_quality": transcript_quality(segments),
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
            write_markdown(path, content)
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
    fact_check_queue(argparse.Namespace(case=str(case_dir), limit=20))
    export_study_session(argparse.Namespace(case=str(case_dir), chapter_minutes=5, questions_per_chapter=2))
    run_pipeline(argparse.Namespace(
        case=str(case_dir),
        dry_run=True,
        keep_going=False,
        process_local=False,
        transcribe=False,
        model="small",
        language="zh",
        keyframes=30,
        scene_keyframes=20,
        scene_threshold=0.35,
        max_single_minutes=60,
        chapter_minutes=5,
        claims=10,
        frame_limit=20,
        overwrite_generated=False,
        download=False,
        write_subs=False,
        sub_langs="zh.*,en.*",
        format="bv*+ba/b",
        timeout=600,
    ))
    next_steps(argparse.Namespace(case=str(case_dir)))
    validate_case(argparse.Namespace(case=str(case_dir), strict=True))
    merge_parts(argparse.Namespace(case=str(case_dir), summary_chars=600, force=True))
    report = {
        "case": str(case_dir),
        "checks": [
            "transcript/clean_segments.json",
            "analysis/chapters.json",
            "analysis/frame_observations.md",
            "study_pack/00_overview.md",
            "analysis/fact_check_queue.json",
            "study_pack/09_study_session.md",
            "analysis/study_session.json",
            "reports/run_pipeline.json",
            "analysis/next_steps.md",
            "reports/validate_case.json",
            "course_study_pack/00_course_overview.md",
        ],
    }
    write_json(case_dir / "reports" / "self_test.json", report)
    print(str(case_dir / "reports" / "self_test.json"))


def source_label(metadata: dict[str, Any]) -> str:
    input_info = metadata.get("input", {})
    return str(input_info.get("path") or input_info.get("raw_input") or "unknown")


def transcript_quality(segments: list[dict[str, Any]]) -> dict[str, Any]:
    texts = [str(seg.get("text", "")).strip() for seg in segments if str(seg.get("text", "")).strip()]
    total_chars = sum(len(t) for t in texts)
    if not texts or total_chars == 0:
        return {
            "level": "missing",
            "score": 0.0,
            "bad_ratio": 1.0,
            "warnings": ["没有可用转写文本。"],
        }
    noise_terms = re.compile(
        r"ctive|白強|骯髒|纴|搞国|搞行|Slam2Box|车距|绿箔|寻油|winter|肉速|小胆|交去|建成箭图|"
        r"RV2|TTR|通商店|策劲|汉文|遗权|咬不起",
        re.I,
    )
    bad_chars = sum(len(re.findall(r"[�\ufffd]|[鎺瑙艰埅婵€閫鍦鐢绋榻纴骯髒強]", t)) for t in texts)
    noisy_segments = sum(1 for t in texts if noise_terms.search(t))
    latin_fragments = sum(len(re.findall(r"[A-Za-z]{1,2}(?=[\u4e00-\u9fff])|(?<=[\u4e00-\u9fff])[A-Za-z]{1,2}", t)) for t in texts)
    short_noise = sum(1 for t in texts if len(t) <= 4 and not re.search(r"ROS|TF|USB|Nav2|SLAM|RViz|雷达|地图|导航", t, re.I))
    bad_ratio = min(1.0, (bad_chars + latin_fragments * 2 + short_noise * 4 + noisy_segments * 80) / max(1, total_chars))
    score = round(max(0.0, 1.0 - bad_ratio), 3)
    if score >= 0.82:
        level = "good"
    elif score >= 0.62:
        level = "usable"
    else:
        level = "poor"
    warnings = []
    if level == "poor":
        warnings.append("转写质量偏低，不能直接照抄学习包中的原文，需要结合关键帧和人工复核。")
    elif level == "usable":
        warnings.append("转写基本可用，但专有名词、命令和参数仍需要对照画面核对。")
    return {
        "level": level,
        "score": score,
        "bad_ratio": round(bad_ratio, 3),
        "segments": len(texts),
        "chars": total_chars,
        "warnings": warnings,
    }


def is_poor_text(text: str) -> bool:
    text = normalize_space(text)
    if not text:
        return True
    if len(text) <= 4 and not re.search(r"ROS|TF|USB|Nav2|SLAM|RViz|雷达|地图|导航", text, re.I):
        return True
    if re.search(
        r"ctive|白強|骯髒|纴|搞国|搞行|Slam2Box|车距|绿箔|寻油|winter|肉速|小胆|交去|建成箭图|"
        r"RV2|TTR|通商店|策劲|汉文|遗权|咬不起",
        text,
        re.I,
    ):
        return True
    bad = len(re.findall(r"[�\ufffd]|[鎺瑙艰埅婵€閫鍦鐢绋榻纴骯髒強]", text))
    return bad / max(1, len(text)) > 0.08


def reliable_text(text: str, max_chars: int = 360) -> str:
    sentences = [s for s in split_sentences(normalize_zh_text(text)) if not is_poor_text(s)]
    if not sentences:
        return "本段语音转写可信度不足，需要回看视频画面确认。"
    return summarize_text("".join(sentences), max_chars)


def chapter_summary(chapter: dict[str, Any], context: dict[str, Any], max_chars: int = 360) -> str:
    text = chapter.get("text", "")
    theme = infer_video_theme(context)
    start = safe_float(chapter.get("start"))
    if is_low_cost_ros_box_context(context):
        if start < 70:
            return "本章主要说明：作者用一百多元的晶晨 S905L/S905L3A 盒子替代更贵的树莓派/香橙派来跑 Linux 和 ROS2，并对比 CPU、内存、存储和价格。"
        if start < 150:
            return "本章演示实际效果：盒子运行机器人中控台，能显示摄像头、摇杆控制、SLAM 栅格地图、保存地图、加载地图和导航控制。"
        return "本章讲成本和部署方式：盒子原系统通常是安卓，需要刷入作者适配的 Linux/ROS2 镜像；刷机需要 U 盘和基本动手能力，也可以购买预刷好的版本。"
    if "本段语音转写可信度不足" not in reliable_text(text, max_chars):
        return reliable_text(text, max_chars)
    if "ROS2" in theme and "激光雷达" in theme:
        if start < 8 * 60:
            return "本章主要讲低成本激光雷达的硬件接入：拆看雷达接口，确认供电和通信线，把雷达通过串口/USB 转接接入机器人或电脑。重点不是价格，而是能否稳定输出 ROS 可用的扫描数据。"
        if start < 16 * 60:
            return "本章进入 ROS2 建图链路：雷达驱动提供 `/scan`，机器人提供 TF 和里程计，SLAM Toolbox 根据这些输入生成地图，RViz2 用来观察结果。"
        if start < 24 * 60:
            return "本章演示遥控建图：机器人端启动建图相关节点，电脑端打开 RViz2，使用键盘控制机器人慢速移动，扫描环境边界，最后保存地图文件。"
        return "本章演示导航部署和验证：把导航包部署到机器人工作空间，启动 Nav2 和 RViz2，设置导航目标点，观察机器人是否能规划路径并绕开新障碍。"
    return "本章转写不够可靠，需要回看视频画面确认；学习时先抓住问题、操作步骤和验证现象。"


def evidence_frames(context: dict[str, Any], start: float, end: float, limit: int = 4) -> list[str]:
    frames = keyframes_near(context.get("keyframes", []), start, end, limit)
    return [f"[{f.get('timestamp')}] `{Path(str(f.get('file'))).name}` ({f.get('reason') or 'keyframe'})" for f in frames]


def command_candidates(text: str) -> list[str]:
    patterns = [
        r"ros2\s+(?:run|launch|topic|service|param|bag)\s+[A-Za-z0-9_./:-]+(?:\s+[A-Za-z0-9_./:=+-]+){0,8}",
        r"colcon\s+build(?:\s+[A-Za-z0-9_./:=+-]+){0,8}",
        r"source\s+[A-Za-z0-9_./:=+-]+",
        r"rviz2(?:\s+[A-Za-z0-9_./:=+-]+){0,6}",
    ]
    found: list[str] = []
    for pattern in patterns:
        for m in re.finditer(pattern, text, flags=re.I):
            value = normalize_space(m.group(0))
            if value not in found:
                found.append(value)
    return found[:12]


def clean_keywords(keywords: list[Any], limit: int = 8) -> list[str]:
    cleaned: list[str] = []
    bad_terms = {
        "ttr", "pie", "logic", "winter", "好不好", "机器隔的", "下一期就来接小胆", "关注我",
        "上远程试试", "下面来运行一下试", "空间里",
    }
    for item in keywords:
        kw = normalize_zh_text(str(item)).strip()
        if not kw or kw.lower() in bad_terms or is_poor_text(kw):
            continue
        if kw not in cleaned:
            cleaned.append(kw)
        if len(cleaned) >= limit:
            break
    return cleaned


def is_low_cost_ros_box_video(text: str) -> bool:
    return bool(
        re.search(r"s905|s905l|s905l3a|晶晨|盒子|电视盒子|树莓派|香橙派|emmc|刷机|镜像|ssh", text, re.I)
        and re.search(r"ros2|rose\s*2|建图|导航|slam|mapping|机器人|小车", text, re.I)
    )


def is_low_cost_ros_box_context(context: dict[str, Any]) -> bool:
    text = " ".join(str(ch.get("text", "")) for ch in context.get("chapters", []))
    metadata = context.get("metadata") or {"input": {"raw_input": ""}}
    source = source_label(metadata) if isinstance(metadata, dict) else ""
    return is_low_cost_ros_box_video(f"{source} {text}")


def display_chapter_title(chapter: dict[str, Any], context: dict[str, Any]) -> str:
    start = safe_float(chapter.get("start"))
    theme = infer_video_theme(context)
    if is_low_cost_ros_box_context(context):
        if start < 70:
            return "硬件选型：S905L 盒子对比树莓派和香橙派"
        if start < 150:
            return "运行效果：Web 中控台、建图和导航演示"
        return "部署方式：刷 Linux/ROS2 镜像并通过 SSH 使用"
    if "ROS2" in theme and "激光雷达" in theme:
        if start < 8 * 60:
            return "硬件接入：雷达供电、通信和安装"
        if start < 16 * 60:
            return "ROS2 建图链路：/scan、TF、里程计和 SLAM Toolbox"
        if start < 24 * 60:
            return "遥控建图：RViz2 观察、键盘移动和保存地图"
        return "Nav2 导航：加载地图、设置目标点并验证绕障"
    keywords = clean_keywords(chapter.get("keywords", []), 3)
    return " / ".join(keywords) if keywords else normalize_zh_text(str(chapter.get("title") or "章节"))


def infer_video_theme(context: dict[str, Any]) -> str:
    text = " ".join(ch.get("text", "") for ch in context.get("chapters", []))
    source = Path(source_label(context["metadata"])).stem.lower()
    haystack = f"{source} {text}".lower()
    if is_low_cost_ros_box_video(haystack):
        return "用一百多元的晶晨 S905L/S905L3A 盒子刷 Linux/ROS2 镜像，替代树莓派/香橙派运行机器人建图、导航和 Web 中控台。"
    if any(k.lower() in haystack for k in ["雷达", "lidar", "slam", "nav2", "rviz"]):
        return "低成本激光雷达接入 ROS2，并完成 SLAM 建图与 Nav2 导航验证。"
    keywords = extract_keywords(text, 8)
    return "围绕 " + "、".join(keywords[:5]) + " 展开。" if keywords else "主题需要结合视频画面进一步确认。"


def chapter_teaching_points(chapter: dict[str, Any], context: dict[str, Any]) -> list[str]:
    text = chapter.get("text", "")
    lowered = text.lower()
    points: list[str] = []
    if is_low_cost_ros_box_video(text):
        if re.search(r"s905|树莓派|香橙派|cpu|内存|emmc|价格|淘宝|盒子", text, re.I):
            points.append("这类方案的核心不是性能最强，而是用足够便宜的 ARM 盒子跑 Linux/ROS2，降低机器人学习和验证成本。")
            points.append("选型时要看 CPU 架构、内存、存储、网口/USB、供电、散热和是否有可用镜像，不要只看价格。")
        if re.search(r"刷机|镜像|u盘|优盘|emmc|安卓|linux|ssh", text, re.I):
            points.append("复刻关键在镜像和启动方式：原安卓盒子要刷入 Linux/ROS2 镜像，启动后先通过 SSH 验证系统可控。")
        if re.search(r"建图|导航|代价地图|web|中控|摇杆|视频流|地图", text, re.I):
            points.append("跑 ROS2 成功不等于项目完成，还要验证 Web 中控台、建图、地图保存、地图加载和导航链路是否顺畅。")
    if re.search(r"雷达|lidar|usb|ttl|串口|供电", text, re.I):
        points.append("硬件重点是供电、通信接口和安装位置；便宜雷达能不能用，取决于能否稳定输出可被 ROS 使用的扫描数据。")
    if re.search(r"ros2|scan|tf|slam|toolbox|里程|odom|rviz", text, re.I):
        points.append("建图不是只看雷达点，SLAM 同时依赖 `/scan`、TF 坐标关系和机器人运动/里程计信息。")
    if re.search(r"keyboard|键盘|w|a|s|d|q|e|保存|地图", lowered, re.I):
        points.append("遥控建图时要慢速移动、少急转，建完后保存地图文件，后续导航阶段会加载这张地图。")
    if re.search(r"nav2|导航|launch|params|map|goal|代价地图|规划", text, re.I):
        points.append("导航阶段要把地图、Nav2 参数、定位、代价地图、路径规划和底盘速度执行串起来。")
    if not points:
        points.append(reliable_text(text, 260))
    return points[:4]


def render_overview(context: dict[str, Any]) -> str:
    metadata = context["metadata"]
    chapters = context["chapters"]
    all_text = " ".join(ch.get("text", "") for ch in chapters)
    keywords = extract_keywords(all_text, 12)
    quality = context.get("transcript_quality") or transcript_quality(context.get("segments", []))
    best = chapters[:5]
    lines = [
        "# 一页速览",
        "",
        f"来源：`{source_label(metadata)}`",
        "",
        "## 结论先说",
        "",
        infer_video_theme(context),
        "",
        "这份学习包应该当成“AI 预处理后的学习材料”，不是最终答案。命令、包名、参数名必须回看对应时间点确认。",
        "",
        "## 转写质量",
        "",
        f"- 质量等级：`{quality.get('level')}`，评分：`{quality.get('score')}`",
        f"- 转写段数：`{quality.get('segments', 0)}`，字符数：`{quality.get('chars', 0)}`",
        *[f"- 警告：{warning}" for warning in quality.get("warnings", [])],
        "",
        "## 视频主题",
        "",
        infer_video_theme(context),
        "",
        "## 你真正要学会的东西",
        "",
    ]
    if is_low_cost_ros_box_video(all_text + " " + source_label(metadata)):
        lines += [
            "- 判断低价 S905L/S905L3A 盒子是否适合跑 ROS2：CPU、内存、eMMC、USB、网络和价格。",
            "- 理解刷机链路：原安卓系统 -> 写入 Linux/ROS2 镜像 -> 启动 -> SSH 登录。",
            "- 验证 ROS2 运行能力：不是只开机，而是能跑建图、导航、Web 中控台、视频流和话题显示。",
            "- 明白低成本方案的边界：适合学习和算法验证，不等于所有复杂机器人任务都够用。",
        ]
    elif any(re.search(r"雷达|lidar|ros2|slam|nav2|rviz|tf|scan", ch.get("text", ""), re.I) for ch in chapters):
        lines += [
            "- 低成本激光雷达如何接到机器人上：供电、串口/USB 转接、安装朝向。",
            "- ROS2 建图链路怎么跑通：雷达驱动发布 `/scan`，TF/里程计提供位姿关系，SLAM Toolbox 输出地图。",
            "- RViz2 的作用是观察和交互，不是建图算法本体；地图歪通常要回到 TF、里程计、雷达姿态和运动速度排查。",
            "- Nav2 导航需要已保存地图、参数文件、定位、代价地图、路径规划、控制器和底盘执行全部配合。",
        ]
    else:
        lines += [f"- {kw}" for kw in keywords[:7]] or ["- 当前材料不足，需要补充转写或关键帧观察。"]
    lines += [
        "",
        "## 推荐学习顺序",
        "",
        *[f"{idx}. [{format_timestamp(ch['start'])}] {display_chapter_title(ch, context)}：{chapter_summary(ch, context, 140)}" for idx, ch in enumerate(best, start=1)],
        "",
        "## 本节怎么学",
        "",
        "先看 `01_full_notes.md` 建立完整链路，再看 `08_practice_checklist.md` 复现操作。遇到转写不顺的地方，直接回到时间戳和关键帧，不要背错字。",
        "",
    ]
    return "\n".join(lines)


def render_full_notes(context: dict[str, Any]) -> str:
    keyframes = context["keyframes"]
    quality = context.get("transcript_quality") or {}
    lines = [
        "# 完整学习笔记",
        "",
        f"转写质量：`{quality.get('level', 'unknown')}`，评分：`{quality.get('score', 'n/a')}`。",
        "下面按课程讲义方式整理。凡是命令、包名、参数名，都应回看视频画面再执行。",
        "",
    ]
    if not context["chapters"]:
        return "# 完整学习笔记\n\n未找到转写内容。请先提供字幕或运行转写。\n"
    for ch in context["chapters"]:
        frames = keyframes_near(keyframes, ch["start"], ch["end"])
        commands = command_candidates(ch.get("text", ""))
        lines += [
            f"## [{format_timestamp(ch['start'])}-{format_timestamp(ch['end'])}] {display_chapter_title(ch, context)}",
            "",
            "这一章在讲什么：",
            "",
            chapter_summary(ch, context, 420),
            "",
            "你要理解的关键点：",
            "",
            *[f"- {point}" for point in chapter_teaching_points(ch, context)],
            "",
            "本章术语：",
            "",
            *[f"- `{kw}`" for kw in clean_keywords(ch.get("keywords", []), 8)],
            "",
            "本章可能出现的命令/配置：",
            "",
            *([f"- `{cmd}`" for cmd in commands] if commands else ["- 没有从转写中可靠识别到命令；请回看关键帧确认。"]),
            "",
            "画面补充：",
            "",
        ]
        if frames:
            lines += [f"- [{f.get('timestamp')}] `{Path(str(f.get('file'))).name}` ({f.get('reason')})" for f in frames]
        else:
            lines += ["- 没有匹配到关键帧；需要回到视频对应时间段检查画面。"]
        lines += [
            "",
            "学习时要记住：",
            "",
            "- 先记链路和因果，不要先背零碎名词。",
            "- 看到转写不通顺时，以视频画面、命令行截图和官方文档为准。",
            "- 如果要照着做，先确认自己的 ROS 版本、硬件接口和包名是否一致。",
            "",
        ]
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
    domain_notes = {
        "ROS2": "机器人软件通信框架。这里主要负责把雷达、TF、建图、导航、显示这些节点组织到同一个系统里。",
        "SLAM": "同步定位与建图。它不是只看雷达点，还要依赖坐标系和机器人运动信息。",
        "Nav2": "ROS2 的导航框架，负责定位、代价地图、路径规划、控制和恢复行为等导航流程。",
        "RViz": "可视化和交互工具，用来观察雷达点、地图、TF、机器人模型和导航目标。",
        "TF": "ROS 中描述坐标系关系的机制。雷达、底盘、地图之间的坐标关系错了，建图和导航都会跟着错。",
        "scan": "激光雷达扫描话题，通常是 `/scan`，是 2D 雷达给 SLAM 和导航使用的重要输入。",
        "地图": "建图阶段生成的环境表示，导航阶段会加载它并配合定位与代价地图使用。",
        "雷达": "本视频里的核心传感器，用来提供周围障碍物的距离扫描数据。",
    }
    used = set()
    for key, desc in domain_notes.items():
        if re.search(re.escape(key), text, re.I):
            related = [ch for ch in context["chapters"] if re.search(re.escape(key), ch.get("text", ""), re.I)][:3]
            lines += [
                f"## {key}",
                "",
                f"定义：{desc}",
                "",
                "为什么重要：它属于本视频技术链路里的核心环节，理解它才能判断问题出在硬件、驱动、建图还是导航。",
                "",
                "相关时间点：",
                "",
                *[f"- [{format_timestamp(ch['start'])}] {normalize_zh_text(ch['title'])}" for ch in related],
                "",
                "常见误区：把显示问题、建图问题、定位问题混在一起。排查时要拆成数据、坐标、算法、执行四层看。",
                "",
            ]
            used.add(key.lower())
    for kw in keywords:
        if kw.lower() in used or is_poor_text(kw):
            continue
        related = [
            ch for ch in context["chapters"]
            if kw in ch.get("text", "")
        ][:3]
        if not related:
            continue
        lines += [
            f"## {kw}",
            "",
            f"定义：这是视频转写中反复出现的关键词，需结合 [{format_timestamp(related[0]['start'])}] 附近画面确认具体含义。",
            "",
            "为什么重要：反复出现通常说明它与本视频主线有关，但自动转写可能会把专有名词识别错。",
            "",
            "相关时间点：",
            "",
            *[f"- [{format_timestamp(ch['start'])}] {ch['title']}" for ch in related],
            "",
            "常见误区：只看转写文字，不回看画面中的代码、命令、图示和 RViz 状态。",
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
    lines += [
        "",
        "## 应用题",
        "",
        "1. 如果把视频里的方法用到自己的机器人上，第一步应该确认哪些硬件和软件条件？",
        "2. 如果建图时地图开始旋转或漂移，你会按什么顺序排查？",
        "",
        "## 参考答案要点",
        "",
        "- 基础题不要死背转写词，必须结合对应时间点的画面。",
        "- 应用时先确认雷达供电/通信、ROS2 驱动、`/scan`、TF、里程计、SLAM、地图保存、Nav2 参数。",
        "- 地图旋转优先排查 TF、雷达安装朝向、里程计方向/尺度、机器人运动过快和 RViz 固定坐标系。",
        "",
    ]
    return "\n".join(lines)


def render_flashcards(context: dict[str, Any]) -> str:
    keywords = extract_keywords(" ".join(ch.get("text", "") for ch in context["chapters"]), 12)
    lines = ["# 闪卡", ""]
    for kw in keywords:
        if is_poor_text(kw):
            continue
        related = next((ch for ch in context["chapters"] if kw in ch.get("text", "")), None)
        source = format_timestamp(related["start"]) if related else "00:00:00.000"
        lines += [
            f"Q: `{kw}` 是什么？",
            "",
            f"A: 它是视频 [{source}] 附近出现的关键词。先用 `01_full_notes.md` 理解上下文，再回看画面确认是否为正确术语。",
            "",
            f"Source: [{source}]",
            "",
        ]
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
    text = " ".join(ch.get("text", "") for ch in context["chapters"])
    commands = command_candidates(text)
    lines = [
        "# 实操清单",
        "",
        "## 环境准备",
        "",
        "- 确认激光雷达供电正常，通信接口能被电脑或机器人主控识别。",
        "- 确认 ROS2 环境可用，并且有雷达驱动、机器人模型/TF、SLAM Toolbox、Nav2、RViz2。",
        "- 确认机器人底盘能接收速度指令，遥控时能慢速、可控地移动。",
        "- 确认视频中的包名、launch 文件名、参数文件名和你本机项目一致。",
        "",
        "## 视频中识别到的命令/线索",
        "",
        *([f"- `{cmd}`" for cmd in commands] if commands else ["- 自动转写没有可靠识别到完整命令，请以关键帧画面为准。"]),
        "",
        "## 操作步骤",
        "",
    ]
    for idx, ch in enumerate(context["chapters"], start=1):
        lines.append(f"{idx}. [{format_timestamp(ch['start'])}] 学习并复现：{normalize_zh_text(ch['title'])}。重点：{'; '.join(chapter_teaching_points(ch, context)[:2])}")
    lines += [
        "",
        "## 验证方法",
        "",
        "- RViz2 中能看到稳定的激光扫描点。",
        "- 建图时地图边界不明显漂移、不旋转、不重复叠影。",
        "- 地图保存后能被导航 launch 正确加载。",
        "- 设置 Nav2 Goal 后，机器人能规划路径并执行移动。",
        "",
        "## 常见错误",
        "",
        "- 雷达安装角度和 URDF/TF 不一致，导致地图方向错。",
        "- 里程计方向、尺度或坐标轴错，导致建图漂移或旋转。",
        "- 遥控建图速度太快、急转太多，SLAM 来不及稳定匹配。",
        "- RViz 固定坐标系选错，看起来像地图歪了，实际是显示坐标关系没对上。",
        "- 直接照抄视频命令，但本机包名、工作空间、地图路径或参数文件不同。",
        "",
    ]
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

    doc = sub.add_parser("doctor", help="Check local dependencies and print setup guidance")
    doc.add_argument("--out", help="Optional JSON report path")
    doc.set_defaults(func=doctor)

    init = sub.add_parser("init", help="Create a case workspace")
    init.add_argument("--input", required=True, help="Video path, folder, URL, subtitle, or share text")
    init.add_argument("--out", required=True, help="Output directory for case workspaces")
    init.set_defaults(func=create_case)

    folder = sub.add_parser("init-folder", help="Create cases for every media/subtitle file in a folder")
    folder.add_argument("--input", required=True, help="Folder containing media files")
    folder.add_argument("--out", required=True, help="Output directory for case workspaces")
    folder.set_defaults(func=create_folder_cases)

    study = sub.add_parser("study-url", help="One-command URL/share-link workflow: acquire, process, and generate a study pack")
    study.add_argument("--input", required=True, help="Video URL or share text")
    study.add_argument("--out", required=True, help="Output directory for case workspaces")
    study.add_argument("--download", action="store_true", help="Download permitted media for speech-to-text transcription")
    study.add_argument("--transcribe", action="store_true", help="Transcribe downloaded media with faster-whisper")
    study.add_argument("--model", default="small", help="faster-whisper model")
    study.add_argument("--language", default="zh", help="Transcription language")
    study.add_argument("--device", default="auto", choices=["cpu", "cuda", "auto"], help="faster-whisper device; auto uses CUDA when available, otherwise CPU")
    study.add_argument("--compute-type", default="auto", help="faster-whisper compute type; auto uses float16 on CUDA and int8 on CPU")
    study.add_argument("--keyframes", type=int, default=30, help="Uniform keyframes for process-local")
    study.add_argument("--scene-keyframes", type=int, default=20, help="Scene-change keyframes for process-local")
    study.add_argument("--scene-threshold", type=float, default=0.35, help="Scene-change threshold")
    study.add_argument("--max-single-minutes", type=int, default=60, help="Long-video warning threshold")
    study.add_argument("--chapter-minutes", type=int, default=8, help="Chapter size")
    study.add_argument("--claims", type=int, default=30, help="Claim limit")
    study.add_argument("--frame-limit", type=int, default=80, help="Frame note limit")
    study.add_argument("--keep-going", action="store_true", help="Continue after a non-critical pipeline step fails")
    study.add_argument("--write-subs", action="store_true", help="Also try platform subtitles; disabled by default because normal text comes from ASR")
    study.add_argument("--sub-langs", default="zh.*,en.*", help="yt-dlp subtitle language selector when --write-subs is used")
    study.add_argument("--format", default="bv*+ba/b", help="yt-dlp format selector")
    study.add_argument("--timeout", type=int, default=1800, help="Timeout in seconds for acquisition commands")
    study.set_defaults(func=study_url)

    process = sub.add_parser("process-local", help="Extract audio/keyframes and optionally transcribe a local media case")
    process.add_argument("--case", required=True, help="Case directory created by init")
    process.add_argument("--keyframes", type=int, default=30, help="Number of uniform keyframes to extract")
    process.add_argument("--scene-keyframes", type=int, default=20, help="Maximum scene-change keyframes to extract")
    process.add_argument("--scene-threshold", type=float, default=0.35, help="FFmpeg scene-change threshold")
    process.add_argument("--transcribe", action="store_true", help="Transcribe extracted audio with faster-whisper")
    process.add_argument("--model", default="small", help="faster-whisper model size or local model path")
    process.add_argument("--language", default="zh", help="Transcription language, or empty string for auto")
    process.add_argument("--device", default="auto", choices=["cpu", "cuda", "auto"], help="faster-whisper device; auto uses CUDA when available, otherwise CPU")
    process.add_argument("--compute-type", default="auto", help="faster-whisper compute type; auto uses float16 on CUDA and int8 on CPU")
    process.add_argument("--max-single-minutes", type=int, default=60, help="Warn when media exceeds this length")
    process.set_defaults(func=process_local)

    split = sub.add_parser("split-media", help="Plan or execute local media splitting for long videos")
    split.add_argument("--case", required=True, help="Case directory created by init")
    split.add_argument("--part-minutes", type=int, default=25, help="Target part length in minutes")
    split.add_argument("--overlap-seconds", type=float, default=8.0, help="Overlap between parts")
    split.add_argument("--execute", action="store_true", help="Actually cut media parts with ffmpeg")
    split.add_argument("--copy-codecs", action="store_true", help="Use ffmpeg stream copy instead of re-encoding")
    split.add_argument("--timeout", type=int, default=1800, help="Timeout in seconds per ffmpeg split command")
    split.set_defaults(func=split_media)

    acquire = sub.add_parser("acquire-url", help="Acquire permitted media for a URL/share case")
    acquire.add_argument("--case", required=True, help="Case directory created by init")
    acquire.add_argument("--download", action="store_true", help="Download permitted media with yt-dlp")
    acquire.add_argument("--dry-run", action="store_true", help="Write the acquisition plan without running yt-dlp")
    acquire.add_argument("--write-subs", action="store_true", help="Also try platform subtitles; disabled by default because normal text comes from ASR")
    acquire.add_argument("--sub-langs", default="zh.*,en.*", help="yt-dlp subtitle language selector when --write-subs is used")
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

    normalize = sub.add_parser("normalize-transcript", help="Normalize transcript text to simplified Chinese and common technical terms")
    normalize.add_argument("--case", required=True, help="Case directory created by init")
    normalize.add_argument("--chapter-minutes", type=int, default=8, help="Approximate chapter size")
    normalize.set_defaults(func=normalize_transcript_command)

    frames = sub.add_parser("frame-notes", help="Create a visual observation worksheet from keyframes")
    frames.add_argument("--case", required=True, help="Case directory created by init")
    frames.add_argument("--limit", type=int, default=80, help="Maximum keyframes to include")
    frames.add_argument("--context-seconds", type=float, default=15.0, help="Transcript window around each frame")
    frames.set_defaults(func=frame_notes)

    merge = sub.add_parser("merge-parts", help="Merge processed part cases into a course-level study pack scaffold")
    merge.add_argument("--case", required=True, help="Parent case directory")
    merge.add_argument("--summary-chars", type=int, default=900, help="Maximum summary characters per part")
    merge.add_argument("--force", action="store_true", help="Overwrite existing course_study_pack files")
    merge.set_defaults(func=merge_parts)

    queue = sub.add_parser("fact-check-queue", help="Create a prioritized fact-check queue from claim candidates")
    queue.add_argument("--case", required=True, help="Case directory or parent case directory")
    queue.add_argument("--limit", type=int, default=80, help="Maximum claims to include")
    queue.set_defaults(func=fact_check_queue)

    next_cmd = sub.add_parser("next-steps", help="Inspect a case and write recommended next commands")
    next_cmd.add_argument("--case", required=True, help="Case directory created by init")
    next_cmd.set_defaults(func=next_steps)

    validate = sub.add_parser("validate-case", help="Validate a case workspace and report missing outputs")
    validate.add_argument("--case", required=True, help="Case directory created by init")
    validate.add_argument("--strict", action="store_true", help="Exit nonzero when errors are found")
    validate.set_defaults(func=validate_case)

    session = sub.add_parser("export-study-session", help="Export an interactive study-coach script")
    session.add_argument("--case", required=True, help="Case directory created by init")
    session.add_argument("--chapter-minutes", type=int, default=8, help="Chapter size fallback when chapters.json is missing")
    session.add_argument("--questions-per-chapter", type=int, default=2, help="Question prompts per chapter")
    session.set_defaults(func=export_study_session)

    run = sub.add_parser("run-pipeline", help="Run or preview the recommended offline pipeline for a case")
    run.add_argument("--case", required=True, help="Case directory created by init")
    run.add_argument("--dry-run", action="store_true", help="Plan steps without executing them")
    run.add_argument("--keep-going", action="store_true", help="Continue after a step fails")
    run.add_argument("--process-local", action="store_true", help="Run process-local automatically for local media")
    run.add_argument("--transcribe", action="store_true", help="Use faster-whisper during process-local")
    run.add_argument("--model", default="small", help="faster-whisper model")
    run.add_argument("--language", default="zh", help="Transcription language")
    run.add_argument("--device", default="auto", choices=["cpu", "cuda", "auto"], help="faster-whisper device; auto uses CUDA when available, otherwise CPU")
    run.add_argument("--compute-type", default="auto", help="faster-whisper compute type; auto uses float16 on CUDA and int8 on CPU")
    run.add_argument("--keyframes", type=int, default=30, help="Uniform keyframes for process-local")
    run.add_argument("--scene-keyframes", type=int, default=20, help="Scene-change keyframes for process-local")
    run.add_argument("--scene-threshold", type=float, default=0.35, help="Scene-change threshold")
    run.add_argument("--max-single-minutes", type=int, default=60, help="Long-video warning threshold")
    run.add_argument("--chapter-minutes", type=int, default=8, help="Chapter size")
    run.add_argument("--claims", type=int, default=30, help="Claim limit")
    run.add_argument("--frame-limit", type=int, default=80, help="Frame note limit")
    run.add_argument("--overwrite-generated", action="store_true", help="Overwrite generated study pack files")
    run.add_argument("--download", action="store_true", help="Allow permitted media download during acquire-url")
    run.add_argument("--write-subs", action="store_true", help="Also try platform subtitles; disabled by default because normal text comes from ASR")
    run.add_argument("--sub-langs", default="zh.*,en.*", help="yt-dlp subtitle language selector when --write-subs is used")
    run.add_argument("--format", default="bv*+ba/b", help="yt-dlp format selector")
    run.add_argument("--timeout", type=int, default=600, help="Command timeout")
    run.set_defaults(func=run_pipeline)

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
