"""Shared channel operations and CLI, always against a symlinked sandbox config."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'lib'))
import bromigos_tvchannels as C

TEXT = '''# Everything above the channels stays
[general]
fps = 20 # untouched
[tv]
enabled = true
# All channels
[[tv.channel]]
name = "Night Block" # its name
shows = ["A", "B"] # picked
order = "in-order"
bumpers = true

# Library comment
[[tv.channel]]
name = "Films"
library = "Movies"
'''


class Channels(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.target = os.path.join(self.tmp.name, 'dotfiles.toml')
        self.file = os.path.join(self.tmp.name, 'config.toml')
        with open(self.target, 'w') as f: f.write(TEXT)
        os.symlink(self.target,self.file)
        self.env = mock.patch.dict(os.environ, {'BROMIGOS_LIVE_CONFIG': self.file,
            'XDG_STATE_HOME':self.tmp.name,'XDG_RUNTIME_DIR':self.tmp.name})
        self.env.start();self.addCleanup(self.env.stop)
        for p in (mock.patch.object(C, 'control',return_value=None),
                  mock.patch.object(C.TV,'state',return_value={}),
                  mock.patch.object(C.TV,'cached_items',return_value=None),
                  mock.patch.object(C.TV,'ROTATION',self.tmp.name+'/rotation.json'),
                  mock.patch.object(C.TV,'PICKS',self.tmp.name+'/picks.json'),
                  mock.patch.object(C.TV,'CACHE',self.tmp.name+'/cache')):
            p.start();self.addCleanup(p.stop)
        self.store = C.Store()

    def cli(self,*args):
        out=io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code=C.main([*args,'--json'])
        return code,json.loads(out.getvalue())

    def test_edits_preserve_comments_and_symlink_and_other_tables(self):
        self.store.item('Night Block','C');self.store.item('Night Block','A',remove=True)
        self.store.move_item('Night Block','C',1)
        self.store.set('Night Block','name','Evening');self.store.set('Evening','order','alternate')
        self.store.set('Evening','bumpers',False);self.store.move('Evening',2)
        self.assertTrue(os.path.islink(self.file))
        with open(self.target) as f: text=f.read()
        for comment in ('# untouched','# its name','# picked','# Library comment','# All channels'):
            self.assertIn(comment,text)
        self.assertEqual(self.store.load().channels()[1]['shows'],['C','B'])
        self.assertIn('[general]\nfps = 20 # untouched',text)

    def test_remove_needs_confirmation_and_undo_restores_comments(self):
        self.assertEqual(self.cli('channel','remove','Night Block')[0],2)
        self.assertEqual(len(self.store.load().channels()),2)
        self.assertEqual(self.cli('channel','remove','Night Block','--yes')[0],0)
        self.assertEqual(self.cli('channel','undo')[0],0)
        self.assertEqual(self.store.load().channels()[0]['name'],'Night Block')
        self.assertIn('# picked',self.store.load().text)

    def test_all_cli_actions_and_json_errors(self):
        self.assertEqual(self.cli('channel','add','New','--shows','C','D','--bumpers')[0],0)
        for action, args in (('rename',('New','Late')),('order',('Late','shuffle')),
                             ('bumpers',('Late','off')),('move',('Late','1')),
                             ('add-item',('Late','E')),('remove-item',('Late','E')),
                             ('move-item',('Late','D','1'))):
            code, doc = self.cli('channel',action,*args);self.assertEqual(code,0,doc)
        code,doc=self.cli('channels');self.assertEqual(code,0)
        self.assertEqual(doc['channels'][0]['name'],'Late')
        self.assertEqual([p['title'] for p in doc['channels'][0]['contents']],['D','C'])
        self.assertEqual(self.cli('channel','rename','Missing','Nope')[0],4)
        self.assertEqual(self.cli('channel','add','Late','--shows','A')[0],3)
        self.assertEqual(self.cli('channel','add-item','Films','A')[0],2)
        self.assertEqual(self.cli('channel','order','Late','invalid')[0],2)

    def test_types_and_read_has_now_next_and_screens(self):
        for name, kw in [('YouTube',{'youtube':'https://www.youtube.com/playlist?list=test'}),
                         ('Folder',{'folder':'~/Videos'}),('Empty',{})]:
            self.store.create(name,**kw)
        doc=self.store.snapshot(live={'screens': {'big':{'key':'night-block'}}})
        self.assertEqual(doc['channels'][0]['on_screens'],['big'])
        self.assertEqual(doc['channels'][0]['screen_numbers']['big'],2)
        self.assertEqual([r['kind'] for r in doc['channels']],['picked','library','youtube','folder','picked'])
        self.assertIn('now',doc['channels'][0]);self.assertIn('next',doc['channels'][0])

    def test_tune_and_reload_use_only_control_socket(self):
        with mock.patch.object(C,'control',return_value='tuned channel 2') as ctl:
            result=self.store.tune('Night Block','scope')
            self.assertEqual(result['screen'],'wave')
            self.assertIn(mock.call('tv set 2 --screen wave'),ctl.call_args_list)
        with mock.patch.object(C,'control',return_value=None):
            self.assertEqual(self.cli('set','2','--screen','big')[0],1)

    def test_guide_edits_share_name_validation(self):
        with self.assertRaises(C.ChannelError):
            self.store.edit(lambda doc: doc.add({'name':'Night Block','shows':['New']}))
        self.assertEqual(len(self.store.load().channels()),2)
        with self.assertRaises(C.ChannelError):
            self.store.edit(lambda doc: doc.set(1,'name','Night Block'))
        self.assertEqual(self.store.load().channels()[1]['name'],'Films')

    def test_unnamed_legacy_channels_use_the_guide_readers_display_name(self):
        self.store.edit(lambda doc: doc.add({'library':'Music'}))
        row=self.store.snapshot(live={})['channels'][-1]
        self.assertEqual(row['name'],'Music')
        self.store.set('Music','bumpers',True)
        self.store.set('Music','name','Albums')
        self.assertEqual(self.store.load().channels()[-1]['name'],'Albums')
        self.store.remove('Albums');self.store.undo()
        self.assertEqual(self.store.load().channels()[-1]['name'],'Albums')

    def test_multiple_editors_load_latest_file(self):
        other=C.Store(self.file)
        self.store.item('Night Block','C')
        other.item('Night Block','D')
        self.assertEqual(self.store.load().channels()[0]['shows'],['A','B','C','D'])

    def test_music_and_youtube_picks(self):
        self.store.item('Night Block','Artist',item_kind='music')
        url='https://www.youtube.com/playlist?list=test'
        self.store.item('Night Block',url,item_kind='youtube')
        row=self.store.snapshot(live={})['channels'][0]
        self.assertEqual(row['table']['items'],['music:artist:Artist',url])
        self.assertTrue(C.membership('Artist',[row]))
        self.assertTrue(C.membership(url,[row]))
        self.store.item('Night Block','Artist',remove=True)
        self.assertNotIn('music:artist:Artist',self.store.load().channels()[0]['items'])

    def test_mixed_picks_resolve_youtube_and_music_without_movie_lookup(self):
        import bromigos_youtube as Y
        source=mock.Mock(name='source');source.name='jellyfin'
        source.video_music.return_value=[{'id':'track','title':'Song','kind':'audio','duration':120}]
        source.video_shows.return_value=[];source.video_movies.return_value=[]
        url='https://www.youtube.com/playlist?list=test'
        ch={'items':[url,'music:album:Album']}
        with mock.patch.object(Y,'videos',return_value={'title':'Clips','videos':[
            {'id':'clip','title':'Clip','url':'https://www.youtube.com/watch?v=clip','duration':60}]}):
            items,groups,missing=C.TV.pick_items(ch,source)
        self.assertEqual(missing,[]);self.assertEqual(len(groups),2)
        self.assertEqual([item['kind'] for item in items],['video','audio'])
        self.assertEqual(items[0]['server'],'youtube')
        source.video_movies.assert_not_called();source.video_music.assert_called_once_with('album','Album')

    def test_live_numbers_account_for_extra_live_channels_and_now_next(self):
        self.store.create('After',shows=['A'])
        live={'screens':{'big':{'key':'after','now':'On air','next':'Next'}},
              'lineups':{'big':[{'key':'own','number':1},{'key':'night-block','number':2},
                                 {'key':'night-block-live','number':3},{'key':'films','number':4},
                                 {'key':'after','number':5}]}}
        row=self.store.snapshot(live=live)['channels'][-1]
        self.assertEqual(row['screen_numbers']['big'],5)
        self.assertEqual((row['now'],row['next']),('On air','Next'))

    def test_changed_picks_refresh_immediately_instead_of_waiting_for_cache_age(self):
        self.store.create('Fresh',shows=['A'])
        ch=C.TV.channels({'tv':{'channel':[self.store.load().channels()[-1]]}},panel=False)[0]
        source=mock.Mock();source.name='jellyfin'
        source.video_shows.return_value=[{'id':'a','title':'A'},{'id':'b','title':'B'}]
        source.video_show_items.side_effect=lambda id_: [{'id':'ep-'+id_,'title':id_,'duration':60,'kind':'episode'}]
        def cached(channel):
            try:
                with open(C.TV.cache_path(channel)) as f:return json.load(f)
            except FileNotFoundError:return None
        with mock.patch.object(C.TV,'server_of',return_value=source),mock.patch.object(C.TV,'cached_items',side_effect=cached):
            first=C.TV.fetch_items(ch,max_age=900)
            second=C.TV.fetch_items(dict(ch,shows=['B']),max_age=900)
            self.assertEqual([i['id'] for i in first['items']],['ep-a'])
            self.assertEqual([i['id'] for i in second['items']],['ep-b'])
            self.assertNotEqual(first['definition'],second['definition'])
            third=C.TV.fetch_items(dict(ch,shows=['Missing']),max_age=900)
            self.assertEqual(third['items'],[])
            self.assertIn('Missing',third['error'])

    def test_packaged_cli_and_media_alias_use_same_writer(self):
        import subprocess
        env=dict(os.environ,HOME=self.tmp.name,XDG_CACHE_HOME=self.tmp.name+'/cache')
        proc=subprocess.run([os.path.join(ROOT,'live/bin/bromigos-live'),'tv','channel','add','CLI',
                             '--shows','One','--json'],env=env,capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        env['PYTHONPATH']=os.path.join(ROOT,'homelab/lib')
        proc=subprocess.run([sys.executable,os.path.join(ROOT,'homelab/bin/bromigos-lab'),
                             'media','channel','add','Two','--to','CLI','--json'],
                             env=env,capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(self.store.load().channels()[-1]['shows'],['One','Two'])


if __name__=='__main__': unittest.main()
