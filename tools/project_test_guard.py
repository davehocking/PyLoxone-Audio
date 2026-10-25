"""Test-only imported-path and warning evidence; never part of library runtime."""
from pathlib import Path
import importlib.metadata
import json
import os
import sys

WARNINGS=[]


def pytest_warning_recorded(warning_message, when, nodeid, location):
    WARNINGS.append({'category':warning_message.category.__name__,'message':str(warning_message.message),'when':when,'nodeid':nodeid})


def pytest_sessionfinish(session, exitstatus):
    import pyloxone_audio
    root=Path(os.environ['PYLOXONE_PROJECT_LIBRARY_ROOT']).resolve()
    package=Path(pyloxone_audio.__file__).resolve()
    assert package.is_relative_to(root),str(package)
    assert importlib.metadata.version('PyLoxone-Audio')=='0.1.0'
    assert 'pyloxone_audio.diagnostics' not in sys.modules
    assert 'custom_components.loxone.audio_diagnostics' not in sys.modules
    owners={}
    if os.environ['PYLOXONE_PROJECT_TEST_SUITE']=='adapter':
        host=Path(os.environ['PYLOXONE_AUDIO_HOST_ROOT']).resolve()
        for name in ['custom_components.loxone.media_player','custom_components.loxone.spotify_continuity','custom_components.loxone.audio_sources']:
            p=Path(sys.modules[name].__file__).resolve()
            assert p.is_relative_to(host),str(p)
            owners[name]=str(p)
    Path(os.environ['PYLOXONE_PROJECT_RECEIPT']).write_text(json.dumps({'package_path':str(package),'version':'0.1.0','owning_modules':owners,'exit_code':int(exitstatus),'warnings':WARNINGS},indent=2)+'\n')
