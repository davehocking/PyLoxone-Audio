"""The distribution exports real code, not host entity logic or a fake facade."""
from pyloxone_audio import native
import pyloxone_audio


def test_public_package_owns_concrete_api_and_excludes_host_draft():
    assert not hasattr(pyloxone_audio, "SourceDiagnostics")
    assert not hasattr(pyloxone_audio, "AudioClient")
    assert pyloxone_audio.AudioServerCommands is native.AudioServerCommands
    assert pyloxone_audio.AudioZoneMetadata is native.AudioZoneMetadata
