"""Native sparse status cannot distinguish enrichment from a context takeover.

The opaque causal labels are NOT supplied to the implementation. Both histories
must remain refused when no complete status supplies a prior parent identity.
"""
import pytest
from test_audio_grouping_ha import grouped_setup, audio_setup
from test_audioserver_playback import rsa_key
from test_preflight_lifetimes_ha import preflight_peer
from test_precommand_parent_qualification_v2_ha import native_row


@pytest.mark.parametrize('unobserved_origin', ['ordinary-enrichment', 'external-context-takeover'])
async def test_observationally_identical_sparse_status_remains_refused(preflight_peer, unobserved_origin):
    p = preflight_peer
    p.status = [native_row(2, None)]
    # The SAME reported source/account/content/parent frame follows the send in
    # both causal stories. No hidden origin flag reaches commands or guards.
    assert await p.call('indistinguishable-' + unobserved_origin) == 'HomeAssistantError', p.receipt
    assert p.routes == ['audio/2/status', 'audio/grouped/play/1,2']
    assert p.before_send == [['Local Library', 'Synthetic retained account', 'library:local:track:existing-2', None]]
