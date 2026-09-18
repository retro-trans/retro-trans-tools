"""Exercise a real next-launch update using two isolated packaged executables."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from retro_trans import __version__
from retro_trans.catalog import atomic_json
from retro_trans.updater import update_directory


def main():
    candidate = (ROOT / "dist" / "Retro-Trans.exe").resolve()
    if os.name != "nt" or not candidate.is_file():
        raise SystemExit("Build dist/Retro-Trans.exe on Windows first.")
    with tempfile.TemporaryDirectory(prefix="retro-trans-update-check-") as folder:
        folder = Path(folder).resolve()
        hook = folder / "old_version.py"
        hook.write_text("import retro_trans\nretro_trans.__version__ = '0.0.0'\n", encoding="utf-8")
        # Only the isolated old-app fixture gets the overridden version.
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
            "--name", "Retro-Trans", "--runtime-hook", str(hook), "--distpath", str(folder / "installed"),
            "--workpath", str(folder / "build"), "--specpath", str(folder),
            "--add-data", str(ROOT / "retro_trans" / "resources") + ";retro_trans/resources", str(ROOT / "launch.py")]
        subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        target = folder / "installed" / "Retro-Trans.exe"
        old_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        environment = os.environ.copy()
        environment["LOCALAPPDATA"] = str(folder / "local-data")
        # Compute the same per-install location with this isolated data root.
        previous_local = os.environ.get("LOCALAPPDATA")
        try:
            os.environ["LOCALAPPDATA"] = environment["LOCALAPPDATA"]
            directory = update_directory(target)
        finally:
            if previous_local is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = previous_local
        directory.mkdir(parents=True)
        shutil.copyfile(candidate, directory / (digest + ".exe"))
        atomic_json(directory / "pending.json", {"version": __version__, "sha256": digest, "bytes": candidate.stat().st_size})
        settings = folder / "local-data" / "RetroTrans" / "settings.json"
        atomic_json(settings, {"last_browse_folder": "preserve-this-setting"})
        process = subprocess.Popen([str(target)], env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 60
            status = {}
            while time.monotonic() < deadline:
                try:
                    status = json.loads((directory / "status.json").read_text())
                    break
                except (OSError, ValueError):
                    time.sleep(0.2)
            assert status.get("message") == "Updated to " + __version__, status
            assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
            assert hashlib.sha256(target.with_name(target.name + ".previous").read_bytes()).hexdigest() == old_hash
            assert json.loads(settings.read_text())["last_browse_folder"] == "preserve-this-setting"
            assert not (directory / "pending.json").exists()
            print("Packaged next-launch update passed: verified replacement, startup, backup and settings.")
        finally:
            # Stop only processes belonging to this newly created test directory.
            environment["RETRO_TRANS_UPDATE_TEST_ROOT"] = str(folder) + os.sep
            subprocess.run(["powershell", "-NoProfile", "-Command",
                "Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($env:RETRO_TRANS_UPDATE_TEST_ROOT, [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }"],
                env=environment, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            process.wait(timeout=10)
            time.sleep(1)


if __name__ == "__main__":
    main()
