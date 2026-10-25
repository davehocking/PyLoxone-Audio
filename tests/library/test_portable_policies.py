"""Concrete package API tests; external boundaries alone may be replaced."""
import pytest
import pyloxone_audio

from contextlib import asynccontextmanager
from pyloxone_audio.metadata import AudioMetadataCoordinator
from pyloxone_audio.native import AudioCommandError, AudioServerCommands


def test_native_policies_are_concrete_public_package_entrypoints():
    assert callable(getattr(pyloxone_audio, 'async_send_prepared_announcement', None))
    assert callable(getattr(pyloxone_audio, 'async_resume_native_session', None))


@pytest.mark.asyncio
async def test_real_native_session_rejects_missing_observation_before_bridge_reads():
    metadata = AudioMetadataCoordinator("audio.example.invalid")
    commands = AudioServerCommands("audio.example.invalid", lambda: ("synthetic", "synthetic-token"))
    calls = []

    class Bridge:
        @asynccontextmanager
        async def async_native_session(self, available):
            calls.append("read")
            yield pyloxone_audio.SpotifyNativeSession("Synthetic owner", "synthetic-account")

    try:
        with pytest.raises(AudioCommandError):
            await pyloxone_audio.async_resume_native_session(commands, metadata, 7, Bridge(), lambda: True)
        assert calls == []
    finally:
        await commands.async_close()
        await metadata.async_stop()
