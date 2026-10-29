"""Offline pinned preview builder/installer; never installs dependencies or runs HA.

Run with --help. Stop HA before changing its integration files. A full supported
HA backup remains necessary; this utility backs up only the loxone component.
"""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path

import stat
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
COMPONENT = 'custom_components/loxone/'
IGNORED = {'__pycache__'}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def safe_path(path):
    """Reject symlinks in every existing ancestor, without resolving them away."""
    path=Path(os.path.abspath(path))
    for part in [path,*path.parents]:
        if part.is_symlink():
            raise ValueError('Symlink paths are not supported')
    return path

def files(root, component_only=False):
    root=safe_path(root)
    start=safe_path(root/'custom_components/loxone') if component_only else root
    result={}
    try:
        mode=start.stat().st_mode
    except FileNotFoundError:
        return result
    if not stat.S_ISDIR(mode):
        raise ValueError('Expected directory')
    def enumeration_error(error):
        raise error
    for current,dirs,names in os.walk(start,followlinks=False,onerror=enumeration_error):
        for name in dirs+names:
            if name == '.private':
                # Reject the entry without inspecting or traversing its contents.
                raise ValueError('Unsupported tree entry; preserve and reconcile manually')
            p=Path(current)/name
            if p.is_symlink():
                raise ValueError('Symlink tree member')
        dirs[:]=[d for d in dirs if d not in IGNORED]
        for name in names:
            p=Path(current)/name
            if not p.is_file():
                raise ValueError('Non-regular tree member')
            result[p.relative_to(root).as_posix()]=sha(p)
    return dict(sorted(result.items()))

def provenance():
    return json.loads((HERE/'PROVENANCE.json').read_text())

def pinned_spec():
    prov=provenance()
    p=REPO/'adapters/pyloxone/BASE.json'
    if sha(p)!=prov['base_spec_sha256']:
        raise ValueError('Adapter base metadata changed; review/re-pin explicitly')
    return json.loads(p.read_text())

def build(base, output):
    """Compose only this reviewed release, refusing incompatible/dirty inputs."""
    base=safe_path(base);output=safe_path(output)
    if output.exists():
        raise ValueError('Output already exists')
    spec=pinned_spec();prov=provenance()
    if files(base,component_only=True)!=spec['base_files']:
        raise ValueError('Unsupported or dirty upstream component')
    overlay=REPO/'adapters/pyloxone/overlay'
    if files(overlay)!=spec['overlay_files']:
        raise ValueError('Dirty adapter overlay')
    if files(REPO/'pyloxone_audio')!=prov['library_runtime_files']:
        raise ValueError('Library runtime changed')
    bodies={}
    for name,expected in prov['shipping_files'].items():
        src=overlay/name if name in spec['overlay_files'] else base/name
        if not name.startswith(COMPONENT):
            src=REPO/name
        if sha(src)!=expected:
            raise ValueError('Shipping member hash mismatch: '+name)
        bodies[name]=src.read_bytes()
    bodies['PREVIEW.json']=(json.dumps(prov,sort_keys=True,indent=2)+'\n').encode()
    output.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation also protects against accidental concurrent overwrite.
    with output.open('xb') as stream, zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(bodies.items()):
            info=zipfile.ZipInfo(name,(2026,10,25,0,0,0))
            info.create_system=3;info.external_attr=(stat.S_IFREG|0o644)<<16
            info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,data,compresslevel=9)
    return sha(output)

def archive_bodies(archive, expected_sha):
    if sha(archive)!=expected_sha:
        raise ValueError('Archive checksum mismatch')
    prov=provenance()
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(set(names))!=len(names) or set(names)!=set(prov['shipping_files'])|{'PREVIEW.json'}:
            raise ValueError('Unexpected or duplicate archive members')
        for info in z.infolist():
            if stat.S_ISLNK(info.external_attr>>16):
                raise ValueError('Symlink archive member')
        if json.loads(z.read('PREVIEW.json'))!=prov:
            raise ValueError('Provenance mismatch')
        bodies={n:z.read(n) for n in prov['shipping_files']}
    if any(hashlib.sha256(v).hexdigest()!=prov['shipping_files'][n] for n,v in bodies.items()):
        raise ValueError('Archive member hash mismatch')
    return {n:v for n,v in bodies.items() if n.startswith(COMPONENT)}

def expected_stock():
    return {n:h for n,h in pinned_spec()['base_files'].items() if '/tests/' not in n}

def rename_no_replace(src, dst, *, src_dir_fd, dst_dir_fd):
    """Linux atomic no-clobber rename; fail closed if unavailable (no fallback)."""
    libc=ctypes.CDLL(None,use_errno=True)
    operation=getattr(libc,'renameat2',None)
    if operation is None:
        raise OSError('Linux renameat2 is required for guarded file replacement')
    operation.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    operation.restype=ctypes.c_int
    if operation(src_dir_fd,os.fsencode(src),dst_dir_fd,os.fsencode(dst),1):
        code=ctypes.get_errno()
        raise OSError(code,os.strerror(code))

def replace_component(config, bodies, before):
    """Pin mutation directories; retain every displaced tree, including failures.

    Retention is deliberate: an editor holding an old file descriptor may still
    write after a successful swap. Never recursively delete that previous tree.
    """
    parent=safe_path(config/'custom_components');parent.mkdir(exist_ok=True)
    target=safe_path(parent/'loxone')
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
    parent_fd=os.open(parent,flags)
    work=None;work_fd=None;displaced=False;published=False
    def identities():
        for path,fd in [(parent,parent_fd),*([(work,work_fd)] if work_fd is not None else [])]:
            safe_path(path)
            a=path.stat();b=os.fstat(fd)
            if (a.st_dev,a.st_ino)!=(b.st_dev,b.st_ino):
                raise ValueError('Directory identity changed; refusing mutation')
    try:
        identities()
        work=Path(tempfile.mkdtemp(prefix='.loxone-recovery-',dir=parent))
        work_fd=os.open(safe_path(work),flags);identities()
        stage=work/'new';stage.mkdir()
        for n,data in bodies.items():
            if not n.startswith(COMPONENT) or '..' in Path(n).parts:
                raise ValueError('Invalid component member')
            p=stage/n[len(COMPONENT):];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        after={n:hashlib.sha256(v).hexdigest() for n,v in bodies.items()}
        if files(config,component_only=True)!=before:
            raise ValueError('Target changed during staging')
        identities()
        if target.exists():
            rename_no_replace('loxone','old',src_dir_fd=parent_fd,dst_dir_fd=work_fd)
            displaced=True
            identities()
            moved={COMPONENT+n:h for n,h in files(work/'old').items()}
            if moved!=before:
                raise ValueError('Displaced component changed; original retained')
        elif before:
            raise ValueError('Target disappeared during staging')
        identities()
        if bodies:
            rename_no_replace('new','loxone',src_dir_fd=work_fd,dst_dir_fd=parent_fd)
            published=True
        if files(config,component_only=True)!=after:
            raise ValueError('Post-replacement verification failed')
        identities()
        if displaced:
            # Keep the exact old tree even on success; report its recovery path.
            if not bodies:stage.rmdir()
            return work
        if not bodies:stage.rmdir()
        work.rmdir()
        return None
    except BaseException as error:
        # Restore only to an absent target with atomic no-clobber semantics.
        # Never move/delete a published or concurrently created target.
        if displaced and not published:
            try:
                identities()
                rename_no_replace('old','loxone',src_dir_fd=work_fd,dst_dir_fd=parent_fd)
            except (OSError,ValueError):
                pass
        raise ValueError('Replacement failed; do not retry blindly. Preserved recovery directory: '+str(work)) from error
    finally:
        if work_fd is not None:os.close(work_fd)
        os.close(parent_fd)

def preview_inventory():
    return {n:h for n,h in provenance()['shipping_files'].items() if n.startswith(COMPONENT)}

def pinned_archive_sha():
    name='PyLoxone-0.10.2-audio-0.1.2-docs-post1-preview.zip'
    rows=[line.split() for line in (HERE/'SHA256SUMS').read_text().splitlines() if line.strip()]
    matches=[row[0] for row in rows if len(row)==2 and row[1]==name]
    if len(matches)!=1 or len(matches[0])!=64:
        raise ValueError('Invalid pinned archive checksum')
    return matches[0]

def validate_receipt(receipt, config):
    fields={'format','config','archive_sha256','before','after'}
    if not isinstance(receipt,dict) or set(receipt)!=fields or type(receipt['format']) is not int or receipt['format']!=1:
        raise ValueError('Unsupported backup receipt format')
    if receipt['config']!=str(config) or receipt['archive_sha256']!=pinned_archive_sha():
        raise ValueError('Wrong config or incompatible preview receipt')
    if receipt['after']!=preview_inventory() or receipt['before'] not in [
        {},expected_stock(),preview_inventory(),provenance()['predecessor_component_files'],
    ]:
        raise ValueError('Unrecognised backup inventories')

def install(archive, config, backup, expected_sha):
    """Install only absent, stock, exact pinned predecessor or this preview."""
    config=safe_path(config);backup=safe_path(backup)
    if not config.is_dir() or backup.exists() or backup.is_relative_to(config) or config.is_relative_to(backup):
        raise ValueError('Use an existing config and a new backup outside it')
    safe_path(config/'custom_components/loxone')
    bodies=archive_bodies(archive,expected_sha)
    if expected_sha!=pinned_archive_sha():
        raise ValueError('Archive is not the pinned preview build')
    before=files(config,component_only=True)
    after={n:hashlib.sha256(v).hexdigest() for n,v in bodies.items()}
    if before not in [{},expected_stock(),after,provenance()['predecessor_component_files']]:
        raise ValueError('Unrecognised/dirty existing component; preserve it and reconcile manually')
    backup.mkdir(parents=True)
    # Copy only the validated inventory, never recurse into newly added entries.
    for name,expected in before.items():
        data=safe_path(config/name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=expected:
            raise ValueError('Component changed while backing up')
        dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
    if files(backup,component_only=True)!=before:
        raise ValueError('Backup verification failed')
    receipt={'format':1,'config':str(config),'archive_sha256':expected_sha,'before':before,'after':after}
    (backup/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    recovery=replace_component(config,bodies,before)
    return dict(receipt,recovery_directory=str(recovery) if recovery else None)

def rollback(config, backup):
    config=safe_path(config);backup=safe_path(backup)
    receipt=json.loads(safe_path(backup/'receipt.json').read_text())
    validate_receipt(receipt,config)
    if files(backup,component_only=True)!=receipt['before']:
        raise ValueError('Wrong config or changed backup')
    current=files(config,component_only=True)
    if current!=receipt['after']:
        raise ValueError('Installed component changed; refusing destructive rollback')
    bodies={n:safe_path(backup/n).read_bytes() for n in receipt['before']}
    if {n:hashlib.sha256(v).hexdigest() for n,v in bodies.items()}!=receipt['before']:
        raise ValueError('Backup changed while reading; refusing replacement')
    return replace_component(config,bodies,current)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build');b.add_argument('--upstream',required=True,type=Path);b.add_argument('--output',required=True,type=Path)
    v=sub.add_parser('verify');v.add_argument('--archive',required=True,type=Path);v.add_argument('--sha256',required=True)
    i=sub.add_parser('install');i.add_argument('--archive',required=True,type=Path);i.add_argument('--sha256',required=True);i.add_argument('--config',required=True,type=Path);i.add_argument('--backup',required=True,type=Path)
    r=sub.add_parser('rollback');r.add_argument('--config',required=True,type=Path);r.add_argument('--backup',required=True,type=Path)
    a=parser.parse_args()
    if a.command=='build':print(build(a.upstream,a.output))
    elif a.command=='verify':archive_bodies(a.archive,a.sha256);print('Archive verified')
    elif a.command=='install':
        result=install(a.archive,a.config,a.backup,a.sha256)
        print('Component files installed and verified; no dependencies/HA commands run. Retained recovery directory:',result['recovery_directory'])
    else:
        recovery=rollback(a.config,a.backup)
        print('Component files rolled back and verified; no HA commands run. Retained recovery directory:',recovery)

if __name__=='__main__':
    main()
