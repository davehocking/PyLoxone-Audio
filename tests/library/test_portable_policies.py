"""Concrete package API tests; external boundaries alone may be replaced."""
import pytest
import pyloxone_audio

from contextlib import asynccontextmanager
from pyloxone_audio.metadata import AudioMetadataCoordinator
from pyloxone_audio.native import AudioCommandError, AudioServerCommands


def test_native_policies_are_concrete_public_package_entrypoints():
    assert callable(getattr(pyloxone_audio, 'async_send_prepared_announcement', None))
    assert callable(getattr(pyloxone_audio, 'async_source_route', None))
