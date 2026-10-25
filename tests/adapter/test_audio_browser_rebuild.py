"""Synthetic browser artwork regressions; no household IO."""
# ruff: noqa: S101, INP001, ANN001, ANN202, D103, SLF001, PLC0415, F811, F401
from unittest.mock import AsyncMock
import pytest
from aiohttp.test_utils import make_mocked_request
from homeassistant.components.media_player import KEY_AUTHENTICATED, MediaPlayerImageView
from custom_components.loxone.audio_catalogue import AudioCatalogue, CatalogueTarget
from custom_components.loxone.audio_radio import RADIO_MEDIA_TYPE
from test_audio_catalogue import catalogue_commands
from test_audioserver_ha import audio_setup, zone_entity_id
from custom_components.loxone.pyloxone_api import audioserver as wire


@pytest.mark.asyncio
async def test_browse_artwork_uses_existing_ha_proxy_and_exact_discovered_id(hass, audio_setup, monkeypatch):
    commands = catalogue_commands()
    for name, value in vars(commands).items():
        monkeypatch.setattr(wire.AudioServerCommands, name, value)
    await audio_setup.setup(playback=True)
    entity = hass.data['media_player'].get_entity(zone_entity_id(hass, 7))
    root = await entity.async_browse_media()
    line_in = next(x for x in root.children if x.title == 'Line-In')
    library = next(x for x in root.children if x.title == 'Local Library')
    assert line_in.thumbnail.startswith('/api/media_player_proxy/')
    assert library.thumbnail.startswith('/api/media_player_proxy/')
    request = make_mocked_request('GET', line_in.thumbnail)
    request[KEY_AUTHENTICATED] = True
    response = await MediaPlayerImageView(hass.data['media_player']).get(
        request, entity.entity_id, RADIO_MEDIA_TYPE, line_in.media_content_id,
    )
    assert response.status == 200 and response.content_type == 'image/svg+xml'
    assert b'<svg' in response.body
    data, mime = await entity.async_get_browse_image(RADIO_MEDIA_TYPE, line_in.media_content_id)
    assert mime == 'image/svg+xml' and b'<svg' in data
    assert await entity.async_get_browse_image(RADIO_MEDIA_TYPE, line_in.media_content_id, 'native-image-version') == (data, mime)
    target = entity._radio_catalogue._parse_item({'type':2, 'name':'Radio', 'audiopath':'tunein:station:one', 'coverurl':'http://images.example.invalid/cover.png'}, 'world')
    item = entity._radio_catalogue._item(target)
    fetch = AsyncMock(return_value=(b'synthetic-image', 'image/png'))
    monkeypatch.setattr(entity, '_async_fetch_image', fetch)
    assert await entity.async_get_browse_image(RADIO_MEDIA_TYPE, item.media_content_id) == (b'synthetic-image', 'image/png')
    fetch.assert_awaited_once_with('http://images.example.invalid/cover.png')
    assert await entity.async_get_browse_image(RADIO_MEDIA_TYPE, 'http://untrusted.invalid/') == (None, None)
    assert await entity.async_get_browse_image('wrong-type', item.media_content_id) == (None, None)
    assert fetch.await_count == 1


@pytest.mark.asyncio
async def test_spotify_saved_playlist_route_and_truthful_ownership_groups():
    c = catalogue_commands()
    catalogue = AudioCatalogue(c, 7)
    root = await catalogue.async_browse()
    spotify = next(x for x in root.children if x.title.startswith('Spotify'))
    c.async_media_folder.return_value = [{'start':0, 'totalitems':0, 'items':[]}]
    page = await catalogue.async_browse(spotify.media_content_id)
    saved = next(x for x in page.children if x.title == 'Saved playlists')
    assert not saved.can_play and saved.can_expand
    rows = [{'type':7, 'name':name, 'id':'spotify@owner:playlist:'+name, 'owner_id':owner} for name,owner in [('Mine','owner'),('Followed','someone-else')]]
    c.async_media_folder.return_value = [{'start':0, 'totalitems':2, 'items':rows}]
    playlists = await catalogue.async_browse(saved.media_content_id)
    c.async_media_folder.assert_awaited_with('spotify', 'owner', '3', 0)
    assert {x.title for x in playlists.children} == {'Your playlists', 'Other playlists'}
    assert all(not x.can_play for x in playlists.children)
    mine = next(x for x in playlists.children if x.title == 'Your playlists')
    assert [x.title for x in (await catalogue.async_browse(mine.media_content_id)).children] == ['Mine']


@pytest.mark.asyncio
async def test_saved_playlist_public_visibility_and_continuation_keep_exact_account():
    c = catalogue_commands()
    catalogue = AudioCatalogue(c, 7)
    saved = catalogue._item(CatalogueTarget('folder', 'Saved playlists', 'spotify', '3', account='owner'))
    rows = [{'type':7, 'name':'Mine', 'id':'spotify@owner:playlist:mine', 'owner_id':'owner'}, {'type':7, 'name':'Public', 'id':'spotify@owner:playlist:public', 'owner_id':'someone', 'public':True}]
    c.async_media_folder.return_value = [{'start':0, 'totalitems':3, 'items':rows}]
    first = await catalogue.async_browse(saved.media_content_id)
    assert {x.title for x in first.children} == {'Your playlists', 'Public playlists', 'More items…'}
    more = next(x for x in first.children if x.title == 'More items…')
    c.async_media_folder.return_value = [{'start':2, 'totalitems':3, 'items':[{'type':7, 'name':'Followed', 'id':'spotify@owner:playlist:followed', 'owner_id':'someone'}]}]
    second = await catalogue.async_browse(more.media_content_id)
    c.async_media_folder.assert_awaited_with('spotify', 'owner', '3', 2)
    assert [x.title for x in second.children] == ['Other playlists']


def test_tunein_discovery_keeps_validated_cover():
    catalogue = AudioCatalogue(catalogue_commands(), 7)
    target = catalogue._parse_item({"type": 2, "name": "Synthetic Radio", "audiopath": "tunein:station:one", "coverurl": "http://images.example.invalid/one.png"}, "world")
    item = catalogue._item(target)
    assert item.thumbnail == "http://images.example.invalid/one.png"
    assert catalogue.resolve(item.media_content_id).audio_path == "tunein:station:one"
