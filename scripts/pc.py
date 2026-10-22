#!/usr/bin/env python3
"""PhotoCraft AROS port: fetch pinned sources, rebuild the work copy from the
patch series, prepare patched crates, and build for x86_64 ABIv11.

Commands (run `pc.py COMMAND --help`):
  config       show where each setting comes from
  fetch        clone/verify the pinned upstream checkouts (upstream/<id>)
  materialize  create work/photocraft from the pin and patches/photocraft/series
  export       write the work copy's commits back to patches/photocraft
  verify       rebuild the series in a new temporary directory, compare trees
  crates       prepare the patched crates.io crates (checksummed, patched)
  build        build the AROS binaries from the work copy into a fresh output

Nothing here edits upstream/<id>, a shared toolchain, an SDK or the Cargo
registry. Existing work copies are never reset or recreated.
"""
import argparse
import datetime
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pcconfig  # noqa: E402

REPO = pcconfig.REPO
UPSTREAMS = REPO / "upstreams.json"
SERIES_DIR = REPO / "patches" / "photocraft"
CRATES_DIR = REPO / "patches" / "crates"
LIBC_DIR = REPO / "patches" / "libc-aros"
PTHREAD_DIR = REPO / "patches" / "aros-pthread"
# The SDK's libpthread.a objects are reproduced exactly by these flags (checked below).
PTHREAD_CFLAGS = ["-O2", "-mcmodel=large", "-fno-omit-frame-pointer"]
# The members patches/aros-pthread changes; only these are linked from the private build.
PTHREAD_PATCHED = ("pthread", "pthread_create")
WORK = REPO / "work" / "photocraft"
# Test tools built with the same profile: name -> (manifest directory, binary).
TOOLS = {"mcp-check": ("tests/mcp-client", "photocraft-mcp-check")}
# Package -> the AROS binary it produces.
PACKAGES = {"photocraft-aros": "PhotoCraft", "photocraft-cli": "photocraft-cli"}
COMMITTER = ["-c", "user.name=PhotoCraft AROS port", "-c", "user.email=photocraft-aros@invalid"]


class Failure(Exception):
    pass


def run(cmd, cwd=None, env=None, capture=True, check=True, input=None):
    result = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, input=input,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    if check and result.returncode != 0:
        err = (result.stderr or b"").decode(errors="replace").strip()
        raise Failure(f"command failed ({result.returncode}): {' '.join(map(str, cmd))}\n{err}")
    return result


def git(repo, *args, **kw):
    return run(["git", "-C", repo, *args], **kw).stdout.decode().strip()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_hash(root):
    """Sorted relative name, NUL, mode bit for execute, content SHA-256 of every regular file."""
    root = Path(root)
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts):
        rel = path.relative_to(root).as_posix().encode()
        executable = b"x" if os.access(path, os.X_OK) else b"-"
        digest.update(rel + b"\0" + executable + bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def upstreams():
    return json.loads(UPSTREAMS.read_text())["repositories"]


def series(series_dir=None):
    series_dir = Path(series_dir or SERIES_DIR)
    names = [line.strip() for line in (series_dir / "series").read_text().splitlines()
             if line.strip() and not line.startswith("#")]
    for name in names:
        if not (series_dir / name).is_file():
            raise Failure(f"series names a missing patch: {name}")
    return names


def check_upstream(rid, spec):
    path = REPO / "upstream" / rid
    head = git(path, "rev-parse", "HEAD")
    if head != spec["commit"]:
        raise Failure(f"upstream/{rid} is at {head}, the pin is {spec['commit']}")
    if git(path, "status", "--porcelain", "--untracked-files=all"):
        raise Failure(f"upstream/{rid} has local changes; it must stay a clean checkout")
    return path


# ---------------------------------------------------------------- commands

def cmd_config(args):
    print(pcconfig.describe())


def cmd_fetch(args):
    for rid, spec in upstreams().items():
        if rid == "egui-aros":
            # Built from the configured checkout at the pinned commit (see egui_aros_vendor).
            continue
        path = REPO / "upstream" / rid
        if not path.exists():
            path.parent.mkdir(exist_ok=True)
            run(["git", "clone", "--quiet", spec["url"], path], capture=False)
            run(["git", "-C", path, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", spec["commit"]])
        url = git(path, "remote", "get-url", "origin")
        if url != spec["url"]:
            raise Failure(f"upstream/{rid} comes from {url}, expected {spec['url']}")
        check_upstream(rid, spec)
        print(f"upstream/{rid}: {spec['commit']} clean")


def apply_series(dest, base_repo, commit, series_dir=None):
    series_dir = Path(series_dir or SERIES_DIR)
    run(["git", "clone", "--quiet", "--no-checkout", base_repo, dest])
    run(["git", "-C", dest, "-c", "advice.detachedHead=false", "checkout", "--quiet", "-b", "aros-v11", commit])
    for name in series(series_dir):
        result = run(["git", *COMMITTER, "-C", dest, "am", "--quiet", "--keep-cr", "--whitespace=nowarn",
                      "--committer-date-is-author-date", series_dir / name], check=False)
        if result.returncode != 0:
            run(["git", "-C", dest, "am", "--abort"], check=False)
            raise Failure(f"{name} does not apply:\n{result.stderr.decode(errors='replace')}")


def cmd_materialize(args):
    spec = upstreams()["photocraft"]
    base = check_upstream("photocraft", spec)
    if WORK.exists() or WORK.is_symlink():
        raise Failure(f"{WORK} exists; it is never recreated. Use `verify` to compare it with the series, "
                      "or move it aside yourself after preserving its branches, stashes and untracked files.")
    WORK.parent.mkdir(exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="materialize-", dir=WORK.parent))
    try:
        apply_series(staging / "photocraft", base, spec["commit"])
        (staging / "photocraft").rename(WORK)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    print(f"{WORK}: {len(series())} patches applied on {spec['commit']}")


def work_state(work):
    status = git(work, "status", "--porcelain", "--untracked-files=all")
    return git(work, "rev-parse", "HEAD"), status


def export_series(work, base_repo, base_commit, series_dir, owner_repo):
    """Replaces `series_dir` with the work copy's commits since `base_commit`.

    Refuses when the work copy or `series_dir` (in the owning repository `owner_repo`) has
    uncommitted, staged or untracked changes: hand-edited headers or candidate patches would
    otherwise be lost. The new series is written beside the old one and must rebuild the work
    copy's tree from `base_repo` before it replaces anything; the swap is two renames, and the
    old directory is put back if the second fails."""
    work, series_dir, owner_repo = Path(work), Path(series_dir), Path(owner_repo)
    head, status = work_state(work)
    if status:
        raise Failure("the work copy has uncommitted or untracked changes; commit them first:\n" + status)
    if run(["git", "-C", work, "merge-base", "--is-ancestor", base_commit, "HEAD"], check=False).returncode:
        raise Failure(f"the work copy's HEAD does not descend from the pin {base_commit}")
    rel = series_dir.resolve().relative_to(owner_repo.resolve())
    dirty = git(owner_repo, "status", "--porcelain", "--untracked-files=all", "--", str(rel))
    if dirty:
        raise Failure(f"{rel} has uncommitted, staged or untracked changes; commit or move them first:\n{dirty}")
    count = int(git(work, "rev-list", "--count", f"{base_commit}..HEAD"))
    work_tree = git(work, "rev-parse", "HEAD^{tree}")
    tag = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    staged = series_dir.parent / f".{series_dir.name}.new-{tag}"
    previous = series_dir.parent / f".{series_dir.name}.old-{tag}"
    staged.mkdir()
    try:
        run(["git", "-C", work, "format-patch", "--quiet", "--no-numbered", "--no-signature", "--full-index", "--binary",
             "--zero-commit", "-o", staged, f"{base_commit}..HEAD"])
        produced = sorted(staged.glob("*.patch"))
        if len(produced) != count:
            raise Failure(f"format-patch wrote {len(produced)} patches for {count} commits")
        (staged / "series").write_text("".join(p.name + "\n" for p in produced))
        for extra in series_dir.iterdir():
            if extra.name != "series" and extra.suffix != ".patch":
                shutil.copy2(extra, staged / extra.name)
        with tempfile.TemporaryDirectory(prefix="export check ") as tmp:
            apply_series(Path(tmp) / "rebuilt", base_repo, base_commit, staged)
            rebuilt = git(Path(tmp) / "rebuilt", "rev-parse", "HEAD^{tree}")
        if rebuilt != work_tree:
            raise Failure(f"the new series rebuilds tree {rebuilt}, not the work copy's {work_tree}")
        os.replace(series_dir, previous)
        try:
            os.replace(staged, series_dir)
        except OSError:
            os.replace(previous, series_dir)
            raise
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    shutil.rmtree(previous)
    return head, count


def cmd_export(args):
    spec = upstreams()["photocraft"]
    base = check_upstream("photocraft", spec)
    head, count = export_series(WORK, base, spec["commit"], SERIES_DIR, REPO)
    print(f"exported {count} patches from {head}; they rebuild its tree; review `git diff` and commit them")


def cmd_verify(args):
    spec = upstreams()["photocraft"]
    base = check_upstream("photocraft", spec)
    with tempfile.TemporaryDirectory(prefix="photocraft verify ") as tmp:
        dest = Path(tmp) / "photo craft"
        apply_series(dest, base, spec["commit"])
        rebuilt = git(dest, "rev-parse", "HEAD^{tree}")
    print(f"series rebuilt tree {rebuilt}")
    if not WORK.exists():
        return
    head, status = work_state(WORK)
    work_tree = git(WORK, "rev-parse", "HEAD^{tree}")
    print(f"work HEAD {head} tree {work_tree}{' (uncommitted changes present)' if status else ''}")
    if work_tree != rebuilt:
        raise Failure("the series does not reproduce the work copy's committed tree; run `export` and commit")
    print("series reproduces the work copy's committed tree (contents and modes)")


def crate_specs():
    return json.loads((CRATES_DIR / "crates.json").read_text())["crates"]


def cmd_crates(args, quiet=False):
    cfg = pcconfig.load(["cargo_home", "build_root"])
    out = {}
    for spec in crate_specs():
        name = f"{spec['name']}-{spec['version']}"
        dest = Path(cfg["build_root"]) / "crates" / name
        if not dest.exists():
            archives = list(Path(cfg["cargo_home"]).glob(f"registry/cache/*/{name}.crate"))
            if len(archives) != 1:
                raise Failure(f"{name}.crate is not in {cfg['cargo_home']}; fetch dependencies first")
            if sha256_file(archives[0]) != spec["checksum"]:
                raise Failure(f"{archives[0]} does not match the Cargo.lock checksum")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="crate-", dir=dest.parent) as tmp:
                with tarfile.open(archives[0]) as tar:
                    tar.extractall(tmp, filter="data")
                staged = Path(tmp) / name
                for patch in (CRATES_DIR / name / "series").read_text().split():
                    run(["patch", "--quiet", "-p1", "-i", CRATES_DIR / name / patch], cwd=staged)
                got = tree_hash(staged)
                if spec.get("tree_sha256") and got != spec["tree_sha256"]:
                    raise Failure(f"patched {name} tree {got} differs from the recorded {spec['tree_sha256']}")
                staged.rename(dest)
        got = tree_hash(dest)
        if spec.get("tree_sha256") and got != spec["tree_sha256"]:
            raise Failure(f"{dest} differs from the reviewed patch result; remove it to rebuild from the archive")
        out[spec["name"]] = {"path": str(dest), "version": spec["version"], "tree_sha256": got}
        if not quiet:
            print(f"{name}: {dest} tree {got}{'' if spec.get('tree_sha256') else ' (not yet recorded)'}")
    return out


def sync_tree(files, dest):
    """Makes `dest` hold exactly `files` ({relative path: (bytes, executable)}), leaving
    unchanged files untouched so that cargo's fingerprints stay valid."""
    dest.mkdir(parents=True, exist_ok=True)
    for rel, (data, executable) in files.items():
        path = dest / rel
        if path.is_file() and path.read_bytes() == data and os.access(path, os.X_OK) == executable:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".pc-tmp")
        tmp.write_bytes(data)
        tmp.chmod(0o755 if executable else 0o644)
        tmp.replace(path)
    wanted = set(files)
    for path in sorted(dest.rglob("*"), reverse=True):
        rel = path.relative_to(dest).as_posix()
        if rel == "Cargo.lock.build" or rel.startswith("target/"):
            continue
        if path.is_file() and rel not in wanted:
            path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def snapshot(worktree):
    """The work copy's files: committed HEAD, or (worktree) the files on disk Git would track."""
    files = {}
    if worktree:
        names = run(["git", "-C", WORK, "ls-files", "-z", "--cached", "--others", "--exclude-standard"]).stdout.split(b"\0")
        for name in filter(None, names):
            path = WORK / name.decode()
            if path.is_file():
                files[name.decode()] = (path.read_bytes(), os.access(path, os.X_OK))
        return files
    data = run(["git", "-C", WORK, "archive", "--format=tar", "HEAD"]).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar.getmembers():
            if member.isfile():
                files[member.name] = (tar.extractfile(member).read(), bool(member.mode & 0o111))
    return files


def egui_aros_vendor(cfg, root, src):
    """egui-aros at the commit pinned in upstreams.json, with its patched crates, prepared by its
    own `ea.py vendor` from that commit: {crate name: path} for the [patch] table, and the record.
    The checkout's upstream/ clones supply the sources its crate patches apply to."""
    spec = upstreams().get("egui-aros")
    if not spec:
        return {}, None
    checkout = Path(cfg["egui_aros"] or "")
    if not cfg["egui_aros"] or not (checkout / ".git").exists():
        raise Failure("upstreams.json pins egui-aros: set egui_aros in local.json to its checkout")
    commit = spec["commit"]
    if git(checkout, "cat-file", "-t", commit) != "commit":
        raise Failure(f"{checkout} has no commit {commit}")
    base = root / f"egui-aros-{commit[:12]}"
    tree = base / "src"
    if not tree.exists():
        data = run(["git", "-C", checkout, "archive", "--format=tar", commit]).stdout
        with tempfile.TemporaryDirectory(prefix="egui-aros-", dir=root) as tmp:
            with tarfile.open(fileobj=io.BytesIO(data)) as tar:
                tar.extractall(tmp, filter="data")
            shutil.copytree(tmp, tree)
    env = dict(os.environ, EGUI_AROS_UPSTREAM_ROOT=str(checkout / "upstream"), EGUI_AROS_BUILD_ROOT=str(base / "build"),
               EGUI_AROS_LOCAL=str(base / "no-local.json"))
    out = run([sys.executable, tree / "scripts" / "ea.py", "vendor", "--dest", base / "vendor", "--cargo-home", cfg["cargo_home"],
               "--lock", src / "Cargo.lock"], env=env).stdout.decode()
    record = json.loads(out)
    record["commit"] = commit
    paths = {name: info["path"] for name, info in record["crates"].items()}
    paths["egui-aros"] = record["egui_aros"]
    return paths, record


def objdump_key(cfg, obj):
    tool = cfg["aros_gcc"].replace("-gcc", "-objdump")
    text = run([tool, "-d", "-r", "--no-show-raw-insn", obj]).stdout.decode().split("\n", 4)[-1]
    return hashlib.sha256(text.encode()).hexdigest()


def build_pthread(cfg, root):
    """libpthread.a from deadwood2/AROS compiler/pthread with patches/aros-pthread applied,
    in a private directory searched before the SDK. The unpatched tree is first checked to
    rebuild the SDK's archive object for object, so the patch is all that differs."""
    patches = [PTHREAD_DIR / n for n in (PTHREAD_DIR / "series").read_text().split()]
    commit = cfg["aros_src_commit"]
    key = hashlib.sha256(b"".join(bytes.fromhex(sha256_file(p)) for p in patches)).hexdigest()[:8]
    out = root / f"aros-pthread-{commit[:12]}-{key}"
    if (out / "pthread.json").exists():
        return out, json.loads((out / "pthread.json").read_text())
    archive = run(["git", "-C", cfg["aros_src"], "archive", "--format=tar", commit, "compiler/pthread"]).stdout
    gcc, ar = cfg["aros_gcc"], cfg["aros_ar"]
    with tempfile.TemporaryDirectory(prefix="pthread-", dir=root) as tmp:
        tmp = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(tmp, filter="data")
        src = tmp / "compiler/pthread"
        # The member list comes from the recipe, not a copy of it.
        recipe, names, collecting = (src / "mmakefile.src").read_text().splitlines(), [], None
        for line in recipe:
            if line.startswith(("LINKLIBFILES", "PTHREADFUNCS")):
                collecting = True
                line = line.split(":=", 1)[1]
            if collecting:
                names += [w for w in line.replace("\\", " ").split() if w]
                collecting = line.rstrip().endswith("\\")
        sdk_objs = tmp / "sdk"
        sdk_objs.mkdir()
        run([ar, "x", Path(cfg["aros_sdk"]) / "lib" / "libpthread.a"], cwd=sdk_objs)
        if sorted(p.stem for p in sdk_objs.glob("*.o")) != sorted(names):
            raise Failure(f"SDK libpthread.a members differ from the recipe's list {names}")
        for stage in ("plain", "patched"):
            if stage == "patched":
                for patch in patches:
                    run(["patch", "--quiet", "-p3", "-i", patch], cwd=src)
            objs = tmp / stage
            objs.mkdir()
            for name in names:
                run([gcc, f"--sysroot={cfg['aros_sdk']}", *PTHREAD_CFLAGS, "-I", src, "-c", src / f"{name}.c", "-o", objs / f"{name}.o"])
            if stage == "plain":
                mismatched = [n for n in names if objdump_key(cfg, objs / f"{n}.o") != objdump_key(cfg, sdk_objs / f"{n}.o")]
                if mismatched:
                    raise Failure(f"{commit} compiler/pthread does not rebuild the SDK's objects: {mismatched}")
        staged = tmp / "out"
        staged.mkdir()
        changed = [n for n in names if objdump_key(cfg, tmp / "patched" / f"{n}.o") != objdump_key(cfg, tmp / "plain" / f"{n}.o")]
        if sorted(changed) != sorted(PTHREAD_PATCHED):
            raise Failure(f"the pthread patches change {changed}, expected {list(PTHREAD_PATCHED)}")
        for n in PTHREAD_PATCHED:
            shutil.copyfile(tmp / "patched" / f"{n}.o", staged / f"{n}.o")
        record = {"aros_src_commit": commit, "patches": {p.name: sha256_file(p) for p in patches},
                  "cflags": PTHREAD_CFLAGS, "members": names, "unpatched_matches_sdk": True,
                  "sdk_archive_sha256": sha256_file(Path(cfg["aros_sdk"]) / "lib" / "libpthread.a"),
                  "objects": {f"{n}.o": sha256_file(staged / f"{n}.o") for n in PTHREAD_PATCHED}}
        (staged / "pthread.json").write_text(json.dumps(record, indent=2) + "\n")
        staged.rename(out)
    return out, record


def cmd_build(args):
    cfg = pcconfig.load(["aros_gcc", "aros_ar", "aros_sdk", "aros_src", "rust_aros", "toolchain", "cargo_home", "build_root"])
    for name in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "CARGO_BUILD_RUSTFLAGS", "CARGO_TARGET_DIR",
                 "CARGO_PROFILE_RELEASE_PANIC"):
        if os.environ.get(name):
            raise Failure(f"clear {name}: it would override the selected native profile or output")
    rustc = run(["rustc", "+" + cfg["toolchain"], "--version"]).stdout.decode().strip()
    if rustc != cfg["rustc_version"]:
        raise Failure(f"toolchain {cfg['toolchain']} reports `{rustc}`, expected `{cfg['rustc_version']}`")
    root = Path(cfg["build_root"])
    root.mkdir(parents=True, exist_ok=True)
    head, status = work_state(WORK)
    files = snapshot(args.worktree)
    src = root / "src"
    sync_tree(files, src)
    # The build copy's lock changes when path patches replace registry crates; keep the
    # original next to it so the manifest can name both.
    lock_original = hashlib.sha256(files["Cargo.lock"][0]).hexdigest()

    rust_aros = Path(cfg["rust_aros"])
    commit = cfg["rust_aros_commit"]
    libc_patches = [LIBC_DIR / n for n in (LIBC_DIR / "series").read_text().split()]
    libc_key = hashlib.sha256(b"".join(bytes.fromhex(sha256_file(p)) for p in libc_patches)).hexdigest()[:8]
    libc = root / f"libc-aros-{commit[:12]}-{libc_key}"
    if not libc.exists():
        archive = run(["git", "-C", rust_aros, "archive", "--format=tar", commit, "std-groundwork/libc-aros"]).stdout
        with tempfile.TemporaryDirectory(prefix="libc-", dir=root) as tmp:
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(tmp, filter="data")
            staged = Path(tmp) / "std-groundwork/libc-aros"
            for patch in libc_patches:
                run(["patch", "--quiet", "-p1", "-i", patch], cwd=staged)
            staged.rename(libc)
    template = run(["git", "-C", rust_aros, "show", f"{commit}:x86_64-aros.json.in"]).stdout.decode()
    target_json = root / "x86_64-aros.json"
    target_text = (template.replace("@AROS_GCC@", cfg["aros_gcc"]).replace("@AROS_SDK@", cfg["aros_sdk"])
                   .replace("@AROS_EXTRA_LIBS@", ""))
    if not target_json.exists() or target_json.read_text() != target_text:
        target_json.write_text(target_text)
    crates = cmd_crates(args, quiet=True)
    egui_aros, egui_aros_record = egui_aros_vendor(cfg, root, src)
    pthread_dir, pthread = build_pthread(cfg, root)

    # getrandom has no AROS backend; photocraft-aros-entropy supplies the custom one.
    # The build root first: patched crates and the egui-aros vendor tree live under it, and their
    # panic locations would otherwise carry this machine's paths. A later, more specific prefix
    # (the source copy, libc-aros) wins where both match.
    flags = ["-Cpanic=" + cfg["panic"], "--cfg", 'getrandom_backend="custom"', f"--remap-path-prefix={root}=/build",
             f"--remap-path-prefix={src}=/photocraft",
             f"--remap-path-prefix={cfg['cargo_home']}=/cargo", f"--remap-path-prefix={libc}=/libc-aros",
             f"--remap-path-prefix={run(['rustc', '+' + cfg['toolchain'], '--print', 'sysroot']).stdout.decode().strip()}=/rust"]
    if cfg["panic"] == "unwind":
        flags.append("-Cforce-unwind-tables=yes")
    # The AROS GCC driver searches the SDK's lib/ before any -L given to it, so a patched
    # libpthread.a cannot win the -lpthread lookup. The two patched objects go first on the
    # link line instead (pre-link arguments reach only final links): they define every symbol
    # of the SDK's pthread.o and pthread_create.o, so -lpthread pulls neither. pthread.c also
    # defines the functions of the other members, so whole-archive linking would collide.
    flags.append("-Zpre-link-args=" + " ".join(str(pthread_dir / f"{n}.o") for n in PTHREAD_PATCHED))
    command = ["cargo", "+" + cfg["toolchain"], "build", "--release", "--target", target_json,
               "-Zbuild-std=std,panic_" + cfg["panic"], "-Zjson-target-spec",
               "--config", "build.rustflags=" + json.dumps(flags),
               "--config", "patch.crates-io.libc.path=" + json.dumps(str(libc))]
    if not args.online:
        command.append("--offline")
    for name, info in crates.items():
        command += ["--config", f"patch.crates-io.{name}.path=" + json.dumps(info["path"])]
    # The port's own crate patches win where both have one (the same patches today).
    for name, path in egui_aros.items():
        if name not in crates:
            command += ["--config", f"patch.crates-io.{name}.path=" + json.dumps(path)]
    if args.tool:
        manifest_dir, tool_binary = TOOLS[args.tool]
        # Built from a copy: the path patches would otherwise rewrite the tool's own lock.
        tool_src = root / "tools" / args.tool
        sync_tree({p.relative_to(REPO / manifest_dir).as_posix(): (p.read_bytes(), os.access(p, os.X_OK))
                   for p in (REPO / manifest_dir).rglob("*") if p.is_file() and "target" not in p.parts}, tool_src)
        command += ["--manifest-path", tool_src / "Cargo.toml"]
        binary_names = [tool_binary]
    else:
        packages = args.package or list(PACKAGES)
        for package in packages:
            if package not in PACKAGES:
                raise Failure(f"unknown package {package}; choose from {sorted(PACKAGES)}")
            command += ["-p", package]
        binary_names = [PACKAGES[p] for p in packages]
    # Release builds: whole-program LTO, which with the stripping at packaging keeps the programs
    # within what apkg accepts for one file (at the same optimisation level).
    if args.lto == "fat":
        command += ["--config", 'profile.release.lto="fat"']
    if args.no_default_features:
        command.append("--no-default-features")
    if args.features:
        command += ["--features", args.features]
    env = dict(os.environ, CARGO_HOME=cfg["cargo_home"], CARGO_TARGET_DIR=str(root / "target"),
               AROS_CC=cfg["aros_gcc"], AROS_GCC=cfg["aros_gcc"], AROS_AR=cfg["aros_ar"], AROS_SDK=cfg["aros_sdk"])
    build_id = str(uuid.uuid4())
    out = root / "out" / f"{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{build_id[:8]}"
    out.mkdir(parents=True)
    manifest = {
        "build_id": build_id,
        "status": "building",
        "date": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "abi": "x86_64 ABIv11",
        "work_head": head,
        "work_dirty": bool(status),
        "source": "worktree" if args.worktree else "committed HEAD",
        "snapshot_sha256": hashlib.sha256(b"".join(
            k.encode() + b"\0" + hashlib.sha256(v[0]).digest() + (b"x" if v[1] else b"-") for k, v in sorted(files.items()))).hexdigest(),
        "upstreams": upstreams(),
        "series": {n: sha256_file(SERIES_DIR / n) for n in series()},
        "crates": crates,
        "libc_aros": {"rust_aros_commit": commit, "patches": {p.name: sha256_file(p) for p in libc_patches},
                      "tree_sha256": tree_hash(libc)},
        "target_json_sha256": sha256_file(target_json),
        "pthread": pthread,
        "egui_aros": egui_aros_record,
        "toolchain": {"name": cfg["toolchain"], "rustc": rustc,
                      "sysroot": run(["rustc", "+" + cfg["toolchain"], "--print", "sysroot"]).stdout.decode().strip(),
                      "gcc": run([cfg["aros_gcc"], "--version"]).stdout.decode().splitlines()[0],
                      "sdk": cfg["aros_sdk"], "panic": cfg["panic"]},
        "cargo_lock_sha256": lock_original,
        "command": [str(c) for c in command],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    log = out / "build.log"
    messages = out / "cargo-messages.jsonl"
    # Machine messages on stdout name every compiled unit; they give the exact set of packages
    # linked into the binaries (std's own dependencies included), for the release notices.
    with log.open("wb") as f, messages.open("wb") as m:
        result = subprocess.run([str(c) for c in command] + ["--message-format=json-render-diagnostics"], cwd=src, env=env,
                                stdout=m, stderr=f)
    manifest["returncode"] = result.returncode
    if result.returncode != 0:
        manifest["status"] = "failed"
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        raise Failure(f"build failed; see {log}")
    manifest["cargo_lock_build_sha256"] = sha256_file(src / "Cargo.lock")
    binaries = {}
    release = root / "target" / "x86_64-aros" / "release"
    for name in binary_names:
        path = release / name
        if path.exists():
            shutil.copy2(path, out / name)
            undefined = run([cfg["aros_gcc"].replace("-gcc", "-nm"), "-u", out / name]).stdout.decode().split()
            binaries[name] = {"sha256": sha256_file(out / name), "bytes": (out / name).stat().st_size,
                              "undefined_symbols": undefined}
            if undefined:
                raise Failure(f"{name} has undefined symbols (collect-aros did not catch them): {undefined[:8]}")
    manifest.update(status="built-not-run", binaries=binaries, linked_packages=linked_packages(messages))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(out), "binaries": binaries, "work_dirty": bool(status)}, indent=2))


def linked_packages(messages):
    """Packages compiled for the AROS target (not build scripts or proc-macros, which run on the
    host): package id -> manifest path."""
    found = {}
    for line in messages.read_text().splitlines():
        if not line.startswith("{"):
            continue
        m = json.loads(line)
        if m.get("reason") != "compiler-artifact" or {"custom-build", "proc-macro"} & set(m["target"]["kind"]):
            continue
        if any("/x86_64-aros/" in name for name in m["filenames"]):
            found[m["package_id"]] = m["manifest_path"]
    return dict(sorted(found.items()))


# Native C test programs: name -> (sources relative to the repository or the work copy, defines).
CTOOLS = {
    "links_test": (["work:crates/aros-fs/tests/links_test.c", "work:crates/aros-fs/c/links.c"], ["-DPC_FS_TEST_EXNEXT"]),
    "taskstack": (["repo:tests/guest/taskstack.c"], []),
    "cliptext": (["repo:tests/guest/cliptext.c"], []),
}


def cmd_ctools(args):
    """Builds the native C test programs with the configured compiler and SDK into a new output."""
    cfg = pcconfig.load(["aros_gcc", "aros_sdk", "build_root"])
    head, status = work_state(WORK)
    if status:
        raise Failure("commit the work copy first; the test programs are built from its files")
    out = Path(cfg["build_root"]) / "out" / f"{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-ctools-{uuid.uuid4().hex[:8]}"
    out.mkdir(parents=True)
    record = {"status": "built-not-run", "work_head": head, "gcc": run([cfg["aros_gcc"], "--version"]).stdout.decode().splitlines()[0],
              "sdk": cfg["aros_sdk"], "binaries": {}}
    for name, (sources, defines) in CTOOLS.items():
        paths = [(WORK if s.startswith("work:") else REPO) / s.split(":", 1)[1] for s in sources]
        run([cfg["aros_gcc"], f"--sysroot={cfg['aros_sdk']}", "-O2", "-Wall", *defines, *paths, "-o", out / name])
        record["binaries"][name] = {"sha256": sha256_file(out / name), "sources": sources}
    (out / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"output": str(out), **record}, indent=2))


def cmd_host(args):
    """Host cargo in the work copy (tests, checks), with the pinned egui-aros and the crates it
    needs that are not on crates.io as [patch] entries: without them the workspace does not
    resolve, because the AROS shell depends on egui-aros. Runs in a copy of the work copy (its
    files on disk), so the lock entries cargo adds for them never reach the work copy."""
    cfg = pcconfig.load(["cargo_home", "build_root"])
    root = Path(cfg["build_root"])
    root.mkdir(parents=True, exist_ok=True)
    src = root / "host-src"
    sync_tree(snapshot(True), src)
    egui_aros, _ = egui_aros_vendor(cfg, root, src)
    command = ["cargo"]
    for name in ("egui-aros", "aros-gui-sys"):
        if name in egui_aros:
            command += ["--config", f"patch.crates-io.{name}.path=" + json.dumps(egui_aros[name])]
    command += args.cargo
    env = dict(os.environ, CARGO_HOME=cfg["cargo_home"], CARGO_TARGET_DIR=str(root / "host-target"))
    result = subprocess.run([str(x) for x in command], cwd=src, env=env)
    if result.returncode:
        raise Failure(f"cargo exited with {result.returncode}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("config", help="show configuration sources").set_defaults(func=cmd_config)
    sub.add_parser("fetch", help="clone or verify pinned upstreams").set_defaults(func=cmd_fetch)
    sub.add_parser("materialize", help="create the work copy from the series").set_defaults(func=cmd_materialize)
    sub.add_parser("export", help="write work copy commits to the series").set_defaults(func=cmd_export)
    sub.add_parser("verify", help="rebuild the series and compare with the work copy").set_defaults(func=cmd_verify)
    sub.add_parser("crates", help="prepare patched crates").set_defaults(func=cmd_crates)
    sub.add_parser("ctools", help="build the native C test programs").set_defaults(func=cmd_ctools)
    h = sub.add_parser("host", help="host cargo in the work copy with the pinned egui-aros patched in")
    h.add_argument("cargo", nargs=argparse.REMAINDER, help="cargo arguments, e.g. test -p NAME")
    h.set_defaults(func=cmd_host)
    b = sub.add_parser("build", help="build AROS binaries")
    b.add_argument("-p", "--package", action="append", default=[], help="photocraft-aros, photocraft-cli (default: workspace defaults)")
    b.add_argument("--features", help="cargo --features")
    b.add_argument("--no-default-features", action="store_true")
    b.add_argument("--lto", choices=["fat"], help="whole-program LTO (release builds)")
    b.add_argument("--worktree", action="store_true", help="build uncommitted files too (recorded as such)")
    b.add_argument("--online", action="store_true", help="allow cargo to download missing crates")
    b.add_argument("--tool", choices=sorted(TOOLS), help="build a test tool from tests/ instead of PhotoCraft")
    b.set_defaults(func=cmd_build)
    args = parser.parse_args()
    try:
        args.func(args)
    except (Failure, pcconfig.ConfigError) as error:
        parser.exit(1, f"pc.py {args.command}: {error}\n")


if __name__ == "__main__":
    main()
