"""Retain complete license trees from bundled Python cryptography dependencies."""
import importlib.metadata
from pathlib import Path
import shutil


def copy_notices(destination):
    destination=Path(destination)
    for name in ('cryptography','cffi','pycparser'):
        package=importlib.metadata.distribution(name)
        found=False
        for entry in package.files or []:
            parts=Path(str(entry)).parts
            if any(part.lower() in ('licenses','license','license.txt','license.apache','license.bsd','copying') for part in parts):
                source=Path(package.locate_file(entry))
                if source.is_file():
                    relative=Path(*parts[1:])
                    target=destination/name/relative
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(source,target)
                    found=True
        if not found:raise RuntimeError('Missing dependency notices: '+name)


if __name__=='__main__':
    import sys
    copy_notices(sys.argv[1])
