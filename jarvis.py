#!/usr/bin/env python3
"""
Jarvis — an always-listening voice coding assistant for macOS.

Pipeline:
    mic  ->  openWakeWord ("hey jarvis")  ->  Whisper (STT)
         ->  Ollama (qwen2.5-coder)        ->  action executor
                                            \\->  `say` (TTS)

Built to launch IntelliJ IDEA / Android Studio, run shell commands,
write code files, and chat back via macOS `say`.

Run:  python jarvis.py
Stop: Ctrl-C
"""

from __future__ import annotations

import json
import os
import queue
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

SAMPLE_RATE = 16_000          # Hz — required by both openWakeWord and Whisper
CHUNK_SAMPLES = 1280          # 80ms frames — openWakeWord's expected size
WAKE_WORD = "hey_jarvis"      # pre-trained model name in openWakeWord
WAKE_THRESHOLD = 0.5          # 0.5 is the openWakeWord recommended default

# Recording-after-wake settings
MAX_COMMAND_SECONDS = 15      # hard cap on a single utterance
SILENCE_HANG_SECONDS = 1.2    # stop after this much trailing silence
SILENCE_RMS_THRESHOLD = 350   # int16 RMS — empirically quiet-room floor

# Models
WHISPER_MODEL_SIZE = "base.en"     # good speed/accuracy balance on Apple Silicon
OLLAMA_MODEL = "qwen2.5-coder:7b"  # set by install.sh; override with $JARVIS_MODEL

# Voice
TTS_VOICE = "Samantha"        # any installed macOS voice; `say -v ?` to list

# Where Jarvis writes new project scaffolds, generated files, etc.
WORKSPACE = Path(os.environ.get("JARVIS_WORKSPACE",
                                Path.home() / "JarvisWorkspace")).expanduser()
WORKSPACE.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------
# TTS  (macOS `say`)
# ----------------------------------------------------------------------

_say_proc: subprocess.Popen | None = None


def speak(text: str, blocking: bool = False) -> None:
    """Speak text through macOS `say`. Cancels any in-flight speech."""
    global _say_proc
    if not text:
        return
    if _say_proc and _say_proc.poll() is None:
        _say_proc.terminate()
    print(f"[jarvis] {text}")
    _say_proc = subprocess.Popen(["say", "-v", TTS_VOICE, text])
    if blocking:
        _say_proc.wait()


# ----------------------------------------------------------------------
# Wake word + STT model loading (lazy — these are slow imports)
# ----------------------------------------------------------------------

def load_models():
    print("[jarvis] loading wake-word model...")
    from openwakeword.model import Model as WakeModel
    from openwakeword import utils as oww_utils

    # Download tflite runtime + model files on first run
    try:
        oww_utils.download_models([WAKE_WORD])
    except Exception:
        # download_models is a no-op if already cached; some versions raise
        pass

    wake_model = WakeModel(
        wakeword_models=[WAKE_WORD],
        inference_framework="tflite",
    )

    print(f"[jarvis] loading Whisper ({WHISPER_MODEL_SIZE})...")
    from faster_whisper import WhisperModel
    # int8 on CPU is fast enough on M-series and uses ~150MB RAM
    whisper_model = WhisperModel(
        WHISPER_MODEL_SIZE, device="cpu", compute_type="int8"
    )

    return wake_model, whisper_model


# ----------------------------------------------------------------------
# Audio capture
# ----------------------------------------------------------------------

class AudioStream:
    """Continuously fills a queue with int16 mono frames at SAMPLE_RATE."""

    def __init__(self) -> None:
        self.q: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: sd.InputStream | None = None

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        if status:
            # Overflow / underflow — non-fatal, just log
            print(f"[audio] {status}", file=sys.stderr)
        # indata is float32 in [-1, 1]; convert to int16 PCM
        pcm = (indata[:, 0] * 32767).astype(np.int16)
        self.q.put(pcm.copy())

    def __enter__(self) -> "AudioStream":
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=CHUNK_SAMPLES,
            callback=self._callback,
        )
        self._stream.start()
        return self

    def __exit__(self, *exc) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()


def rms(frame: np.ndarray) -> float:
    """Root-mean-square energy of an int16 frame."""
    if frame.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))


def record_command(stream: AudioStream) -> np.ndarray:
    """Record from `stream.q` until we hit trailing silence or the cap."""
    speak("Yes?")
    frames: list[np.ndarray] = []
    silence_chunks_needed = int(SILENCE_HANG_SECONDS * SAMPLE_RATE / CHUNK_SAMPLES)
    max_chunks = int(MAX_COMMAND_SECONDS * SAMPLE_RATE / CHUNK_SAMPLES)

    silent_run = 0
    spoke = False
    for _ in range(max_chunks):
        chunk = stream.q.get()
        frames.append(chunk)
        loud = rms(chunk) > SILENCE_RMS_THRESHOLD
        if loud:
            spoke = True
            silent_run = 0
        else:
            silent_run += 1
        if spoke and silent_run >= silence_chunks_needed:
            break

    if not frames:
        return np.array([], dtype=np.int16)
    return np.concatenate(frames)


def transcribe(whisper_model, audio_int16: np.ndarray) -> str:
    """Whisper expects float32 in [-1, 1]."""
    if audio_int16.size == 0:
        return ""
    audio_f32 = audio_int16.astype(np.float32) / 32768.0
    segments, _info = whisper_model.transcribe(
        audio_f32, language="en", vad_filter=True
    )
    return " ".join(seg.text.strip() for seg in segments).strip()


# ----------------------------------------------------------------------
# LLM brain (Ollama)
# ----------------------------------------------------------------------

SYSTEM_PROMPT = f"""You are Jarvis, a voice-controlled coding assistant running on the user's Mac.
The user codes in IntelliJ IDEA and Android Studio. Their workspace folder is {WORKSPACE}.

You receive transcribed voice commands. Reply with ONLY a JSON object — no prose, no
markdown fences. The schema:

{{
  "speak": "<one short sentence to say back, max ~15 words>",
  "actions": [
    // zero or more, executed in order:
    {{"type": "open_app",     "name": "IntelliJ IDEA" | "Android Studio" | "<other Mac app>"}},
    {{"type": "open_path",    "app":  "IntelliJ IDEA" | "Android Studio", "path": "<absolute path>"}},
    {{"type": "shell",        "cmd":  "<shell command>"}},
    {{"type": "write_file",   "path": "<absolute path>", "content": "<file contents>"}},
    {{"type": "mkdir",        "path": "<absolute path>"}}
  ]
}}

Rules:
- "speak" MUST be present and short — it will be read out by macOS `say`.
- Use absolute paths under {WORKSPACE} when creating new files/projects unless the user
  names a different location.
- Prefer `open_path` with an IDE over plain `open_app` whenever the user mentions a project.
- For Android Studio, the app name is exactly "Android Studio".
- For IntelliJ, the app name is exactly "IntelliJ IDEA" (or "IntelliJ IDEA Ultimate" if that's
  what's installed — try the plain name first).
- Never run destructive shell commands (rm -rf, dd, mkfs, etc.). If the user asks, refuse in
  "speak" and return an empty actions list.
- If the request is conversational (not a command), just answer in "speak" with empty actions.

Examples:

User: "Open Android Studio"
{{"speak": "Opening Android Studio.", "actions": [{{"type": "open_app", "name": "Android Studio"}}]}}

User: "Make a new Python file called fizzbuzz that prints fizzbuzz from 1 to 100"
{{"speak": "Writing fizzbuzz dot py.", "actions": [
  {{"type": "write_file", "path": "{WORKSPACE}/fizzbuzz.py",
    "content": "for i in range(1, 101):\\n    if i % 15 == 0: print('FizzBuzz')\\n    elif i % 3 == 0: print('Fizz')\\n    elif i % 5 == 0: print('Buzz')\\n    else: print(i)\\n"}},
  {{"type": "open_path", "app": "IntelliJ IDEA", "path": "{WORKSPACE}/fizzbuzz.py"}}
]}}

User: "What's two plus two"
{{"speak": "Four.", "actions": []}}
"""


def call_ollama(user_text: str) -> dict:
    """Returns the parsed action dict, or a fallback if parsing fails."""
    import ollama

    model = os.environ.get("JARVIS_MODEL", OLLAMA_MODEL)
    try:
        resp = ollama.chat(
            model=model,
            format="json",  # forces valid JSON output
            options={"temperature": 0.2},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
        )
        raw = resp["message"]["content"]
        return json.loads(raw)
    except Exception as e:
        print(f"[jarvis] ollama error: {e}", file=sys.stderr)
        return {"speak": "Sorry, I had trouble thinking about that.", "actions": []}


# ----------------------------------------------------------------------
# Action executor
# ----------------------------------------------------------------------

DANGEROUS_PATTERNS = (
    "rm -rf /", "rm -rf ~", "rm -rf $HOME",
    "mkfs", "dd if=", ":(){ :|:& };:",
    "sudo rm", "shutdown", "halt",
)


def looks_dangerous(cmd: str) -> bool:
    low = cmd.lower().strip()
    return any(p in low for p in DANGEROUS_PATTERNS)


def execute_action(action: dict) -> None:
    t = action.get("type")
    try:
        if t == "open_app":
            name = action["name"]
            subprocess.Popen(["open", "-a", name])
            print(f"[jarvis] opened app: {name}")

        elif t == "open_path":
            app = action.get("app") or "IntelliJ IDEA"
            path = os.path.expanduser(action["path"])
            subprocess.Popen(["open", "-a", app, path])
            print(f"[jarvis] opened in {app}: {path}")

        elif t == "shell":
            cmd = action["cmd"]
            if looks_dangerous(cmd):
                speak("That command looks dangerous, skipping.")
                return
            print(f"[jarvis] $ {cmd}")
            subprocess.Popen(cmd, shell=True)

        elif t == "write_file":
            path = Path(os.path.expanduser(action["path"]))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(action.get("content", ""))
            print(f"[jarvis] wrote {path}")

        elif t == "mkdir":
            path = Path(os.path.expanduser(action["path"]))
            path.mkdir(parents=True, exist_ok=True)
            print(f"[jarvis] mkdir {path}")

        else:
            print(f"[jarvis] unknown action type: {t!r}")

    except Exception as e:
        print(f"[jarvis] action failed ({t}): {e}", file=sys.stderr)


# ----------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------

def main() -> None:
    # Graceful Ctrl-C
    def _bye(*_):
        print("\n[jarvis] shutting down")
        sys.exit(0)
    signal.signal(signal.SIGINT, _bye)

    wake_model, whisper_model = load_models()

    speak("Jarvis online.", blocking=True)
    print("[jarvis] listening for 'Hey Jarvis' (Ctrl-C to quit)")

    with AudioStream() as stream:
        while True:
            chunk = stream.q.get()
            scores = wake_model.predict(chunk)
            score = scores.get(WAKE_WORD, 0.0)

            if score >= WAKE_THRESHOLD:
                print(f"[jarvis] wake word ({score:.2f})")
                # Drain a bit of the queue so we don't transcribe the wake word itself
                while not stream.q.empty():
                    try:
                        stream.q.get_nowait()
                    except queue.Empty:
                        break

                audio = record_command(stream)
                text = transcribe(whisper_model, audio)
                if not text:
                    speak("I didn't catch that.")
                    continue

                print(f"[jarvis] heard: {text!r}")
                action = call_ollama(text)

                speak(action.get("speak", ""))
                for a in action.get("actions", []) or []:
                    execute_action(a)

                # Brief pause so TTS doesn't trigger the wake word on itself
                time.sleep(0.3)
                wake_model.reset()


if __name__ == "__main__":
    main()
