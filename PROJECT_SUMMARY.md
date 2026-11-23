# ClipSpeak Project History

## v2.0 — November 23, 2026: rewritten from scratch

The offline Piper engine was replaced by **Gemini 3.8 Flash TTS** through OpenRouter's
`/api/v1/audio/speech` endpoint.

Why a rewrite instead of an update:
- v1.1 no longer started on LMDE 7 / Debian 13: the `AppIndicator3` namespace is gone,
  only `AyatanaAppIndicator3` exists.
- Almost all of v1.1 was Piper plumbing (bundled binary and libraries, 278 MB of voices,
  per-language models, `langdetect`), and the new model makes all of it unnecessary:
  it detects the language by itself and offers 30 voices.

What was kept: tray icon, Unix-socket command channel for the `--speak` shortcut,
desktop notifications, `.deb` packaging (now 17 KB, `Architecture: all`).

Technical notes about the model (measured on 2026-11-23):
- Output is raw PCM only: signed 16-bit little-endian, 24 kHz, mono.
- The `speed` parameter is ignored. Speed, pitch and style are steered with the `instructions`
  field (sent to Gemini as `speech_metadata.style`, not read aloud). With the same text:
  slow 14.9 s / normal 9.4 s / fast 7.2 s; median pitch low 117 Hz / normal 167 Hz / high 250 Hz.
- Audio is not streamed: it arrives in one piece after about 1.5 s + 0.25 s per second of audio.
  ClipSpeak therefore splits long texts (first chunk around 180 characters) and synthesizes the
  next chunk while the current one plays.
- Cost: about $0.014 per minute of audio (Flash), less with Flash Lite.

## v1.1 — December 7, 2025

Offline TTS with Piper voices for 9 languages, `langdetect`, GTK/AppIndicator tray, speed control,
"fat" .deb with voices included.
