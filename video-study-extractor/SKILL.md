---
name: video-study-extractor
description: Extract learning value from videos, audio files, subtitles, local folders, and platform links such as Bilibili, Douyin, Xiaohongshu, YouTube, and direct video URLs. Use when Codex needs to turn video lessons, screen recordings, talks, experiments, demos, short videos, or course folders into timestamped study packs with transcripts, keyframes, knowledge points, fact checks, corrections, quizzes, flashcards, and guided learning plans.
---

# Video Study Extractor

## Purpose

Use this skill to make AI study a video before teaching the user. The goal is not a plain summary. The goal is a timestamped, evidence-backed study pack that combines speech, subtitles, frames, OCR/visual observations, and external fact checking.

Default user-facing language: Chinese, unless the user asks otherwise.

## Core Workflow

1. Intake the input.
   - Accept local video/audio files, a folder of videos, existing subtitle files, direct video URLs, platform links, or copied share text.
   - Extract URLs from share text before deciding the adapter.
   - Record source, title/path, duration when known, platform, assumptions, and output directory.

2. Acquire media.
   - Prefer local files when provided.
   - Prefer existing subtitles when available.
   - For URLs, use platform adapters. See `references/platform-adapters.md` before handling platform-specific URLs.
   - Do not bypass DRM, paywalls, login-only content, or platform access controls.
   - If URL acquisition fails, ask for a local video file or subtitle file instead of pretending success.

3. Split long videos.
   - If duration is 60 minutes or less, process as one unit.
   - If duration is over 60 minutes, split into chapter-based parts when chapters exist; otherwise split into 20-30 minute parts.
   - Process parts independently, then merge repeated concepts and produce one global study pack.

4. Extract transcript.
   - Prefer user-provided or platform-provided subtitles.
   - Otherwise extract audio and transcribe with faster-whisper, whisper.cpp, cloud ASR, or the locally available toolchain.
   - Keep timestamps. Produce text, SRT, and machine-readable segments when possible.

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
   - Verify unstable or high-impact claims using current authoritative sources when browsing is available.
   - Prefer official docs, standards, textbooks, papers, and vendor documentation.
   - Mark unverified claims honestly. Do not invent citations.
   - Read `references/fact-checking.md` before producing a correction report.

9. Produce the study pack.
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

10. Teach interactively.
   - If the user asks to learn the video, teach one small section at a time.
   - Ask 1-3 questions after each section.
   - If the user answers incorrectly, explain using the relevant timestamp and correction notes.
   - Do not merely repeat the notes; act as a study coach.

## Quick Start

For a local video or folder, first create a case workspace:

```powershell
python <skill>/scripts/video_study_case.py init --input "D:\Videos\lesson.mp4" --out ".\video-study-cases"
```

For share text or a URL:

```powershell
python <skill>/scripts/video_study_case.py init --input "https://www.bilibili.com/video/BV..." --out ".\video-study-cases"
```

Then use the generated `study_plan.md` as the checklist for available local tools and next actions.

## Decision Rules

- If the input is a platform URL and network or downloader support is missing, fall back to asking for a local file.
- If the video has subtitles, use them first but still sample frames because visual content may contain important details not spoken aloud.
- If transcript and visual evidence conflict, surface the conflict.
- If the video is instructional, prioritize actionable steps, commands, prerequisites, common failures, and validation checks.
- If the video is entertainment or commentary, prioritize timeline, claims, viewpoints, and evidence rather than forcing technical templates.
- If a claim can materially mislead the learner, fact-check it before presenting it as knowledge.

## Bundled Resources

- `scripts/video_study_case.py`: Create case workspaces, classify inputs, extract URLs from share text, generate processing plans, and optionally inspect local media with available tools.
- `references/platform-adapters.md`: Platform adapter strategy and fallback behavior for local files, Bilibili, Douyin, Xiaohongshu, YouTube, and generic URLs.
- `references/output-templates.md`: Required study pack structure and formatting.
- `references/fact-checking.md`: Claim extraction, source priority, correction report rules.
- `references/troubleshooting.md`: Common failures and fallback actions.
