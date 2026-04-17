# solstone-linux

Standalone Linux desktop observer for [solstone](https://solpbc.org). Captures screen and audio from a GNOME Wayland session, stores segments locally, and syncs to a solstone server.

**Note:** Activity detection (idle timeout, screen lock, power save) currently requires a GNOME desktop. On other desktops (KDE, Sway, Hyprland, XFCE), screen and audio capture works but activity-based segment boundaries won't trigger.

## System Dependencies

**Fedora:**
```bash
dnf install python3-gobject gtk4 gstreamer1-plugins-base gstreamer1-plugin-pipewire pipewire-gstreamer alsa-lib-devel pulseaudio-utils pipewire-pulseaudio
```

**Debian/Ubuntu:**
```bash
apt install python3-gi gir1.2-gdk-4.0 gir1.2-gtk-4.0 gstreamer1.0-pipewire libasound2-dev pulseaudio-utils pipewire-pulse
```

**Arch:**
```bash
pacman -S python-gobject gtk4 gstreamer gst-plugin-pipewire libpulse alsa-lib
```

## Install

For a first-time install on this machine:

```bash
git clone https://github.com/solpbc/solstone-linux.git
cd solstone-linux
make install-service
solstone-linux setup
```

See `INSTALL.md` for distro packages, tray notes, and troubleshooting details.

## Setup

```bash
solstone-linux setup
```

## Run

```bash
# Foreground
solstone-linux run
```

## Status

```bash
solstone-linux status
```

## License

AGPL-3.0-only — Copyright (c) 2026 sol pbc
