"""Den music picks resolve to server audio tracks, not video transcodes."""
import unittest
from unittest import mock
from bromigos_homelab.adapters.labvideo import JellyfinVideo, PlexVideo


class Music(unittest.TestCase):
    def jellyfin(self):
        a=mock.Mock();a._user.return_value='user';a.FIELDS=JellyfinVideo.FIELDS
        a.name='jellyfin';a.endpoint='https://media.example.org';a.auth_headers.return_value={}
        a._item=lambda item:JellyfinVideo._item(a,item)
        def fetch(path,**kw):
            if 'IncludeItemTypes=MusicArtist' in path or 'IncludeItemTypes=MusicAlbum' in path:
                return {'Items':[{'Id':'artist','Name':'Example'}]}
            return {'Items':[{'Type':'Audio','Id':'track','Name':'Song','RunTimeTicks':1200000000}]}
        a.fetch.side_effect=fetch
        return a

    def test_jellyfin_artist_and_album_audio_and_direct_stream(self):
        a=self.jellyfin()
        for kind in ('artist','album'):
            (item,)=JellyfinVideo.video_music(a,kind,'Example')
            self.assertEqual((item['kind'],item['duration']),('audio',120))
            stream=JellyfinVideo.video_stream(a,item)
            self.assertIn('/Audio/track/stream',stream['url']);self.assertTrue(stream['direct'])
            self.assertIsNone(stream['session'])
        self.assertTrue(any('ArtistIds=artist' in call.args[0] for call in a.fetch.call_args_list))
        self.assertTrue(any('ParentId=artist' in call.args[0] for call in a.fetch.call_args_list))

    def test_music_requires_unambiguous_title(self):
        a=self.jellyfin();a.fetch.return_value={'Items':[]};a.fetch.side_effect=None
        with self.assertRaises(LookupError): JellyfinVideo.video_music(a,'artist','Missing')
        a.fetch.return_value={'Items':[{'Id':'1','Name':'Example'},{'Id':'2','Name':'Example'}]}
        with self.assertRaises(LookupError): JellyfinVideo.video_music(a,'album','Example')

    def test_plex_music_uses_tracks_and_direct_file(self):
        a=mock.Mock();a.name='plex';a.endpoint='https://media.example.org';a.auth_headers.return_value={}
        a._sections.return_value=[{'key':'4'}];a._item=lambda item:PlexVideo._item(a,item)
        def get(path,**kw):
            if '/all?type=' in path:return {'Metadata':[{'ratingKey':'artist','title':'Example'}]}
            return {'Metadata':[{'ratingKey':'track','type':'track','title':'Song','duration':120000,
                                  'Media':[{'Part':[{'key':'/music/song.flac'}]}]}]}
        a._get.side_effect=get
        for kind in ('artist','album'):
            (item,)=PlexVideo.video_music(a,kind,'Example')
            self.assertEqual(item['kind'],'audio')
            stream=PlexVideo.video_stream(a,item)
            self.assertEqual(stream['url'],'https://media.example.org/music/song.flac')
            self.assertTrue(stream['direct']);self.assertIsNone(stream['session'])
