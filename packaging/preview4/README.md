# PhotoCraft 0.7.0 for AROS — ABIv11 preview 4

PhotoCraft is an image editor with layers, masks, adjustment layers, brushes, type and vector tools, and PSD support. The archive includes two programs for x86_64 AROS:

- **PhotoCraft**: the editor.
- **photocraft-cli**: a command-line tool. It converts and inspects images, runs editing commands, and serves an MCP automation interface over standard input and output.

This is an experimental preview for AROS x86_64 ABIv11.

## Requirements

- AROS x86_64 ABIv11.
- About 160 MB of disk space. The editor loads into memory in full; allow additional RAM for documents and editing.
- No extra libraries. Both programs use only libraries that come with AROS, and nothing in the system is replaced or added.

## Installation

Unpack the archive into any drawer, for example `Work:`:

    UnZip PhotoCraft-0.7.0-preview4.x86_64-aros-v11.zip -d Work:

This creates the drawer `Work:PhotoCraft` and its icon. To remove PhotoCraft, delete that drawer and its icon. PhotoCraft keeps its settings, presets and crash-recovery files in `PhotoCraftData` inside its own drawer; set the variable `PHOTOCRAFT_CONFIG_DIR` to keep them elsewhere.

## Starting the editor

Double-click the **PhotoCraft** icon. The icon gives the program the stack it needs (4,000,000 bytes).

From a Shell, set the stack first:

    Stack 4000000
    Work:PhotoCraft/PhotoCraft
    Work:PhotoCraft/PhotoCraft "Work:Pictures/photo one.png"

Files named on the command line are opened at start.

## Command line

`photocraft-cli` sets up the stack it needs itself; no `Stack` command is required:

    photocraft-cli info picture.psd
    photocraft-cli convert picture.psd picture.png
    photocraft-cli commands --filter blur
    photocraft-cli --help

`info` prints the document's size, mode and layers as JSON. `convert` writes the format given by the output name's extension (PNG, JPEG, TIFF, WebP, PSD, PhotoCraft's own `.pcraft` and others).

## MCP automation

`photocraft-cli mcp` runs an MCP server on standard input and output, for an MCP client (a script or another program) that starts it as a child process:

    photocraft-cli mcp --automation-read-root "Work:Pictures" --automation-write-root "Work:Out"

- The server works on **its own documents**: it opens, edits and saves files itself. It does not see or control the document open in the PhotoCraft window.
- It reads only below the read root and writes only below the write root. Paths that leave a root or pass through a link are refused. This is a check made before each file operation, not a full sandbox: grant only drawers you trust, and do not let other programs change links inside them while the server runs.
- One message may be at most 1 MiB (1,048,576 bytes); a longer one ends the session.
- **The client must close the server's standard input when it is done, and also after an error.** When a session ends for another reason (a failed handshake, an overlong message), the server says so on its error output and waits for standard input to close before it exits.
- Messages travel through AROS pipes one byte at a time, so large requests are slow: keep requests small; let the server read and write image files itself instead of sending image data in messages.

The TCP options (`mcp --bridge`, `serve --port`) are not part of this preview.

## Saving files

PhotoCraft writes a new file next to the old one and then puts it in its place. On AROS that last step deletes the old file and renames the new one. If renaming fails at that point, the new contents stay in the temporary file next to it (a name starting with a dot and ending in `.pcsave.tmp`), and the error message names it. A file with its delete protection set (`Protect file -d`) cannot be replaced: saving fails and the file is left as it was.

## Known limitations

- **File names:** use names made of letters without accents, digits, spaces and punctuation. A file whose name contains accented letters (such as `café.png` made by another program) cannot be opened; both programs refuse such a name on the command line. A name with accented letters typed into PhotoCraft or sent to the MCP server is written in UTF-8, so other AROS programs show those letters as two odd characters each.
- **Fonts:** fonts in `FONTS:TrueType` appear in the Type tool's font list, but text set in them is drawn with PhotoCraft's built-in font. Use the built-in Inter and JetBrains Mono for now.
- Text can be copied to and pasted from the clipboard, including accented letters; images cannot.
- Files dropped on the window are not opened.
- The canvas and interface are drawn by the CPU; large documents are slow.
- HEIF images are not supported.

## Licenses

PhotoCraft is licensed under the MIT license or the Apache License 2.0, at your option. The `Licenses` drawer holds these licenses, the notices for the fonts, icons and word list built into the programs, the notices for the AROS and Rust libraries linked into them, and the licenses of every Rust package they contain. `SOURCE.txt` names the exact sources; the source archive of this release holds the recipe and every change made for AROS.
