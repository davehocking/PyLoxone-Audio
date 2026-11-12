"""Explicit test peer lifecycle controls for the 0.1.6 transport contract.

Historical assertions that every peer is closed now run after this explicit
fixture cleanup, not after every successful command. Functional/guard assertions
are unchanged; controlled-clock and owning-unload tests separately exercise the
production retention/expiry policy. This helper never releases caller fences,
changes metadata, changes credentials or sends/replays a native command.
"""
async def close_retained_peer(commands):
    session = getattr(commands, '_session', None)
    if session is not None:
        if session._busy:
            raise AssertionError('Fixture cleanup must not hide an active request')
        await session.close()
        if session.reader is not None and not session.reader.done():
            raise AssertionError('Command reader leaked after explicit peer cleanup')
        if session._idle_timer is not None:
            raise AssertionError('Idle timer leaked after explicit peer cleanup')


class ColdAuthState:
    """Selecting an authentication hook explicitly selects a cold test route."""
    def __init__(self, commands):
        self._commands = commands
        self._auth_hook = None

    @property
    def auth_hook(self):
        return self._auth_hook

    @auth_hook.setter
    def auth_hook(self, value):
        self._auth_hook = value
        if value is not None:
            # There is no second authentication on a clean warm lease. These
            # named legacy auth tests must actually create their tested stage.
            self._commands.reuse_session = False
            session = getattr(self._commands, '_session', None)
            if session is not None:
                if session._busy:
                    raise AssertionError('Cold auth must be selected between requests')
                session.invalidate()


class ColdAuthControls(dict):
    """A requested during-seek AUTH hook selects the existing cold route."""
    def __init__(self, commands, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._state = ColdAuthState(commands)

    def __setitem__(self, key, value):
        if key == 'during_seek' and value:
            self._state.auth_hook = value
        super().__setitem__(key, value)
