# Changelog

All notable changes to solstone-linux are documented here.
The format is based on Keep a Changelog (https://keepachangelog.com/),
and this project adheres to Semantic Versioning.

## Unreleased

- Added frame-count silent-stream detection, in-flight stream liveness checks,
  per-connector recovery escalation, D-Bus `StreamHealth`, and a tray
  degradation glyph so a silent HDMI stream cannot go unnoticed like the
  82-hour right-HDMI incident.

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
