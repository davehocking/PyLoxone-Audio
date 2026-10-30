"""HACS stock recognition: real pinned files, synthetic config only."""
from pathlib import Path
import json
import os
import shutil
import pytest
from test_preview import preview, bundle


def test_hacs_stock_tests_are_backed_up_and_restored(bundle, tmp_path):
    config = tmp_path / 'config'
    config.mkdir()
    source = Path(os.environ['PREVIEW_TEST_UPSTREAM']) / 'custom_components/loxone'
    shutil.copytree(source, config / 'custom_components/loxone', ignore=shutil.ignore_patterns('__pycache__'))
    before = preview.files(config, component_only=True)
    tests = {name: digest for name, digest in before.items() if '/pyloxone_api/tests/' in name}
    assert len(tests) == 3
    backup = tmp_path / 'backup'
    preview.install(bundle, config, backup, preview.sha(bundle))
    receipt = json.loads((backup / 'receipt.json').read_text())
    assert receipt['before'] == before
    assert preview.files(backup, component_only=True) == before
    assert all(preview.sha(backup / name) == digest for name, digest in tests.items())
    assert not any('/tests/' in name for name in preview.files(config, component_only=True))
    preview.rollback(config, backup)
    assert preview.files(config, component_only=True) == before


@pytest.mark.parametrize('change', ['modified-test', 'extra-test', 'missing-test', 'partial-tests', 'runtime', 'symlink-test'])
def test_hacs_recognition_does_not_ignore_dirty_or_partial_trees(bundle, tmp_path, change):
    config = tmp_path / 'config'
    config.mkdir()
    source = Path(os.environ['PREVIEW_TEST_UPSTREAM']) / 'custom_components/loxone'
    shutil.copytree(source, config / 'custom_components/loxone', ignore=shutil.ignore_patterns('__pycache__'))
    tests = config / 'custom_components/loxone/pyloxone_api/tests'
    known = tests / 'test_discover.py'
    outside = tmp_path / 'outside'
    before = None
    if change == 'modified-test':
        known.write_text('# owner changes must be preserved\n')
    elif change == 'extra-test':
        (tests / 'extra.py').write_text('# not in the pinned upstream\n')
    elif change == 'missing-test':
        known.unlink()
    elif change == 'partial-tests':
        known.unlink()
        (tests / 'test_run_alone.py').unlink()
    elif change == 'runtime':
        (config / 'custom_components/loxone/const.py').write_text('# modified runtime\n')
    else:
        outside.write_text('# must not be traversed or replaced\n')
        known.unlink()
        known.symlink_to(outside)
    if change != 'symlink-test':
        before = preview.files(config, component_only=True)
    backup = tmp_path / 'backup'
    with pytest.raises(ValueError):
        preview.install(bundle, config, backup, preview.sha(bundle))
    assert not backup.exists()
    if change == 'symlink-test':
        assert known.is_symlink()
        assert outside.read_text() == '# must not be traversed or replaced\n'
    else:
        assert preview.files(config, component_only=True) == before
