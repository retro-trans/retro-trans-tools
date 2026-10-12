"""Bounded retries for transient Windows sharing locks in owned Vita workspaces."""
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import time

from . import diagnostics
from .core import PatchError, check_cancel, report


def sharing_retry(operation, cancel=None, progress=None, timeout=12):
    deadline = time.monotonic() + timeout
    while True:
        check_cancel(cancel)
        try:
            return operation()
        except OSError as exc:
            # Retry only sharing/lock violations. Missing files, disk errors,
            # wrong hashes and ordinary permissions are not transient locks.
            if getattr(exc, 'winerror', None) not in (32, 33) or time.monotonic() >= deadline:
                raise
            diagnostics.event('vita_file_access', state='waiting', errno=exc.winerror)
            report(progress, 'Waiting for Windows to release a temporary file…', None)
            time.sleep(0.2)


@contextmanager
def temporary_workspace(parent, progress=None):
    parent = Path(parent).resolve()
    workspace = tempfile.TemporaryDirectory(prefix='.retro-pkg-', dir=str(parent))
    root = Path(workspace.name)
    if root.resolve().parent != parent or root.is_symlink():
        raise PatchError('Temporary Vita workspace is outside its output folder.')
    try:
        yield root
    finally:
        original_error = sys.exc_info()[1]
        try:
            # Delete only this context's generated directory. The native
            # installer has already been waited for before the context exits.
            sharing_retry(workspace.cleanup, progress=progress)
            diagnostics.event('vita_workspace', state='removed')
        except OSError as exc:
            diagnostics.event('vita_workspace', state='retained', errno=getattr(exc, 'winerror', None))
            if original_error is not None:
                # In particular, preserve cancellation or verification failure
                # instead of replacing it with a second cleanup exception.
                report(progress, 'Windows still holds temporary files; the original error is preserved.', None)
            else:
                raise PatchError('The output was saved and verified, but Windows still holds temporary '
                                 'files in the working folder. Close programs inspecting that folder. '
                                 'Keep the completed output; do not patch over it.') from exc
