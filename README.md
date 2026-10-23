# PhotoCraft for AROS

An AROS port of [PhotoCraft](https://github.com/storytold/photocraft), an image editor. It supports layers, masks, painting and PSD and PNG files.

## Download and run

[Download v0.7.0-preview4](https://github.com/tomaszstaniak/aros-photocraft/releases/tag/v0.7.0-preview4) for **AROS x86_64 ABIv11**, or find `photocraft` in the apkg catalogue. The download includes PhotoCraft and `photocraft-cli`.

These builds are experimental and not optimised. They use CPU rendering and can be slow, especially in large windows.

Unpack the archive into a drawer and double-click the PhotoCraft icon. From a Shell, run `Stack 4000000` before starting `PhotoCraft`.

## Known limitations

Use file names without accented letters. System TrueType fonts appear in the font list but render with a built-in font. Image clipboard exchange and file drops are unavailable. Large documents can be slow. Non-Latin-1 keyboard layouts can produce incorrect characters.

If replacing a saved file fails after the old file has been removed, the new contents remain in a temporary file. The error message gives its name.

## Build from source

This repository contains source revisions, AROS patches and build scripts. See [Building](docs/development.md), [Patch workflow](docs/patching.md) and [Source revisions](upstreams.json). The window and renderer use [egui-aros](https://github.com/tomaszstaniak/egui-aros), pinned in `upstreams.json`.

The repository stores build recipes rather than a full upstream source tree. Licenses and author notices are included in the source and application archives.

This port builds on the original [AROS PhotoCraft port](https://github.com/aros-development-team/ports/tree/master/graphics/photocraft) and Intuition shell by Nick Andrews (Kalamatee).
