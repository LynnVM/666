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

## First Utility

Create a case workspace:

```powershell
python .\video-study-extractor\scripts\video_study_case.py init --input "D:\Videos\lesson.mp4" --out ".\video-study-cases"
```

The script creates a repeatable workspace and a `study_plan.md` for the agent to continue processing.
