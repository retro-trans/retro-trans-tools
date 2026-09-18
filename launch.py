"""Packaged entry point, updater helper and offline startup diagnostics."""
import sys
from retro_trans import __version__
from retro_trans.catalog import atomic_json, load_catalog
from retro_trans.core import engine_context
from retro_trans.gui import Application, main
from retro_trans.updater import helper_main, maybe_install_pending


def diagnose(path):
    app = None
    report = {"ok": False, "version": __version__}
    try:
        app = Application(startup=False, visible=False)
        app.update_idletasks()
        catalog = load_catalog()
        import tempfile
        import subprocess
        with tempfile.TemporaryDirectory() as cache:
            with engine_context(cache=cache) as engine:
                result = subprocess.run([str(engine), "-V"], capture_output=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if result.returncode != 0:
                    raise RuntimeError("Bundled engine did not start.")
        report.update(ok=True, tk=app.tk.call("info", "patchlevel"),
            window=[app.winfo_width(), app.winfo_height()], patches=len(catalog.edges))
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        if app:
            app.destroy()
    atomic_json(path, report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 2 and args[0] in ("--diagnose", "--health-check"):
        sys.exit(diagnose(args[1]))
    if len(args) == 3 and args[0] == "--apply-update":
        sys.exit(helper_main(args[1], args[2]))
    if len(args) == 2 and args[0] == "--updated":
        main(health_report=args[1])
    elif args == ["--skip-update"] or not maybe_install_pending():
        main()
