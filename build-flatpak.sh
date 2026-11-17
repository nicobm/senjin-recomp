#!/bin/sh
# Build and install the Flatpak locally.
#
# Run this inside `toolbox enter` (the Fedora toolbox has flatpak-builder),
# from the repository root:
#
#   ./build-flatpak.sh [--debug] "/path/to/your/game/dump.zip"
#
# or copy your dump to game.zip and run:
#
#   ./build-flatpak.sh [--debug]
#
# --debug also installs the <app-id>.Debug runtime (the debug symbols that
# flatpak-builder splits out of the build); it is only useful with gdb and is
# not needed to play, so it is not installed by default.
#
# The manifest uses this directory as its source tree and a generic game.zip
# for the game data: the repository never hardcodes the name of a particular
# dump, and no source snapshot is needed.  The Freedesktop Platform and SDK
# 26.08 are installed automatically if they are missing, and the Python build
# dependencies are downloaded into flatpak/wheels/ on the first run; the
# Flatpak build itself has no network access.
#
# The result is exported to the persistent repo/ directory and installed
# through one local remote, "senjin-local", which is left disabled: the app
# is built locally, so `flatpak update` has nothing to fetch.  To update it,
# run this script again.
set -eu
cd "$(dirname "$0")"

APP_ID="io.github.senjinaleste.Recomp"
DEBUG_ID="$APP_ID.Debug"
LOCAL_REMOTE="senjin-local"

# --debug: also install the debug runtime (see the comment at the top).
WITH_DEBUG=0
while [ $# -gt 0 ]; do
    case "$1" in
        --debug) WITH_DEBUG=1; shift ;;
        --) shift; break ;;
        *) break ;;
    esac
done

# 1. Flatpak tooling.
command -v flatpak >/dev/null 2>&1 || {
    echo "error: flatpak is not installed" >&2
    exit 1
}
command -v flatpak-builder >/dev/null 2>&1 || {
    echo "error: flatpak-builder is not installed (inside the toolbox: sudo dnf install flatpak-builder)" >&2
    exit 1
}

# 2. The user's game data, under the generic name the manifest expects.
if [ $# -ge 1 ]; then
    if [ ! -e game.zip ] || [ "$(realpath "$1")" != "$(realpath game.zip)" ]; then
        cp -f "$1" game.zip
    fi
fi
[ -f game.zip ] || {
    echo "error: game.zip not found; pass the path to your dump or copy it as game.zip" >&2
    exit 1
}
python3 - "$PWD/game.zip" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    names = z.namelist()
if "senxin_aleste_apm3.exe" not in names:
    sys.exit("error: game.zip does not contain senxin_aleste_apm3.exe")
if not any(n.startswith("windata/") for n in names):
    sys.exit("error: game.zip does not contain windata/")
PY

# 3. The Freedesktop runtime and SDK required by the manifest.  Install them
#    if they are missing: use existing user remotes first, then system remotes
#    (Fedora usually configures its remotes system-wide), and add Flathub as a
#    user remote only as a last resort.
RUNTIME_REF="org.freedesktop.Platform//26.08"
SDK_REF="org.freedesktop.Sdk//26.08"

flatpak_ref_installed() {
    flatpak info "$1" >/dev/null 2>&1
}

flatpak_has_remote() {
    # `flatpak remotes` hides disabled remotes unless --show-disabled is given,
    # and senjin-local is disabled between builds; without it, a second run
    # would not find the remote and `remote-add` would fail with
    # "Remote senjin-local already exists".  Older flatpak has no
    # --show-disabled, so fall back to the plain listing.
    remotes=$(flatpak remotes "$1" --show-disabled --columns=name 2>/dev/null) ||
        remotes=$(flatpak remotes "$1" --columns=name 2>/dev/null) || return 1
    printf '%s\n' "$remotes" | grep -qx "$2"
}

install_flatpak_ref() {
    ref="$1"
    flatpak_ref_installed "$ref" && return 0

    # Prefer the user installation: it needs no root and is the same
    # installation flatpak-builder --user uses.
    for remote in flathub flathub-verified_floss flathub-floss fedora; do
        if flatpak_has_remote --user "$remote"; then
            echo "Installing $ref from $remote (user)..."
            if flatpak install -y --user "$remote" "$ref"; then
                flatpak_ref_installed "$ref" && return 0
            fi
        fi
    done

    # Fedora normally configures its remotes system-wide, and --user cannot
    # use a system remote.  Try the system installation next.
    for remote in flathub flathub-verified_floss flathub-floss fedora; do
        if flatpak_has_remote --system "$remote"; then
            echo "Installing $ref from $remote (system)..."
            if flatpak install -y "$remote" "$ref"; then
                flatpak_ref_installed "$ref" && return 0
            fi
        fi
    done

    # Last resort: add Flathub as a user remote and install there.
    if ! flatpak_has_remote --user flathub; then
        echo "Adding the Flathub remote (user)..."
        if flatpak remote-add --if-not-exists --user flathub \
                https://flathub.org/repo/flathub.flatpakrepo; then
            echo "Installing $ref from flathub (user)..."
            if flatpak install -y --user flathub "$ref"; then
                flatpak_ref_installed "$ref" && return 0
            fi
        fi
    fi

    echo "error: could not install $ref" >&2
    echo "  install it manually with:" >&2
    echo "    flatpak install -y flathub $RUNTIME_REF $SDK_REF" >&2
    echo "  (or add Flathub to your user installation and use --user)" >&2
    return 1
}

install_flatpak_ref "$RUNTIME_REF" || exit 1
install_flatpak_ref "$SDK_REF" || exit 1

# 4. Python build dependencies.  flatpak-builder needs them before it starts
#    the build, and the build sandbox has no network: fetch the exact wheels
#    once and keep them in flatpak/wheels/ (ignored by git).
WHEELS="flatpak/wheels"
CAPSTONE="capstone-5.0.9-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
PEFILE="pefile-2024.8.26-py3-none-any.whl"
CAPSTONE_SHA256="273fd8d747d2e35c88f91450be51a603ecfaafb00d96d9f315dcb8689c86193e"
PEFILE_SHA256="76f8b485dcd3b1bb8166f1128d395fa3d87af26360c2358fb75b80019b957c6f"
CAPSTONE_URL="https://files.pythonhosted.org/packages/d1/39/17747862222bb062e86b501f1f148d5ff589b77908b080d30f7f085cbfb7/$CAPSTONE"
PEFILE_URL="https://files.pythonhosted.org/packages/54/16/12b82f791c7f50ddec566873d5bdd245baa1491bac11d15ffb98aecc8f8b/$PEFILE"

check_sha256() {
    [ -f "$1" ] || return 1
    command -v sha256sum >/dev/null 2>&1 || return 0
    [ "$(sha256sum "$1" | cut -d' ' -f1)" = "$2" ]
}

fetch_wheel() {
    url="$1"; out="$2"; sha="$3"
    if check_sha256 "$out" "$sha"; then
        return 0
    fi
    rm -f "$out" "$out.part"
    echo "Downloading $(basename "$out")..."
    if command -v curl >/dev/null 2>&1; then
        curl -fL --retry 3 -o "$out.part" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -O "$out.part" "$url"
    else
        echo "error: need curl or wget to download $out" >&2
        exit 1
    fi
    mv -f "$out.part" "$out"
    if ! check_sha256 "$out" "$sha"; then
        echo "error: wrong sha256 for $out" >&2
        echo "  expected: $sha" >&2
        exit 1
    fi
}

mkdir -p "$WHEELS"
fetch_wheel "$CAPSTONE_URL" "$WHEELS/$CAPSTONE" "$CAPSTONE_SHA256"
fetch_wheel "$PEFILE_URL" "$WHEELS/$PEFILE" "$PEFILE_SHA256"

# 5. Build, export and install for the current user.
#
#    `flatpak-builder --install` installs the app through throw-away
#    "<last-id-component>-origin" remotes (recomp-origin, debug-origin, and
#    recomp1-origin/... when those names are taken).  Those remotes point at
#    the repository of one particular build, so as soon as the checkout moves,
#    or the repository is rebuilt elsewhere, every `flatpak update` prints
#
#      No se encontró la ref. «app/io.github.senjinaleste.Recomp/x86_64/master»
#      en el remoto recomp-origin
#
#    and keeps doing it until the remote is deleted.  Deleting the remote
#    alone is not enough either: flatpak then cannot resolve the origin of the
#    installed refs and reports "Remote ... not found".
#
#    Instead, export into the persistent repo/ directory and install from one
#    stable local remote, "senjin-local".  The remote is left disabled: the
#    app is built locally, so `flatpak update` has nothing to fetch, and a
#    disabled remote cannot fail later (for example if repo/ is deleted).  To
#    update the app, run this script again.

flatpak_origin_of() {
    flatpak info --user --show-origin "$1" 2>/dev/null || true
}

# Origin remotes used by an app or debug runtime installed by an older
# version of this script.  They are deleted after the refs have been
# reinstalled from senjin-local below, never before: deleting them first would
# leave `flatpak update` with refs whose origin does not exist.
STALE_ORIGINS=""
# `flatpak list --columns=ref` prints refs without the kind prefix
# (io.github.senjinaleste.Recomp/x86_64/master), unlike `flatpak remote-ls`;
# accept both spellings.
for ref in $(flatpak list --user --all --columns=ref 2>/dev/null); do
    case "$ref" in
        app/"$APP_ID"/*|"$APP_ID"/*|runtime/"$DEBUG_ID"/*|"$DEBUG_ID"/*) ;;
        *) continue ;;
    esac
    origin=$(flatpak_origin_of "$ref")
    case "$origin" in
        ""|-|"$LOCAL_REMOTE") continue ;;
        *-origin) ;;
        *) continue ;;
    esac
    case " $STALE_ORIGINS " in
        *" $origin "*) ;;
        *) STALE_ORIGINS="$STALE_ORIGINS $origin" ;;
    esac
done

echo "Building $APP_ID (this takes a few minutes)..."
flatpak-builder --user --force-clean --disable-rofiles-fuse \
    --repo="$PWD/repo" build-dir io.github.senjinaleste.Recomp.json

# The remote URL is a file:// URI; the checkout path may contain spaces, so
# let Python escape it.
repo_uri=$(python3 -c 'import pathlib, sys
print(pathlib.Path(sys.argv[1]).as_uri())' "$PWD/repo")

# Do not add --no-enumerate: flatpak hides the refs of a no-enumerate remote
# from `flatpak remote-ls` unless it has an xa.main-ref set (see
# flatpak_dir_list_remote_refs), and `flatpak remote-add` does not set one, so
# the remote would be listed but appear empty.  The remote is disabled after
# the install instead, which also keeps it out of app stores and updates.
if flatpak_has_remote --user "$LOCAL_REMOTE"; then
    flatpak remote-modify --user --no-gpg-verify --no-use-for-deps --enumerate \
        --enable --url="$repo_uri" "$LOCAL_REMOTE"
else
    flatpak remote-add --user --no-gpg-verify --no-use-for-deps \
        "$LOCAL_REMOTE" "$repo_uri"
fi

# Install the app, plus the debug runtime only with --debug: installing the
# app does not pull its debug extension.
# `flatpak remote-ls` prints full refs, `flatpak list` prints them without the
# kind prefix; both spellings are accepted here.
refs=$(flatpak remote-ls --user --all --columns=ref "$LOCAL_REMOTE" 2>/dev/null || true)

set --
if [ -n "$refs" ]; then
    while IFS= read -r ref; do
        case "$ref" in
            app/"$APP_ID"/*) set -- "$@" "$ref" ;;
            "$APP_ID"/*) set -- "$@" "app/$ref" ;;
            runtime/"$DEBUG_ID"/*)
                if [ "$WITH_DEBUG" = 1 ]; then set -- "$@" "$ref"; fi
                ;;
            "$DEBUG_ID"/*)
                if [ "$WITH_DEBUG" = 1 ]; then set -- "$@" "runtime/$ref"; fi
                ;;
        esac
    done <<EOF
$refs
EOF
else
    # The remote could not be listed: use the refs the export just wrote
    # (repo/refs/heads/<kind>/<id>/<arch>/<branch>).
    for ref in "$PWD"/repo/refs/heads/app/"$APP_ID"/*/*; do
        [ -f "$ref" ] || continue
        set -- "$@" "${ref#"$PWD"/repo/refs/heads/}"
    done
    if [ "$WITH_DEBUG" = 1 ]; then
        for ref in "$PWD"/repo/refs/heads/runtime/"$DEBUG_ID"/*/*; do
            [ -f "$ref" ] || continue
            set -- "$@" "${ref#"$PWD"/repo/refs/heads/}"
        done
    fi
fi
[ "$#" -gt 0 ] || {
    echo "error: $LOCAL_REMOTE ($repo_uri) does not provide $APP_ID" >&2
    echo "  check it with: flatpak remote-ls --user $LOCAL_REMOTE" >&2
    exit 1
}

flatpak install --user --reinstall --noninteractive "$LOCAL_REMOTE" "$@"

# The debug runtime is opt-in: remove one left installed by an older build (or
# installed by hand) so it stops showing up as a pinned runtime in
# `flatpak uninstall --unused`.  Run the script with --debug to keep it.
if [ "$WITH_DEBUG" = 0 ]; then
    for ref in $(flatpak list --user --all --columns=ref 2>/dev/null); do
        case "$ref" in
            runtime/"$DEBUG_ID"/*|"$DEBUG_ID"/*) ;;
            *) continue ;;
        esac
        echo "Removing the debug runtime $ref (use --debug to keep it)..."
        flatpak uninstall --user -y --noninteractive "$ref" >/dev/null 2>&1 || true
    done
fi

# Local builds are updated by running this script, not by `flatpak update`.
flatpak remote-modify --user --disable "$LOCAL_REMOTE" ||
    echo "warning: could not disable the $LOCAL_REMOTE remote" >&2

# Now the old origin remotes have no installed refs left.  --force is what
# makes the deletion work: without it flatpak refuses (and prompts to remove
# the refs) when a remote still has installed refs.
for remote in $STALE_ORIGINS; do
    flatpak_has_remote --user "$remote" || continue
    if flatpak list --user --all --columns=origin 2>/dev/null | grep -qxF "$remote"; then
        echo "warning: $remote is still the origin of an installed ref; keeping it" >&2
        continue
    fi
    echo "Removing the old Flatpak remote $remote..."
    flatpak remote-delete --user --force --noninteractive "$remote" >/dev/null 2>&1 ||
        echo "warning: could not remove the Flatpak remote $remote" >&2
done

echo "Installed $APP_ID. Run it with: flatpak run $APP_ID"
