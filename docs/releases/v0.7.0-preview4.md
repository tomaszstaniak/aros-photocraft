# PhotoCraft 0.7.0 for AROS — preview 4

For AROS x86_64 ABIv11. Experimental and not optimised; the window is drawn by the CPU.

## Changes since preview 2

- Fixed a possible crash after closing PhotoCraft when it was started from Workbench. A background thread could make the C library release the starting drawer's lock that Workbench releases again on exit; the program now keeps that lock for itself.
- The programs are built with whole-program optimisation and stripped of unneeded symbols, so they are smaller.
- PhotoCraft is available as `photocraft` in the apkg catalogue. Its program is larger than 64 MiB, so it needs apkg 0.6.0 or later.

Preview 3 was withdrawn: it exited at startup with "cannot preserve the startup directory". This build fixes that.

## Installation

Unpack the archive into any drawer and double-click the PhotoCraft icon. From a Shell, run `Stack 4000000` before starting `PhotoCraft`. With apkg 0.6.0 or later: `apkg install photocraft`.

## Known limitations

Use file names without accented letters. System TrueType fonts appear in the font list but render with a built-in font. Image clipboard exchange and opening files dropped onto the window are unavailable. Large documents can be slow. Letters typed with a keymap for another 8-bit charset (such as the Polish one) come out as the wrong characters.

If replacing a saved file fails after the old file has been removed, the new contents remain in a temporary file. The error message gives its name.
