# video-study-extractor

AI video study coach for Codex skills.

This project turns videos, audio files, subtitles, folders, and platform links into timestamped study packs. It is designed for learning, not just summarization: the AI extracts transcripts and keyframes, understands the lesson structure, checks important claims, and then teaches the learner with notes, quizzes, flashcards, and guided learning plans.

## What It Supports

- Local video files such as MP4, MOV, MKV, WEBM, AVI.
- Local audio files such as MP3, WAV, M4A, FLAC.
- Existing subtitle files such as SRT, VTT, ASS, TXT.
- Local folders containing multiple videos.
- Platform URLs and share text from sites such as Bilibili, Douyin, Xiaohongshu, YouTube, and direct video URLs.

Platform links are handled with adapters and fallbacks. If a platform link cannot be accessed reliably or lawfully, provide a local downloaded video or subtitle file.

## Study Pack Outputs

The skill aims to produce:

- `00_overview.md`
- `01_full_notes.md`
- `02_timeline.md`
- `03_key_knowledge.md`
- `04_corrections_and_supplements.md`
- `05_quiz.md`
- `06_flashcards.md`
- `07_guided_learning_plan.md`
- `08_practice_checklist.md`

## Compliance

Use this project only for content you have the right to access and study. It does not bypass DRM, paywalls, login-only restrictions, private content, or platform access controls.

## Install As A Codex Skill

Copy the `video-study-extractor/` folder into your Codex skills directory:

```powershell
Copy-Item -Recurse -LiteralPath .\video-study-extractor -Destination "$env:USERPROFILE\.codex\skills\video-study-extractor"
```

Then invoke it with prompts like:

```text
Use $video-study-extractor to study this video: D:\Videos\lesson.mp4
```

## Current Status

This repository is still early, but it now contains a usable local-media pipeline:

- Create a repeatable study case workspace.
- Classify local files, folders, URLs, and share text.
- Probe local media when `ffprobe` is available.
- Extract 16 kHz mono WAV audio from local videos.
- Extract timestamped uniform and scene-change keyframes from local videos.
- Optionally transcribe audio with `faster-whisper`.
- Create editable study-pack templates.
- Generate `metadata.json`, `study_plan.md`, `keyframes/keyframes.json`, `transcript/`, `reports/process_local.json`, and `study_pack/`.

Platform URL adapters are specified but not yet fully automated. For Bilibili, Douyin, Xiaohongshu, and similar sites, the most reliable current path is to provide a local downloaded video.

## Dependencies

Minimum:

```powershell
python --version
```

For local video processing, install either system FFmpeg or Python fallback dependencies:

```powershell
pip install imageio-ffmpeg
```

For transcription:

```powershell
pip install faster-whisper
```

If you already have `ffmpeg` and `ffprobe` on PATH, the script will use them. If system `ffmpeg` is missing, it tries `imageio-ffmpeg` for extraction. Media probing still needs `ffprobe`.

## Local Video Pipeline

Create a case workspace:

```powershell
python .\video-study-extractor\scripts\video_study_case.py init --input "D:\Videos\lesson.mp4" --out ".\video-study-cases"
```

For a folder of videos:

```powershell
python .\video-study-extractor\scripts\video_study_case.py init-folder --input "D:\Videos\Course" --out ".\video-study-cases"
```

The script prints the created case directory. Then process local media:

```powershell
python .\video-study-extractor\scripts\video_study_case.py process-local --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --keyframes 30 --scene-keyframes 20
```

To also transcribe with faster-whisper:

```powershell
python .\video-study-extractor\scripts\video_study_case.py process-local --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --keyframes 30 --scene-keyframes 20 --transcribe --model small --language zh
```

Create editable study-pack files:

```powershell
python .\video-study-extractor\scripts\video_study_case.py study-pack-template --case ".\video-study-cases\lesson-xxxxxxxxxxxx"
```

After processing, ask Codex to inspect the generated case and produce the study pack:

```text
Use $video-study-extractor to finish the study pack for .\video-study-cases\lesson-xxxxxxxxxxxx
```

## Roadmap

- `v0.3`: Scene-change keyframes, folder batching, and study-pack templates.
- `v0.4`: Study pack generation helpers and stronger transcript/keyframe fusion.
- `v0.5`: Bilibili/YouTube public URL adapters.
- `v0.6`: Douyin/Xiaohongshu share-link fallbacks and stronger OCR.
- `v1.0`: Stable multi-platform video learning coach with fact-checking and guided study.
