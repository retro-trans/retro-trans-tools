"""Packaged entry point, updater helper and offline startup diagnostics."""
import sys
from retro_trans import __version__
from retro_trans.catalog import atomic_json, load_catalog
from retro_trans.core import engine_context
from retro_trans.gui import Application, main
from retro_trans.updater import helper_main, maybe_install_pending
from retro_trans.z3_saves import GUIDE
from retro_trans import chd
from retro_trans import mx_converter, mx_crypto


def diagnose(path):
    app = None
    report = {"ok": False, "version": __version__}
    try:
        app = Application(startup=False, visible=False)
        app.update_idletasks()
        app.vita_game.set('Vita3K PKG')
        license_controls = app.tabs[3].grid_slaves(row=2)
        if not hasattr(app, 'auto_vita_license') or not license_controls or not all(widget.grid_info() for widget in license_controls):
            raise RuntimeError('Local PKG rebuilding requires a matching-license input.')
        app.vita_game.set('Hardware rePatch')
        catalog = load_catalog()
        if not GUIDE.read_text(encoding="utf-8").strip():
            raise RuntimeError("Bundled Z3 save instructions are missing.")
        if not mx_converter.GUIDE.read_text(encoding="utf-8").strip():
            raise RuntimeError("Bundled MX save instructions are missing.")
        if mx_crypto.cmac(bytes.fromhex('2b7e151628aed2a6abf7158809cf4f3c'), b'').hex() != 'bb1d6929e95937287fa37d129b756746':
            raise RuntimeError('Savedata cryptography self-check failed.')
        from retro_trans import vita_pfs
        vita_pfs.constants()
        if vita_pfs.cbc_tail(bytes.fromhex('6bc1bee22e409f96e93d7e117393172a'),
                bytes.fromhex('2b7e151628aed2a6abf7158809cf4f3c'),bytes.fromhex('000102030405060708090a0b0c0d0e0f')).hex() != '7649abac8119b246cee98e9b12e9197d':
            raise RuntimeError('Vita package cryptography self-check failed.')
        import tempfile
        import subprocess
        with tempfile.TemporaryDirectory() as cache:
            with engine_context(cache=cache) as engine:
                result = subprocess.run([str(engine), "-V"], capture_output=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if result.returncode != 0:
                    raise RuntimeError("Bundled engine did not start.")
            from pathlib import Path
            source = Path(cache) / 'health.iso'
            source.write_bytes(bytes(range(256)) * 64)
            chd.compress_verified(source, Path(cache) / 'health.chd', chd.Disc('dvd', source.stat().st_size))
        report.update(ok=True, tk=app.tk.call("info", "patchlevel"), title=app.title(),
            window=[app.winfo_width(), app.winfo_height()], patches=len(catalog.edges),
            tabs=[app.notebook.tab(tab, "text") for tab in app.notebook.tabs()], z3_save_converter=True,
            chd_round_trip=True, mx_converter='experimental early Hugo intermission', mx_cng_self_check=True,
            mx_crypto_provider='CommonCrypto' if sys.platform == 'darwin' else 'Windows CNG',
            vita_pkg_profile_engine=True,vita_pkg_crypto_self_check=True,
            whole_pkg_xdelta=False,installed_cpk_patching=True,local_pkg_rebuilding=True,license_required_for_pkg_patching=True)
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        if app:
            app.destroy()
    atomic_json(path, report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    from retro_trans import diagnostics
    import atexit
    diagnostics.start_session()
    atexit.register(diagnostics.close_session)
    previous_excepthook = sys.excepthook
    def log_uncaught(exc_type, exc, tb):
        diagnostics.exception(exc)
        previous_excepthook(exc_type, exc, tb)
    sys.excepthook = log_uncaught
    args = sys.argv[1:]
    if args and args[0] in ('--vita-pkg','--vita-repatch'):
        hardware = args[0] == '--vita-repatch'
        import argparse
        parser = argparse.ArgumentParser(description='Translate an original Vita PKG using its release profile.')
        parser.add_argument('--package',required=True)
        parser.add_argument('--patch',help='Local ZIP/JSON; omit to download the matching translation automatically.')
        parser.add_argument('--output',required=True)
        parser.add_argument('--license',required=True,help='Matching local game work.bin/.rif; never downloaded.')
        options = parser.parse_args(args[1:])
        if hardware:
            from retro_trans.vita_repatch import apply
        else:
            from retro_trans.vita_translation import apply
        try:
            with diagnostics.operation('vita_repatch' if hardware else 'vita_pkg'):
                progress=lambda message,fraction: diagnostics.progress(message)
                if hardware:
                    apply(options.package,options.output,options.patch,work_bin=options.license,progress=progress)
                else:
                    apply(options.package,options.license,options.output,options.patch,progress=progress)
        except Exception as exc:
            diagnostics.exception(exc)
            sys.exit(1)
        sys.exit(0)
    if len(args) == 2 and args[0] in ("--diagnose", "--health-check"):
        sys.exit(diagnose(args[1]))
    if len(args) == 2 and args[0] == '--network-check':
        from retro_trans.network_check import diagnose_network
        sys.exit(diagnose_network(args[1]))
    if len(args) == 3 and args[0] == "--apply-update":
        sys.exit(helper_main(args[1], args[2]))
    if len(args) == 2 and args[0] == "--updated":
        main(health_report=args[1])
    elif args == ["--skip-update"] or not maybe_install_pending():
        main()
