"""Fail closed if the concrete package or pure tests try importing any HA code."""
import importlib.abc
import json
import os
from pathlib import Path
import sys

ATTEMPTS = []


class RejectHA(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'homeassistant', 'custom_components', 'pytest_homeassistant_custom_component'}:
            ATTEMPTS.append(fullname)
            raise ImportError('Home Assistant is deliberately rejected: '+fullname)
        return None


if any(name.split('.')[0] in {'homeassistant','custom_components'} for name in sys.modules):
    raise RuntimeError('HA was loaded before the independence guard')
sys.meta_path.insert(0, RejectHA())


def pytest_sessionfinish(session, exitstatus):
    loaded = sorted(name for name in sys.modules if name.split('.')[0] in {'homeassistant','custom_components'})
    output = os.environ.get('AUDIO_INDEPENDENCE_RECEIPT')
    receipt = {'ha_import_attempts':ATTEMPTS,'ha_modules_loaded':loaded,'pytest_exit':int(exitstatus),
        'package_path':str(Path(sys.modules['pyloxone_audio'].__file__).resolve())}
    if output:
        Path(output).write_text(json.dumps(receipt,indent=2)+'\n')
    if ATTEMPTS or loaded:
        session.exitstatus = 1
