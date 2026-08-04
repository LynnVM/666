# video-study-extractor

AI video study-and-replication coach for Codex skills.

This project helps an AI study videos, audio files, subtitles, folders, and platform links, then teach the learner interactively. The intended result is not just a summary or a folder of Markdown files: the AI should understand the lesson, explain the principles, convert the video into a reproduction path, give the learner one command/check at a time, diagnose the learner's output, and continue coaching.

The generated study pack is backend evidence for the AI teacher. It contains timestamps, transcripts, keyframes, knowledge points, fact-check queues, quizzes, flashcards, and practice checklists, but the main user experience should be conversational coaching.

## What It Supports

- Local video files such as MP4, MOV, MKV, WEBM, AVI.
- Local audio files such as MP3, WAV, M4A, FLAC.
- Existing subtitle files such as SRT, VTT, ASS, TXT.
- Local folders containing multiple videos.
- Platform URLs and share text from sites such as Bilibili, Douyin, Xiaohongshu, YouTube, and direct video URLs.

Platform links are handled with adapters and fallbacks. The normal workflow uses the link to acquire permitted media, then generates text with speech-to-text transcription. Platform subtitles are optional auxiliary evidence only. If a platform link cannot be accessed reliably or lawfully, provide a local downloaded video file.

## Backend Study Pack Outputs

The skill can produce these supporting files:

- `00_overview.md`
- `01_full_notes.md`
- `02_timeline.md`
- `03_key_knowledge.md`
- `04_corrections_and_supplements.md`
- `05_quiz.md`
- `06_flashcards.md`
- `07_guided_learning_plan.md`
- `08_practice_checklist.md`
- `09_study_session.md`

For interactive learning, start from `09_study_session.md`, then teach in chat instead of handing the user the files as the final answer.

## Compliance

Use this project only for content you have the right to access and study. It does not bypass DRM, paywalls, login-only restrictions, private content, or platform access controls.

## Install As A Codex Skill

Copy the `video-study-extractor/` folder into your Codex skills directory:

```powershell
Copy-Item -Recurse -LiteralPath .\video-study-extractor -Destination "$env:USERPROFILE\.codex\skills\video-study-extractor"
```

Then invoke it with prompts like:

```text
Use $video-study-extractor to study this video, explain the principles, and guide me step by step to reproduce it: D:\Videos\lesson.mp4
```

## Current Status

This repository is still early, but it now contains a usable local-media pipeline:

- Create a repeatable study case workspace.
- Check local dependencies with `doctor`.
- Classify local files, folders, URLs, and share text.
- Probe local media when `ffprobe` is available.
- Extract 16 kHz mono WAV audio from local videos.
- Extract timestamped uniform and scene-change keyframes from local videos.
- Optionally transcribe audio with `faster-whisper`.
- Acquire permitted public media from URL/share-text cases with `yt-dlp` when available.
- Generate the main transcript from speech-to-text rather than relying on platform subtitles.
- Plan and optionally execute long-video splitting into smaller part cases.
- Merge processed part cases into a course-level study pack scaffold.
- Clean SRT/VTT/TXT transcripts, merge overly short captions, and generate chapter JSON.
- Create a frame-observation worksheet so AI can inspect keyframes with nearby transcript context.
- Create editable study-pack templates.
- Generate draft study packs from transcripts and keyframe indexes.
- Export an interactive study-session script for AI-guided learning.
- Extract claim candidates that should be fact-checked.
- Recommend the next command for an in-progress case.
- Validate case workspaces and report missing outputs.
- Preview or run the offline case pipeline with one command.
- Generate `metadata.json`, `study_plan.md`, `keyframes/keyframes.json`, `transcript/`, `reports/process_local.json`, and `study_pack/`.

Platform URL acquisition is best-effort. It uses `yt-dlp` when available to download permitted public media for speech-to-text transcription. For Bilibili, Douyin, Xiaohongshu, and similar sites, the most reliable fallback is still a local downloaded video file.

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

For URL/share-link acquisition:

```powershell
pip install yt-dlp
```

If you already have `ffmpeg` and `ffprobe` on PATH, the script will use them. If system `ffmpeg` is missing, it tries `imageio-ffmpeg` for extraction. Media probing still needs `ffprobe`.

## One-Command URL Study And Coaching

For the normal "give AI one video link, let it study the video, then coach the learner" workflow, use `study-url`.

```powershell
python .\video-study-extractor\scripts\video_study_case.py study-url --input "https://www.bilibili.com/video/BV..." --out ".\video-study-cases" --download --transcribe --model small --language zh --device cpu --compute-type int8
```

This command creates a case, acquires permitted media, extracts audio and keyframes, transcribes speech, cleans the transcript, generates the backend study pack, exports an AI-guided replication script, and validates the case.

The final files are printed at the end. For interactive coaching, the AI should read:

- `study_pack/09_study_session.md`

Then it should start the first reproduction step in chat: explain the goal, prerequisites, principle chain, first command/check, and what output the learner should send back.

Use CPU by default on Windows because it is reliable without CUDA. If CUDA is installed correctly, use:

```powershell
python .\video-study-extractor\scripts\video_study_case.py study-url --input "https://www.bilibili.com/video/BV..." --out ".\video-study-cases" --download --transcribe --model small --language zh --device cuda --compute-type float16
```

## Local Video Pipeline

Check local dependencies:

```powershell
python .\video-study-extractor\scripts\video_study_case.py doctor
```

Create a case workspace:

```powershell
python .\video-study-extractor\scripts\video_study_case.py init --input "D:\Videos\lesson.mp4" --out ".\video-study-cases"
```

For a folder of videos:

```powershell
python .\video-study-extractor\scripts\video_study_case.py init-folder --input "D:\Videos\Course" --out ".\video-study-cases"
```

For a platform URL or copied share text:

```powershell
python .\video-study-extractor\scripts\video_study_case.py init --input "https://www.bilibili.com/video/BV..." --out ".\video-study-cases"
```

Check what acquisition would run:

```powershell
python .\video-study-extractor\scripts\video_study_case.py acquire-url --case ".\video-study-cases\bilibili-xxxxxxxxxxxx" --dry-run
```

Acquire permitted public media for speech-to-text:

```powershell
python .\video-study-extractor\scripts\video_study_case.py acquire-url --case ".\video-study-cases\bilibili-xxxxxxxxxxxx" --download
```

Only request platform subtitles as optional auxiliary evidence:

```powershell
python .\video-study-extractor\scripts\video_study_case.py acquire-url --case ".\video-study-cases\bilibili-xxxxxxxxxxxx" --download --write-subs
```

The script prints the created case directory. Then process local media:

```powershell
python .\video-study-extractor\scripts\video_study_case.py process-local --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --keyframes 30 --scene-keyframes 20
```

For long videos, first generate a split plan:

```powershell
python .\video-study-extractor\scripts\video_study_case.py split-media --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --part-minutes 25
```

To actually cut the media and create one case per part:

```powershell
python .\video-study-extractor\scripts\video_study_case.py split-media --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --part-minutes 25 --execute
```

After processing each part case, merge the parts back into a course-level scaffold:

```powershell
python .\video-study-extractor\scripts\video_study_case.py merge-parts --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --force
```

Create a prioritized fact-check queue:

```powershell
python .\video-study-extractor\scripts\video_study_case.py fact-check-queue --case ".\video-study-cases\lesson-xxxxxxxxxxxx"
```

Ask the script what to do next for a case:

```powershell
python .\video-study-extractor\scripts\video_study_case.py next-steps --case ".\video-study-cases\lesson-xxxxxxxxxxxx"
```

Validate a case workspace:

```powershell
python .\video-study-extractor\scripts\video_study_case.py validate-case --case ".\video-study-cases\lesson-xxxxxxxxxxxx"
```

Export an AI-guided study session:

```powershell
python .\video-study-extractor\scripts\video_study_case.py export-study-session --case ".\video-study-cases\lesson-xxxxxxxxxxxx"
```

Preview the remaining offline pipeline:

```powershell
python .\video-study-extractor\scripts\video_study_case.py run-pipeline --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --dry-run
```

To also transcribe with faster-whisper:

```powershell
python .\video-study-extractor\scripts\video_study_case.py process-local --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --keyframes 30 --scene-keyframes 20 --transcribe --model small --language zh
```

Clean subtitles/transcripts before generating the study pack:

```powershell
python .\video-study-extractor\scripts\video_study_case.py clean-transcript --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --chapter-minutes 8
```

If you have a separate subtitle file:

```powershell
python .\video-study-extractor\scripts\video_study_case.py clean-transcript --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --source "D:\Videos\lesson.srt"
```

Create a visual observation worksheet from extracted keyframes:

```powershell
python .\video-study-extractor\scripts\video_study_case.py frame-notes --case ".\video-study-cases\lesson-xxxxxxxxxxxx"
```

Create editable study-pack files:

```powershell
python .\video-study-extractor\scripts\video_study_case.py study-pack-template --case ".\video-study-cases\lesson-xxxxxxxxxxxx"
```

Generate a draft study pack from transcript and keyframe indexes:

```powershell
python .\video-study-extractor\scripts\video_study_case.py generate-study-pack --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --chapter-minutes 8 --claims 30 --force
```

This fills the study pack with a first-pass overview, chapter notes, timeline, key knowledge, quiz, flashcards, guided plan, practice checklist, and a correction file containing claim candidates for later fact-checking.

Run an offline self-test fixture:

```powershell
python .\video-study-extractor\scripts\video_study_case.py self-test --out ".\work\self-test"
```

After processing, ask Codex to inspect the generated case and produce the study pack:

```text
Use $video-study-extractor to finish the study pack for .\video-study-cases\lesson-xxxxxxxxxxxx
```

## Roadmap

- `v0.3`: Scene-change keyframes, folder batching, and study-pack templates.
- `v0.4`: Draft study pack generation and claim candidate extraction.
- `v0.5`: Public URL/share-link acquisition adapter using `yt-dlp`, subtitles-first.
- `v0.6`: Transcript cleaning, chapter JSON, frame-observation worksheets, and offline self-test fixture.
- `v0.7`: Long-video split plans, optional FFmpeg part cutting, child case generation, part merging, fact-check queues, dependency doctor, next-step recommendations, case validation, study-session export, and pipeline runner.
- `v1.0`: Stable multi-platform video learning coach with fact-checking and guided study.
