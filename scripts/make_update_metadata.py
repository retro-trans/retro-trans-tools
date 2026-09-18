"""Generate application update metadata from the exact packaged executable."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from retro_trans import __version__
from retro_trans.core import sha256_file
from retro_trans.catalog import atomic_json

directory = Path(sys.argv[1])
executable = directory / "Retro-Trans.exe"
atomic_json(directory / "UPDATE.json", {"schema_version": 1, "version": __version__,
    "platform": "windows-x86_64", "asset": executable.name,
    "bytes": executable.stat().st_size, "sha256": sha256_file(executable)})
