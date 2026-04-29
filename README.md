# Jarvis

A voice-controlled coding assistant for macOS. Always listening, fully local, free.

Say *"Hey Jarvis, make a Python file called fizzbuzz that prints 1 to 100"* and watch your Mac open IntelliJ with the file already written.

> **Status:** working prototype. Single-shot commands work well; no agent loop or memory yet — see [Roadmap](#roadmap).

## Demo

*Add a screen recording or GIF here.* A 15-second clip of saying "Hey Jarvis, open Android Studio" goes a long way.

## How it works

```
   mic
    │
    ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  openWakeWord   │ →  │     Whisper     │ →  │     Ollama      │
│  ("hey jarvis") │    │     (STT)       │    │ qwen2.5-coder   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                       │
                       ┌───────────────────────────────┤
                       ▼                               ▼
                ┌──────────────┐              ┌──────────────┐
                │  macOS say   │              │  Action exec │
                │    (TTS)     │              │ open / write │
                └──────────────┘              └──────────────┘
```

Everything runs on your Mac. No API keys, no subscriptions, no data leaves your machine.

## Features

- Wake word detection — say "Hey Jarvis" anytime
- Local speech-to-text via Whisper
- Local code generation via Qwen2.5-Coder (7B) running in Ollama
- Voice replies through macOS `say`
- Action types Jarvis can take:
  - `open_app` — launch IntelliJ IDEA, Android Studio, or any Mac app
  - `open_path` — open a folder/file directly in your IDE
  - `write_file` — create/overwrite a file with full contents
  - `mkdir` — create a directory
  - `shell` — run any shell command (with a guard against destructive ones)
- Built-in safety check — blocks `rm -rf /`, `mkfs`, fork bombs, etc.

## Quick start

Requires macOS (tested on Apple Silicon) and ~6 GB free disk space.

```bash
git clone https://github.com/<your-username>/jarvis.git
cd jarvis
chmod +x install.sh start_jarvis.command
./install.sh
```

The installer pulls Homebrew (if missing), `ffmpeg`, Ollama, the `qwen2.5-coder:7b` model, and sets up a Python 3.12 virtualenv. First run takes 10–20 minutes, mostly the model download.

Then launch:

```bash
./start_jarvis.command
```

Grant microphone permission when prompted (System Settings → Privacy & Security → Microphone). When you hear "Jarvis online," start talking.

## Example commands

```
"Hey Jarvis, open Android Studio"
"Hey Jarvis, make a Python file called scraper that downloads example dot com"
"Hey Jarvis, create a folder called todo-app with index.html, style.css, and script.js for a basic todo list, then open it in IntelliJ"
"Hey Jarvis, what's two plus two"
```

Generated files land in `~/JarvisWorkspace/` by default. Override with the `JARVIS_WORKSPACE` env var.

## Customizing

| What             | Where                                    |
|------------------|------------------------------------------|
| Voice            | `TTS_VOICE` in `jarvis.py` (`say -v ?` to list options) |
| Wake word        | `WAKE_WORD` in `jarvis.py` — supports `hey_jarvis`, `alexa`, `hey_mycroft` out of the box |
| LLM model        | `JARVIS_MODEL` env var or `OLLAMA_MODEL` in `jarvis.py` |
| Wake sensitivity | `WAKE_THRESHOLD` in `jarvis.py` (default 0.5) |
| Action behavior  | `SYSTEM_PROMPT` in `jarvis.py` — add new examples here |

To add a new action type (e.g., browser control), extend `execute_action()` in `jarvis.py` and document it in the system prompt.

## Roadmap

- [ ] **Iteration loop** — let Jarvis read shell command output and react to errors
- [ ] **Conversation memory** — short-term context so "add X to that project" works
- [ ] **Streaming TTS** — start speaking before the model finishes generating
- [ ] **Custom wake word** — train an "OK Jarvis" model since openWakeWord's default is "Hey Jarvis"
- [ ] **Cloud brain option** — drop-in Claude / OpenAI backend for harder tasks
- [ ] **Linux support** — replace `say` and `open` with Linux equivalents

## Troubleshooting

**Wake word never fires** — check microphone permission for Terminal in System Settings → Privacy & Security → Microphone.

**Slow responses** — try a smaller model: `ollama pull qwen2.5-coder:1.5b`, then `JARVIS_MODEL=qwen2.5-coder:1.5b ./start_jarvis.command`.

**Jarvis triggers on its own voice** — bump the `time.sleep(0.3)` after action execution in `jarvis.py` to ~1.5s.

**`brew: command not found`** — Apple Silicon installs Homebrew at `/opt/homebrew` but doesn't add it to PATH. Run: `eval "$(/opt/homebrew/bin/brew shellenv)"` and add the same line to `~/.zshrc`.

**numpy/openWakeWord build errors** — your Python is too new (3.13/3.14). Force 3.12: `brew install python@3.12 && rm -rf .venv && $(brew --prefix python@3.12)/bin/python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`.

## Stack

- [openWakeWord](https://github.com/dscripka/openWakeWord) — wake word detection
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — speech-to-text
- [Ollama](https://ollama.com) + [Qwen2.5-Coder](https://qwenlm.github.io/) — code generation
- [sounddevice](https://python-sounddevice.readthedocs.io/) — audio capture
- macOS `say` — text-to-speech

## License

MIT — see [LICENSE](LICENSE).
