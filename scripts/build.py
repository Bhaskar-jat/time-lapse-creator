from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = "Time Lapse Creator"
ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
SRC_DIR = ROOT / "src"


def run_command(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def clean_artifacts() -> None:
    shutil.rmtree(DIST_DIR, ignore_errors=True)
    shutil.rmtree(BUILD_DIR, ignore_errors=True)


def build_with_pyinstaller() -> None:
    system = platform.system()
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        APP_NAME,
        "--paths",
        str(SRC_DIR),
        "--windowed",
    ]

    if system == "Windows":
        command.append("--onefile")
    elif system == "Darwin":
        command.extend(["--osx-bundle-identifier", "com.openai.timelapsecreator"])

    command.append(str(ROOT / "main.py"))
    run_command(command)


def create_dmg() -> Path:
    if platform.system() != "Darwin":
        raise RuntimeError("DMG creation is only available on macOS.")

    app_path = DIST_DIR / f"{APP_NAME}.app"
    if not app_path.exists():
        raise RuntimeError(f"Expected app bundle at {app_path}")

    dmg_staging_dir = BUILD_DIR / "dmg"
    shutil.rmtree(dmg_staging_dir, ignore_errors=True)
    dmg_staging_dir.mkdir(parents=True, exist_ok=True)

    staged_app_path = dmg_staging_dir / app_path.name
    shutil.copytree(app_path, staged_app_path)

    applications_link = dmg_staging_dir / "Applications"
    if applications_link.exists() or applications_link.is_symlink():
        applications_link.unlink()
    applications_link.symlink_to("/Applications")

    dmg_path = DIST_DIR / "Time-Lapse-Creator.dmg"
    if dmg_path.exists():
        dmg_path.unlink()

    run_command(
        [
            "hdiutil",
            "create",
            "-volname",
            APP_NAME,
            "-srcfolder",
            str(dmg_staging_dir),
            "-ov",
            "-format",
            "UDZO",
            str(dmg_path),
        ]
    )
    return dmg_path


def main() -> int:
    clean_artifacts()
    build_with_pyinstaller()

    system = platform.system()
    if system == "Darwin":
        dmg_path = create_dmg()
        print(f"Created macOS app bundle at {DIST_DIR / f'{APP_NAME}.app'}")
        print(f"Created macOS DMG at {dmg_path}")
    elif system == "Windows":
        print(f"Created Windows executable at {DIST_DIR / f'{APP_NAME}.exe'}")
    else:
        print(f"Created Linux bundle in {DIST_DIR}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
