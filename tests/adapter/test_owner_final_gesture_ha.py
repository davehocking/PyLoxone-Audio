"""Fresh final compiled-native gesture requests through the unchanged owning assertions."""
import json
import os
from pathlib import Path
import pytest
import test_gm03_mobile_ha as existing
from test_audio_grouping_ha import grouped_setup, audio_setup

@pytest.mark.parametrize('index',range(12))
async def test_final_native_gesture_owning_wire(hass,grouped_setup,monkeypatch,index):
    root=Path(os.environ['GM03_FOCUS_EXPORT']).parent
    traces=json.loads((root/'final-gesture/gesture-traces.json').read_text())
    gestures=[t['calls'][0] for t in traces]
    controls=json.loads((root/'final-controls/gesture-owning-requests.json').read_text())
    requests=gestures+controls
    assert len(requests)==12
    monkeypatch.setattr(existing,'REQUESTS',requests)
    await existing.test_literal_mobile_release_registered_service_to_native_bus(hass,grouped_setup,index)
