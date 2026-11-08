"""New full owning-service qualification lifetime and ambiguity controls."""
import asyncio
import time

import pytest
from homeassistant.helpers import entity_registry as er
from test_audio_grouping_ha import grouped_setup, audio_setup, STATE, payload, row
from test_audioserver_playback import rsa_key
from test_preflight_lifetimes_ha import preflight_peer
from test_precommand_parent_qualification_v2_ha import native_row

PHASES = ['status-auth', 'status-send', 'status-cleanup', 'group-auth', 'group-send', 'group-cleanup']
BOUNDARIES = ['content-ABA', 'account-ABA', 'source-ABA', 'parent-ABA',
              'auth-ABA', 'topology-ABA', 'availability-ABA', 'lifecycle-ABA',
              'command-owner-ABA', 'intent', 'registry-ABA']


@pytest.mark.parametrize('phase', PHASES)
@pytest.mark.parametrize('boundary', BOUNDARIES)
async def test_each_published_boundary_revokes_until_cleanup_and_allows_fresh_intent(preflight_peer, phase, boundary):
    p = preflight_peer
    fired = []
    async def perturb(observed_phase):
        if observed_phase != phase or fired:
            return
        fired.append(observed_phase)
        e = p.g.entities[p.ids[2]]
        before = p.identity(2)
        parent = before[3]
        if boundary.endswith('-ABA') and boundary.split('-')[0] in ('content', 'account', 'source', 'parent'):
            changed = {
                'content-ABA': {'audiopath': 'library:local:track:replacement'},
                'account-ABA': {'sourceName': 'Synthetic replacement account'},
                'source-ABA': {'audiopath': 'tunein:station:replacement'},
                'parent-ABA': {'parent': {'id': 'parent-B'}},
            }[boundary]
            await p.emit({**native_row(2, parent), **changed})
            await p.emit(native_row(2, parent))
        elif boundary == 'auth-ABA':
            await p.publish('synthetic-replacement-token')
            await p.publish('synthetic-active-token')
        elif boundary == 'topology-ABA':
            callback = p.g.callbacks[p.entry.entry_id]['callback']
            for players in ((1, 3), (1, 2)):
                await callback({STATE: payload(row('pair', players), row('untouched', (5, 6)))})
        elif boundary == 'availability-ABA':
            for value in (False, True):
                p.co.connection_available = value
                p.co.audio_grouping.notify()
        elif boundary == 'lifecycle-ABA':
            for value in (True, False):
                e._audio_removed = value
                p.co.audio_grouping.notify()
        elif boundary == 'command-owner-ABA':
            original = e._audio_commands
            from pyloxone_audio.native import AudioServerCommands
            replacement = AudioServerCommands('audio.example.invalid', lambda: ('synthetic-user', 'synthetic-active-token'))
            for value in (replacement, original):
                e._audio_commands = value
                p.co.audio_grouping.notify()
        elif boundary == 'intent':
            e._source_generation += 1
            p.co.audio_grouping.notify()
        elif boundary == 'registry-ABA':
            registry = er.async_get(p.co.hass)
            for value in (er.RegistryEntryDisabler.INTEGRATION, None):
                registry.async_update_entity(e.entity_id, disabled_by=value)
                p.co.audio_grouping.notify()
        else:
            raise AssertionError('Unspecified boundary')
    p.hook = perturb
    label = phase + '-' + boundary
    result = await p.call(label)
    assert fired == [phase]
    assert result in ('HomeAssistantError', 'CancelledError'), p.receipt
    writes = [r for r in p.routes if not r.endswith('/status')]
    assert writes == (['audio/grouped/play/1,2'] if phase in ('group-send', 'group-cleanup') else []), p.receipt
    assert len([r for r in p.routes if r.endswith('/status')]) <= 1
    # Do not reset uncertainty, membership or cache to recover; this is a NEW
    # explicit service, not replay of captured work.
    p.hook = None
    count = len(writes)
    if boundary == 'registry-ABA':
        # HA legitimately processes disabling as removal of this exact entity.
        # Restoring the registry flag is NOT a re-registration of that object.
        # A fresh call to that removed entity must also refuse; do not fake a
        # re-add or weaken lifecycle guards to satisfy an invalid fixture.
        assert p.g.entities[p.ids[2]]._audio_removed
        assert await p.call(label + '-fresh') == 'HomeAssistantError', p.receipt
        assert len([r for r in p.routes if not r.endswith('/status')]) == count
    else:
        assert await p.call(label + '-fresh') == 'success', p.receipt
        assert len([r for r in p.routes if not r.endswith('/status')]) == count + 1


@pytest.mark.parametrize('phase', PHASES)
@pytest.mark.parametrize('change', ['progress', 'identical-token', 'unrelated-room'])
async def test_benign_observations_do_not_invalidate_request(preflight_peer, phase, change):
    p = preflight_peer
    fired = []
    async def perturb(observed):
        if observed != phase or fired:
            return
        fired.append(observed)
        if change == 'progress':
            await p.emit(native_row(2, p.identity(2)[3], time=25, title='Synthetic updated title'))
        elif change == 'identical-token':
            await p.publish('synthetic-active-token')
        else:
            await p.emit(native_row(5, 'unrelated-parent', mode='play'))
    p.hook = perturb
    assert await p.call('benign-' + phase + '-' + change) == 'success', p.receipt
    assert fired == [phase]
    assert p.routes == ['audio/2/status', 'audio/grouped/play/1,2']
    assert p.before_send[0][3] is None  # independent status never populated cache


@pytest.mark.parametrize('kind', ['wrong-player', 'duplicate-player', 'empty-list', 'boolean',
                                  'account', 'content', 'source', 'event', 'unknown-event',
                                  'missing-mode', 'missing-account', 'missing-content', 'malformed-parent'])
async def test_preflight_ambiguous_or_contradictory_status_never_sends_transport(preflight_peer, kind):
    p = preflight_peer
    good = native_row(2, 'parent-A')
    p.status = {
        'wrong-player': [native_row(3, 'parent-A')],
        'duplicate-player': [good, good], 'empty-list': [], 'boolean': True,
        'account': [native_row(2, 'parent-A', sourceName='Synthetic replacement account')],
        'content': [native_row(2, 'parent-A', audiopath='library:local:track:replacement')],
        'source': [native_row(2, 'parent-A', audiopath='tunein:station:replacement')],
        'event': [native_row(2, 'parent-A', eventype=1, mode='play', eventstate='active')],
        'unknown-event': [native_row(2, 'parent-A', eventype=False)],
        'missing-mode': [{k: v for k, v in good.items() if k != 'mode'}],
        'missing-account': [{k: v for k, v in good.items() if k != 'sourceName'}],
        'missing-content': [{k: v for k, v in good.items() if k != 'audiopath'}],
        'malformed-parent': [{**native_row(2, None), 'parent': {'id': False}}],
    }[kind]
    result = await p.call('status-' + kind)
    # A malformed optional parent is not used as a qualification. With intact
    # known identity the original strict transport may run, but enrichment must
    # still fail. All other malformed/contradictory known fields forbid send.
    assert result == 'HomeAssistantError', p.receipt
    assert p.routes == (['audio/2/status', 'audio/grouped/play/1,2'] if kind == 'malformed-parent' else ['audio/2/status'])


@pytest.mark.parametrize('kind', ['boolean', 'partial', 'error'])
async def test_good_preflight_cannot_turn_bad_group_reply_into_success(preflight_peer, kind):
    p = preflight_peer
    p.group_reply = kind
    assert await p.call('group-reply-' + kind) == 'HomeAssistantError', p.receipt
    assert p.routes == ['audio/2/status', 'audio/grouped/play/1,2']


async def test_pending_read_uses_existing_total_deadline_without_write_or_retry(preflight_peer):
    p = preflight_peer
    p.status_release = asyncio.Event()
    start = time.monotonic()
    assert await p.call('status-deadline') == 'HomeAssistantError'
    assert 7.8 <= time.monotonic() - start < 11
    assert p.routes == ['audio/2/status']


async def test_cancellation_during_preflight_drains_socket_and_reservation(preflight_peer):
    p = preflight_peer
    p.status_release = asyncio.Event()
    task = asyncio.create_task(p.call('status-cancel'))
    try:
        await asyncio.wait_for(p.status_sent.wait(), 2)
        task.cancel()
        assert await task == 'CancelledError'
        assert p.routes == ['audio/2/status']
    finally:
        p.status_release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
