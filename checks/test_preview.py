"""Filesystem-only preview regression tests; synthetic config, no HA/devices."""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import zipfile
import pytest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('preview',ROOT/'preview-build/preview.py')
preview=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)

@pytest.fixture
def bundle(tmp_path):
    # Real published-layout archive built from the recorded official component.
    base=Path(__import__('os').environ['PREVIEW_TEST_UPSTREAM'])
    output=tmp_path/'preview.zip'
    preview.build(base,output)
    return output

def test_real_build_repeatable_and_clean(bundle,tmp_path):
    other=tmp_path/'again.zip'
    preview.build(Path(__import__('os').environ['PREVIEW_TEST_UPSTREAM']),other)
    assert bundle.read_bytes()==other.read_bytes()
    with zipfile.ZipFile(bundle) as z:
        assert 'custom_components/loxone/text.py' in z.namelist()
        assert all('/tests/' not in n and '__pycache__' not in n for n in z.namelist())
        assert json.loads(z.read('custom_components/loxone/manifest.json'))['requirements'][-1]=='PyLoxone-Audio==0.1.2'

@pytest.mark.parametrize('dirty',['modified','extra','symlink'])
def test_builder_rejects_dirty_base(dirty,tmp_path):
    base=tmp_path/'upstream'
    shutil.copytree(Path(__import__('os').environ['PREVIEW_TEST_UPSTREAM'])/'custom_components',base/'custom_components')
    p=base/'custom_components/loxone/text.py'
    if dirty=='modified':p.write_text('changed')
    elif dirty=='extra':(p.parent/'unexpected.py').write_text('changed')
    else:p.unlink();p.symlink_to('const.py')
    with pytest.raises((ValueError,OSError)):preview.build(base,tmp_path/'bad.zip')
    assert not (tmp_path/'bad.zip').exists()

def test_archive_install_update_rollback_preserves_config(bundle,tmp_path):
    config=tmp_path/'config';config.mkdir()
    (config/'configuration.yaml').write_text('default_config:\n')
    (config/'.storage').mkdir();(config/'.storage/core.config_entries').write_text('{"synthetic":true}')
    (config/'custom_components/other').mkdir(parents=True);(config/'custom_components/other/__init__.py').write_text('# unrelated')
    keep={p: p.read_bytes() for p in config.rglob('*') if p.is_file()}
    backup=tmp_path/'backup'
    preview.install(bundle,config,backup,preview.sha(bundle))
    expected=preview.provenance()['shipping_files']
    assert preview.files(config,component_only=True)=={n:h for n,h in expected.items() if n.startswith('custom_components/')}
    # Re-install/update from the same exact version is deterministic and backed up.
    second=tmp_path/'second'
    preview.install(bundle,config,second,preview.sha(bundle))
    preview.rollback(config,second)
    assert preview.files(config,component_only=True)=={n:h for n,h in expected.items() if n.startswith('custom_components/')}
    preview.rollback(config,backup)
    assert not (config/'custom_components/loxone').exists()
    assert all(p.read_bytes()==v for p,v in keep.items())

def test_update_stock_0102_and_rollback(bundle,tmp_path):
    config=tmp_path/'config';config.mkdir()
    source=Path(__import__('os').environ['PREVIEW_TEST_UPSTREAM'])/'custom_components/loxone'
    shutil.copytree(source,config/'custom_components/loxone',ignore=shutil.ignore_patterns('tests','__pycache__'))
    before=preview.files(config,component_only=True)
    preview.install(bundle,config,tmp_path/'backup',preview.sha(bundle))
    preview.rollback(config,tmp_path/'backup')
    assert preview.files(config,component_only=True)==before

@pytest.mark.parametrize('step',['install','rollback'])
def test_intervening_change_refused(bundle,tmp_path,step):
    config=tmp_path/'config';config.mkdir();backup=tmp_path/'backup'
    if step=='rollback':preview.install(bundle,config,backup,preview.sha(bundle))
    target=config/'custom_components/loxone';target.mkdir(parents=True,exist_ok=True)
    (target/'owner-change.py').write_text('# preserve')
    before=preview.files(config,component_only=True)
    with pytest.raises(ValueError):
        if step=='install':preview.install(bundle,config,backup,preview.sha(bundle))
        else:preview.rollback(config,backup)
    assert preview.files(config,component_only=True)==before

def test_archive_wrong_hash_or_extra_member_refused(bundle,tmp_path):
    config=tmp_path/'config';config.mkdir()
    with pytest.raises(ValueError):preview.install(bundle,config,tmp_path/'bad-hash','0'*64)
    with zipfile.ZipFile(bundle,'a') as z:z.writestr('../escape','not allowed')
    with pytest.raises(ValueError):preview.install(bundle,config,tmp_path/'bad-path',preview.sha(bundle))
    assert not (config/'custom_components/loxone').exists()

def test_symlink_config_or_backup_refused(bundle,tmp_path):
    config=tmp_path/'config';config.mkdir()
    alias=tmp_path/'alias';alias.symlink_to(config,target_is_directory=True)
    with pytest.raises(ValueError):preview.install(bundle,alias,tmp_path/'backup',preview.sha(bundle))
    (config/'custom_components').symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(ValueError):preview.install(bundle,config,tmp_path/'backup',preview.sha(bundle))

@pytest.mark.parametrize('member',['custom_components','custom_components/loxone'])
def test_component_traversal_root_symlink_refused(tmp_path,member):
    root=tmp_path/'root';root.mkdir();outside=tmp_path/'outside';outside.mkdir()
    link=root/member;link.parent.mkdir(parents=True,exist_ok=True)
    link.symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError):preview.files(root,component_only=True)

@pytest.mark.parametrize('member',['config-parent','config-component','backup-component','receipt'])
def test_rollback_symlinks_refused_without_touching_targets(bundle,tmp_path,member):
    config=tmp_path/'config';config.mkdir();first=tmp_path/'first';backup=tmp_path/'backup'
    preview.install(bundle,config,first,preview.sha(bundle))
    preview.install(bundle,config,backup,preview.sha(bundle))
    original={'config-parent':config/'custom_components','config-component':config/'custom_components/loxone',
              'backup-component':backup/'custom_components/loxone','receipt':backup/'receipt.json'}[member]
    outside=tmp_path/'outside';original.rename(outside);original.symlink_to(outside,target_is_directory=outside.is_dir())
    before={str(p.relative_to(outside)):p.read_bytes() for p in outside.rglob('*') if p.is_file()} if outside.is_dir() else outside.read_bytes()
    with pytest.raises(ValueError):preview.rollback(config,backup)
    after={str(p.relative_to(outside)):p.read_bytes() for p in outside.rglob('*') if p.is_file()} if outside.is_dir() else outside.read_bytes()
    assert before==after

@pytest.mark.parametrize('step',['build','install','rollback','backup'])
def test_unsupported_private_entry_is_rejected_without_traversal(bundle,tmp_path,monkeypatch,step):
    config=tmp_path/'config';config.mkdir();backup=tmp_path/'backup'
    if step in ['rollback','backup']:
        preview.install(bundle,config,tmp_path/'first',preview.sha(bundle))
        preview.install(bundle,config,backup,preview.sha(bundle))
    if step=='build':
        root=tmp_path/'base';shutil.copytree(Path(__import__('os').environ['PREVIEW_TEST_UPSTREAM'])/'custom_components',root/'custom_components')
    else:root=backup if step=='backup' else config
    blocked=root/'custom_components/loxone'/'.private';blocked.mkdir(parents=True)
    original=__import__('os').scandir
    def refuse_scan(path):
        if not isinstance(path,int) and '.private' in Path(path).parts:raise AssertionError('Forbidden traversal')
        return original(path)
    monkeypatch.setattr(__import__('os'),'scandir',refuse_scan)
    with pytest.raises(ValueError):
        if step=='build':preview.build(root,tmp_path/'bad.zip')
        elif step=='install':preview.install(bundle,config,backup,preview.sha(bundle))
        else:preview.rollback(config,backup)
    assert blocked.is_dir()

@pytest.mark.parametrize('change',['after','before','format','extra','archive','backup'])
def test_changed_receipt_or_backup_is_refused(bundle,tmp_path,change):
    config=tmp_path/'config';config.mkdir();backup=tmp_path/'backup'
    preview.install(bundle,config,backup,preview.sha(bundle))
    receipt=json.loads((backup/'receipt.json').read_text())
    if change=='after':
        (config/'custom_components/loxone/owner-change.py').write_text('# preserve')
        receipt['after']=preview.files(config,component_only=True)
    elif change=='before':receipt['before']={'custom_components/loxone/arbitrary.py':'0'*64}
    elif change=='format':receipt['format']=99
    elif change=='extra':receipt['unrecognised']=True
    elif change=='archive':receipt['archive_sha256']='0'*64
    else:
        p=backup/'custom_components/loxone/arbitrary.py';p.parent.mkdir(parents=True);p.write_text('# changed backup')
        receipt['before']={p.relative_to(backup).as_posix():preview.sha(p)}
    (backup/'receipt.json').write_text(json.dumps(receipt))
    before=preview.files(config,component_only=True)
    with pytest.raises(ValueError):preview.rollback(config,backup)
    assert preview.files(config,component_only=True)==before

@pytest.mark.parametrize('failure',['publish','publish-and-restore','postverify','late-edit','competing-target'])
def test_failed_replacement_preserves_original_and_intervening_edits(bundle,tmp_path,monkeypatch,failure):
    config=tmp_path/'config';config.mkdir()
    source=Path(__import__('os').environ['PREVIEW_TEST_UPSTREAM'])/'custom_components/loxone'
    shutil.copytree(source,config/'custom_components/loxone',ignore=shutil.ignore_patterns('tests','__pycache__'))
    target=config/'custom_components/loxone';before=preview.files(config,component_only=True)
    (config/'configuration.yaml').write_text('synthetic: preserve\n')
    original=getattr(preview,'rename_no_replace',__import__('os').replace)
    original_files=preview.files
    def injected(src,dst,**kwargs):
        if str(dst)=='old' and failure=='late-edit':(target/'owner-change.py').write_text('# preserve late edit')
        if str(dst)=='loxone' and str(src)=='new':
            if failure in ['publish','publish-and-restore']:raise OSError('Injected publish failure')
            if failure=='competing-target':
                target.mkdir();(target/'owner-change.py').write_text('# preserve competing target')
        if failure=='publish-and-restore' and str(src)=='old':raise OSError('Injected restoration failure')
        return original(src,dst,**kwargs)
    def checked_files(root,component_only=False):
        result=original_files(root,component_only)
        if failure=='postverify' and Path(root)==config and component_only and result!=before:
            raise ValueError('Injected post-verification failure')
        return result
    monkeypatch.setattr(preview,'rename_no_replace',injected,raising=False)
    monkeypatch.setattr(preview,'files',checked_files)
    with pytest.raises((ValueError,OSError)):
        preview.install(bundle,config,tmp_path/'backup',preview.sha(bundle))
    # No original is ever destroyed, even if publishing AND restoration fail.
    candidates=[target,*list((config/'custom_components').glob('.loxone-recovery-*/old'))]
    assert any(p.is_dir() and all((p/n[len(preview.COMPONENT):]).is_file() and preview.sha(p/n[len(preview.COMPONENT):])==h for n,h in before.items()) for p in candidates)
    if failure in ['late-edit','competing-target']:
        assert any((p/'owner-change.py').is_file() for p in candidates)
    assert (config/'configuration.yaml').read_text()=='synthetic: preserve\n'

@pytest.mark.parametrize('step',['build','install','rollback','backup'])
@pytest.mark.parametrize('location',['root','child'])
def test_inventory_enumeration_errors_fail_closed(bundle,tmp_path,monkeypatch,step,location):
    config=tmp_path/'config';config.mkdir();backup=tmp_path/'backup'
    (config/'configuration.yaml').write_text('synthetic: preserve\n')
    if step!='build':
        preview.install(bundle,config,tmp_path/'first',preview.sha(bundle))
        if step in ['rollback','backup']:preview.install(bundle,config,backup,preview.sha(bundle))
    if step=='build':
        root=tmp_path/'base';shutil.copytree(Path(__import__('os').environ['PREVIEW_TEST_UPSTREAM'])/'custom_components',root/'custom_components')
    else:root=backup if step=='backup' else config
    denied=root/'custom_components/loxone'
    if location=='child':
        denied=denied/'unreadable-extra';denied.mkdir();(denied/'synthetic.txt').write_text('# preserve opaque input')
    snapshots={r:preview.files(r) for r in [root,config]}
    receipt=(backup/'receipt.json').read_bytes() if (backup/'receipt.json').exists() else None
    original=__import__('os').scandir
    def reject(path):
        if not isinstance(path,int) and Path(path)==denied:raise PermissionError('Injected inventory enumeration denial')
        return original(path)
    with monkeypatch.context() as patcher:
        patcher.setattr(__import__('os'),'scandir',reject)
        with pytest.raises(PermissionError):
            if step=='build':preview.build(root,tmp_path/'bad.zip')
            elif step=='install':preview.install(bundle,config,backup,preview.sha(bundle))
            else:preview.rollback(config,backup)
    assert all(preview.files(r)==before for r,before in snapshots.items())
    if receipt is not None:assert (backup/'receipt.json').read_bytes()==receipt
    else:assert not backup.exists()
    assert not (tmp_path/'bad.zip').exists()
