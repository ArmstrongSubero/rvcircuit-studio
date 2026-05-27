# Third-Party Licenses

Rovari Studio includes or depends on the following third-party components.

## Rovari Studio & Rovari SDK
- **License:** Apache License 2.0
- **Copyright:** 2025 Rovari — rv-embedded.com
- **Files:** All files except those listed below
- **Full text:** ../LICENSE

## WCH CH32V HAL / Peripheral Library
- **License:** Apache License 2.0
- **Copyright:** 2021 Nanjing Qinheng Microelectronics Co., Ltd.
- **Files:** `targets/CH32V307/vendor/`
- **Source:** https://github.com/openwch
- **Full text:** WCH-HAL-Apache-2.0.txt

## OpenOCD (WCH fork)
- **License:** GNU General Public License v2.0
- **Copyright:** Free Software Foundation / contributors
- **Files:** Bundled `openocd` binary (if included)
- **Source:** https://github.com/newbrain/riscv-openocd-wch
- **Full text:** OpenOCD-GPL-2.0.txt

## RISC-V GNU Toolchain (GCC, Binutils, Newlib)
- **License:** GNU General Public License v3.0 with Runtime Library Exception
- **Copyright:** Free Software Foundation / contributors
- **Note:** The Runtime Library Exception allows linking GCC runtime
  libraries (libgcc, libstdc++, newlib) into user firmware without
  requiring the firmware to be GPL-licensed.
- **Files:** External toolchain, not bundled
- **Full text:** https://www.gnu.org/licenses/gpl-3.0.txt

## Python Dependencies
Rovari Studio's Python dependencies (PyQt5, qutepart, pyserial, etc.)
are installed separately and carry their own licenses. See each
package's documentation for details.
