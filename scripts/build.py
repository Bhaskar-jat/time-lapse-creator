from __future__ import annotations

import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


APP_NAME = "Time Lapse Creator"
APP_BUNDLE_ID = "com.openai.timelapsecreator"
ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
SRC_DIR = ROOT / "src"


def run_command(command: list[str], retries: int = 0, retry_delay_seconds: float = 2.0) -> None:
    attempts_remaining = retries + 1
    while attempts_remaining > 0:
        try:
            subprocess.run(command, cwd=ROOT, check=True)
            return
        except subprocess.CalledProcessError:
            attempts_remaining -= 1
            if attempts_remaining == 0:
                raise
            time.sleep(retry_delay_seconds)


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
        command.extend(["--osx-bundle-identifier", APP_BUNDLE_ID])

    command.append(str(ROOT / "main.py"))
    run_command(command)


def app_bundle_path() -> Path:
    return DIST_DIR / f"{APP_NAME}.app"


def configure_macos_app_bundle(app_path: Path) -> None:
    info_plist_path = app_path / "Contents" / "Info.plist"
    if not info_plist_path.exists():
        raise RuntimeError(f"Expected Info.plist at {info_plist_path}")

    with info_plist_path.open("rb") as plist_file:
        info_plist = plistlib.load(plist_file)

    info_plist["CFBundleIdentifier"] = APP_BUNDLE_ID
    info_plist["CFBundleShortVersionString"] = "0.1.0"
    info_plist["CFBundleVersion"] = "0.1.0"
    info_plist["NSCameraUsageDescription"] = (
        "Time Lapse Creator uses the camera to capture the webcam overlay in your timelapse."
    )

    with info_plist_path.open("wb") as plist_file:
        plistlib.dump(info_plist, plist_file)

    run_command(
        [
            "codesign",
            "--force",
            "--deep",
            "--sign",
            "-",
            str(app_path),
        ]
    )


def create_macos_zip(app_path: Path) -> Path:
    zip_path = DIST_DIR / "Time-Lapse-Creator-macOS.zip"
    if zip_path.exists():
        zip_path.unlink()

    run_command(
        [
            "ditto",
            "-c",
            "-k",
            "--sequesterRsrc",
            "--keepParent",
            str(app_path),
            str(zip_path),
        ]
    )
    return zip_path


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

    with tempfile.TemporaryDirectory(dir=BUILD_DIR) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        temp_rw_dmg = temp_dir / "Time-Lapse-Creator-temp.dmg"
        temp_final_dmg = temp_dir / "Time-Lapse-Creator.dmg"

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
                "UDRW",
                str(temp_rw_dmg),
            ],
            retries=2,
        )

        run_command(
            [
                "hdiutil",
                "convert",
                str(temp_rw_dmg),
                "-ov",
                "-format",
                "UDZO",
                "-o",
                str(temp_final_dmg),
            ],
            retries=2,
        )

        shutil.move(temp_final_dmg, dmg_path)
    return dmg_path


def main() -> int:
    clean_artifacts()
    build_with_pyinstaller()

    system = platform.system()
    if system == "Darwin":
        app_path = app_bundle_path()
        configure_macos_app_bundle(app_path)
        zip_path = create_macos_zip(app_path)
        dmg_path = create_dmg()
        print(f"Created macOS app bundle at {app_path}")
        print(f"Created macOS ZIP at {zip_path}")
        print(f"Created macOS DMG at {dmg_path}")
    elif system == "Windows":
        print(f"Created Windows executable at {DIST_DIR / f'{APP_NAME}.exe'}")
    else:
        print(f"Created Linux bundle in {DIST_DIR}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
