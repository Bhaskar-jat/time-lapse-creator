# Time Lapse Creator

Small cross-platform Python desktop app that records all connected displays as a single 1080p timelapse, with a circular webcam overlay in the bottom-right corner.

## What it does

- Shows a compact desktop window with `Start`, `Pause`, and `Stop` controls.
- Captures every connected display and arranges them in one frame using the monitors' real screen layout.
- Scales the merged desktop into a single 1920×1080 output frame.
- Overlays the latest webcam frame as a circular picture-in-picture in the lower-right corner.
- Records at a default cadence that turns **1 hour of real time into 1 minute of video**.
- Displays the current recording duration and the estimated video length if you stopped immediately.
- Saves sessions to your `Downloads/Time Lapse Creator/` folder by default.
- Lets you change the save location from the app window before starting a recording.
- Lets you switch between `Merged screens + camera` and `Camera only` capture modes.
- Remembers the last-used save folder and capture mode between app launches.
- Opens with a pink gradient theme by default.
- Includes multiple built-in themes, quick accent presets, and custom color pickers for the background and buttons.
- Renders the captured screenshots into a video when you press `Stop`.

## Why the timing works

The app defaults to:

- `30 FPS` output video
- `60x` timelapse speed
- `2 seconds` between captures

That means 3,600 seconds of real recording generates 1,800 frames, which becomes 60 seconds of video at 30 FPS.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell, activate with:

```powershell
.venv\Scripts\Activate.ps1
```

## Run

```bash
python main.py
```

Or install it as a package and use:

```bash
pip install -e .
time-lapse-creator
```

## Output

- Recordings are written under `~/Downloads/Time Lapse Creator/session-YYYYMMDD-HHMMSS/` by default
- Raw captures go to `.../frames/` inside the same session folder
- Final video is saved as `timelapse.mp4` when supported, otherwise an `.avi` fallback is used
- Use `Change Save Folder` in the app to pick a different location for both frames and videos
- Use the capture mode selector in the app to switch between desktop+camera output and camera-only output

## Build desktop apps

Install build tooling:

```bash
pip install -r requirements.txt -r requirements-build.txt
```

Create a packaged app for the current platform:

```bash
python scripts/build.py
```

Platform results:

- On macOS, the script builds `dist/Time Lapse Creator.app` and `dist/Time-Lapse-Creator.dmg`
- On Windows, the same script builds `dist/Time Lapse Creator.exe`

Because PyInstaller does not cross-compile between macOS and Windows, the `.dmg` must be built on macOS and the `.exe` must be built on Windows.

## GitHub builds and sharing

The repo now includes a GitHub Actions workflow at `.github/workflows/build-release.yml`.

- `workflow_dispatch`: lets you run builds manually from the GitHub Actions tab
- `push tags v*`: builds macOS and Windows apps, then publishes them to a GitHub Release

Recommended release flow:

```bash
git tag v0.1.0
git push origin v0.1.0
```

After that finishes:

- Share the release page with friends: `https://github.com/<your-user>/<your-repo>/releases/tag/v0.1.0`
- Or share the direct Windows download: `https://github.com/<your-user>/<your-repo>/releases/download/v0.1.0/Time%20Lapse%20Creator.exe`
- Or share the direct macOS download: `https://github.com/<your-user>/<your-repo>/releases/download/v0.1.0/Time-Lapse-Creator.dmg`

## macOS permissions

macOS requires you to allow:

- `Screen Recording` access for the Python app/interpreter you launch
- `Camera` access for the same Python app/interpreter

Without those permissions, screen capture or webcam overlay will be unavailable.

## Notes

- The layout logic uses the monitors' real geometry, so mixed horizontal and vertical monitor setups are preserved automatically.
- `Pause` stops adding new frames and keeps the current session open.
- `Stop` finishes the session and renders the video.
- If no webcam is available, the app still records the screens and shows a neutral preview circle.
