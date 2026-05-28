# RV Circuit Studio

Desktop CircuitPython IDE. Replaces Mu.

Offline, no accounts, no cloud. Runs from a flash drive. Ideal for environments where there is spotty internet access or data privacy is needed. Your code stays on your machine. No login, no telemetry, no "sync to cloud", no latency or 3rd party servers just you and your board! 

WE WILL NEVER GATHER OR COLLECT ANY OF YOUR DATA! ALL OPEN SOURCE!! PRIVACY FIRST!

## What it does

Code editor with syntax highlighting and code folding that auto detects CircuitPython boards. Saves code.py to the CIRCUITPY drive and the board reloads automatically, there is a serial REPL with color support. Source-level debugger with breakpoints and watch expressions. Real-time serial plotter with library manager for Adafruit bundles. Snippet manager with common CircuitPython patterns.

## Install

### Windows

Download the standalone portable exe from [Releases](https://github.com/ArmstrongSubero/rvcircuit-studio/releases) No install or admin priviledges required!

Or via pip:

```
pip install rvcircuit-studio
rvcircuit-studio
```

### macOS

```
pip install rvcircuit-studio
```

If `rvcircuit-studio` isn't found after install, add the bin directory to your PATH:

```
echo 'export PATH="$HOME/.pyenv/versions/3.12.3/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
rvcircuit-studio
```

### Linux

```
pip install rvcircuit-studio
rvcircuit-studio
```

## Requirements

Python 3.10+. Tested with Pico and Pico 2. Recommend Pico 2. Baochip and Dabao Board support coming soon. 
However should work with any CircuitPython board. 

## License

Apache 2.0

## Contributing

Bug reports are welcome open an issue if it's a big bug. Unfortunately due to the prevalance of AI pull requests I won't be accepting them sorry, but reach out to me via email armstrongsubero@gmail.com, I'm very open to suggestions and improvement. 

## AI Policy

While bug reports welcome and you can open an issue. Please no AI generated content in issues or discussions.


## Author

Armstrong Subero @ [rvembedded.com](https://rvembedded.com)
