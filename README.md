# RV Circuit Studio

A native desktop CircuitPython IDE. Built with PySide6.

**Mu is gone. This is what replaces it.**

RV Circuit Studio is a fully offline, distributable desktop IDE for CircuitPython — the kind of tool educators have been asking for since Mu was sunsetted. No browser required. No internet required. Copy it to a flash drive and hand it to a classroom.

## Features

- **Code editor** with syntax highlighting, line numbers, code folding (qutepart)
- **Auto-detect CircuitPython boards** — plug in a board, it shows up
- **Save to board** — one click saves `code.py` to the CIRCUITPY drive and auto-reloads
- **Serial REPL** with ANSI color support, Ctrl+C interrupt, Ctrl+D soft reboot
- **Source-level debugger** — step, continue, breakpoints, watch expressions, frame history
- **Serial plotter** — real-time graphing of serial data (pyqtgraph)
- **Library manager** — browse and install CircuitPython libraries from the Adafruit bundle
- **File explorer** with project workspace management
- **Snippet manager** — insert common CircuitPython patterns
- **Find & replace** across files
- **Dark theme** — GitHub-style palette, easy on the eyes

## Install

```
pip install rvcircuit-studio
```

Then run:

```
rvcircuit-studio
```

### Requirements

- Python 3.10+
- A CircuitPython board (tested with RP2040, ESP32-S3, nRF52840)

## Screenshots

*Coming soon*

## For Educators

RV Circuit Studio is designed for classroom deployment:

- **Fully offline** — no accounts, no cloud, no telemetry
- **Single command install** — `pip install rvcircuit-studio`
- **Cross-platform** — Windows, macOS, Linux
- **Distributable** — bundle with PyInstaller for a standalone `.exe`

## Development

```bash
git clone https://github.com/ArmstrongSubero/rvcircuit-studio.git
cd rvcircuit-studio
pip install -e .
rvcircuit-studio
```

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Author

Armstrong Subero — [rvembedded.com](https://rvembedded.com)
