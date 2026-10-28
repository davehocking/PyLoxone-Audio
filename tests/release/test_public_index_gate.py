"""Production gate regressions; synthetic fixtures, no publication or network."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]


class PublicIndexGateContract(unittest.TestCase):
    def test_release_requires_a_separate_post_upload_public_index_gate(self):
        workflow = yaml.load((ROOT / '.github/workflows/release.yml').read_text(), Loader=yaml.BaseLoader)
        gate = workflow['jobs'].get('verify-public', {})
        self.assertEqual(gate.get('needs'), 'publish', 'Upload alone must not complete a production release')
        self.assertEqual(gate['if'], "github.event_name == 'release'")
        self.assertNotIn('continue-on-error', gate)
        self.assertNotIn('secrets.', str(gate))
        self.assertTrue(any('download-artifact@' in step.get('uses', '') for step in gate['steps']))
        command = '\n'.join(step.get('run', '') for step in gate['steps'])
        self.assertIn('tools/verify_public_release.py', command)
        self.assertIn('--dist dist', command)
        self.assertIn('--version', command)
        self.assertNotIn('--find-links', command)
        self.assertNotIn('continue-on-error', str(gate))


import hashlib
import importlib.util
import json
import tempfile
from unittest.mock import patch


class PublicIndexVerifier(unittest.TestCase):
    def gate(self):
        path = ROOT / 'tools/verify_public_release.py'
        self.assertTrue(path.is_file(), 'A production release must verify actual public artifact identity')
        spec = importlib.util.spec_from_file_location('public_index_gate', path)
        self.assertIsNotNone(spec)
        if spec is None or spec.loader is None:
            self.fail('Verifier module cannot be loaded')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def fixture(self):
        expected = {
            'pyloxone_audio-1.2.3-py3-none-any.whl': {'sha256': 'a' * 64, 'size': 10},
            'pyloxone_audio-1.2.3.tar.gz': {'sha256': 'b' * 64, 'size': 20},
        }
        data = {'info': {'name': 'PyLoxone-Audio', 'version': '1.2.3'}, 'urls': [
            {'filename': n, 'digests': {'sha256': v['sha256']}, 'size': v['size'],
             'url': 'https://files.pythonhosted.org/packages/' + n, 'yanked': False}
            for n, v in expected.items()]}
        return expected, data

    def test_index_rejects_wrong_version_missing_extra_duplicate_yanked_or_digest(self):
        gate = self.gate()
        expected, data = self.fixture()
        self.assertEqual(set(gate.validate_index(data, expected, '1.2.3')), set(expected))
        mutations = [
            lambda d: d['info'].update(version='1.2.2'),
            lambda d: d['info'].update(name='other-project'),
            lambda d: d['urls'].pop(),
            lambda d: d['urls'].append(dict(d['urls'][0])),
            lambda d: d['urls'][0]['digests'].update(sha256='c' * 64),
            lambda d: d['urls'][0].update(size=999),
            lambda d: d['urls'][0].update(yanked=True),
            lambda d: d['urls'][0].update(url='file:///local-wheel'),
            lambda d: d['urls'][0].update(url='https://untrusted.invalid/wheel'),
        ]
        for mutation in mutations:
            bad = json.loads(json.dumps(data)); mutation(bad)
            with self.subTest(mutation=mutations.index(mutation)), self.assertRaises(ValueError):
                gate.validate_index(bad, expected, '1.2.3')

    def test_downloaded_bytes_must_match_tested_artifact_not_just_http_success(self):
        gate = self.gate()
        body = b'tested wheel bytes'
        expected = {'sha256': hashlib.sha256(body).hexdigest(), 'size': len(body)}
        gate.validate_bytes(body, expected)
        with self.assertRaises(ValueError):
            gate.validate_bytes(body + b'changed', expected)

    def test_only_propagation_reads_retry_and_exhaustion_remains_failure(self):
        gate = self.gate(); calls = []
        def read():
            calls.append(1)
            if len(calls) < 3:
                raise gate.PropagationPending('not indexed yet')
            return 'public'
        self.assertEqual(gate.retry_read(read, attempts=3, delay=0, sleep=lambda _: None), 'public')
        self.assertEqual(len(calls), 3)
        with self.assertRaises(gate.PropagationPending):
            gate.retry_read(lambda: (_ for _ in ()).throw(gate.PropagationPending('missing')), attempts=2, delay=0, sleep=lambda _: None)
        calls.clear()
        def mismatch():
            calls.append(1); raise ValueError('wrong digest')
        with self.assertRaises(ValueError):
            gate.retry_read(mismatch, attempts=6, delay=0, sleep=lambda _: None)
        self.assertEqual(len(calls), 1)

    def test_normal_install_receipt_rejects_cache_local_wrong_digest_runtime_or_import(self):
        gate = self.gate()
        expected, _ = self.fixture()
        runtime = {'__init__.py': 'd' * 64, 'py.typed': 'e' * 64}
        report = {'version': '1', 'install': [{'is_direct': False, 'is_yanked': False, 'requested': True,
                              'metadata': {'name': 'PyLoxone-Audio', 'version': '1.2.3'},
                              'download_info': {'url': 'https://files.pythonhosted.org/packages/pkg.whl',
                                                'archive_info': {'hashes': {'sha256': 'a' * 64}}}}]}
        probe = {'version': '1.2.3', 'prefix': '/fresh/venv', 'module_file': '/fresh/venv/lib/python3.14/site-packages/pyloxone_audio/__init__.py',
                 'runtime': runtime, 'dependencies': {'websockets': '15', 'pycryptodome': '3.23', 'aiohttp': '3'},
                 'python': [3, 14, 7], 'homeassistant_imported': False}
        gate.validate_installation(report, probe, expected, runtime, '1.2.3')
        mutations = [
            lambda r, p: r.update(version='unknown'),
            lambda r, p: r['install'][0].update(is_direct=True),
            lambda r, p: r['install'][0].update(is_yanked=True),
            lambda r, p: r['install'][0].update(requested=False),
            lambda r, p: r['install'][0]['download_info'].update(url='file:///local.whl'),
            lambda r, p: r['install'][0]['download_info']['archive_info']['hashes'].update(sha256='f' * 64),
            lambda r, p: p.update(version='1.2.2'),
            lambda r, p: p.update(module_file='/checkout/pyloxone_audio/__init__.py'),
            lambda r, p: p.update(runtime={}),
            lambda r, p: p.update(dependencies={}),
            lambda r, p: p.update(python=[3, 13, 9]),
            lambda r, p: p.update(homeassistant_imported=True),
        ]
        for index, mutation in enumerate(mutations):
            r, p = json.loads(json.dumps(report)), json.loads(json.dumps(probe)); mutation(r, p)
            with self.subTest(index=index), self.assertRaises(ValueError):
                gate.validate_installation(r, p, expected, runtime, '1.2.3')


    def test_dependency_downloads_cannot_come_from_a_private_index(self):
        gate = self.gate()
        expected, _ = self.fixture()
        runtime = {'__init__.py': 'd' * 64}
        project = {'is_direct': False, 'is_yanked': False, 'requested': True,
                   'metadata': {'name': 'PyLoxone-Audio', 'version': '1.2.3'},
                   'download_info': {'url': 'https://files.pythonhosted.org/pkg.whl', 'archive_info': {'hashes': {'sha256': 'a' * 64}}}}
        dependency = {'is_direct': False, 'is_yanked': False, 'requested': False,
                      'metadata': {'name': 'aiohttp', 'version': '3'},
                      'download_info': {'url': 'https://private.invalid/dependency.whl'}}
        probe = {'version': '1.2.3', 'prefix': '/fresh', 'module_file': '/fresh/lib/pyloxone_audio/__init__.py',
                 'runtime': runtime, 'dependencies': {'websockets': '15', 'pycryptodome': '3', 'aiohttp': '3'},
                 'python': [3, 14, 7], 'homeassistant_imported': False}
        with self.assertRaises(ValueError):
            gate.validate_installation({'version': '1', 'install': [project, dependency]}, probe, expected, runtime, '1.2.3')

    def test_gate_exercises_fresh_wheel_and_sdist_normal_named_pins(self):
        import io
        import tarfile
        import types
        import zipfile
        gate = self.gate()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dist = root / 'dist'; dist.mkdir()
            work = root / 'work'; work.mkdir()
            metadata = b'Name: PyLoxone-Audio\nVersion: 1.2.3\n'
            wheel = dist / 'pyloxone_audio-1.2.3-py3-none-any.whl'
            sdist = dist / 'pyloxone_audio-1.2.3.tar.gz'
            with zipfile.ZipFile(wheel, 'w') as archive:
                archive.writestr('pyloxone_audio-1.2.3.dist-info/METADATA', metadata)
                archive.writestr('pyloxone_audio/__init__.py', b'')
                archive.writestr('pyloxone_audio/py.typed', b'')
            with tarfile.open(sdist, 'w:gz') as archive:
                info = tarfile.TarInfo('pyloxone_audio-1.2.3/PKG-INFO')
                info.size = len(metadata); archive.addfile(info, io.BytesIO(metadata))
            expected, runtime = gate.tested_artifacts(dist, '1.2.3')
            data = {'info': {'name': 'PyLoxone-Audio', 'version': '1.2.3'}, 'urls': [
                {'filename': name, 'digests': {'sha256': value['sha256']}, 'size': value['size'],
                 'url': 'https://files.pythonhosted.org/packages/' + name, 'yanked': False}
                for name, value in expected.items()]}
            commands = []
            def fetch(url):
                if url.endswith('/json'):
                    return json.dumps(data).encode()
                return (dist / url.rsplit('/', 1)[-1]).read_bytes()
            def execute(command, **kwargs):
                commands.append(command)
                prefix = str(Path(command[0]).parents[1])
                if 'install' in command:
                    self.assertIn('--isolated', command)
                    self.assertIn('--no-cache-dir', command)
                    self.assertIn('https://pypi.org/simple', command)
                    self.assertIn('PyLoxone-Audio==1.2.3', command)
                    self.assertNotIn('--find-links', command)
                    name = sdist.name if '--no-binary=PyLoxone-Audio' in command else wheel.name
                    report = {'version': '1', 'install': [{'is_direct': False, 'is_yanked': False,
                        'requested': True, 'metadata': {'name': 'PyLoxone-Audio', 'version': '1.2.3'},
                        'download_info': {'url': 'https://files.pythonhosted.org/packages/' + name,
                            'archive_info': {'hashes': {'sha256': expected[name]['sha256']}}}}]}
                    Path(command[command.index('--report') + 1]).write_text(json.dumps(report))
                if '-c' in command:
                    probe = {'version': '1.2.3', 'prefix': prefix,
                        'module_file': prefix + '/lib/pyloxone_audio/__init__.py', 'runtime': runtime,
                        'dependencies': {'websockets': '15', 'pycryptodome': '3', 'aiohttp': '3'},
                        'python': [3, 14, 7], 'homeassistant_imported': False}
                    return types.SimpleNamespace(returncode=0, stdout=json.dumps(probe), stderr='')
                return types.SimpleNamespace(returncode=0, stdout='', stderr='')
            with patch.object(gate, 'fetch', side_effect=fetch), patch.object(gate.venv.EnvBuilder, 'create'), patch.object(gate.subprocess, 'run', side_effect=execute):
                result = gate.run_gate(dist, '1.2.3', work)
            installs = [command for command in commands if 'install' in command]
            self.assertEqual(len(installs), 2, 'Production gate must actually exercise wheel AND sdist')
            self.assertEqual(len({command[0] for command in installs}), 2, 'Each resolution needs a fresh environment')
            self.assertEqual(sum('--no-binary=PyLoxone-Audio' in command for command in installs), 1)
            self.assertTrue(result['fresh_normal_named_pin_install'])
            self.assertTrue(result['fresh_sdist_named_pin_install'])

    def test_failed_gate_retains_non_success_receipt_and_nonzero_exit(self):
        gate = self.gate()
        for failure in (gate.PropagationPending('public version missing'), ValueError('digest mismatch'), RuntimeError('dependency install failed')):
            with self.subTest(failure=str(failure)), tempfile.TemporaryDirectory() as directory:
                work = Path(directory) / 'fresh'
                args = ['verify_public_release.py', '--dist', directory, '--version', '1.2.3', '--work-dir', str(work)]
                with patch('sys.argv', args), patch.object(gate, 'run_gate', side_effect=failure):
                    self.assertEqual(gate.main(), 1)
                self.assertFalse(json.loads((work / 'result.json').read_text())['success'])


if __name__ == '__main__':
    unittest.main()
