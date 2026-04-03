# solstone-linux

Standalone Linux desktop observer for [solstone](https://solpbc.org). Captures screen and audio from a GNOME Wayland session, stores segments locally, and syncs to a solstone server.

## System Dependencies

**Fedora:**
```bash
dnf install python3-gobject gtk4 gstreamer1-plugins-base pipewire-gstreamer alsa-lib-devel pulseaudio-utils pipewire-pulseaudio
```

**Debian/Ubuntu:**
```bash
apt install python3-gi gir1.2-gdk-4.0 gir1.2-gtk-4.0 gstreamer1.0-pipewire libasound2-dev pulseaudio-utils pipewire-pulse
```

## Install

```bash
pipx install --system-site-packages solstone-linux
```

`--system-site-packages` is required for PyGObject/GStreamer access.

## Setup

```bash
solstone-linux setup
```

## Run

```bash
# Foreground
solstone-linux run

# As a systemd user service
solstone-linux install-service
```

## Status

```bash
solstone-linux status
```

## License

AGPL-3.0-only — Copyright (c) 2026 sol pbc
