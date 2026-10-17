"""Release-profile-driven Vita PKG translation with a user-supplied license.

Release assets are declarative patches and generated extras, never executable
code, game packages or licenses. The existing Z3 hardware flow is separate.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

from . import diagnostics, vita_pkg
from .core import (Asset, GitHubClient, PatchError, cache_directory, check_cancel,
                   decode, engine_context, report, valid_hash, valid_size)
from .solutions import output_name
from .vita_repatch import require, no_links, independent, verify

SCHEMA = 'retro-trans-vita-pkg-v1'
MANIFEST = 'VITA-PKG.json'
MAX_ZIP = 64*1024**2
# Complete inventories for larger games (e.g. Z3: 589 originals, 160 deltas)
# exceed 128 KiB. Retain a bounded reader and every per-file integrity check.
MAX_METADATA = 256*1024
GUIDE = ('Install the translated PKG through Vita3K: File → Install .pkg. '
         'Supply the same matching local work.bin or .rif when requested. '
         'Restart the game and check the title-screen version. Back up existing saves before installation. '
         'This custom package is for Vita3K and is not Sony-signed or verified on hardware. '
         'Installation verification does not establish gameplay compatibility.')


def identity(row, maximum=2*1024**3):
    require(isinstance(row,dict) and type(row.get('bytes')) is int and
            0 < valid_size(row['bytes']) <= maximum, 'Unsupported Vita asset size.')
    valid_hash(row.get('sha256'))


def game_path(name):
    require(isinstance(name,str) and len(name) <= 240, 'Invalid Vita game path.')
    parts = name.split('/')
    require(1 <= len(parts) <= 10, 'Unsupported Vita path depth.')
    for part in parts:
        require(len(part.encode('ascii')) < 68, 'Unsupported native PFS name.')
        output_name(part)
    require(parts[0].casefold() not in ('sce_pfs','license','nonpdrm') and
            all(part.casefold() not in ('work.bin','self_auth.bin') and not
                part.casefold().endswith(('.rif','.zrif')) for part in parts),
            'A translation profile cannot supply licenses or PFS databases.')
    return name


def validate(data):
    try:
        require(isinstance(data,dict) and set(data) ==
                {'schema','name','build','title_id','content_id','target','minimum_app_version',
                 'engine','package','source_files','files','extras'}, 'Unsupported Vita PKG profile.')
        title = data['title_id']
        require(data['schema'] == SCHEMA and isinstance(title,str) and
                re.fullmatch(r'[A-Z]{4}[0-9]{5}',title) and isinstance(data['content_id'],str) and
                re.fullmatch(r'[A-Z]{2}[0-9]{4}-'+title+r'_00-[A-Z0-9_]{16}',data['content_id']) and
                data['target'] == 'Vita3K' and isinstance(data['minimum_app_version'],str) and
                re.fullmatch(r'0\.\d+\.\d+',data['minimum_app_version']),
                'Invalid Vita game identity or unsupported app version.')
        from . import __version__
        require((0,5,8) <= tuple(map(int,data['minimum_app_version'].split('.'))) <=
                tuple(map(int,__version__.split('.'))), 'This Vita profile needs a newer app version.')
        require(data['engine'] == 'pfs-v5-pkg-key2',
                'This release needs an unsupported Vita encryption format. Update the tools.')
        require(set(data['package']) == {'bytes','sha256'}, 'Invalid original package identity.')
        identity(data['package'],16*1024**3)
        require(isinstance(data['name'],str) and 0 < len(data['name']) <= 150 and
                all(ord(c) >= 32 for c in data['name']) and
                isinstance(data['build'],str) and re.fullmatch(r'0\.\d+\.\d+',data['build']), 'Invalid Vita build label.')
        require(isinstance(data['source_files'],list) and 2 <= len(data['source_files']) <= 10000,
                'Incomplete original game inventory.')
        sources,case_paths = {},set()
        for row in data['source_files']:
            require(isinstance(row,dict) and set(row) == {'path','bytes','sha256'}, 'Invalid original game file.')
            name = game_path(row['path'])
            require(name.casefold() not in case_paths, 'Duplicate original game path.')
            identity(row,4*1024**3)
            sources[name] = {key:row[key] for key in ('bytes','sha256')}
            case_paths.add(name.casefold())
        require({'eboot.bin','sce_sys/param.sfo'} <= set(sources), 'Missing Vita executable or metadata.')
        require(isinstance(data['files'],list) and 1 <= len(data['files']) <= 1000 and
                isinstance(data['extras'],list) and len(data['extras']) <= 1000, 'Invalid translation inventory.')
        paths,assets = set(),set()
        for row in data['files']:
            require(isinstance(row,dict) and set(row) == {'path','source','target','patch'} and
                    row['path'] in sources and row['path'].casefold() not in paths, 'Invalid translation component.')
            require(row['source'] == sources[row['path']], 'Unexpected translation source.')
            identity(row['target'],4*1024**3); identity(row['patch'],MAX_ZIP)
            require(set(row['target']) == {'bytes','sha256'} and
                    set(row['patch']) == {'name','bytes','sha256'}, 'Invalid translation identity.')
            name = output_name(row['patch']['name'])
            require(name.endswith('.xdelta') and name.casefold() not in assets, 'Invalid translation patch name.')
            paths.add(row['path'].casefold()); assets.add(name.casefold())
        for row in data['extras']:
            require(isinstance(row,dict) and set(row) == {'path','name','bytes','sha256'}, 'Invalid translation extra.')
            name,path = output_name(row['name']),game_path(row['path'])
            require(path.casefold() not in case_paths|paths and name.casefold() not in assets,
                    'A generated extra cannot overwrite an original game file or another asset.')
            identity(row,4*1024**2)
            paths.add(path.casefold()); assets.add(name.casefold())
        require(MANIFEST.casefold() not in assets and
                sum(row['bytes'] for row in data['extras']) <= 16*1024**2 and
                sum(row['bytes'] for row in data['source_files']) <= 16*1024**3,
                'Translation profile exceeds supported size.')
        all_paths = case_paths|paths
        require(not any('/'.join(path.split('/')[:i]) in all_paths
                        for path in all_paths for i in range(1,len(path.split('/')))), 'Conflicting Vita file and folder paths.')
        return data
    except (KeyError,TypeError,ValueError,AttributeError,UnicodeError) as exc:
        raise PatchError('Invalid Vita PKG profile.') from exc


def read_description(raw):
    require(len(raw) <= MAX_METADATA, 'Vita PKG profile is too large.')
    try:
        return validate(json.loads(raw.decode('utf-8')))
    except (ValueError,UnicodeError) as exc:
        raise PatchError('Invalid Vita PKG JSON.') from exc


def inventory(data):
    rows = {row['patch']['name']:row['patch'] for row in data['files']}
    rows.update({row['name']:row for row in data['extras']})
    return rows


@contextmanager
def archive_description(path,cancel=None,progress=None):
    path = no_links(path)
    require(path.is_file() and 0 < path.stat().st_size <= MAX_ZIP, 'Select the release Vita PKG patch ZIP.')
    with tempfile.TemporaryDirectory(prefix='retro-vita-pkg-patches-') as temporary:
        folder = Path(temporary)
        try:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                require(2 <= len(entries) <= 2001 and len({item.filename.casefold() for item in entries}) == len(entries),
                        'Invalid Vita PKG ZIP inventory.')
                for item in entries:
                    require(output_name(item.filename) == item.orig_filename and not item.is_dir() and
                            not item.flag_bits & 1 and stat.S_IFMT(item.external_attr>>16) in (0,stat.S_IFREG) and
                            item.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED), 'Unsafe Vita PKG ZIP entry.')
                require(sum(item.file_size for item in entries) <= MAX_ZIP and
                        0 < archive.getinfo(MANIFEST).file_size <= MAX_METADATA, 'Oversized Vita PKG ZIP.')
                data = read_description(archive.read(MANIFEST))
                expected = inventory(data)
                require(set(archive.namelist()) == set(expected)|{MANIFEST}, 'Vita PKG ZIP inventory mismatch.')
                for name,row in expected.items():
                    check_cancel(cancel)
                    require(archive.getinfo(name).file_size == row['bytes'], 'Vita patch ZIP size mismatch.')
                    with archive.open(name) as source,(folder/name).open('xb') as output:
                        while True:
                            check_cancel(cancel)
                            chunk = source.read(256*1024)
                            if not chunk: break
                            output.write(chunk)
                    verify(folder/name,row,cancel,progress)
        except (zipfile.BadZipFile,KeyError,RuntimeError,EOFError) as exc:
            raise PatchError('Invalid or damaged release Vita PKG patch ZIP.') from exc
        yield data,folder


@contextmanager
def description_context(description=None,client=None,cache=None,cancel=None,progress=None,repo=None,pkg=None):
    if description:
        path = no_links(description)
        if path.suffix.lower() == '.zip':
            with archive_description(path,cancel,progress) as resolved: yield resolved
        else:
            with path.open('rb') as stream: data = read_description(stream.read(MAX_METADATA+1))
            for name,row in inventory(data).items(): verify(no_links(path.parent/name),row,cancel,progress)
            yield data,path.parent
        return
    from .core import validate_repo
    if repo is None and pkg is not None:
        from .vita_downloads import automatic_description
        with automatic_description(pkg,client,cache,cancel,progress) as resolved: yield resolved
        return
    require(repo is not None, 'Choose the release Vita patch ZIP or VITA-PKG.json.')
    repo = validate_repo(repo)
    client = client or GitHubClient()
    try:
        release = client.json('https://api.github.com/repos/'+repo+'/releases/latest',cancel)
    except PatchError as exc:
        raise PatchError('Vita release is unavailable or private. Select its downloaded Vita patch ZIP.') from exc
    require(isinstance(release,dict) and not release.get('draft') and
            re.fullmatch(r'v0\.\d+\.\d+',release.get('tag_name','')), 'No compatible Vita release.')
    items = [item for item in release.get('assets',[]) if isinstance(item.get('name'),str) and
             item['name'].endswith('-Vita-PKG-patches.zip')]
    name = output_name(items[0]['name']) if len(items) == 1 else ''
    require(len(items) == 1, 'Vita release has no Vita PKG patch ZIP. Choose a local ZIP.')
    item = items[0]
    url = 'https://github.com/'+repo+'/releases/download/'+release['tag_name']+'/'+name
    require(item.get('browser_download_url') == url and (item.get('digest') or '').startswith('sha256:'),
            'Vita PKG download lacks verified publisher metadata.')
    asset = Asset(name,url,valid_size(item['size']),valid_hash(item['digest'][7:]))
    require(0 < asset.size <= MAX_ZIP, 'Unexpected Vita PKG ZIP size.')
    path = client.download(asset,cache or cache_directory(),cancel,progress)
    verify(path,dict(bytes=asset.size,sha256=asset.sha256),cancel,progress)
    with archive_description(path,cancel,progress) as resolved:
        require(resolved[0]['build'] == release['tag_name'][1:], 'Vita profile version differs from release.')
        yield resolved


def apply(pkg,license_path,output,description=None,client=None,cache=None,cancel=None,progress=None):
    require(os.name == 'nt', 'Vita PKG rebuilding is currently verified on Windows only.')
    from . import vita_pfs as pfs
    pkg,license_path,output = no_links(pkg).resolve(),no_links(license_path).resolve(),no_links(output).absolute()
    validation_path = output.with_suffix('.validation.json')
    require(output.suffix.lower() == '.pkg' and output.parent.is_dir() and
            not os.path.lexists(output) and not os.path.lexists(validation_path) and
            independent(pkg,output) and independent(license_path,output), 'Choose a new English .pkg output filename.')
    check_cancel(cancel)
    if not description:
        from .vita_downloads import VitaReleaseClient
        client = client or VitaReleaseClient()
    client,cache = client or GitHubClient(),Path(cache) if cache else cache_directory()
    with description_context(description,client,cache,cancel,progress,pkg=pkg) as (data,patches):
        title = data['title_id']
        verify(pkg,data['package'],cancel,progress)
        license_data = vita_pkg.license_bytes(pkg,license_path,title)
        values = pfs.constants()
        parsed = pfs.read_pkg(pkg,values,data['content_id'])
        declared_sources = {row['path']:row for row in data['source_files']}
        pfs.validate_original_paths(pkg,parsed,license_data[0x50:0x60],set(declared_sources),values)
        diagnostics.event('vita_profile',mode='generic_pkg',files=len(data['files']))
        with vita_pkg.decrypted_source(pkg,license_path,output,client,cache,cancel,progress,
                                       title_id=title,workspace=True,package_identity=data['package']) as workspace:
            source,root = workspace['source'],workspace['root']
            actual = {file.relative_to(source).as_posix():no_links(file) for file in source.rglob('*') if file.is_file()}
            require(set(actual) == set(declared_sources), 'Original package installation has an unexpected inventory.')
            for row in data['source_files']: verify(actual[row['path']],row,cancel,progress)
            targets = dict(actual)
            english = root/'english'
            english.mkdir()
            with engine_context(client,cache,cancel,progress) as engine:
                for row in data['files']:
                    target = english/row['path']
                    target.parent.mkdir(parents=True,exist_ok=True)
                    report(progress,'Applying English translation\u2026',None)
                    decode(engine,actual[row['path']],patches/row['patch']['name'],target,row['target']['bytes'],cancel,progress)
                    verify(target,row['target'],cancel,progress)
                    targets[row['path']] = target
            for row in data['extras']:
                target = english/row['path']
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(patches/row['name'],target)
                verify(target,row,cancel,progress)
                targets[row['path']] = target
            template = pfs.small_member(pkg,parsed,'sce_pfs/files.db')[:1024]
            license_data = vita_pkg.license_bytes(pkg,license_path,title)
            expected = pfs.make_pfs(targets,template,license_data[0x50:0x60],root/'pfs',values,cancel,progress)
            declared = {row['path']:{key:row[key] for key in ('bytes','sha256')} for row in data['source_files']}
            declared.update({row['path']:row['target'] for row in data['files']})
            declared.update({row['path']:{key:row[key] for key in ('bytes','sha256')} for row in data['extras']})
            require(expected == declared, 'Game files changed while rebuilding PFS; no PKG was saved.')
            payload = {file.relative_to(root/'pfs').as_posix():file for file in (root/'pfs').rglob('*') if file.is_file()}
            candidate = root/'english.pkg'
            result = pfs.write_pkg(pkg,payload,candidate,values,targets['sce_sys/param.sfo'],cancel,progress)
            report(progress,'Verifying English PKG installation\u2026',None)
            exe = vita_pkg.extract_runtime(workspace['archive'],root/'verification-engine',cancel)
            fs = vita_pkg.portable_directory(exe)/'fs'
            vita_pkg.run_installer(exe,candidate,vita_pkg.encoded_license(license_data),fs,cancel,progress)
            installed = fs/'ux0/app'/title
            installed_files = {file.relative_to(installed).as_posix():no_links(file) for file in installed.rglob('*') if file.is_file()}
            require(set(installed_files) == set(expected), 'English PKG did not install with the expected game files.')
            for name,row in expected.items(): verify(installed_files[name],row,cancel,progress)
            verify(pkg,data['package'],cancel,progress)
            require(vita_pkg.license_bytes(pkg,license_path,title) == license_data, 'License changed during conversion.')
            check_cancel(cancel)
            result.update(version=data['build'],native_pkg_install_verified=True,verified_files=len(expected),
                          original_pkg_unchanged=True,license_unchanged=True,gameplay_tested=False)
            report_file = root/'validation.json'
            report_file.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
            require(not os.path.lexists(output) and not os.path.lexists(validation_path), 'Output appeared during conversion.')
            # Windows rename does not replace an existing output. No game data is
            # published until native installation and every full-file hash pass.
            report_file.rename(validation_path)
            candidate.rename(output)
    report(progress,'English PKG saved and verified.',1)
    return output
