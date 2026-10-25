"""Synthetic regressions for owner-reported standard HA audio feedback."""
# ruff: noqa: S101, INP001, ANN001, ANN202, D103, PLR2004, SLF001, PLC0415
import asyncio
from unittest.mock import AsyncMock,MagicMock
import pytest
from custom_components.loxone import audio_sources as sources
from custom_components.loxone.audio_catalogue import CatalogueTarget
from custom_components.loxone.pyloxone_api import audioserver as wire
from test_audio_sources import Metadata

@pytest.mark.asyncio
async def test_ackless_spotify_uses_fresh_exact_room_account_playing_evidence(monkeypatch):
    """Native device executes serviceplay without any command/result envelope."""
    metadata=Metadata()
    commands=wire.AudioServerCommands('audio.example.invalid',lambda:('synthetic','token'))
    monkeypatch.setattr(commands,'async_service_accounts',AsyncMock(return_value=[{'cmd':'spotify','id':'owner','user':'Canonical user','configerror':False}]))
    socket=AsyncMock();socket.__aenter__.return_value=socket
    async def receive():await asyncio.Future()
    socket.recv.side_effect=receive
    async def send(command):
        assert command=='audio/7/serviceplay/spotify/owner/spotify%40owner%3Atrack%3Aone'
        asyncio.get_running_loop().call_soon(metadata.set,{'mode':'play','audiopath':'spotify:track:one','sourceName':'Canonical user'})
    socket.send.side_effect=send
    monkeypatch.setattr(wire,'connect',MagicMock(return_value=socket))
    monkeypatch.setattr(commands,'_authenticate',AsyncMock())
    target=CatalogueTarget('item','One','spotify','spotify@owner:track:one',audio_path='spotify@owner:track:one',account='owner')
    await asyncio.wait_for(sources.async_select_catalogue(commands,metadata,7,target,is_available=lambda:True),.15)
    socket.send.assert_awaited_once()
    assert not commands.source_fences and not metadata.listeners and commands._socket is None

@pytest.mark.asyncio
async def test_native_catalogue_retains_supplied_cover_for_standard_browser():
    from custom_components.loxone.audio_catalogue import AudioCatalogue
    from test_audio_catalogue import catalogue_commands
    commands=catalogue_commands()
    commands.async_media_folder.return_value=[{'start':0,'totalitems':1,'items':[{'type':2,'id':'spotify@owner:track:one','name':'One','thumbnail':'https://images.example.invalid/one.jpg','coverurl':'https://images.example.invalid/full.jpg'}]}]
    catalogue=AudioCatalogue(commands,7)
    root=await catalogue.async_browse()
    spotify=next(x for x in root.children if x.title.startswith('Spotify'))
    child=(await catalogue.async_browse(spotify.media_content_id)).children[0]
    assert child.thumbnail=='https://images.example.invalid/one.jpg'
    assert child.title=='One' and child.media_class=='track' and child.can_play

@pytest.mark.asyncio
async def test_scoped_spotify_search_groups_clean_titles_and_playlist_ownership():
    from custom_components.loxone.audio_catalogue import AudioCatalogue
    from test_audio_catalogue import catalogue_commands
    commands=catalogue_commands()
    commands.async_search_capabilities.return_value={'spotify':['track','album','playlist']}
    def row(kind,name,suffix,**extra):
        return {'type':2 if kind=='track' else 7,'id':f'spotify@owner:{kind}:{suffix}','name':name,'tag':kind,'thumbnail':'https://images.example.invalid/'+suffix+'.jpg',**extra}
    commands.async_global_search.return_value={'spotify':{'tracks':{'items':[row('track','One','one')]},'albums':{'items':[row('album','Album','album')]},'playlists':{'items':[row('playlist','Mine','mine',owner_id='owner'),row('playlist','Shared','shared',owner_id='someone',public=True),row('playlist','Unknown visibility','other',owner_id='someone')]}}}
    catalogue=AudioCatalogue(commands,7)
    root=await catalogue.async_browse();spotify=next(x for x in root.children if x.title.startswith('Spotify'))
    result=await catalogue.async_search('one',spotify.media_content_id)
    assert {x.title for x in result.result}=={'Tracks','Albums','Your playlists','Public playlists','Other playlists'}
    tracks=next(x for x in result.result if x.title=='Tracks')
    assert tracks.can_expand and not tracks.can_play
    page=await catalogue.async_browse(tracks.media_content_id)
    assert len(page.children)==1 and page.children[0].title=='One'
    assert page.children[0].thumbnail=='https://images.example.invalid/one.jpg'
    assert page.children[0].can_play and not page.can_play

@pytest.mark.asyncio
async def test_standard_browser_track_filter_restricts_native_search_categories():
    from homeassistant.components.media_player.const import MediaClass
    from custom_components.loxone.audio_catalogue import AudioCatalogue
    from test_audio_catalogue import catalogue_commands
    commands=catalogue_commands();commands.async_search_capabilities.return_value={'spotify':['track','album','playlist']}
    commands.async_global_search.return_value={'spotify':{'tracks':{'items':[{'type':2,'id':'spotify@owner:track:one','name':'One'}]}}}
    catalogue=AudioCatalogue(commands,7);root=await catalogue.async_browse();spotify=next(x for x in root.children if x.title.startswith('Spotify'))
    assert {MediaClass.TRACK,MediaClass.ALBUM,MediaClass.PLAYLIST}<=set(spotify.search_media_classes)
    result=await catalogue.async_search('one',spotify.media_content_id,media_filter_classes=[MediaClass.TRACK])
    assert commands.async_global_search.await_args.args[1]=={'spotify':('track',)}
    assert len(result.result)==1 and result.result[0].title=='One' and result.result[0].can_play

@pytest.mark.asyncio
async def test_source_choices_are_exact_native_recent_provider_selections_not_favourites():
    from custom_components.loxone.audio_catalogue import AudioCatalogue
    from test_audio_catalogue import catalogue_commands
    commands=catalogue_commands()
    commands.async_recent_sources=AsyncMock(return_value={'items':[
        {'type':2,'audiopath':'tunein:station:latest','title':'Latest station'},
        {'type':2,'audiopath':'tunein:station:older','title':'Older station'},
        {'type':2,'audiopath':'loxoneradio:station:one','title':'Loxone station'},
        {'type':7,'audiopath':'spotify@owner:playlist:one','title':'Saved context'},
        {'type':2,'audiopath':'library:local:track:one','title':'Indexed song'},
        {'type':7,'audiopath':'spotify:playlist:unscoped','title':'Unknown playback account'}], 'ts':123})
    catalogue=AudioCatalogue(commands,7)
    await catalogue.async_refresh_sources()
    assert set(catalogue.source_choices)=={'Line-In','TuneIn','Loxone Radio','Spotify','Local Library'}
    assert catalogue.source_choices['TuneIn'].audio_path=='tunein:station:latest'
    assert catalogue.source_choices['Spotify'].account=='owner' and catalogue.source_choices['Spotify'].is_context
    assert catalogue.source_choices['Line-In'].folder=='ABCDEF123456#1000001'
    commands.async_room_favourites.assert_not_awaited()
    commands.async_recent_sources.assert_awaited_once_with(7)
    commands.async_recent_sources.return_value={'items':[],'ts':124}
    await catalogue.async_refresh_sources()
    assert set(catalogue.source_choices)=={'Line-In'}

@pytest.mark.asyncio
@pytest.mark.parametrize('row',[
    {'mode':'play','audiopath':'spotify:track:other','sourceName':'Canonical user'},
    {'mode':'play','audiopath':'spotify:track:one','sourceName':'Wrong user'},
    {'mode':'stop','audiopath':'spotify:track:one','sourceName':'Canonical user'},
    {'mode':'play','audiopath':'spotify:track:one','sourceName':'Canonical user','eventype':5},
])
async def test_ackless_spotify_never_accepts_wrong_track_account_or_interruption(monkeypatch,row):
    metadata=Metadata();commands=wire.AudioServerCommands('audio.example.invalid',lambda:('synthetic','token'))
    monkeypatch.setattr(commands,'async_service_accounts',AsyncMock(return_value=[{'cmd':'spotify','id':'owner','user':'Canonical user','configerror':False}]))
    socket=AsyncMock();socket.__aenter__.return_value=socket
    async def receive():await asyncio.Future()
    socket.recv.side_effect=receive
    async def send(command):asyncio.get_running_loop().call_soon(metadata.set,row)
    socket.send.side_effect=send
    monkeypatch.setattr(wire,'connect',MagicMock(return_value=socket));monkeypatch.setattr(commands,'_authenticate',AsyncMock())
    target=CatalogueTarget('item','One','spotify','spotify@owner:track:one',audio_path='spotify@owner:track:one',account='owner')
    with pytest.raises((TimeoutError,wire.AudioCommandError)):
        await asyncio.wait_for(sources.async_select_catalogue(commands,metadata,7,target,is_available=lambda:True),.03)
    socket.send.assert_awaited_once();assert 7 in commands.source_fences
    await commands.async_close();assert not commands.source_fences and not metadata.listeners

@pytest.mark.asyncio
@pytest.mark.parametrize('recent',[None,{}, {'items':None},{'items':[None]},{'items':[{}]*257}])
async def test_source_history_is_bounded_and_never_accepts_a_partial_malformed_snapshot(recent):
    from custom_components.loxone.audio_catalogue import AudioCatalogue
    from test_audio_catalogue import catalogue_commands
    commands=catalogue_commands();commands.async_recent_sources=AsyncMock(return_value=recent)
    catalogue=AudioCatalogue(commands,7)
    with pytest.raises(ValueError):await catalogue.async_refresh_sources()
    assert not catalogue.source_choices

@pytest.mark.asyncio
async def test_native_recent_query_validates_exact_player_and_response_key(monkeypatch):
    commands=wire.AudioServerCommands('audio.example.invalid',lambda:('synthetic','token'))
    query=AsyncMock(return_value={'items':[]});monkeypatch.setattr(commands,'_async_request',query)
    assert await commands.async_recent_sources(7)=={'items':[]}
    query.assert_awaited_once_with('audio/7/recent','recent_result')
    for invalid in (True,None,'7/other',-1):
        with pytest.raises(ValueError):await commands.async_recent_sources(invalid)
    query.assert_awaited_once()

