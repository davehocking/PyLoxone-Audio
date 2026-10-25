"""Independent-review regressions: filtering and entry-owned discovery."""
# ruff: noqa: S101, INP001, ANN001, ANN202, D103, SLF001, PLC0415, F401, F811
import asyncio
from unittest.mock import AsyncMock
import pytest
from homeassistant.components.media_player import BrowseMedia,SearchMediaQuery
from homeassistant.components.media_player.const import MediaClass
from custom_components.loxone.audio_catalogue import AudioCatalogue
from test_audio_catalogue import catalogue_commands
from test_audioserver_ha import audio_setup,zone_entity_id

@pytest.mark.asyncio
@pytest.mark.parametrize('scoped',[False,True])
async def test_track_filter_never_includes_loxone_radio(scoped):
    commands=catalogue_commands();commands.async_search_capabilities.return_value={'local':['track']}
    commands.async_global_search.return_value={'local':{'tracks':{'items':[]}}}
    catalogue=AudioCatalogue(commands,7)
    radio=AsyncMock(return_value=[BrowseMedia(title='One',media_class=MediaClass.CHANNEL,media_content_type='pyloxone_radio',media_content_id='one',can_play=True,can_expand=False)])
    catalogue._loxone_radio_search=radio
    folder=None
    if scoped:
        root=await catalogue.async_browse();folder=next(c.media_content_id for c in root.children if c.title=='Loxone Radio')
    result=await catalogue.async_search('one',folder,media_filter_classes=[MediaClass.TRACK])
    assert not any(item.media_class==MediaClass.CHANNEL for item in result.result)
    radio.assert_not_awaited()

@pytest.mark.asyncio
async def test_linked_spotify_with_no_matching_filter_categories_returns_empty_not_unlinked():
    commands=catalogue_commands();commands.async_search_capabilities.return_value={'spotify':['track']}
    catalogue=AudioCatalogue(commands,7);root=await catalogue.async_browse();folder=next(c.media_content_id for c in root.children if c.title.startswith('Spotify'))
    result=await catalogue.async_search('one',folder,media_filter_classes=[MediaClass.ALBUM])
    assert result.result==[];commands.async_global_search.assert_not_awaited()

@pytest.mark.parametrize('service,row',[
    ('loxoneradio',{'type':2,'id':'loxoneradio:station:one','audiopath':'loxoneradio:station:one','name':'One'}),
    ('library',{'type':11,'id':'one','audiopath':'playlist:one','name':'One'}),
])
def test_all_native_item_branches_preserve_valid_artwork(service,row):
    row={**row,'coverurl':'https://images.example.invalid/one.jpg'}
    target=AudioCatalogue._parse_source_item(row,service)
    assert target.thumbnail==row['coverurl']

def test_explicit_is_public_playlist_visibility_is_preserved():
    target=AudioCatalogue._parse_source_item({'type':7,'id':'spotify@owner:playlist:one','name':'One','owner_id':'someone','is_public':True},'spotify','owner')
    assert target.playlist_group=='Public playlists'


@pytest.mark.asyncio
async def test_favourites_obey_requested_result_class():
    commands=catalogue_commands()
    commands.async_room_favourites=AsyncMock(return_value=[{'id':7,'start':0,'totalitems':2,'items':[
        {'id':1,'name':'One radio','type':'tunein','audiopath':'tunein:station:one'},
        {'id':2,'name':'One track','type':'library_track','audiopath':'library:local:track:one'}]}])
    catalogue=AudioCatalogue(commands,7)
    result=await catalogue.async_search('One','pyloxone-radio:favourites',media_filter_classes=[MediaClass.TRACK])
    assert [row.title for row in result.result]==['One track']
    assert all(row.media_class==MediaClass.TRACK for row in result.result)

@pytest.mark.asyncio
@pytest.mark.parametrize('kind,expected', [('album',MediaClass.ALBUM),('artist',MediaClass.ARTIST),('playlist',MediaClass.PLAYLIST)])
async def test_local_category_filters_return_the_requested_native_media_class(kind,expected):
    commands=catalogue_commands();commands.async_search_capabilities.return_value={'local':[kind]}
    commands.async_global_search.return_value={'local':{kind+'s':{'items':[{'type':7,'id':'library:local:'+kind+':one','name':'One'}]}}}
    catalogue=AudioCatalogue(commands,7);root=await catalogue.async_browse();folder=next(x for x in root.children if x.title=='Local Library')
    result=await catalogue.async_search('One',folder.media_content_id,media_filter_classes=[expected])
    assert len(result.result)==1 and result.result[0].media_class==expected
    assert expected in folder.search_media_classes
    assert expected in root.search_media_classes

@pytest.mark.asyncio
@pytest.mark.parametrize('operation',['startup','browse','search'])
async def test_entry_unload_owns_every_discovery_task(hass,audio_setup,monkeypatch,operation):
    entry=await audio_setup.setup(playback=True)
    entity=hass.data['media_player'].get_entity(zone_entity_id(hass,7));entered=asyncio.Event()
    async def blocked(*args,**kwargs):entered.set();await asyncio.Future()
    if operation=='startup':
        monkeypatch.setattr(entity._audio_commands,'async_room_favourites',blocked)
        coroutine=entity._async_refresh_audio_sources()
    elif operation=='browse':
        monkeypatch.setattr(entity._radio_catalogue,'async_browse',blocked)
        coroutine=entity.async_browse_media()
    else:
        monkeypatch.setattr(entity._radio_catalogue,'async_search',blocked)
        coroutine=entity.async_search_media(SearchMediaQuery(search_query='one'))
    task=asyncio.create_task(coroutine)
    try:
        await asyncio.wait_for(entered.wait(),1)
        assert task in entity._discovery_tasks
        assert await hass.config_entries.async_unload(entry.entry_id)
        with pytest.raises(asyncio.CancelledError):await task
        assert not entity._discovery_tasks
    finally:
        task.cancel();await asyncio.gather(task,return_exceptions=True)
