# PhotoCraft 0.7.0 for AROS — preview 5

For AROS x86_64 ABIv11. Experimental and not optimised; the window is drawn by the CPU.

## Changes since preview 4

- A picture opened from a Shell with a name typed at the root of a volume (`PhotoCraft photo.png` in `RAM:`) now opens, and names starting with `/` (the parent drawer) are understood. Before, such a name was turned into one that does not exist.
- If PhotoCraft cannot lock the drawer it was started from, it now stops at once with return code 20 instead of starting with only a warning. This is a safeguard; no case is known where it happens.

The crash after closing that the preview 4 notes describe as fixed was found in PdfCraft. In PhotoCraft no way for it to happen is known, so that change is a safeguard too.

## Installation

Unpack the archive into any drawer and double-click the PhotoCraft icon. From a Shell, run `Stack 4000000` before starting `PhotoCraft`. With apkg 0.6.0 or later: `apkg install photocraft`.

## Known limitations

Use file names without accented letters. System TrueType fonts appear in the font list but render with a built-in font. Image clipboard exchange and opening files dropped onto the window are unavailable. Large documents can be slow. Letters typed with a keymap for another 8-bit charset (such as the Polish one) come out as the wrong characters.

If replacing a saved file fails after the old file has been removed, the new contents remain in a temporary file. The error message gives its name.
