---
name: diagnosing-voice
description: Diagnose Hermes voice mode issues — STT/TTS provider failures, audio device problems, latency, ffmpeg missing, and voice message transcription.
version: 1.0.2
metadata:
  hermes:
    tags: [hermes, voice, tts, stt, troubleshooting]
    related_skills: [hermes-configuration-guide, diagnosing-cli-tui]
---

# Diagnosing Voice Mode

Goal: reduce any voice problem to one concrete fix — a config.yaml field, a provider switch, or a missing dependency. Voice mode covers STT (speech-to-text), TTS (text-to-speech), and voice message transcription.

## 1. Configuration shape

```yaml
# ~/.hermes/config.yaml
voice:
  record_key: "ctrl+b"
  max_recording_seconds: 120
  auto_tts: false
  beep_enabled: true
  silence_threshold: 200
  silence_duration: 3.0
  stop_phrases: ["stop"]

stt:
  enabled: true
  provider: "local"           # local | groq | openai | mistral | xai | elevenlabs | deepinfra
  local:
    model: "base"             # tiny | base | small | medium | large-v3
    language: ""

tts:
  provider: "edge"            # edge | elevenlabs | openai | minimax | mistral | gemini | xai | deepinfra | neutts | kittentts | piper
  edge:
    voice: "en-US-AriaNeural"
    speed: 1.0
  streaming:
    min_len: 20
```

## 2. How to inspect

> [!NOTE]
> Voice controls are **in-session slash commands**, not `hermes voice` CLI subcommands. There is no `hermes voice status`, `hermes voice tts`, or `hermes voice stt`. The only valid subcommands are: `/voice`, `/voice on`, `/voice off`, `/voice tts`, `/voice status`.

- `/voice status` — show current voice mode state and provider config
- `/voice on` / `/voice off` — toggle voice mode
- `/voice tts` — toggle spoken output (not a provider test — controls whether TTS is spoken)
- `hermes logs --follow` — watch for voice-related errors
- `arecord -l` (Linux) / `system_profiler SPAudioDataType` (macOS) — list audio devices

## 3. Pitfalls (symptom → cause → fix)

1. **No audio output / agent responds in text only** — `tts.provider` not set or invalid; provider API key missing. → Set `tts.provider` in config.yaml; verify API key in `$HERMES_HOME/.env`.
2. **Ctrl+B does nothing / microphone not detected** — (a) audio device not connected or not default; (b) PulseAudio bridge not active (WSL2); (c) `voice.record_key` changed. → Check `arecord -l` (Linux) or audio settings (macOS); verify default input device; check config.yaml for custom record_key.
3. **Transcription is inaccurate or misses words** — (a) STT model too small (`base` is fastest but least accurate); (b) background noise; (c) microphone quality. → Switch `stt.local.model` to `small` or `medium`; use a headset or directional mic; reduce background noise.
4. **TTS not responding** — (a) `tts.provider` not set; (b) provider API key missing; (c) provider service down. → Verify config; check API key; run `/voice tts` to confirm TTS is enabled.
5. **Voice bubbles showing as files on Telegram** — ffmpeg not installed (required for audio format conversion). → Install ffmpeg with your system package manager (e.g. `apt install ffmpeg` on Debian/Ubuntu, `brew install ffmpeg` on macOS); restart gateway.
6. **Response latency too high** — (a) STT model too large; (b) TTS provider slow; (c) network latency. → Start with local STT + Edge TTS (no-key baseline); switch one stage at a time; check network.
7. **STT returns garbage text** — (a) wrong language hint; (b) model too small; (c) audio quality poor. → Set `stt.local.language` to ISO-639-1 code; upgrade model; improve audio input.
8. **Voice mode crashes on start** — (a) missing Python dependencies (`pip install hermes-agent[voice]`); (b) audio device busy. → Install voice extras; check for other apps using the microphone.

## 4. Localization workflow

1. `/voice status` — check current provider and mode state.
2. `/voice tts` — confirm TTS output is enabled.
3. Check config.yaml `stt:` and `tts:` blocks — verify provider, model, API key.
4. Check `$HERMES_HOME/.env` — verify provider API keys.
5. Match the failure: no output → pitfall 1; no input → pitfall 2; bad quality → pitfall 3.
6. Apply the fix, restart gateway, and test with `/voice status`.

## 5. Cross-references

- `hermes-configuration-guide` — for $HERMES_HOME resolution and config.yaml structure
- `diagnosing-cli-tui` — for Windows CLI/TUI rendering and encoding issues
- `diagnosing-auth` — for provider API key and token issues

*Facts re-verified 2026-09-21 against upstream source at commit `cedf4a3d78675283fa93e4e6ea2d6212bf414667`: `hermes_cli/voice.py`, `hermes_cli/tts.py`, `hermes_cli/stt.py`; plus the official docs (hermes-agent.nousresearch.com/docs/user-guide/features/voice-mode). Re-verify before reuse.*
