"""Exact compiled native GM03 emission provenance, not manually restated calls."""
import hashlib
import json
from pathlib import Path


def native_trace(kind):
    root=Path(__file__).resolve().parents[2]
    directory=root/'tests/frontend'
    provenance=json.loads((directory/'gm03-native-provenance.json').read_text())
    for name,digest in provenance['inputs'].items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
    asset=root/'adapters/pyloxone/frontend/dist/group-control-card-0.1.3.dev7.js'
    assert hashlib.sha256(asset.read_bytes()).hexdigest()==provenance['module_sha256']
    filename='gm03-native-requests.json' if kind=='workflow' else 'gm03-native-numeric.json'
    requests=json.loads((directory/filename).read_text())
    assert len(requests)==provenance['counts'][kind]
    return requests
