# Platform Adapters

Use adapters as an ordered strategy, not as a guarantee that every platform can always be downloaded.

## Compliance

Only process content the user has the right to access and study. Do not bypass DRM, paywalls, login-only restrictions, private content, or platform access controls. Do not provide guidance for bulk scraping. If acquisition fails, request a local video/audio/subtitle file.

## Input Classifier

Classify input as one of:

- `local_video`: local file ending in mp4, mov, mkv, webm, avi, flv.
- `local_audio`: local file ending in mp3, wav, m4a, flac, aac, ogg.
- `subtitle`: srt, vtt, ass, txt.
- `local_folder`: folder containing media files.
- `share_text`: text containing one or more URLs plus platform copy.
- `url`: direct URL.

Extract URLs from share text before platform detection.

## Adapter Order

1. Existing local media.
2. Existing subtitle files.
3. Platform/native public subtitles when available.
4. `yt-dlp` or equivalent local downloader, if installed and permitted.
5. User-provided local file fallback.

## Platform Notes

### Local Files

Use direct media probing and local extraction. This is the most stable path and should be preferred for Douyin, Xiaohongshu, and other platforms with fragile share links.

### YouTube

Prefer subtitles first. Then use `yt-dlp` for public videos when available. Preserve video title, channel, URL, and chapters.

### Bilibili

Prefer public subtitles/danmaku only when relevant to the learning goal. Use `yt-dlp` when available. If cookie/login is needed, do not ask for credentials in chat; ask the user to provide a downloaded local file.

### Douyin / TikTok

Treat share links as fragile. Extract the resolved URL when possible. Prefer user-provided local downloads for reliable processing.

### Xiaohongshu

Treat share links as fragile and frequently login-bound. Prefer local user-provided video files.

### Direct Video URLs

If the URL points directly to a media file, download only when permitted. Otherwise request a local file.

## Failure Messages

If a platform adapter fails, say:

```text
平台链接解析失败或受限制。请提供本地视频文件、音频文件或字幕文件，我会继续处理。
```
