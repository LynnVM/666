# Troubleshooting

## URL Cannot Be Downloaded

Ask for a local file or subtitle. Do not keep retrying fragile platform links.

## No Audio Track

Proceed with keyframes and OCR/vision. Mark transcript as unavailable.

## No Subtitles

Extract audio and transcribe. If transcription tools are unavailable, ask the user whether to install/configure them or proceed visually.

## Transcription Model Download Fails

Use a local model path if available. In restricted networks, the user may need to configure a mirror. Do not assume internet access.

## GPU Transcription

Default transcription uses `--device auto --compute-type auto`: CUDA/float16 when a CUDA GPU is visible to ctranslate2, otherwise CPU/int8.

Run `doctor` first. If it reports `ctranslate2-cuda - OK`, auto mode will use GPU. To force GPU, use:

```powershell
python <skill>/scripts/video_study_case.py process-local --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --keyframes 30 --scene-keyframes 20 --transcribe --model small --language zh --device cuda --compute-type float16
```

If CUDA fails with a missing DLL, cuBLAS, cuDNN, driver, or ctranslate2 error, retry with:

```powershell
python <skill>/scripts/video_study_case.py process-local --case ".\video-study-cases\lesson-xxxxxxxxxxxx" --keyframes 30 --scene-keyframes 20 --transcribe --model small --language zh --device cpu --compute-type int8
```

Do not let GPU setup block the learning flow. CPU/int8 is slower but reliable.

## Video Over 60 Minutes

Split into 20-30 minute parts unless chapters exist. Generate part notes first, then a merged study pack.

## Too Many Keyframes

Limit by scene-change score, OCR change, and timestamp spacing. Keep an index of dropped/kept frames.

## Visual/OCR Is Weak

Use transcript as primary evidence and ask for higher-resolution video or screenshots for important unreadable screens.

## Fact Checking Cannot Browse

Mark the fact-check section as "not externally verified" and list claims that should be checked later.

## Output Is Too Generic

Re-run understanding with a video-type template: programming, robotics, lecture, experiment, paper talk, game analysis, product tutorial, or interview.
