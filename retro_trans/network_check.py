"""Opt-in packaged HTTPS check; downloads only public metadata/tools/patches.

Never reads game inputs, licenses or settings. No check runs on normal launch.
"""
from pathlib import Path
import ssl
import sys
import tempfile

from . import __version__, vita_pkg, vita_repatch
from .catalog import CATALOG_URL, Catalog, atomic_json
from .core import GitHubClient, PatchError


def diagnose_network(path):
    report = {'ok': False, 'version': __version__, 'frozen': bool(getattr(sys, 'frozen', False)),
              'real_game_pkg_tested': False}
    step = 'certificate bundle'
    try:
        client = GitHubClient()
        context = client.tls_context() or ssl.create_default_context()
        report['tls'] = {'verification_required': context.verify_mode == ssl.CERT_REQUIRED,
                         'hostname_checked': context.check_hostname,
                         'trusted_ca_count': context.cert_store_stats()['x509_ca'],
                         'default_ca_count': ssl.create_default_context().cert_store_stats()['x509_ca']}
        if not report['tls']['verification_required'] or not report['tls']['hostname_checked']:
            raise PatchError('HTTPS verification is not enabled.')
        step = 'public catalog'
        catalog = Catalog(client.json(CATALOG_URL))
        report['catalog_patches'] = len(catalog.edges)
        with tempfile.TemporaryDirectory(prefix='retro-network-check-') as temp:
            cache = Path(temp)
            step = 'Vita profile and patch ZIP'
            with vita_repatch.description_context(client=client, cache=cache) as resolved:
                report['vita_patch_files'] = len(resolved[0]['files'])
            step = 'official Vita3K download'
            asset = vita_pkg.runtime_asset(client, None)
            client.download(asset, cache)
            report['vita3k'] = {'asset': asset.name, 'bytes': asset.size, 'sha256': asset.sha256}
        report['ok'] = True
    except Exception as exc:
        # Do not serialize raw exceptions, URLs, headers or machine paths.
        report['failed_step'] = step
        report['error_type'] = type(exc).__name__
        report['error'] = str(exc) if isinstance(exc, PatchError) else 'Network check failed.'
    atomic_json(path, report)
    return 0 if report['ok'] else 1
