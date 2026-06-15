# Changelog

All notable changes to solstone-linux are documented here.
The format is based on Keep a Changelog (https://keepachangelog.com/),
and this project adheres to Semantic Versioning.

## [0.3.1] - 2026-06-15

### Changed
- chat notifications now use the journal's current callosum connection path,
  with the observer key still sent in the authorization header.

## [0.3.0] - 2026-06-14

setup is now zero-config: the observer connects to your journal automatically,
with no url to type.

### Changed
- setup no longer asks for a journal url. if your journal runs on another
  machine you reach directly, set its address with
  `solstone-linux setup --server-url <url>`.

## [0.2.0] - 2026-06-13

setup is now hands-off: the first time the observer runs, it connects itself
to your journal automatically, with no separate key step.

### Changed

- **first run sets itself up.** earlier versions asked you to create and paste
  a key to connect the observer to your journal. now the observer introduces
  itself to your journal on first run and remembers the connection on its own.
  you go straight from install to observing, with no manual key step.

## [0.1.1] - 2026-06-02

A focused maintenance release: two reliability fixes and a round of
install-instruction corrections from fresh-machine testing on Fedora,
Debian, and openSUSE.

### Fixed

- **Idle monitors no longer silently drop observations.** When a monitor
  produced no frames during a segment (a static screen with nothing
  changing on it), GStreamer still wrote a header-only WebM file. Those
  empty files were finalized, uploaded, and then failed to process in your
  journal — so that monitor's segment was lost without any signal. The
  observer now drops these empty recordings at the source and emits an
  `observe.stream_silent` event (logged at WARNING) so the gap is visible
  instead of silent.
- **Install no longer clobbers your system icon theme.** On GNOME,
  `install-service` was writing a stray `index.theme` into the shared
  hicolor icon directory, which shadowed the system index and caused
  unrelated app icons to render as the solstone diamond. The installer now
  drops only the solstone status icons (the system index already declares
  their directory) and self-heals any previously broken install on the next
  `install-service` run. A foreign or unreadable `index.theme` is left
  untouched.

### Documentation

- Corrected the Fedora and Debian system-dependency lines after fresh-box
  install testing: dropped packages that do not exist in their repos
  (`gstreamer1-plugin-pipewire` on Fedora, `gir1.2-gdk-4.0` on Debian) and
  hoisted the cairo / pycairo build toolchain onto the main install line so
  a fresh install succeeds in one shot. Added `gstreamer1.0-tools` to the
  Debian line — `gst-launch-1.0` is required for screen recording and is
  not pulled in transitively.
- Added a verified openSUSE dependency block and mirrored the corrected
  dependency lists between `README.md` and `INSTALL.md`.
- Updated the install path to lead with `pipx install solstone-linux`, then
  `solstone-linux install-service`, then `solstone-linux setup`.

### Internal

- The release script now tags the commit and cuts a GitHub release only on
  a production PyPI run; a TestPyPI run no longer leaves a tag or public
  release behind.

## [0.1.0] - 2026-05-19

First public release of solstone-linux — the Linux desktop observer
for your solstone journal.

solstone-linux runs as a systemd user service in your GNOME Wayland
session. It experiences screen and audio along with you, holds short
segments locally, and uploads them to your journal in the background.

### Install paths

- From PyPI: `pipx install --system-site-packages solstone-linux`,
  then `solstone-linux install-service` to register the systemd unit.
- From a clone: `git clone` this repo and run `make install-service`
  for development or unreleased changes.

Both paths rely on host packages for PyGObject, GStreamer with the
PipeWire plugin, PipeWire itself, `pactl`, and `xdg-desktop-portal`
with ScreenCast support. PyGObject and the GStreamer bindings ride
along from system site-packages — that is why `--system-site-packages`
matters.
