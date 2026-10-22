# PhotoCraft 0.7.0 for AROS — preview 2 (rebuild 2)

Experimental build for x86_64 AROS ABIv11.

The same program as preview 2, rebuilt so that the programs no longer contain
file paths of the computer they were built on.

## Changes since preview 1

- Files chosen in the Open and Save As requesters outside the program's own drawer now
  open and save where they were chosen.
- Home, End and the function keys no longer type stray characters into text fields.
- The editor runs on a shared AROS integration for egui programs, also used by the
  WordCraft port.
- Amiga+C, Amiga+X and Amiga+V copy, cut and paste, like Ctrl+C, Ctrl+X and Ctrl+V.
- Edges of translucent pictures and shadows no longer show a thin seam line.

## Installation

Unpack the archive into a drawer and double-click the PhotoCraft icon. From a Shell, run
`Stack 4000000` before starting `PhotoCraft`.

## Known limitations

Use file names without accented letters. System TrueType fonts appear in the font list but
render with a built-in font. Image clipboard exchange and opening files dropped onto the
window are unavailable. Large documents can be slow. Letters typed with a keymap for another
8-bit charset (such as the Polish one) come out as the wrong characters.

If replacing a saved file fails after the old file has been removed, the new contents remain
in a temporary file. The error message gives its name.
