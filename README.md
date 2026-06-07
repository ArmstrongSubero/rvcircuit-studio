
# RV Circuit Studio

Desktop CircuitPython IDE. **Privacy First**. Powerful and **Low Latency**. Native Performance. **A modern replacement for Mu Editor**. 

<img width="1919" height="1029" alt="Screenshot 2026-06-06 224041" src="https://github.com/user-attachments/assets/5a9c1075-dd6b-43a5-bba9-0676dfb06317" />

##


The **first** native dedicated CircuitPython IDE with: 
  - Auto backup to host on every Run
  - Record to CSV data pipeline (record live, autosave, analyze with stats)
  - Open CSV from board into analysis view
  - Native IDE with One click import aware library manager
  - Native IDE with integrated plotter + debugger + library manager in one tool
  - First with readonly filesystem error guidance
  - In-built snippet system

Native, performant IDE that's 100% offline from day one, no accounts, no cloud. Runs from a flash drive. Ideal for environments where there is spotty internet access or data privacy is needed. Your code stays on your machine. No login, no telemetry, no "sync to cloud", no latency or 3rd party servers just you and your board! 

**Protect your privacy!**

No accounts, no telemetry, no cloud. Your code stays on your machine. ALL FREE AND OPEN SOURCE!! 

## Key features



### 🐞 Visual Debugger
Dual purpose Visual Debugger for CircuitPython. Step through code line by line with the executing line highlighted in the editor. Advanced view with dedicated toggle window allows you to set conditional breakpoints, watch variables live, and restart from the top.

<img width="1915" height="589" alt="image" src="https://github.com/user-attachments/assets/a4b1f179-5209-4fd5-bf1c-59f4c1ffd338" />


### 📦 One Click Library Manager
Write your code, and the IDE analyzes your imports and installs all required libraries with a single click. Search and browse the entire Adafruit and Community Bundle.

<img width="939" height="437" alt="image" src="https://github.com/user-attachments/assets/f05972e9-a03e-458d-81b0-63a046c0aca3" />


### 📈 Serial Plotter
Real time streaming plotter that handles every CircuitPython print format: tuples, CSV, space separated, and labelled values. Record sessions with a single click. XY parametric mode for phase plots, Lissajous figures, and spirals.

<img width="1918" height="393" alt="image" src="https://github.com/user-attachments/assets/156918f8-f9ed-452c-bac0-5ee540319dd2" />


### 📊 Data Analysis
Hit Record, capture sensor data, then open the Analysis view. Zoom, pan, per-point hover, clickable legend to show and hide traces, and per channel statistics (min/max/avg/std). Export to CSV or load CSV files from the board for post hoc analysis.

<img width="900" height="620" alt="image" src="https://github.com/user-attachments/assets/3bf9a26c-9753-435c-848d-f555d125916e" />

### 💾 Auto-Backup
Every time you hit Run, your code is saved to the board and backed up to your computer automatically. Board gets corrupted or wiped? Your code is safe.

<img width="1016" height="637" alt="image" src="https://github.com/user-attachments/assets/13edb60e-f7f2-4da6-805a-18467776298e" />



### 📂 Visual File Management
Manage files on your board like a local drive. Create, edit, and organize without leaving the IDE.

<img width="361" height="286" alt="image" src="https://github.com/user-attachments/assets/c93642c6-0f02-4e9f-8757-da6075ca5d77" />


### 🧩 Code Snippets
Library of ready to run examples covering GPIO, debounce, state machines, ADC/DAC, PWM, DSP filters, serial protocols, and more. Each snippet opens as a complete sample in its own tab.

<img width="1343" height="558" alt="image" src="https://github.com/user-attachments/assets/1302d53f-cfb5-4ddc-ba79-8d28675fc1fa" />


### 🔤 Universal Font Scaling
Editor and UI font sizes are independently adjustable. Set everything to 16pt on a large monitor or keep it compact on a laptop.

<img width="533" height="459" alt="image" src="https://github.com/user-attachments/assets/b6fbd0cc-6730-49f0-9c0a-bc1d8165f2d8" />


### 📷 Camera View
Share your microcontroller setup during streaming, remote learning, or collaboration.

<img width="1913" height="94" alt="image" src="https://github.com/user-attachments/assets/52085be0-9be0-45ee-83c4-aa5c6f250f06" />


---

## How It Compares

| Feature | RV Circuit Studio | Mu | Browser based IDEs | VS Code + Tio |
|---|---|---|---|---|
| Real-time streaming plotter | Yes | Broken | Batch only | No |
| Record and analyze data | Yes | No | No | No |
| XY / parametric plots | Yes | No | Yes | No |
| Open CSV in analysis view | Yes | No | No | No |
| Visual line-by-line debugger | Yes | No | No | No |
| One click library manager | Yes | No | No | Manual (CircUp) |
| Auto-backup to host | Yes | No | No | No |
| Offline / native | Yes | Yes | No | Yes |
| Zero-install option | .exe download | pip | Yes | No |
| Auto-start on connect | Yes | No | N/A | No |
| Code snippets library | Yes | Yes | No | Extensions |

---

## What it does

Code editor with syntax highlighting, debugger, data capture and analysis that auto detects CircuitPython boards. Saves code.py to the CIRCUITPY drive and the board reloads automatically, there is a serial REPL with color support. Source level debugger with breakpoints and watch expressions. Real time serial plotter with analysis and library manager for Adafruit bundles. Snippet manager with common CircuitPython patterns.

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
