---
name: video-study-extractor
description: 'Study videos, audio files, subtitles, local folders, and platform links such as Bilibili, Douyin, Xiaohongshu, YouTube, and direct video URLs, then teach the user interactively. Use when Codex needs to learn from video lessons, tutorials, screen recordings, experiments, demos, talks, short videos, or course folders and then act as a study-and-replication coach: extract transcripts/keyframes as backend evidence, explain the underlying knowledge, give step-by-step reproduction commands or checks, wait for user outputs, diagnose problems, and continue coaching. Also supports generating timestamped study packs, fact checks, quizzes, flashcards, and guided learning materials as supporting artifacts.'
---

# Video Study Extractor

## Purpose

Use this skill to make AI study a video before teaching the user. The goal is not a plain summary and not a folder of documents as the final answer. The default user-facing outcome is an interactive study-and-replication session: explain the knowledge, convert the video into reproducible steps, give the next command/check, wait for the user's output, diagnose, and continue.

Use the timestamped study pack as backend evidence for the AI teacher. The pack combines speech-to-text transcription, frames, OCR/visual observations, and external fact checking. For platform links, use the link to acquire permitted media, then transcribe the audio; platform subtitles are optional auxiliary evidence only.

Default user-facing language: Chinese, unless the user asks otherwise.

## Core Workflow

1. Intake the input.
   - Accept local video/audio files, a folder of videos, existing subtitle files, direct video URLs, platform links, or copied share text.
   - Extract URLs from share text before deciding the adapter.
   - Record source, title/path, duration when known, platform, assumptions, and output directory.

2. Acquire media.
   - Prefer local files when provided.
   - For URLs/share text, acquire permitted media first so text can come from speech-to-text.
   - Use existing subtitles only when the user explicitly provides them or asks to include platform subtitles.
   - For URLs, use platform adapters. See `references/platform-adapters.md` before handling platform-specific URLs.
   - Do not bypass DRM, paywalls, login-only content, or platform access controls.
   - If URL acquisition fails, ask for a local video file or subtitle file instead of pretending success.

3. Split long videos.
   - If duration is 60 minutes or less, process as one unit.
   - If duration is over 60 minutes, run `split-media` to create a split plan. Use `--execute` only when the user wants actual part files.
   - Prefer chapter-based parts when chapters exist; otherwise split into 20-30 minute parts with a small overlap.
   - Process parts independently, then run `merge-parts` to create a course-level scaffold.

4. Extract transcript.
   - Default to extracting audio and transcribing with faster-whisper, whisper.cpp, cloud ASR, or the locally available toolchain.
   - Treat user-provided or platform-provided subtitles as optional auxiliary evidence, not the default transcript source.
   - Keep timestamps. Produce text, SRT, and machine-readable segments when possible.
   - Run transcript cleaning before study-pack generation when subtitles or transcript segments are available.

5. Extract keyframes.
   - Use more than uniform sampling: combine uniform frames, scene-change frames, slide/text-change frames, code-screen frames, and user-requested timestamps.
   - Name frames with timestamps when possible.
   - Keep an index explaining why each keyframe was selected.

6. Read visual content.
   - Inspect keyframes with available vision tools.
   - Extract visible text, code, commands, diagrams, equations, UI states, experimental observations, and errors.
   - Align visual observations with transcript timestamps.

7. Understand the lesson.
   - Classify the video type: programming, robotics/hardware, course lecture, experiment, paper/tech talk, product tutorial, game analysis, interview/podcast, or mixed.
   - Extract prerequisites, chapter structure, core concepts, procedures, commands/code, examples, warnings, conclusions, and practice tasks.
   - For detailed output templates, read `references/output-templates.md`.

8. Fact-check important claims.
   - Extract explicit factual claims, technical claims, commands, configuration advice, safety claims, formulas, and definitions.
   - Run `fact-check-queue` after claim candidates exist, especially for long videos with multiple part cases.
   - Verify unstable or high-impact claims using current authoritative sources when browsing is available.
   - Prefer official docs, standards, textbooks, papers, and vendor documentation.
   - Mark unverified claims honestly. Do not invent citations.
   - Read `references/fact-checking.md` before producing a correction report.

9. Produce the study pack as backend evidence.
   - Create timestamped outputs:
     - `00_overview.md`
     - `01_full_notes.md`
     - `02_timeline.md`
     - `03_key_knowledge.md`
     - `04_corrections_and_supplements.md`
     - `05_quiz.md`
     - `06_flashcards.md`
     - `07_guided_learning_plan.md`
     - `08_practice_checklist.md`
   - Use Chinese filenames only when the user asks; default to ASCII filenames for portability.

10. Teach and replicate interactively.
   - Read `references/coaching-mode.md` before starting chat-based coaching or reproduction guidance.
   - Treat `study_pack/09_study_session.md` as the AI's private lesson plan, not as the final response.
   - If the user asks to learn or reproduce the video, do not merely summarize or point to files.
   - Start by stating: what the video ultimately reproduces, prerequisites, the overall principle chain, and the first small check/action.
   - For each step, explain why the step matters, give exact commands or actions, say what output the user should send back, then wait.
   - Diagnose the user's output before moving on.
   - If the video is technical or practical, prioritize reproduction path, commands, environment checks, validation signs, common failures, and fixes.
   - Ask 1-3 questions only when they help verify understanding or decide the next step.

## Quick Start

Check local dependencies first when setup is uncertain:

```powershell
python <skill>/scripts/video_study_case.py doctor
```

Transcription defaults to `--device auto --compute-type auto`: use CUDA/float16 when ctranslate2 can see a CUDA GPU, otherwise use CPU/int8. Run `doctor` to see what auto mode will choose. To force GPU transcription:

```powershell
python <skill>/scripts/video_study_case.py process-local --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --keyframes 30 --scene-keyframes 20 --transcribe --model small --language zh --device cuda --compute-type float16
```

If CUDA fails with a missing DLL, driver, cuBLAS, cuDNN, or ctranslate2 error, retry with reliable CPU mode:

```powershell
python <skill>/scripts/video_study_case.py process-local --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --keyframes 30 --scene-keyframes 20 --transcribe --model small --language zh --device cpu --compute-type int8
```

For the normal "user gives one video link, AI learns it and then coaches the user" workflow, prefer the one-command URL workflow:

```powershell
python <skill>/scripts/video_study_case.py study-url --input "https://www.bilibili.com/video/BV..." --out ".\video-study-cases" --download --transcribe --model small --language zh
```

This command should be the default for URL/share-text requests when media acquisition is permitted. It creates the case, acquires media, processes local media if available, transcribes speech, cleans the transcript, generates the backend study pack, exports the study-and-replication script, and validates the case. Auto mode uses GPU when available and CPU when not. Add `--write-subs` only if the user explicitly wants platform subtitles as auxiliary evidence.

After this command succeeds, read `study_pack/09_study_session.md` and start coaching in chat. Do not answer with only "files generated" unless the user explicitly asks for files.

For a local video or folder, first create a case workspace:

```powershell
python <skill>/scripts/video_study_case.py init --input "D:\Videos\lesson.mp4" --out ".\video-study-cases"
```

For a folder of videos:

```powershell
python <skill>/scripts/video_study_case.py init-folder --input "D:\Videos\Course" --out ".\video-study-cases"
```

For share text or a URL:

```powershell
python <skill>/scripts/video_study_case.py init --input "https://www.bilibili.com/video/BV..." --out ".\video-study-cases"
```

For a URL/share-text case, acquire permitted media for ASR:

```powershell
python <skill>/scripts/video_study_case.py acquire-url --case ".\video-study-cases\bilibili-xxxxxxxxxxxx" --download
```

Use `--dry-run` to inspect the planned `yt-dlp` commands before acquisition. Use `--write-subs` only when platform subtitles are explicitly requested as auxiliary evidence.

Then process local media when the case contains a local video or audio file:

```powershell
python <skill>/scripts/video_study_case.py process-local --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --keyframes 30 --scene-keyframes 20
```

For long videos, generate a split plan first:

```powershell
python <skill>/scripts/video_study_case.py split-media --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --part-minutes 25
```

Use `--execute` to cut media parts and create child cases:

```powershell
python <skill>/scripts/video_study_case.py split-media --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --part-minutes 25 --execute
```

After part cases are processed, merge them:

```powershell
python <skill>/scripts/video_study_case.py merge-parts --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --force
```

Create a fact-check queue:

```powershell
python <skill>/scripts/video_study_case.py fact-check-queue --case ".\video-study-cases\lesson-xxxxxxxxxxxx"
```

When a case is partially processed, ask the script for recommended next commands:

```powershell
python <skill>/scripts/video_study_case.py next-steps --case ".\video-study-cases\lesson-xxxxxxxxxxxx"
```

Validate case completeness:

```powershell
python <skill>/scripts/video_study_case.py validate-case --case ".\video-study-cases\lesson-xxxxxxxxxxxx"
```

Export an interactive study-coach script:

```powershell
python <skill>/scripts/video_study_case.py export-study-session --case ".\video-study-cases\lesson-xxxxxxxxxxxx"
```

Preview the remaining offline pipeline:

```powershell
python <skill>/scripts/video_study_case.py run-pipeline --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --dry-run
```

Use optional transcription when `faster-whisper` is installed:

```powershell
python <skill>/scripts/video_study_case.py process-local --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --keyframes 30 --scene-keyframes 20 --transcribe --model small --language zh
```

Create editable study pack files when the user wants a ready-to-fill output scaffold:

```powershell
python <skill>/scripts/video_study_case.py study-pack-template --case ".\video-study-cases\lesson-xxxxxxxxxxxx"
```

Generate a first-pass study pack from transcripts and keyframe indexes:

```powershell
python <skill>/scripts/video_study_case.py generate-study-pack --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --chapter-minutes 8 --claims 30 --force
```

For better output quality, clean transcript segments before generation:

```powershell
python <skill>/scripts/video_study_case.py clean-transcript --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --chapter-minutes 8
```

Create a visual observation worksheet after keyframes exist:

```powershell
python <skill>/scripts/video_study_case.py frame-notes --case ".\video-study-cases\lesson-xxxxxxxxxxxx"
```

Run an offline fixture to verify the installed script:

```powershell
python <skill>/scripts/video_study_case.py self-test --out ".\work\video-study-self-test"
```

After acquisition or processing, read `metadata.json`, relevant reports such as `reports/acquire_url.json`, `reports/process_local.json`, `reports/clean_transcript.json`, `transcript/transcript.txt`, `analysis/chapters.json`, `analysis/frame_observations.md`, and `keyframes/keyframes.json`. Inspect the listed keyframes with vision tools before producing the study pack.

## Decision Rules

- If the input is a platform URL and network or downloader support is missing, write the acquisition report and fall back to asking for a local file.
- If environment setup is uncertain, run `doctor` before media processing.
- If transcription is requested, default to auto mode. Run `doctor`; auto mode uses `--device cuda --compute-type float16` when `ctranslate2-cuda` is available, otherwise `--device cpu --compute-type int8`.
- If GPU transcription fails, preserve the error in the report and retry with `--device cpu --compute-type int8` rather than blocking the whole learning workflow.
- If the case state is unclear, run `next-steps` and follow the highest-priority command.
- If generated outputs look incomplete, run `validate-case` and address warnings/errors.
- If the user wants to learn interactively or reproduce what the video teaches, run `export-study-session` after notes and fact-check queue are generated, then start the first coaching step in chat.
- If the user wants fewer manual commands, run `run-pipeline --dry-run` first, then run without `--dry-run` only for safe offline steps.
- If local media is longer than 60 minutes, split it before final study-pack generation unless the user explicitly wants one large case.
- If the video has subtitles, keep them as auxiliary evidence but still generate the main transcript from speech unless the user asks otherwise.
- If subtitles are too fragmented or noisy, run `clean-transcript` before generating notes.
- If keyframes exist, run `frame-notes` and fill visual observations before finalizing notes.
- If transcript and visual evidence conflict, surface the conflict.
- If the video is instructional, prioritize actionable steps, commands, prerequisites, common failures, and validation checks.
- If the video is entertainment or commentary, prioritize timeline, claims, viewpoints, and evidence rather than forcing technical templates.
- If a claim can materially mislead the learner, fact-check it before presenting it as knowledge.

## Bundled Resources

- `scripts/video_study_case.py`: Check dependencies, create case workspaces, validate case completeness, batch-create cases from folders, classify inputs, extract URLs from share text, acquire public subtitles/media with `yt-dlp` when available, recommend next commands, generate processing plans, run or preview offline pipeline steps, split long local media into part cases, merge processed part cases, extract local audio, extract uniform and scene-change keyframes, optionally transcribe with faster-whisper, clean transcript segments, generate chapter JSON, create frame-observation worksheets, create study-pack templates, generate first-pass study packs, create fact-check queues, export interactive study sessions, run an offline self-test fixture, and extract claim candidates for fact checking.
- `references/platform-adapters.md`: Platform adapter strategy and fallback behavior for local files, Bilibili, Douyin, Xiaohongshu, YouTube, and generic URLs.
- `references/output-templates.md`: Required study pack structure and formatting.
- `references/coaching-mode.md`: Chat-based teaching and reproduction loop for turning studied videos into step-by-step coaching.
- `references/fact-checking.md`: Claim extraction, source priority, correction report rules.
- `references/troubleshooting.md`: Common failures and fallback actions.
