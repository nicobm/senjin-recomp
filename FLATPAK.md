# Flatpak (Fedora Silverblue / Bazzite)

Local-only Flatpak packaging for the native Linux port. The game files are
supplied by the user and are not part of the repository.

## Prerequisites

- A Flatpak host (Fedora Silverblue, Bazzite, ...).
- A toolbox with `flatpak-builder`:

  ```sh
  toolbox enter
  # inside the toolbox, if needed:
  sudo dnf install flatpak-builder
  ```

- The Freedesktop runtime and SDK 26.08. `build-flatpak.sh` installs them
  automatically with `flatpak install -y` if they are missing. To install them
  manually instead:

  ```sh
  flatpak install -y flathub \
      org.freedesktop.Platform//26.08 org.freedesktop.Sdk//26.08
  ```

  If you prefer a per-user install, add Flathub to your user installation
  first and use `flatpak install -y --user flathub ...`.

- Your own game dump: a `.zip`, `.rar` or `.7z` archive, or the extracted
  folder with `senxin_aleste_apm3.exe` and `windata/`. With no argument,
  `build-flatpak.sh` searches the XDG Downloads and Documents folders.
  Reading RAR/7z needs `bsdtar`, `unrar` or `7z`; ZIP needs nothing extra.
- `curl` or `wget` for the first build: the script downloads the two Python
  wheels into `flatpak/wheels/`. No source snapshot is needed.

## Build

Inside `toolbox enter`, from the repository root:

```sh
./build-flatpak.sh
```

With no argument the script searches the XDG Downloads and Documents folders
for a `.zip`, `.rar` or `.7z`, looks inside for `senxin_aleste_apm3.exe`,
checks its SHA-256 against [`recomp/exe.sha256`](recomp/exe.sha256) and writes
the normalized `game.zip` the manifest expects. You can also pass the dump
explicitly. Spaces are fine without quotes (the script joins the words again),
but quote or escape shell metacharacters such as the parentheses and brackets
in dump names:

```sh
./build-flatpak.sh "/path/to/your/dump.zip"
./build-flatpak.sh /path/to/SenjinAleste.rar
./build-flatpak.sh "Senxin Aleste (1.02.00)(2022-01-25)(JPN)[Sega ALLS][TP].zip"
```

An existing `game.zip` is reused while its executable hash matches, so the
dump is not copied again on every build. Pass another dump or delete
`game.zip` to make the script search from scratch.

The script checks the dump layout, installs the Freedesktop runtime and SDK if
they are missing, downloads the two Python wheels if they are missing, builds
with `flatpak-builder`, exports the result into the persistent `repo/`
directory (ignored by git) and installs it through a single local remote called
`senjin-local`. The manifest uses this
directory as its source tree (`{"type": "dir", "path": "."}`), so it always
builds the checkout you are running from; no source snapshot is needed.

`flatpak-builder` splits the debug symbols of the binary into a separate
`io.github.senjinaleste.Recomp.Debug` runtime. It is **not** needed to play:
the script does not install it and removes one left by an older build, so it
does not appear as a pinned runtime in `flatpak uninstall --unused`. If you
want the symbols for `gdb`, run `./build-flatpak.sh --debug`.

The remote is left disabled after the install: the app is built locally, so
`flatpak update` has nothing to fetch and stays quiet, even if you later move
or delete the checkout. **To update the app, run `./build-flatpak.sh`
again**; it rebuilds and reinstalls from the local repository.

If you prefer to run `flatpak-builder` by hand, make sure `flatpak/wheels/`
contains the two wheels first (run `./build-flatpak.sh` once, or download them
from the URLs in the script), then:

```sh
# Normalize a zip/rar/7z/folder into game.zip (same check as the script):
python3 tools/find_game.py --sha256-file recomp/exe.sha256 \
    --output game.zip --input "/path/to/your/dump.zip"

flatpak-builder --user --force-clean --disable-rofiles-fuse --repo=repo \
    build-dir io.github.senjinaleste.Recomp.json
flatpak remote-add --user --if-not-exists --no-gpg-verify --no-use-for-deps \
    senjin-local "file://$PWD/repo"
flatpak install --user --reinstall senjin-local \
    io.github.senjinaleste.Recomp//master
flatpak remote-modify --user --disable senjin-local
```

`./build-flatpak.sh` does the same, removes the remotes of older builds and
keeps the debug runtime out unless you pass `--debug`.

The manifest uses `game.zip`; no particular dump name is hardcoded in the
repository.

### Troubleshooting

- `Unable to get source file 'flatpak/wheels/...'`: run
  `./build-flatpak.sh` from the repository root; it downloads the wheels into
  `flatpak/wheels/`. Do not create `wheels/` at the repository root.
- `Can't load 'io.github.senjinaleste.Recomp.json'`: you are not in the
  repository root. `cd` to the directory that contains the manifest.
- `org.freedesktop.Sdk/x86_64/26.08 not installed` or `Unable to find sdk
  org.freedesktop.Sdk version 26.08`: `build-flatpak.sh` installs the runtime
  and SDK automatically, trying your existing user remotes first, then system
  remotes, and finally adding Flathub as a user remote. If that fails, install
  them manually:

  ```sh
  flatpak install -y flathub \
      org.freedesktop.Platform//26.08 org.freedesktop.Sdk//26.08
  ```

  Or add Flathub to your user installation and install per-user:

  ```sh
  flatpak remote-add --if-not-exists --user flathub \
      https://flathub.org/repo/flathub.flatpakrepo
  flatpak install -y --user flathub \
      org.freedesktop.Platform//26.08 org.freedesktop.Sdk//26.08
  ```

- `flatpak update` reports `No se encontró la ref. «.../master» en el remoto
  recomp-origin` (or `debug-origin`), or `Unable to update ...: Remote "..."
  not found`: this comes from an install made by an older `build-flatpak.sh`,
  which used `flatpak-builder --install`. That command creates throw-away
  `*-origin` remotes pointing at the repository of one particular build, so
  they break as soon as the checkout moves or the repository is rebuilt
  elsewhere. Run `./build-flatpak.sh` again: it reinstalls the app from the
  `senjin-local` remote and only then deletes the old `*-origin` remotes (in
  that order, so nothing is left pointing at a deleted remote). Deleting the
  old remotes by hand without reinstalling first makes `flatpak update` fail
  with `Remote ... not found` for the installed refs.

  If you only want to clean up without rebuilding, reinstall from the existing
  `repo/` first, then remove the remotes:

  ```sh
  flatpak remote-add --user --if-not-exists --no-gpg-verify \
      --no-use-for-deps senjin-local "file://$PWD/repo"
  flatpak install --user --reinstall senjin-local \
      io.github.senjinaleste.Recomp//master \
      io.github.senjinaleste.Recomp.Debug//master
  flatpak remote-modify --user --disable senjin-local
  flatpak remote-delete --user --force recomp-origin
  flatpak remote-delete --user --force debug-origin
  ```

## Run

After installation, **Senjin Aleste** also appears in the desktop application
menu (GNOME, KDE, and other freedesktop-compliant environments) with a
placeholder gamepad icon. The menu entry runs the same
`senjin-aleste-launch` wrapper, so it uses the writable data directory
described below.

You can still start it from a terminal:

```sh
flatpak run io.github.senjinaleste.Recomp
```

`flatpak update` leaves the app alone on purpose (the `senjin-local` remote is
disabled): rebuild with `./build-flatpak.sh` to get a new version, and check
`flatpak list --app` / `flatpak remote-ls senjin-local` to see what is
installed locally. `flatpak remotes` hides disabled remotes, so `senjin-local`
only shows up there with `flatpak remotes --show-disabled`.

If the menu entry does not appear immediately, log out and back in (or check
that the app is installed with `flatpak list --app`). The icon is a
placeholder; replace `flatpak/io.github.senjinaleste.Recomp.svg` with your own
SVG and rebuild if you want a different one.

## Flatseal / application details

The package ships AppStream metadata
(`flatpak/io.github.senjinaleste.Recomp.metainfo.xml`), so Flatseal and app
stores show the real name, developer, version and release date instead of the
app-ID fallback.

Flatseal may also list a **Background** portal permission. This is not
declared by the Flatpak manifest and the game does not need it; it is a
host-side xdg-desktop-portal permission. Turn it off in Flatseal, or remove
the stored permission:

```sh
flatpak permission-remove background background io.github.senjinaleste.Recomp
```

## Where the game writes

`/app` is read-only, but the game writes `config.txt`, `aleste.ini`,
`save.dat`, rankings and replays into its own folder. On first start the
launcher copies the game data to:

```
~/.var/app/io.github.senjinaleste.Recomp/data/senjin-aleste/game
```

It then `cd`s there and starts the game. The copy uses `cp -an`, so existing
settings and saves are never overwritten when the Flatpak is updated.

To reset the writable game data (keeping the Flatpak installed):

```sh
rm -rf ~/.var/app/io.github.senjinaleste.Recomp/data/senjin-aleste
```

## Permissions

- `--socket=wayland`, `--socket=fallback-x11`: Wayland, with X11 fallback.
- `--socket=pulseaudio`, `--device=dri`, `--device=input`: audio, GPU and
  gamepads.
- `--nofilesystem=home`, `--nofilesystem=host`, `--unshare=network`: no home,
  host or network access. The app's own `~/.var/app/...` directory remains
  writable.
- No external ffmpeg: the Freedesktop 26.08 runtime ships `ffmpeg`, which the
  game uses for xWMA decoding.
- Python build dependencies (`capstone`, `pefile`) are downloaded by
  `build-flatpak.sh` into `flatpak/wheels/` and installed with `--no-index`;
  the Flatpak build itself does not need network access.

## Japanese font

The runtime does not ship fonts; Flatpak exposes the host fonts through
fontconfig. If the game shows `????`, install a Japanese font on the host, for
example `google-noto-sans-cjk-fonts`:

```sh
# Silverblue/Bazzite
rpm-ostree install google-noto-sans-cjk-fonts
# or, without layering, copy a font to ~/.local/share/fonts and run fc-cache -f
```

Then restart the app.

## Uninstall

```sh
flatpak uninstall io.github.senjinaleste.Recomp
flatpak remote-delete --user senjin-local
rm -rf ~/.var/app/io.github.senjinaleste.Recomp
```

`flatpak uninstall` also removes the debug runtime. Removing the
`senjin-local` remote and the `repo/` directory is optional: they are only
used by `./build-flatpak.sh`, and the remote is disabled, so `flatpak update`
never reads them. Keep `repo/` if you plan to rebuild (the next build reuses
it); deleting it only makes the next export start from scratch.

`flatpak uninstall --unused` may report that
`runtime/org.freedesktop.Sdk/x86_64/26.08` is pinned and will not be removed.
That is normal: flatpak pins every runtime it installs explicitly, and the SDK
is only used to build. It is not an error, and keeping it avoids downloading
the SDK again on the next build. To drop it anyway:

```sh
flatpak pin --remove runtime/org.freedesktop.Sdk/x86_64/26.08
flatpak uninstall --unused
```

## Legal

The Flatpak is for your own copy of the game. Do not distribute a bundle that
contains the game executable or `windata/`.
