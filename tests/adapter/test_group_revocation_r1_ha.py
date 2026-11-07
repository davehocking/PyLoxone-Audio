"""R1: published revocation is permanent for a request, not for future use.

Invented credentials/rooms and the actual HA service/authenticated native path.
"""
import asyncio
import json

import pytest
from homeassistant.exceptions import HomeAssistantError
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audio_grouping_ha import STATE, payload, row
from test_audio_grouping_ha import grouped_setup as grouped_setup
from test_audio_grouping_ha import audio_setup as audio_setup
from test_audioserver_playback import SyntheticAudioSocket
from test_audioserver_playback import rsa_key as rsa_key


@pytest.mark.parametrize('phase', ['auth', 'reply', 'cleanup'])
@pytest.mark.parametrize('boundary', ['token-only', 'availability-group', 'availability-notify', 'identical-token'])
async def test_published_reversion_fences_until_cleanup_and_allows_fresh_request(
    hass, grouped_setup, monkeypatch, rsa_key, phase, boundary
):
    g = grouped_setup
    entry, co, ids = await g.setup()
    await g.feed(entry, row('native', (1, 2)))
    auth = ['synthetic-active-token']
    co.api.get_token_dict = lambda: {'token': auth[0]}
    co.audio_commands._credentials = lambda: ('synthetic-user', auth[0])
    sockets = []
    perturbing = True
    original_data = dict(entry.data)

    async def perturb():
        if not perturbing:
            return
        if boundary in ('token-only', 'identical-token'):
            for value in (('synthetic-replacement-token', 'synthetic-active-token') if boundary == 'token-only' else ('synthetic-active-token',)):
                auth[0] = value
                # No group frame: the owning callback must observe this boundary.
                co._on_token_changed({'token': value, 'valid_until': 9999999999})
        else:
            for available in (False, True):
                co.connection_available = available
                if boundary == 'availability-group':
                    await g.callbacks[entry.entry_id]['callback']({STATE: payload(row('native', (1, 2)))})
                else:
                    co.audio_grouping.notify()

    class Socket(SyntheticAudioSocket):
        async def send(self, message):
            if message.startswith('audio/grouped/'):
                self.sent.append(message)
                if phase == 'reply':
                    await perturb()
                self.queue.put_nowait(json.dumps({'grouped_play_result': {'players': [{'playerid': p, 'mode': 'play'} for p in (1, 2)]}}))
                return
            await super().send(message)
            if message.startswith('secure/authenticate/') and phase == 'auth':
                await perturb()

        async def __aexit__(self, *args):
            if phase == 'cleanup':
                await perturb()
            await super().__aexit__(*args)

    def connect(*args, **kwargs):
        s = Socket(rsa_key)
        sockets.append(s)
        return s

    monkeypatch.setattr(wire, 'connect', connect)
    before = {i: hass.states.get(i) for i in ids.values()}
    failure = None
    try:
        await hass.services.async_call('media_player', 'media_play', {'entity_id': ids[1]}, blocking=True)
    except (HomeAssistantError, asyncio.CancelledError) as error:
        failure = error
    sent = [m for s in sockets for m in s.sent if m.startswith('audio/grouped/')]
    stable = boundary == 'identical-token'
    assert (failure is None) == stable
    assert sent == ([] if phase == 'auth' and not stable else ['audio/grouped/play/1,2'])
    assert not co.audio_grouping.native.uncertain
    assert all(s.closed for s in sockets)
    assert co.audio_commands._socket is None
    assert not co.audio_grouping.native._scope
    assert not co.audio_grouping.native._tasks
    assert not co.audio_grouping.native._requests
    assert all(not e._transport_tasks for e in g.entities.values())
    assert all(hass.states.get(i).state == state.state for i, state in before.items())
    co.api.send_websocket_command.assert_not_awaited()
    if boundary in ('token-only', 'identical-token'):
        assert entry.data['token'] == 'synthetic-active-token'
        assert all(entry.data[k] == v for k, v in original_data.items() if k not in ('token', 'valid_until'))
    # Fresh explicit service after fresh authority can succeed; never auto replay.
    perturbing = False
    await g.feed(entry, row('native', (1, 2)))
    await hass.services.async_call('media_player', 'media_play', {'entity_id': ids[2]}, blocking=True)
    assert [m for s in sockets for m in s.sent if m.startswith('audio/grouped/')] == sent + ['audio/grouped/play/1,2']
    assert all(s.closed for s in sockets)


@pytest.mark.parametrize('has_grouping', [False, True])
async def test_token_persistence_does_not_require_optional_grouping(hass, grouped_setup, has_grouping):
    g = grouped_setup
    entry, co, _ = await g.setup()
    if not has_grouping:
        co.audio_grouping = None
    before = dict(entry.data)
    co._on_token_changed({'token': 'invented-refreshed-token', 'valid_until': 12345})
    assert entry.data == {**before, 'token': 'invented-refreshed-token', 'valid_until': 12345}


async def test_optional_observation_failure_does_not_break_token_persistence(hass, grouped_setup, monkeypatch, caplog):
    entry, co, _ = await grouped_setup.setup()

    def failed():
        raise ValueError('synthetic observer failure')

    with monkeypatch.context() as m:
        m.setattr(co.audio_grouping.native, 'observe_current', failed)
        co._on_token_changed({'token': 'invented-refreshed-token'})
    assert entry.data['token'] == 'invented-refreshed-token'
    assert 'Audio grouping token observation failed (ValueError)' in caplog.text
    assert 'invented-refreshed-token' not in caplog.text


async def test_persistence_failure_does_not_erase_observed_request_revocation(hass, grouped_setup, monkeypatch):
    g = grouped_setup
    entry, co, _ = await g.setup()
    await g.feed(entry, row('native', (1, 2)))
    token = ['synthetic-active-token']
    co.api.get_token_dict = lambda: {'token': token[0]}
    request = co.audio_grouping.native._watch_request(frozenset({1, 2}))

    def failed(*args, **kwargs):
        raise OSError('synthetic persistence unavailable')

    try:
        with monkeypatch.context() as m:
            m.setattr(hass.config_entries, 'async_update_entry', failed)
            for value in ('synthetic-replacement-token', 'synthetic-active-token'):
                token[0] = value
                co._on_token_changed({'token': value})
        assert not request()
    finally:
        co.audio_grouping.native._requests.discard(request)
