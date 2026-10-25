"""Portable offline source/wheel test entrypoint for this library and its adapter."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('suite',choices=['library','adapter'])
    parser.add_argument('--library-root',type=Path)
    parser.add_argument('--host-base',type=Path)
    parser.add_argument('--work-dir',type=Path,required=True)
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1]
    work=args.work_dir.resolve()
    work.mkdir(parents=True,exist_ok=False)
    lib=(args.library_root or repo).resolve()
    assert (lib/'pyloxone_audio/__init__.py').is_file()
    scratch=Path(os.environ.get('TMPDIR',str(work))).resolve()
    scratch.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',TMPDIR=tempfile.mkdtemp(prefix='la-',dir=scratch))
    roots=[str(lib),str(repo/'tools')]
    temporary_metadata=None
    if lib==repo:
        stage=work/'metadata-source'
        stage.mkdir()
        for name in ['pyproject.toml','README.md','API.md','LICENSE','NOTICE.md']:
            shutil.copyfile(repo/name,stage/name)
        shutil.copytree(repo/'pyloxone_audio',stage/'pyloxone_audio',ignore=shutil.ignore_patterns('__pycache__'))
        metadata=work/'metadata';metadata.mkdir()
        result=subprocess.run([sys.executable,'-c','import setuptools.build_meta as b; b.prepare_metadata_for_build_wheel('+repr(str(metadata))+')'],cwd=stage,env=env,capture_output=True,text=True)
        (work/'source-metadata.log').write_text(result.stdout+result.stderr)
        assert result.returncode==0
        generated=next(metadata.glob('*.dist-info'))
        temporary_metadata=lib/generated.name
        assert not temporary_metadata.exists()
        roots.append(str(metadata))
    host=None
    if args.suite=='adapter':
        assert args.host_base, '--host-base is required for the real owning integration'
        base=args.host_base.resolve()
        spec=json.loads((repo/'adapters/pyloxone/BASE.json').read_text())
        host=work/'assembled-host';host.mkdir()
        for name,expected in spec['base_files'].items():
            assert digest(base/name)==expected, 'Unsupported host base: '+name
            target=host/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(base/name,target)
        for name,expected in spec['overlay_files'].items():
            source=repo/'adapters/pyloxone/overlay'/name
            assert digest(source)==expected,name
            target=host/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target)
        assert all(digest(host/n)==h for n,h in spec['assembled_files'].items())
        roots += [str(host),str(repo/'tests/adapter')]
        env['PYLOXONE_AUDIO_HOST_ROOT']=str(host)
    else:
        env['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
        env['AUDIO_INDEPENDENCE_RECEIPT']=str(work/'ha-rejected.json')
    env.update(PYTHONPATH=os.pathsep.join(roots),PYLOXONE_PROJECT_LIBRARY_ROOT=str(lib),PYLOXONE_PROJECT_TEST_SUITE=args.suite,PYLOXONE_PROJECT_RECEIPT=str(work/'actual-imports.json'))
    paths={}
    for directory in [repo/'pyloxone_audio',repo/'tests'/args.suite,repo/'adapters/pyloxone',repo/'tools']:
        for current,dirs,names in os.walk(directory):
            dirs[:]=[d for d in dirs if d not in {'.private','__pycache__','.pytest_cache'}]
            for name in names:
                p=Path(current)/name;paths[str(p.relative_to(repo))]=digest(p)
    for name in ['pyproject.toml','README.md','API.md','LICENSE','NOTICE.md','pytest.ini','CONTRIBUTING-RELEASE.md']:
        paths[name]=digest(repo/name)
    (work/'input-manifest.json').write_text(json.dumps(paths,indent=2)+'\n')
    cmd=[sys.executable,'-m','pytest','-q','--disable-socket','--allow-unix-socket','-p','no:cacheprovider','-p','project_test_guard','-W','error::RuntimeWarning','-W','error::ResourceWarning','-W','error::pytest.PytestUnraisableExceptionWarning','--junitxml='+str(work/'result.xml')]
    if args.suite=='library':cmd+=['-p','pytest_asyncio.plugin','-p','pytest_socket','-o','asyncio_mode=auto']
    cmd += [str(repo/'tests'/args.suite)]
    try:
        if temporary_metadata is not None:
            shutil.copytree(generated,temporary_metadata)
        # A source checkout as cwd precedes PYTHONPATH under python -m and can
        # silently shadow an installed wheel. Run from the empty owned work dir.
        result=subprocess.run(cmd,cwd=work,env=env,capture_output=True,text=True,timeout=1500)
    finally:
        if temporary_metadata is not None and temporary_metadata.exists():
            shutil.rmtree(temporary_metadata)
    (work/'stdout.log').write_text(result.stdout+result.stderr)
    unchanged=all(digest(repo/n)==h for n,h in paths.items())
    cases=[]
    if (work/'result.xml').exists():
        for c in ET.parse(work/'result.xml').getroot().iter('testcase'):
            outcome=next((k for k in ['error','failure','skipped'] if c.find(k) is not None),'passed')
            cases.append({'id':c.get('classname')+'::'+c.get('name'),'outcome':outcome})
    receipt={'suite':args.suite,'argv':cmd,'cwd':str(work),'library_root':str(lib),'host_base':str(args.host_base) if args.host_base else None,'assembled_host':str(host) if host else None,'exit_code':result.returncode,'inputs_unchanged':unchanged,'counts':dict(Counter(c['outcome'] for c in cases)),'cases':cases}
    (work/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k!='cases'},indent=2))
    print((work/'stdout.log').read_text()[-10000:])
    return result.returncode or (0 if unchanged else 1)


if __name__=='__main__':
    raise SystemExit(main())
