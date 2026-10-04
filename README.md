<div align="center">

# FarsiSub · فارسی‌ساب

**Persian subtitles from video and audio — entirely on your own computer.**
No cloud, no account, no upload. Your files never leave your machine.

[**⬇ Download for Windows**](https://github.com/kterfan/farsi-sub/releases/latest) ·
[Install](#install) · [Features](#features) · [Build from source](#for-developers)

English · [فارسی](README.fa.md)

![FarsiSub main window](docs/screenshots/main-dark.png)

</div>

---

## What it does

Drop a video (or an audio file), pick a style, press start. FarsiSub transcribes the
Persian speech with [whisper.cpp](https://github.com/ggml-org/whisper.cpp) and writes
a subtitle file that follows Persian typography rules: correct half-spaces (ZWNJ),
Persian digits, proper punctuation. Then you can open the built-in editor, watch the
video, fix what the model got wrong, and save.

Everything runs offline. The only thing that ever touches the internet is the one-time
download of the speech-recognition model, on first launch.

> The interface is in Persian (right-to-left). The project is built for Persian speech;
> other languages are not a goal.

## Install

1. Go to the **[latest release](https://github.com/kterfan/farsi-sub/releases/latest)** and
   download `FarsiSub-<version>-Setup.exe` from the *Assets* list.
2. Run it. No administrator rights are needed; it installs for your user only.
3. On first launch FarsiSub offers to download a speech model (see the table below).
   Pick one and wait for it to finish — after that it works offline.

**Requirements**

- Windows 10 or 11, 64-bit
- An NVIDIA graphics card is recommended: transcription is about 3.4× faster than
  real time on an RTX 3060 with `large-v3`. Without one the program falls back to the
  CPU, which works everywhere but is much slower.
- Disk space for the model (0.6 – 3.1 GB) plus the program itself (the installer is about 360 MB)

**About the SmartScreen warning.** The installer is not code-signed yet, so Windows may
show *"Windows protected your PC"*. Click **More info → Run anyway**. The whole source is
in this repository and the installer is built from it by GitHub Actions
(see [`.github/workflows/build-windows.yml`](.github/workflows/build-windows.yml)).

Updating is the same: run the newer installer over the old one. Your models, settings
and learned corrections are kept.

### Models

| Model | Size | Persian quality | Speed |
|---|---|---|---|
| Large v3 (full) — default | 3.1 GB | best | slow |
| Large v3 (compressed) | 1.1 GB | 1–2 % more errors | medium |
| Turbo (full) | 1.6 GB | below large | very fast |
| Turbo q8 | 0.9 GB | below turbo | very fast |
| Turbo q5 | 0.6 GB | lowest | very fast |

If in doubt, take the default. On a laptop without a good GPU, *Large v3 compressed* is
a sensible middle.

## Features

- **Four subtitle styles** — *Sentence*, *Smart*, *Persian Reels* (one line, a standout
  keyword on its own cue), and *Word by word* — plus a custom style of your own.
  Switching style costs nothing: the audio is transcribed once and every style is just
  a re-render of the same words.
- **Persian text rules** — half-spaces, Persian or Latin digits, optional final period.
- **Output formats** — SRT, VTT, ASS (font, colour, outline, keyword colour), plain
  text, and a **video with the subtitle burned in** (MP4) for Instagram and other places
  that take no separate subtitle file.
- **Built-in editor**
  - the video plays beside the text, with the current line drawn on the picture
  - words the model was unsure about are coloured, and `F3` jumps to the next one
  - split, merge, delete, move a word to the neighbouring line — timings follow the
    words, so nothing drifts
  - drag the edge of a line on the waveform to retime it
  - find and replace across the whole subtitle
  - unlimited undo / redo
  - **teachable dictionary:** correct a word once and it is fixed in every future video
- **Two-model mode** — a second model fills the gaps the first one left silent and
  arbitrates repeated text.
- **Queue** — add many files; they run one after another, with a per-file progress bar,
  and a tray icon with progress and notifications.
- **Light and dark theme**; the window adapts to small screens without hiding any command.
- **Command line** for scripting (see below).

Supported input: `mp4 mkv mov avi webm m4v wmv flv` and `mp3 wav m4a aac flac ogg opus wma`.

![The subtitle editor](docs/screenshots/editor.png)

## Where your data lives

Next to the program, not in `AppData`:

```
data\models\          speech models
data\projects\        words, timings and confidences, for editing later (.fsub)
data\logs\            farsisub.log and crash.log
data\glossary.json    corrections you taught it
```

Uninstalling removes only the logs. Models, projects and your dictionary stay on purpose,
so a reinstall does not cost you a 3 GB download — delete the `data\` folder by hand if you
want them gone.

## How it works

*Transcribe once, render as many times as you like.*

```
video → PyAV (16 kHz WAV) → whisper.cpp → WordStream → normalise → segment → SRT/ASS/…
                                              ↑
                                         the editor
```

whisper.cpp returns every word with its start time and confidence. That list — the
*WordStream* — is saved as `.fsub`. Style, digits, line length and every other rule are
only a rendering of it, and manual edits survive a change of style.

---

## For developers

### Run from source

Python 3.12 or newer (`hazm` requires it).

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
python tools/bootstrap.py --flavour cuda --skip-model     # fetches whisper.cpp into bin/
FarsiSub.bat                                              # the window
```

Command line:

```bash
PYTHONPATH=src python -m farsisub.cli video.mp4 --profile smart
PYTHONPATH=src python -m farsisub.cli video.fsub --profile reels --render-only
PYTHONPATH=src python -m farsisub.cli video.fsub --profile word --format ass --render-only
PYTHONPATH=src python -m farsisub.cli --list-models
```

If a project was shaped in the editor, `--render-only` writes those edited lines; the
style then only decides the line breaks.

### Tests

```bash
python tests/run_tests.py     # no pytest needed
pytest tests/                 # once a venv exists
```

Tests run against a temporary data folder (`FARSISUB_DATA`), never your real `data\`.
The GUI tests need PySide6 and run headless with `QT_QPA_PLATFORM=offscreen`.

### Build the installer

Pushing to `master` or a `claude/**` branch builds the installer on GitHub Actions and
attaches it to the run as an artifact. Pushing a tag such as `v1.8.0` also publishes a
GitHub Release with the installer attached. To build by hand on Windows:

```
.venv\Scripts\python.exe -m PyInstaller installer\farsisub.spec --noconfirm --distpath dist --workpath build\pyi
.venv\Scripts\python.exe installer\verify_build.py dist\FarsiSub
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\farsisub.iss
```

Project status and open work are in [HANDOFF.md](HANDOFF.md) (Persian);
per-version changes are in [CHANGELOG.md](CHANGELOG.md) (Persian).

<details>
<summary>Engineering notes — things that are easy to break (all measured, none guessed)</summary>

- **Flash attention silently disables DTW.** In whisper.cpp, if `flash_attn` is on then
  `dtw_token_timestamps` is zeroed and every `t_dtw` comes back as −1. So `-dtw` always
  travels with `-nfa`.
- **whisper.cpp's built-in VAD collapses the timeline.** With `--vad`, words after three
  seconds of silence came back about 3.5 s early. VAD is off; hallucinations over silence
  are removed using our own energy envelope.
- **whisper-cli reads only flac/mp3/ogg/wav**, so video is first converted to a mono
  16 kHz WAV with PyAV.
- **DTW gives one time per token** (the start). A word's end is closed from the next
  word's start, otherwise cues overlap.
- Token times are in **hundredths of a second**, not milliseconds.
- `-ml` and `-sow` must stay off; segmentation is our job.
- Tokens are sub-words; a word's confidence is the **minimum** over its tokens.
- Control tokens such as `[_TT_350]` contain digits and must be filtered explicitly.
- `%LOCALAPPDATA%` is rewritten for sandboxed processes, which is why data lives beside
  the program: a model downloaded once landed in a container's private folder and the
  app the user ran could not see it.
- Never connect a Qt signal with a lambda: with no receiver object the slot runs on the
  worker thread, and touching a widget from there is an access violation.
- A Qt layout override that raises a Python exception takes the whole process down
  (segfault, no traceback) under PySide 6.11.

</details>

## Author

Design and code by **Erfan Esmailzadeh** (عرفان اسمعیل‌زاده) —
<https://github.com/kterfan/farsi-sub>

Bundled components keep their own licences: whisper.cpp (MIT), Qt / PySide6 (LGPL),
FFmpeg via PyAV (LGPL), the Vazirmatn font (OFL).

## Licence

MIT — see [LICENSE](LICENSE).
