"""Verified, per-installation Windows updates staged for the next launch."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from . import __version__
from .core import Asset, GitHubClient, PatchError, cache_directory, check_cancel, sha256_file, valid_hash, valid_size
from .catalog import APP_REPO, atomic_json, version_key


def update_directory(target=None):
    target = Path(target or sys.executable).resolve()
    key = hashlib.sha256(str(target).casefold().encode("utf-8")).hexdigest()[:20]
    return cache_directory().parent / "updates" / key


def stage_update(client=None, directory=None, current=__version__, cancel=None):
    client = client or GitHubClient()
    directory = Path(directory) if directory else update_directory()
    release = client.json("https://api.github.com/repos/{}/releases/latest".format(APP_REPO), cancel)
    if release.get("draft") or release.get("prerelease"):
        return None
    version = release["tag_name"].lstrip("v")
    if version_key(version) <= version_key(current):
        return None
    try:
        status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
        if status.get("failed_version") == version:
            return "Update {} needs attention; see About / Updates.".format(version)
    except (OSError, ValueError):
        pass
    assets = {a["name"]: a for a in release["assets"]}
    metadata = assets.get("UPDATE.json")
    if not metadata:
        raise PatchError("App release has no UPDATE.json.")
    prefix = "https://github.com/{}/releases/download/{}/".format(APP_REPO, release["tag_name"])
    if metadata["browser_download_url"] != prefix + "UPDATE.json":
        raise PatchError("Unexpected app-update metadata URL.")
    raw = client.read(metadata["browser_download_url"], cancel)
    if len(raw) != metadata["size"] or metadata.get("digest") != "sha256:" + hashlib.sha256(raw).hexdigest():
        raise PatchError("App-update metadata failed verification.")
    data = json.loads(raw)
    if data.get("schema_version") != 1 or data.get("version") != version or data.get("platform") != "windows-x86_64" or data.get("asset") != "Retro-Trans.exe":
        raise PatchError("Unsupported application update metadata.")
    digest, size = valid_hash(data["sha256"]), valid_size(data["bytes"])
    asset = assets.get(data["asset"])
    if not asset or asset["size"] != size or asset.get("digest") != "sha256:" + digest or asset["browser_download_url"] != prefix + data["asset"]:
        raise PatchError("Application update disagrees with its release metadata.")
    # Download is interruptible; a pending update appears only after completion.
    download = client.download(Asset(data["asset"], asset["browser_download_url"], size, digest), directory / "downloads", cancel)
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / (digest + ".exe")
    if not candidate.exists() or sha256_file(candidate, cancel) != digest:
        fd, temp = tempfile.mkstemp(dir=str(directory), suffix=".part")
        os.close(fd)
        try:
            shutil.copyfile(download, temp)
            check_cancel(cancel)
            os.replace(temp, candidate)
        finally:
            Path(temp).unlink(missing_ok=True)
    check_cancel(cancel)
    atomic_json(directory / "pending.json", {"version": version, "sha256": digest, "bytes": size})
    return "App {} downloaded; installs on next launch.".format(version)


def pending_update(directory, current=__version__):
    directory = Path(directory)
    data = json.loads((directory / "pending.json").read_text(encoding="utf-8"))
    if version_key(data["version"]) <= version_key(current):
        return None
    digest, size = valid_hash(data["sha256"]), valid_size(data["bytes"])
    candidate = directory / (digest + ".exe")
    if not candidate.is_file() or candidate.stat().st_size != size or sha256_file(candidate) != digest:
        raise PatchError("Staged application update failed verification.")
    return data, candidate


def _kill_started_process(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        process.kill()
    process.wait(timeout=10)


def _health_check(executable, version, report_path, launch=False):
    report_path.unlink(missing_ok=True)
    flag = "--updated" if launch else "--health-check"
    process = subprocess.Popen([str(executable), flag, str(report_path)],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            if data.get("ok") is True and data.get("version") == version:
                if not launch:
                    return process.wait(timeout=10) == 0
                return True
            break
        except (OSError, ValueError):
            if process.poll() is not None:
                break
            time.sleep(0.1)
    _kill_started_process(process)
    return False


def _install_staged(target, directory, health_check=_health_check, retry_seconds=30):
    """Called by the detached helper. Failed installs restore the previous EXE."""
    target, directory = Path(target).resolve(), Path(directory).resolve()
    backup = target.with_name(target.name + ".previous")
    temporary = target.with_name("." + target.name + ".update-" + uuid.uuid4().hex)
    moved = False
    data = {}
    try:
        pending = pending_update(directory)
        if pending is None:
            return False
        data, candidate = pending
        if not health_check(candidate, data["version"], directory / "preflight.json"):
            raise PatchError("The downloaded app did not pass its startup check.")
        with temporary.open("xb") as dest, candidate.open("rb") as src:
            shutil.copyfileobj(src, dest)
        if sha256_file(temporary) != data["sha256"]:
            raise PatchError("Copied update failed verification.")
        deadline = time.monotonic() + retry_seconds
        while True:
            try:
                # Only this app's previous executable may be replaced here.
                os.replace(target, backup)
                moved = True
                os.replace(temporary, target)
                break
            except PermissionError:
                if moved or time.monotonic() >= deadline:
                    raise
                time.sleep(0.25)
        if not health_check(target, data["version"], directory / "startup.json", launch=True):
            raise PatchError("The new app could not start; the previous version was restored.")
        atomic_json(directory / "status.json", {"message": "Updated to " + data["version"]})
        (directory / "pending.json").unlink(missing_ok=True)
        return True
    except Exception as exc:
        if moved:
            os.replace(backup, target)
        atomic_json(directory / "status.json", {"failed_version": data.get("version"),
            "message": "Automatic update failed: {}. Existing app retained. Download a new copy from GitHub if this folder is read-only.".format(exc)})
        (directory / "pending.json").unlink(missing_ok=True)
        return False
    finally:
        temporary.unlink(missing_ok=True)


def install_staged(target, directory, health_check=_health_check, retry_seconds=30):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # OS-managed lock automatically releases even if a helper crashes.
    with (directory / "install.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        try:
            return _install_staged(target, directory, health_check, retry_seconds)
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def maybe_install_pending():
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return False
    target, directory = Path(sys.executable).resolve(), update_directory()
    try:
        pending = pending_update(directory)
        if pending is None:
            return False
        # A copied copy of the CURRENT app is the helper, not downloaded code.
        # Copying also lets the original one-file bootloader fully exit.
        helper = directory / ("update-helper-" + uuid.uuid4().hex + ".exe")
        shutil.copyfile(target, helper)
        subprocess.Popen([str(helper), "--apply-update", str(target), str(directory)],
                         creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except FileNotFoundError:
        return False
    except (PatchError, OSError, ValueError, KeyError) as exc:
        atomic_json(directory / "status.json", {"message": "Could not install staged update: " + str(exc)})
        return False


def helper_main(target, directory):
    # Command-line paths cannot redirect an update to an unrelated cache folder.
    if Path(directory).resolve() != update_directory(target).resolve():
        raise PatchError("Invalid update helper directory.")
    success = install_staged(target, directory)
    if not success:
        subprocess.Popen([str(Path(target).resolve()), "--skip-update"],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0 if success else 1


def update_status():
    try:
        return json.loads((update_directory() / "status.json").read_text(encoding="utf-8"))["message"]
    except (OSError, ValueError, KeyError):
        return "Updates install automatically on the next launch."
