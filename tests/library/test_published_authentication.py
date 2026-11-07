"""Bounded published-auth guard ownership; no transport or credentials retained by observer registry."""
import gc
import weakref

import pytest
from pyloxone_audio.native import AudioServerCommands


@pytest.mark.parametrize('history', ['stable', 'identical', 'persistent', 'ABA', 'unpublished'])
def test_published_authentication_guard_history_and_fresh_lifetime(history):
    token = ['synthetic-A']
    commands = AudioServerCommands('synthetic.invalid', lambda: ('synthetic-user', token[0]))
    guard = commands.authentication_guard()
    if history in {'persistent', 'ABA', 'unpublished'}:
        token[0] = 'synthetic-B'
        if history != 'unpublished':
            commands.observe_authentication()
        if history != 'persistent':
            token[0] = 'synthetic-A'
            if history == 'ABA':
                commands.observe_authentication()
    elif history == 'identical':
        commands.observe_authentication()
    assert guard() == (history not in {'persistent', 'ABA'})
    assert commands.authentication_guard()()
    ref = weakref.ref(guard)
    del guard
    gc.collect()
    assert ref() is None and len(commands._authentication_guards) == 0


def test_published_credential_getter_failure_revokes_without_exception_text(caplog):
    failed = [False]
    def credentials():
        if failed[0]:
            raise RuntimeError('synthetic-private-getter-do-not-log')
        return 'synthetic-user', 'synthetic-A'
    commands = AudioServerCommands('synthetic.invalid', credentials)
    guard = commands.authentication_guard()
    failed[0] = True
    commands.observe_authentication()
    failed[0] = False
    commands.observe_authentication()
    assert not guard() and commands.authentication_guard()()
    assert 'synthetic-private-getter-do-not-log' not in caplog.text


async def test_authentication_guards_close_and_do_not_accumulate():
    commands = AudioServerCommands('synthetic.invalid', lambda: ('synthetic-user', 'synthetic-A'))
    for _ in range(100):
        assert commands.authentication_guard()()
    gc.collect()
    assert len(commands._authentication_guards) == 0
    guards = [commands.authentication_guard() for _ in range(12)]
    assert len(commands._authentication_guards) == 12
    await commands.async_close()
    assert not any(guard() for guard in guards)
    assert not commands.authentication_guard()()
    del guards
    gc.collect()
    assert len(commands._authentication_guards) == 0
