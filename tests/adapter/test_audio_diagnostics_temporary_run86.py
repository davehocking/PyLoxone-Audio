"""R85-02: discard only this journal's abandoned atomic payloads, serially."""
import asyncio
import os
import stat

import pytest
from custom_components.loxone import media_player, spotify_continuity, audio_sources
from custom_components.loxone.audio_diagnostics import RollingJournal
from custom_components.loxone.const import DOMAIN
from test_audio_diagnostics_storage_ha import row
from test_audioserver_ha import audio_setup


@pytest.mark.parametrize('restart', [False, True], ids=['cached', 'restart'])
@pytest.mark.parametrize('expired', [False, True], ids=['current', 'expired'])
def test_abandoned_exact_atomic_names_and_total_bytes(tmp_path, restart, expired):
    clock = [100000.0]
    journal = RollingJournal(tmp_path/'journal', clock=lambda: clock[0], disk_bytes=1600, segment_bytes=400)
    journal.maintain([row(clock, n) for n in range(10)])
    committed = {p.name: p.read_bytes() for p in journal.path.glob('events-*.jsonl')}
    for name, data in committed.items():
        (journal.path/(name+'.tmp')).write_bytes(data)
    (journal.path/'state.json.tmp').write_bytes(b'{"invalid_records":0}')
    if restart:
        journal = RollingJournal(journal.path, clock=lambda: clock[0], disk_bytes=1600, segment_bytes=400)
    if expired:
        clock[0] += 86401
    journal.maintain([])
    assert not list(journal.path.glob('*.tmp'))
    if not expired:
        assert {p.name: p.read_bytes() for p in journal.path.glob('*.jsonl')} == committed
        journal.maintain([row(clock, 11)])
        assert journal.export()['events'][-1]['sequence'] == 11
    else:
        assert journal.export()['events'] == []
    assert sum(p.stat().st_size for p in journal.path.iterdir() if stat.S_ISREG(p.lstat().st_mode)) <= 1600 + 400 + 8192


@pytest.mark.parametrize('kind', ['symlink', 'fifo', 'directory'])
def test_temporary_nonregular_is_not_followed_or_removed(tmp_path, kind):
    clock = [100000.0]
    journal = RollingJournal(tmp_path/'journal', clock=lambda: clock[0])
    journal.path.mkdir()
    sentinel = tmp_path/'sentinel'
    sentinel.write_bytes(b'SYNTHETIC outside evidence')
    pending = journal.path/'events-0000000000000000.jsonl.tmp'
    if kind == 'symlink':
        pending.symlink_to(sentinel)
    elif kind == 'fifo':
        os.mkfifo(pending)
    else:
        pending.mkdir()
    with pytest.raises(OSError):
        journal.maintain([])
    assert pending.lstat()
    assert sentinel.read_bytes() == b'SYNTHETIC outside evidence'


def test_temporary_cleanup_leaves_foreign_names(tmp_path):
    journal = RollingJournal(tmp_path/'journal')
    journal.path.mkdir()
    names = ['events-other.jsonl.tmp', 'events-1.jsonl.tmp.backup', 'foreign.tmp', 'state.json.tmp.backup']
    for name in names:
        (journal.path/name).write_bytes(b'FOREIGN')
    journal.maintain([])
    assert all((journal.path/name).read_bytes() == b'FOREIGN' for name in names)


def test_temporary_cleanup_count_is_bounded(tmp_path):
    journal = RollingJournal(tmp_path/'journal')
    journal.path.mkdir()
    for n in range(66):
        (journal.path/f'events-{n:016d}.jsonl.tmp').write_bytes(b'pending')
    with pytest.raises(OSError):
        journal.maintain([])
    assert len(list(journal.path.glob('*.tmp'))) >= 2


async def test_off_housekeeping_removes_expired_interruption(hass, audio_setup, tmp_path):
    hass.config.config_dir = str(tmp_path)
    entry = await audio_setup.setup(playback=True)
    collector = hass.data[DOMAIN][entry.entry_id].audio_diagnostics
    clock = [100000.0]
    collector.journal.clock = lambda: clock[0]
    async with collector.lock:
        await collector._run_disk(collector.journal.maintain, [row(clock)])
        segment = next(collector.journal.path.glob('*.jsonl'))
        pending = segment.with_name(segment.name+'.tmp')
        pending.write_bytes(segment.read_bytes())
    clock[0] += 86401
    collector.wake.set()
    for _ in range(100):
        if not pending.exists():
            break
        await asyncio.sleep(0.01)
    assert not pending.exists()
    assert not collector.enabled and not collector._task.done()
    assert not list(collector.journal.path.glob('*.jsonl'))
