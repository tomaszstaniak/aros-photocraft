# Preserved source changes

| Directory | Applies to | Applied by |
|---|---|---|
| `photocraft/` | storytold/photocraft at the pin in `upstreams.json`; order in `series` | `scripts/pc.py materialize` (`git am`) |
| `crates/` | crates.io crates named in `crates/crates.json` (registry checksum and patched-tree hash recorded) | `scripts/pc.py build` |
| `libc-aros/` | rust-aros `std-groundwork/libc-aros` at the commit in `scripts/pcconfig.py` | `scripts/pc.py build` |
| `aros-pthread/` | deadwood2/AROS `compiler/pthread` at the commit in `scripts/pcconfig.py` | `scripts/pc.py build` |

Every patch carries its problem, rationale, scope, upstream status,
verification and removal condition in its header (for `photocraft/`, the commit
message). Patches 0001 and 0002 of `photocraft/` are imports of the AROS ports
recipe, unchanged; 0011 and 0012 are diagnostics that log nothing at the
default level. See [the patch workflow](../docs/patching.md).
