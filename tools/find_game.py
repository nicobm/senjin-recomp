#!/usr/bin/env python3
"""Find a Senjin Aleste dump, verify its executable and write game.zip.

The Flatpak manifest reads a file called game.zip.  This helper accepts a
zip/rar/7z archive (or an extracted folder), finds senxin_aleste_apm3.exe,
checks its SHA-256 against recomp/exe.sha256 and writes a normalized zip with
the executable and windata/ at the archive root.

Without --input it first reuses a valid game.zip, then searches the XDG
Downloads and Documents folders.  Archives whose name mentions Senjin/Senxin
are checked first; every .zip, .rar and .7z is checked otherwise.
"""

import argparse
import hashlib
import os
import posixpath
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

EXE_NAME = "senxin_aleste_apm3.exe"
DATA_DIR = "windata"
ARCHIVE_SUFFIXES = (".zip", ".rar", ".7z")
MAX_SEARCH_DEPTH = 4
CHUNK = 1 << 20


class ToolError(Exception):
    pass


def fail(message):
    print("error: %s" % message, file=sys.stderr)
    raise SystemExit(1)


def clean_entry(name):
    """Archive names are relative; also accept the common './' and '\' forms."""
    name = name.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    return name


def entry_basename(name):
    name = name.rstrip("/\\")
    return name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()


def escape_glob(pattern):
    """bsdtar treats --include/--exclude arguments as glob patterns."""
    for char in "\\*?[":
        pattern = pattern.replace(char, "\\" + char)
    return pattern


def pick_exe(names):
    for name in names:
        if entry_basename(name) == EXE_NAME:
            return name
    return None


def hash_stream(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(CHUNK), b""):
        digest.update(chunk)
    return digest.hexdigest()


def hash_file(path):
    with open(path, "rb") as stream:
        return hash_stream(stream)


class Check:
    def __init__(self, path):
        self.path = path
        self.entry = None       # original archive entry, for streaming
        self.root = ""          # top-level folder around the exe ("" = root)
        self.digest = None
        self.has_data = False
        self.tool = None
        self.error = None
        self.match = False

    def __str__(self):
        return str(self.path)


class ArchiveTool:
    name = "?"

    def list(self, archive):
        raise NotImplementedError

    def read(self, archive, entry):
        raise NotImplementedError

    def extract(self, archive, dest):
        raise NotImplementedError

    def _run(self, command):
        try:
            proc = subprocess.run(command, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
        except OSError as exc:
            raise ToolError(str(exc))
        if proc.returncode != 0:
            message = proc.stderr.decode("utf-8", "replace").strip()
            if not message:
                message = "exit status %d" % proc.returncode
            raise ToolError(message.splitlines()[-1])
        return proc.stdout


class Bsdtar(ArchiveTool):
    name = "bsdtar"

    def list(self, archive):
        output = self._run(["bsdtar", "-tf", str(archive)])
        return output.decode("utf-8", "replace").splitlines()

    def read(self, archive, entry):
        # Selecting an entry by name is still a glob in bsdtar: escape the
        # brackets of names like "...[Sega ALLS][TP].zip" or a dump whose
        # folder has them.  --include also avoids path normalization surprises.
        return self._run(["bsdtar", "-xOf", str(archive),
                          "--include", escape_glob(clean_entry(entry))])

    def extract(self, archive, dest):
        self._run(["bsdtar", "-xf", str(archive), "-C", str(dest)])


class Unrar(ArchiveTool):
    name = "unrar"

    def list(self, archive):
        output = self._run(["unrar", "lb", str(archive)])
        return output.decode("utf-8", "replace").splitlines()

    def read(self, archive, entry):
        return self._run(["unrar", "p", "-inul", str(archive), entry])

    def extract(self, archive, dest):
        self._run(["unrar", "x", "-o+", "-idq", str(archive), str(dest) + os.sep])


class SevenZip(ArchiveTool):
    def __init__(self, name):
        self.name = name

    def list(self, archive):
        output = self._run([self.name, "l", "-slt", "-ba", str(archive)])
        names = []
        for line in output.decode("utf-8", "replace").splitlines():
            if line.startswith("Path = "):
                names.append(line[len("Path = "):])
        # With -slt the first Path is the archive itself.
        if names and (names[0] == str(archive)
                      or Path(names[0]).name == Path(archive).name):
            names = names[1:]
        return names

    def read(self, archive, entry):
        return self._run([self.name, "x", "-so", str(archive), entry])

    def extract(self, archive, dest):
        self._run([self.name, "x", "-y", "-o" + str(dest), str(archive)])


def available_tools():
    tools = []
    if shutil.which("bsdtar"):
        tools.append(Bsdtar())
    if shutil.which("unrar"):
        tools.append(Unrar())
    for name in ("7z", "7zz"):
        if shutil.which(name):
            tools.append(SevenZip(name))
    return tools


def check_zip(path, expected):
    check = Check(path)
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            entries = [(info, clean_entry(info.filename)) for info in infos]
            exe = next(((info, name) for info, name in entries
                        if entry_basename(name) == EXE_NAME), None)
            if exe is None:
                return check
            info, name = exe
            check.entry = info.filename
            check.root = posixpath.dirname(name)
            if check.root == ".":
                check.root = ""
            prefix = "%s/%s/" % (check.root, DATA_DIR) if check.root else DATA_DIR + "/"
            check.has_data = any(name.startswith(prefix) for _, name in entries)
            with archive.open(info.filename) as stream:
                check.digest = hash_stream(stream)
            check.match = check.digest == expected and check.has_data
    except (OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as exc:
        check.error = str(exc)
    return check


def check_with_tools(path, expected):
    check = Check(path)
    errors = []
    for tool in available_tools():
        try:
            names = tool.list(path)
        except ToolError as exc:
            errors.append("%s: %s" % (tool.name, exc))
            continue
        exe = pick_exe(names)
        if exe is None:
            check.tool = tool
            return check
        cleaned = clean_entry(exe)
        check.entry = exe
        check.root = posixpath.dirname(cleaned)
        if check.root == ".":
            check.root = ""
        prefix = "%s/%s/" % (check.root, DATA_DIR) if check.root else DATA_DIR + "/"
        check.has_data = any(clean_entry(name).startswith(prefix) for name in names)
        try:
            data = tool.read(path, exe)
        except ToolError as exc:
            errors.append("%s: %s" % (tool.name, exc))
            continue
        check.tool = tool
        check.digest = hashlib.sha256(data).hexdigest()
        check.match = check.digest == expected and check.has_data
        return check
    check.error = "; ".join(errors) or "no archive tool available (install bsdtar, unrar or 7z)"
    return check


def find_exe_in_folder(folder):
    direct = folder / EXE_NAME
    if direct.is_file():
        return direct
    for depth in range(1, 3):
        pattern = "*/" * depth + EXE_NAME
        for path in folder.glob(pattern):
            if path.is_file():
                return path
    return None


def check_folder(path, expected):
    check = Check(path)
    if path.is_file() and path.name.lower() == EXE_NAME:
        exe = path
    else:
        exe = find_exe_in_folder(path)
    if exe is None:
        return check
    root = exe.parent
    check.entry = str(exe)
    check.root = str(root)
    check.has_data = (root / DATA_DIR).is_dir()
    try:
        check.digest = hash_file(exe)
    except OSError as exc:
        check.error = str(exc)
        return check
    check.match = check.digest == expected and check.has_data
    return check


def check_path(path, expected):
    if path.is_dir() or (path.is_file() and path.name.lower() == EXE_NAME):
        return check_folder(path, expected)
    if path.suffix.lower() == ".zip":
        check = check_zip(path, expected)
        if check.error and available_tools():
            # A zip that Python cannot read may still be readable by libarchive.
            check = check_with_tools(path, expected)
        return check
    return check_with_tools(path, expected)


def walk_files(folder, max_depth=None):
    base = Path(folder)
    for root, dirs, files in os.walk(base, followlinks=False):
        rel = Path(root).relative_to(base)
        depth = 0 if rel == Path(".") else len(rel.parts)
        if max_depth is not None and depth >= max_depth:
            dirs[:] = []
        else:
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            yield Path(root) / name


def search_archives(folders):
    seen = set()
    found = []
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            continue
        for path in walk_files(folder, MAX_SEARCH_DEPTH):
            if path.suffix.lower() not in ARCHIVE_SUFFIXES:
                continue
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            if key in seen:
                continue
            seen.add(key)
            found.append(path)

    def order(path):
        name = path.name.lower()
        hint = 0 if "senjin" in name or "senxin" in name else 1
        try:
            modified = -path.stat().st_mtime
        except OSError:
            modified = 0
        return (hint, modified, name)

    return sorted(found, key=order)


def resolve_input(argument, folders):
    path = Path(argument).expanduser()
    candidates = [path] if path.is_absolute() else [Path.cwd() / path]
    if not path.is_absolute():
        candidates += [Path(folder) / path for folder in folders]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    # A bare file name may live deeper in Downloads/Documents.
    wanted = path.name.lower()
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            continue
        for candidate in walk_files(folder, MAX_SEARCH_DEPTH):
            if candidate.name.lower() == wanted:
                return candidate

    fail("cannot find %r in the current directory or:\n%s"
         % (argument, "\n".join("  %s" % folder for folder in folders)))


def describe_failure(check, expected):
    if check.error:
        fail("cannot read %s: %s" % (check.path, check.error))
    if check.entry is None:
        fail("%s does not contain %s\n"
             "  The supported dump is Senjin Aleste APM3 VER. 1.02."
             % (check.path, EXE_NAME))
    if not check.has_data:
        fail("%s contains %s but no %s/ directory at the same level"
             % (check.path, EXE_NAME, DATA_DIR))
    fail("%s contains an unsupported %s\n"
         "  expected sha256: %s\n"
         "  found:          %s\n"
         "  The supported dump is Senjin Aleste APM3 VER. 1.02."
         % (check.path, EXE_NAME, expected, check.digest))


def atomic_output(destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination.with_name(destination.name + ".tmp"), destination


def zip_entries(source, root, destination):
    temporary, destination = atomic_output(destination)
    try:
        with zipfile.ZipFile(source) as archive, \
                zipfile.ZipFile(temporary, "w", allowZip64=True) as output:
            for info in archive.infolist():
                name = clean_entry(info.filename)
                if root:
                    prefix = root.rstrip("/") + "/"
                    if not name.startswith(prefix):
                        continue
                    name = name[len(prefix):]
                if not name or name.endswith("/"):
                    continue
                if name.startswith("/") or ".." in name.split("/"):
                    continue
                out_info = zipfile.ZipInfo(name, date_time=info.date_time)
                out_info.compress_type = info.compress_type
                out_info.external_attr = info.external_attr
                out_info.internal_attr = info.internal_attr
                out_info.create_system = info.create_system
                with archive.open(info) as source_file, \
                        output.open(out_info, "w") as target_file:
                    shutil.copyfileobj(source_file, target_file, CHUNK)
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def copy_file(source, destination):
    temporary, destination = atomic_output(destination)
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def zip_folder(folder, destination):
    temporary, destination = atomic_output(destination)
    folder = Path(folder)
    skip = {temporary.resolve(), destination.resolve()}
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=1, allowZip64=True) as output:
            for path in walk_files(folder):
                if path.is_file() and path.resolve() not in skip:
                    output.write(path, path.relative_to(folder).as_posix())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def materialize(check, destination, quiet=False):
    destination = Path(destination)
    source = check.path
    if source.is_dir() or (source.is_file() and source.name.lower() == EXE_NAME):
        if not quiet:
            print("Writing %s from %s..." % (destination.name, source))
        zip_folder(check.root, destination)
        return

    if source.suffix.lower() == ".zip":
        if source.resolve() == destination.resolve() and not check.root:
            return
        if not check.root:
            if not quiet:
                print("Using %s..." % source)
            copy_file(source, destination)
        else:
            if not quiet:
                print("Writing %s from %s..." % (destination.name, source))
            zip_entries(source, check.root, destination)
        return

    if check.tool is None:
        fail("no archive tool can extract %s" % source)
    if not quiet:
        print("Writing %s from %s..." % (destination.name, source))
    with tempfile.TemporaryDirectory(prefix="senjin-dump-") as temporary:
        root = Path(temporary)
        try:
            check.tool.extract(source, root)
        except ToolError as exc:
            fail("cannot extract %s with %s: %s" % (source, check.tool.name, exc))
        game = root / check.root if check.root else root
        if not (game / EXE_NAME).is_file():
            fail("could not find %s in the extracted archive" % EXE_NAME)
        zip_folder(game, destination)


def read_expected(path):
    try:
        line = Path(path).read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError) as exc:
        fail("cannot read the expected hash from %s: %s" % (path, exc))
    digest = line.split()[0].lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        fail("%s does not contain a SHA-256 hash" % path)
    return digest


def xdg_dir(kind, fallback):
    """Resolve XDG_DOWNLOAD_DIR / XDG_DOCUMENTS_DIR like xdg-user-dir.

    The script runs inside a toolbox, which may not have xdg-user-dir, so read
    ~/.config/user-dirs.dirs directly.  It is shared with the host and keeps
    localized names such as ~/Descargas and ~/Documentos.
    """
    variable = "XDG_%s_DIR" % kind
    value = os.environ.get(variable)
    if not value:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME",
                                          Path.home() / ".config"))
        try:
            lines = (config_home / "user-dirs.dirs").read_text(
                encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        for line in lines:
            line = line.strip()
            if line.startswith(variable + "="):
                candidate = line.split("=", 1)[1].strip()
                if candidate.startswith('"') and candidate.endswith('"'):
                    candidate = candidate[1:-1]
                if candidate:
                    value = candidate
                    break

    home = Path.home()
    fallback_path = home / fallback
    if not value and shutil.which("xdg-user-dir"):
        try:
            proc = subprocess.run(["xdg-user-dir", kind],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL)
            if proc.returncode == 0:
                value = proc.stdout.decode("utf-8", "replace").strip()
        except OSError:
            value = ""
    if not value:
        return fallback_path

    value = value.replace("${HOME}", str(home)).replace("$HOME", str(home))
    path = Path(os.path.expandvars(value)).expanduser()
    if path == home:
        return fallback_path
    if path.is_dir():
        return path
    if fallback_path.is_dir():
        return fallback_path
    return path


def default_search_dirs():
    return [xdg_dir("DOWNLOAD", "Downloads"),
            xdg_dir("DOCUMENTS", "Documents")]


def main():
    parser = argparse.ArgumentParser(
        description="Find a Senjin Aleste dump and write game.zip.")
    parser.add_argument("--input", help="dump to use (.zip/.rar/.7z or folder)")
    parser.add_argument("--output", default="game.zip", help="output zip")
    parser.add_argument("--sha256-file", default="recomp/exe.sha256",
                        help="file with the expected executable SHA-256")
    parser.add_argument("--search-dir", action="append", default=[],
                        help="folder to search (repeatable)")
    args = parser.parse_args()

    expected = read_expected(args.sha256_file)
    destination = Path(args.output)
    folders = [folder for folder in args.search_dir if folder]
    if not folders:
        folders = [str(folder) for folder in default_search_dirs()]

    if args.input:
        path = resolve_input(args.input, folders)
        check = check_path(path, expected)
        if not check.match:
            describe_failure(check, expected)
        materialize(check, destination)
        return

    # Keep an already valid game.zip: rebuilding does not need to copy the dump
    # again, and it also works if the original download is gone.
    if destination.is_file():
        check = check_path(destination, expected)
        if check.match:
            print("Using existing %s (sha256 matches)." % destination)
            return

    if not folders:
        fail("no search folders: pass the dump as an argument or use --search-dir")
    print("Looking for a Senjin Aleste dump in:")
    for folder in folders:
        print("  %s" % folder)

    notes = []
    candidates = search_archives(folders)
    for path in candidates:
        check = check_path(path, expected)
        if check.match:
            materialize(check, destination)
            print("Using %s (supported %s)." % (path, EXE_NAME))
            return
        if check.error:
            notes.append("%s: %s" % (path, check.error))
        elif check.entry is not None:
            if check.digest is not None and check.digest != expected:
                notes.append("%s: %s sha256 %s (unsupported)"
                             % (path, EXE_NAME, check.digest))
            elif not check.has_data:
                notes.append("%s: no %s/ directory" % (path, DATA_DIR))

    for note in notes:
        print("note: %s" % note, file=sys.stderr)
    fail("no dump with the supported %s was found in:\n%s\n"
         "Pass the dump as an argument, e.g.:\n"
         "  ./build-flatpak.sh \"/path/to/dump.zip\""
         % (EXE_NAME, "\n".join("  %s" % folder for folder in folders)))


if __name__ == "__main__":
    main()
