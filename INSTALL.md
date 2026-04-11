# installing solstone-linux

these instructions are for a coding agent and human working together. solstone-linux is a standalone observer that captures screen and audio on linux desktops using PipeWire and GStreamer, and uploads to a solstone server.

solstone must already be installed and running. if it isn't, start there: https://solstone.app/install

## before you begin

if `sol` is not in PATH, check `~/.local/bin/sol` or use `.venv/bin/sol` inside the solstone repo.

check if solstone-linux is already installed and running:

```
systemctl --user status solstone-linux
sol remote list
```

if it's already active and connected, you're done.

## what to sort out together

- **system dependencies.** the observer needs PyGObject, GStreamer, and PipeWire bindings from system packages. installing these requires sudo.
- **stream name.** this identifies the capture source. the machine's hostname is the typical choice.

## install sequence

1. install system dependencies for your distro. if you need sudo, walk your human through it.

   **fedora:**
   ```
   sudo dnf install python3-gobject gtk4 gstreamer1-plugins-base gstreamer1-plugin-pipewire pipewire-gstreamer alsa-lib-devel pulseaudio-utils pipewire-pulseaudio
   ```

   **debian / ubuntu:**
   ```
   sudo apt install python3-gi gir1.2-gdk-4.0 gir1.2-gtk-4.0 gstreamer1.0-pipewire libasound2-dev pulseaudio-utils pipewire-pulse
   ```

   **arch:**
   ```
   sudo pacman -S python-gobject gtk4 gstreamer gst-plugin-pipewire libpulse alsa-lib
   ```

2. if not already cloned, clone into solstone's observers directory and install with pipx:
   ```
   cd "$(sol root)/observers"
   git clone https://github.com/solpbc/solstone-linux.git
   cd solstone-linux
   ```
   ```
   pipx install --system-site-packages .
   ```
   `--system-site-packages` is required — the observer imports PyGObject and GStreamer bindings that only exist in system site-packages.

3. register the observer with solstone and save the API key:
   ```
   sol remote create solstone-linux
   ```

4. write the config to `~/.local/share/solstone-linux/config/config.json`:
   ```json
   {
     "server_url": "http://localhost:5015",
     "key": "THE_API_KEY_FROM_STEP_3",
     "stream": "HOSTNAME"
   }
   ```

5. install and start the systemd user service:
   ```
   solstone-linux install-service
   ```

6. install the system tray indicator (optional):
   ```
   solstone-linux install-tray
   ```
   this installs status icons and an XDG autostart entry so the tray app launches on login. to start it immediately: `solstone-tray &`

7. verify it's running and connected:
   ```
   systemctl --user status solstone-linux
   sol remote list
   ```

## notes

- activity detection (idle timeout, screen lock, power save) requires a GNOME desktop. other desktops capture screen and audio fine but won't get activity-based segment boundaries.
- if pipx is not installed: `pip install --user pipx` or install via your package manager.
