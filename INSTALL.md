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

1. install system dependencies for your distro, including `pipx`. if you need sudo, walk your human through it.

   **fedora:**
   ```
   sudo dnf install python3-gobject gtk4 gstreamer1-plugins-base gstreamer1-plugin-pipewire pipewire-gstreamer alsa-lib-devel pulseaudio-utils pipewire-pulseaudio xdg-desktop-portal pipx
   ```

   **debian / ubuntu:**
   ```
   sudo apt install python3-gi gir1.2-gdk-4.0 gir1.2-gtk-4.0 gstreamer1.0-pipewire libasound2-dev pulseaudio-utils pipewire-pulse xdg-desktop-portal pipx
   ```

   **arch:**
   ```
   sudo pacman -S python-gobject gtk4 gstreamer gst-plugin-pipewire libpulse alsa-lib xdg-desktop-portal pipx
   ```

2. if not already cloned, clone into solstone's observers directory and deploy:
   ```
   cd "$(sol root)/observers"
   git clone https://github.com/solpbc/solstone-linux.git
   cd solstone-linux
   make deploy
   ```
   `make deploy` installs with pipx using `--system-site-packages`, then installs and starts the user service.

3. run the interactive setup:
   ```
   solstone-linux setup
   ```
   this prompts for the server URL and auto-registers via `sol` when available.

4. verify the service is running:
   ```
   systemctl --user status solstone-linux
   ```

## updating after a code change

```
git pull && make upgrade
```

## notes

- activity detection (idle timeout, screen lock, power save) works on both GNOME and KDE. other desktops capture screen and audio fine but may not get activity-based segment boundaries.
- the tray icon uses the StatusNotifierItem (SNI) D-Bus protocol. it works on KDE natively and GNOME with the AppIndicator extension. if no SNI host is available, the observer runs normally without a tray icon.

## appendix: GNOME tray support

the system tray icon appears automatically when the observer starts in a graphical session. on KDE Plasma this works out of the box. on GNOME, the AppIndicator extension is required.

GNOME removed native system tray support. the AppIndicator extension restores it via the same StatusNotifierItem protocol KDE uses. without it, the observer runs fine but has no tray icon.

**ubuntu:** already installed and enabled by default — skip this step.

**fedora:**
```
sudo dnf install gnome-shell-extension-appindicator
```
then log out and back in, or restart GNOME Shell (Alt+F2, type `r`, enter). enable the extension in GNOME Extensions app if not auto-enabled.

**arch:**
```
sudo pacman -S gnome-shell-extension-appindicator
```

to check if it's working: `gnome-extensions list | grep appindicator` should show it. if the tray icon still doesn't appear, verify it's enabled: `gnome-extensions enable appindicatorsupport@rgcjonas.gmail.com`
