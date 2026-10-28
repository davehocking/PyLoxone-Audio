"""Production gate: verify tested artifacts on public PyPI and a fresh named install.

Read-only public-index retries only. Never uploads, deletes or changes a release.
A failure writes success=false and exits nonzero. Requires Python 3.14.
"""
from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen
import venv
import zipfile

PROJECT = 'PyLoxone-Audio'
INDEX = 'https://pypi.org/simple'
ATTEMPTS = 6
DELAY = 15


class PropagationPending(RuntimeError):
    """Only a transient public read may be repeated, never a write/upload."""


def require(condition, message):
    if not condition:
        raise ValueError(message)


def normal_name(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def public_file(url):
    parts = urlsplit(url)
    return (parts.scheme == 'https' and parts.hostname == 'files.pythonhosted.org'
            and not parts.username and not parts.password and parts.port in (None, 443))


def retry_read(read, attempts=ATTEMPTS, delay=DELAY, sleep=time.sleep):
    require(1 <= attempts <= ATTEMPTS, 'Retry budget must remain bounded')
    for attempt in range(attempts):
        try:
            return read()
        except PropagationPending:
            if attempt + 1 == attempts:
                raise
            sleep(delay)


def validate_bytes(body, expected):
    require(len(body) == expected['size'], 'Public artifact size differs from tested artifact')
    require(hashlib.sha256(body).hexdigest() == expected['sha256'], 'Public artifact digest differs from tested artifact')


def validate_index(data, expected, version):
    require(normal_name(data['info']['name']) == normal_name(PROJECT), 'Wrong public project')
    require(data['info']['version'] == version, 'Wrong public version')
    rows = data['urls']
    require(len(rows) == len(expected) and {r['filename'] for r in rows} == set(expected), 'Missing, extra or duplicate public distributions')
    result = {}
    for row in rows:
        wanted = expected[row['filename']]
        require(not row.get('yanked', False), 'Public distribution is yanked')
        require(row['digests']['sha256'] == wanted['sha256'] and row['size'] == wanted['size'], 'Public metadata differs from tested artifact')
        require(public_file(row['url']), 'Distribution is not on the normal public file host')
        result[row['filename']] = row['url']
    return result


def validate_installation(report, probe, expected, runtime, version, kind='wheel'):
    require(report.get('version') == '1', 'Unknown pip installation report format')
    for dependency in report['install']:
        require(public_file(dependency['download_info']['url']), 'Dependency used a local/private artifact')
        require(dependency.get('is_direct') is False and dependency.get('is_yanked') is False,
                'Dependency was direct or yanked rather than a normal public-index resolution')
    rows = [r for r in report['install'] if normal_name(r['metadata']['name']) == normal_name(PROJECT)]
    require(len(rows) == 1, 'Named-pin install did not download the requested project')
    row = rows[0]
    require(row.get('requested') is True and row.get('is_direct') is False
            and row.get('is_yanked') is False, 'Install was not a normal non-yanked named pin')
    require(row['metadata']['version'] == version and probe['version'] == version, 'Installed version differs')
    require(public_file(row['download_info']['url']), 'Install used a local/private artifact')
    require(kind in ('wheel', 'sdist'), 'Unknown distribution install kind')
    suffix = '.whl' if kind == 'wheel' else '.tar.gz'
    artifact = next(v for n, v in expected.items() if n.endswith(suffix))
    require(row['download_info']['archive_info']['hashes']['sha256'] == artifact['sha256'], 'Installed download differs from tested distribution')
    require(Path(probe['module_file']).is_relative_to(Path(probe['prefix'])), 'Import shadows the fresh installation')
    require(probe['runtime'] == runtime, 'Installed runtime inventory or bytes differ')
    require(probe['python'][:2] == [3, 14], 'Gate did not use Python 3.14')
    require(set(probe['dependencies']) == {'websockets', 'pycryptodome', 'aiohttp'}, 'Declared dependencies were not imported')
    require(not probe['homeassistant_imported'], 'Portable library imported Home Assistant')


def tested_artifacts(dist, version):
    files = sorted(dist.iterdir())
    require(len(files) == 2 and len([p for p in files if p.name.endswith('.whl')]) == 1
            and len([p for p in files if p.name.endswith('.tar.gz')]) == 1, 'Expected exactly one tested wheel and sdist')
    expected = {p.name: {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'size': p.stat().st_size} for p in files}
    wheel = next(p for p in files if p.name.endswith('.whl'))
    sdist = next(p for p in files if p.name.endswith('.tar.gz'))
    with zipfile.ZipFile(wheel) as archive:
        metadata = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
        require(len(metadata) == 1, 'Invalid wheel metadata inventory')
        meta = BytesParser().parsebytes(archive.read(metadata[0]))
        runtime = {n.removeprefix('pyloxone_audio/'): hashlib.sha256(archive.read(n)).hexdigest()
                   for n in archive.namelist() if n.startswith('pyloxone_audio/') and not n.endswith('/')}
    require(normal_name(meta['Name']) == normal_name(PROJECT) and meta['Version'] == version, 'Tested wheel project/version mismatch')
    require('__init__.py' in runtime and 'py.typed' in runtime, 'Tested wheel lacks runtime')
    with tarfile.open(sdist) as archive:
        members = [m for m in archive.getmembers() if m.name.count('/') == 1 and m.name.endswith('/PKG-INFO')]
        require(len(members) == 1 and members[0].isfile(), 'Invalid sdist metadata inventory')
        stream = archive.extractfile(members[0])
        if stream is None:
            raise ValueError('Missing sdist metadata bytes')
        meta = BytesParser().parsebytes(stream.read())
    require(normal_name(meta['Name']) == normal_name(PROJECT) and meta['Version'] == version, 'Tested sdist project/version mismatch')
    return expected, runtime


def fetch(url):
    try:
        with urlopen(url, timeout=30) as response:
            return response.read(50 * 1024 * 1024 + 1)
    except HTTPError as error:
        if error.code in (404, 408, 429, 500, 502, 503, 504):
            raise PropagationPending('Public index/file not yet readable') from error
        raise
    except URLError as error:
        raise PropagationPending('Public index read unavailable') from error


PROBE = r'''
import hashlib, importlib, importlib.metadata as md, json, pathlib, sys
import pyloxone_audio, websockets, Crypto, aiohttp
root=pathlib.Path(pyloxone_audio.__file__).parent
runtime={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
         for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
for path in sorted(root.glob('*.py')):
    importlib.import_module('pyloxone_audio.'+path.stem)
print(json.dumps({'version':md.version('PyLoxone-Audio'),'prefix':sys.prefix,
 'module_file':pyloxone_audio.__file__,'runtime':runtime,'python':list(sys.version_info[:3]),
 'dependencies':{name:md.version(name) for name in ('websockets','pycryptodome','aiohttp')},
 'homeassistant_imported':any(n=='homeassistant' or n.startswith('homeassistant.') for n in sys.modules)}))
'''


def run_gate(dist, version, work):
    require(sys.version_info[:2] == (3, 14), 'Use Python 3.14 for the production gate')
    expected, runtime = tested_artifacts(dist, version)
    (work / 'tested-distributions.json').write_text(json.dumps(expected, indent=2) + '\n')
    def public_metadata():
        data = json.loads(fetch(f'https://pypi.org/pypi/{PROJECT}/{version}/json'))
        urls = validate_index(data, expected, version)
        (work / 'pypi.json').write_text(json.dumps(data, indent=2) + '\n')
        return urls
    urls = retry_read(public_metadata)
    downloads = work / 'public-downloads'; downloads.mkdir()
    for name, url in urls.items():
        body = retry_read(lambda: fetch(url))
        validate_bytes(body, expected[name])
        (downloads / name).write_bytes(body)
    probes = {}
    for kind in ('wheel', 'sdist'):
        install_work = work / kind
        install_work.mkdir()
        probes[kind] = install_named_pin(install_work, expected, runtime, version, kind)
    return {'success': True, 'project': PROJECT, 'version': version, 'index': INDEX,
            'tested_distributions': expected, 'runtime': runtime, 'public_downloads_match': True,
            'fresh_normal_named_pin_install': True, 'fresh_sdist_named_pin_install': True,
            'dependencies_checked': True, 'installed': probes, 'upload_or_release_writes': 0}


def install_named_pin(work, expected, runtime, version, kind):
    environment = work / 'venv'
    require(not environment.exists(), 'Gate installation must be fresh')
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / 'bin/python'
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PIP_', 'PYTHON'))}
    report_path = work / 'pip-report.json'
    require(kind in ('wheel', 'sdist'), 'Unknown distribution install kind')
    binary = '--only-binary=PyLoxone-Audio' if kind == 'wheel' else '--no-binary=PyLoxone-Audio'
    command = [str(python), '-I', '-m', 'pip', '--isolated', 'install', '--no-cache-dir',
               '--index-url', INDEX, binary, '--report', str(report_path), f'{PROJECT}=={version}']
    (work / 'install-command.json').write_text(json.dumps(command, indent=2) + '\n')
    # Repeat only a missing named-pin read due to index propagation, never upload.
    def install():
        result = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True, timeout=180)
        with (work / 'install.log').open('a') as log:
            log.write(result.stdout + result.stderr)
        if result.returncode:
            if f'No matching distribution found for {PROJECT}=={version}'.lower() in result.stderr.lower():
                raise PropagationPending('Named pin not yet visible on public simple index')
            raise RuntimeError('Normal public-index dependency installation failed; see install.log')
    retry_read(install)
    result = subprocess.run([str(python), '-I', '-m', 'pip', '--isolated', 'check'], cwd=work, env=env, capture_output=True, text=True, timeout=60)
    (work / 'pip-check.log').write_text(result.stdout + result.stderr)
    require(result.returncode == 0, 'Installed dependencies failed pip check')
    result = subprocess.run([str(python), '-I', '-c', PROBE], cwd=work, env=env, capture_output=True, text=True, timeout=60)
    (work / 'import.log').write_text(result.stdout + result.stderr)
    require(result.returncode == 0, 'Fresh installed imports failed')
    probe = json.loads(result.stdout)
    report = json.loads(report_path.read_text())
    validate_installation(report, probe, expected, runtime, version, kind)
    (work / 'installed-runtime.json').write_text(json.dumps(probe, indent=2) + '\n')
    return probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    args = parser.parse_args()
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=False)
    result_path = work / 'result.json'
    result_path.write_text(json.dumps({'success': False, 'version': args.version, 'status': 'incomplete'}) + '\n')
    try:
        result = run_gate(args.dist.resolve(), args.version, work)
    except Exception as error:
        result_path.write_text(json.dumps({'success': False, 'version': args.version,
                                          'error_type': type(error).__name__, 'error': str(error)}, indent=2) + '\n')
        print('PRODUCTION GATE FAILED/INCOMPLETE; see retained result.json', file=sys.stderr)
        return 1
    result_path.write_text(json.dumps(result, indent=2) + '\n')
    print('PRODUCTION GATE PASSED: actual PyPI files and fresh public-index installation verified')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
