import contextlib
import io
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import market_video_import as m

CHANNEL = {'name':'Example', 'handle':'@example'}
def meta(i, day='20260926', **extra):
    return dict(id=f'{i:011d}', upload_date=day, duration=600, title='Example', **extra)
def state():
    return {'version':1,'channels':{},'videos':{}}

class ImportTests(unittest.TestCase):
    def test_first_three_and_no_backfill(self):
        s=state(); today=date(2026,9,26)
        items=[meta(i, f'202609{27-i:02d}') for i in range(1,6)]
        m.merge_channel(s,CHANNEL,items,today,14,set())
        self.assertEqual([v['status'] for v in s['videos'].values()], ['pending']*3+['baseline']*2)
        m.merge_channel(s,CHANNEL,[meta(6)]+items,today,14,set())
        self.assertEqual(len(m.queue(s,today,14,10)),4)

    def test_date_short_and_live_filters(self):
        today=date(2026,9,26)
        for changes in [{'upload_date':'20260911'}, {'upload_date':None}, {'upload_date':'20260927'},
                        {'duration':180}, {'is_short':True}, {'live_status':'is_upcoming'},
                        {'webpage_url':'https://youtube.com/shorts/123'}]:
            item=meta(1);item.update(changes)
            self.assertFalse(m.eligible(item,today,14),changes)
        self.assertTrue(m.eligible(meta(1,'20260912'),today,14))

    def test_known_duplicate_and_global_limit(self):
        s=state();today=date(2026,9,26)
        for c in range(5):
            channel={'name':str(c),'handle':f'@c{c}'}
            m.merge_channel(s,channel,[meta(i) for i in range(c*3,c*3+3)],today,14,{'00000000000'})
        self.assertEqual(s['videos']['00000000000']['status'],'already_imported')
        self.assertEqual(len(m.queue(s,today,14,10)),10)
        m.merge_channel(s,CHANNEL,[meta(1)],today,14,set())
        self.assertEqual(len(s['videos']),15)

    def test_expiry_and_retry(self):
        s=state();today=date(2026,9,26)
        m.merge_channel(s,CHANNEL,[meta(1),meta(2)],today,14,set())
        first=s['videos']['00000000001'];first.update(status='failed',attempts=1)
        self.assertEqual(m.queue(s,today,14,1)[0]['id'],'00000000002')
        self.assertEqual(m.queue(s,date(2026,10,11),14,10),[])
        self.assertEqual(first['status'],'expired')
        self.assertEqual(len(s['videos']),2)

    def run_mock(self, error, count=3):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);m.save(root/'channels.json',[CHANNEL])
            args=SimpleNamespace(output=root/'out',channels=root/'channels.json',known_ids=None,
                max_age_days=14,max_per_run=10,window=30,transcribe=True)
            day=datetime.now(timezone.utc).strftime('%Y%m%d')
            with patch.object(m,'discover',return_value=[meta(i,day) for i in range(count)]), \
                 patch.object(m,'caption_export',side_effect=error) as export, \
                 patch.object(m.time,'sleep'), contextlib.redirect_stdout(io.StringIO()):
                code=m.run(args)
            return code, export.call_count, m.load(root/'out/state.json',{})

    def test_block_stops_and_keeps_pending(self):
        code,calls,s=self.run_mock(type('IpBlocked',(Exception,),{})())
        self.assertEqual((code,calls),(2,1))
        self.assertEqual(sorted(v['status'] for v in s['videos'].values()),['blocked','pending','pending'])

    def test_failed_captions_never_mark_complete(self):
        code,calls,s=self.run_mock(ValueError('No captions'))
        self.assertEqual((code,calls),(2,3))
        self.assertTrue(all(v['status']=='failed' for v in s['videos'].values()))

if __name__=='__main__':
    unittest.main()
