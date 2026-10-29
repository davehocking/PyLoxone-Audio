"""Exact published predecessor upgrade/rollback; filesystem-only, never HA."""
import importlib.util
import json
import os
from pathlib import Path
import zipfile
import pytest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('preview_predecessor',ROOT/'preview-build/preview.py')
preview=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)

@pytest.fixture
def previous(tmp_path):
    config=tmp_path/'config';config.mkdir()
    with zipfile.ZipFile(os.environ['PREVIEW_TEST_PREDECESSOR']) as z:
        for name in z.namelist():
            if name.startswith(preview.COMPONENT):
                p=config/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(name))
    assert preview.files(config,component_only=True)==preview.provenance()['predecessor_component_files']
    (config/'configuration.yaml').write_text('synthetic: keep\n')
    return config

def test_exact_010_upgrade_preserves_settings_and_rolls_back(previous,tmp_path):
    before=preview.files(previous,component_only=True)
    bundle=ROOT/'preview-build/PyLoxone-0.10.2-audio-0.1.2-docs-post1-preview.zip'
    backup=tmp_path/'backup'
    receipt=preview.install(bundle,previous,backup,preview.sha(bundle))
    assert receipt['before']==before
    assert preview.files(previous,component_only=True)==preview.preview_inventory()
    assert (previous/'configuration.yaml').read_text()=='synthetic: keep\n'
    preview.rollback(previous,backup)
    assert preview.files(previous,component_only=True)==before
    assert (previous/'configuration.yaml').read_text()=='synthetic: keep\n'

@pytest.mark.parametrize('mutation',['edited','extra','removed'])
def test_dirty_predecessor_is_refused_without_backup_or_target_mutation(previous,tmp_path,mutation):
    target=previous/'custom_components/loxone/media_player.py'
    if mutation=='edited':target.write_text('# changed')
    elif mutation=='extra':(target.parent/'owner-addition.py').write_text('# keep')
    else:target.unlink()
    before=preview.files(previous)
    bundle=ROOT/'preview-build/PyLoxone-0.10.2-audio-0.1.2-docs-post1-preview.zip'
    with pytest.raises(ValueError):preview.install(bundle,previous,tmp_path/'backup',preview.sha(bundle))
    assert preview.files(previous)==before
    assert not (tmp_path/'backup').exists()
