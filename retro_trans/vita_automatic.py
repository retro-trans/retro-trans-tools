"""Lightweight Vita package detection for Automatic; downloads run on Patch."""
from dataclasses import dataclass
from pathlib import Path

from .core import PatchError, check_cancel
from .vita_downloads import package_content


@dataclass(frozen=True)
class VitaPackage:
    content_id: str
    platform: str = 'PS Vita'
    version: str = 'original'
    format: str = 'pkg'

    @property
    def title_id(self):
        return self.content_id[7:16]

    @property
    def label(self):
        return 'PS Vita ' + self.title_id + ' — original PKG'


@dataclass(frozen=True)
class VitaAutomaticPlan:
    source: VitaPackage

    @property
    def summary(self):
        return 'Original → latest compatible English PKG for Vita3K'

    @property
    def details(self):
        return (self.source.label + '\n\nThe app will find the newest published translation '
                'matching your complete original PKG hash and download its patch ZIP when you click Patch. '
                'Select your matching local work.bin or .rif. Small translation patches are downloaded and the PKG is rebuilt locally; '
                'your game package and license are not uploaded. Private releases can use your existing '
                'GitHub CLI sign-in. The translated PKG is verified in an isolated Vita3K installation. '
                'Use the Vita tab for hardware rePatch or a local patch override.')


def detect(path, cancel=None):
    check_cancel(cancel)
    if not Path(path).is_file():
        return None
    try:
        return VitaPackage(package_content(path))
    except (PatchError, OSError):
        return None


def append_packages(root, matches, cancel=None):
    known = {Path(path).resolve() for path, _ in matches}
    result = list(matches)
    for path in sorted(Path(root).glob('*.pkg')):
        check_cancel(cancel)
        if path.resolve() not in known:
            candidate = detect(path, cancel)
            if candidate is not None:
                result.append((path, candidate))
    return result
