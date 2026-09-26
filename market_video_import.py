"""Prepared, manual-only recent-video scanner and optional caption export.
No Discord, paid model calls, deletion, Git push or scheduler.
"""
from __future__ import annotations
import argparse
import json
import os
import tempfile
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
ID = re.compile(r'^[A-Za-z0-9_-]{11}$')

def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(path)

def load(path, default):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else default

def published(meta):
    value = meta.get('upload_date')
    if isinstance(value, str) and re.fullmatch(r'\d{8}', value):
        try:
            return datetime.strptime(value, '%Y%m%d').date()
        except ValueError:
            return None
    return None

def eligible(meta, today, days):
    date = published(meta)
    return (date is not None and today-timedelta(days=days) <= date <= today
            and isinstance(meta.get('duration'), (int, float)) and meta['duration'] > 180
            and not meta.get('is_short') and not meta.get('is_live')
            and meta.get('live_status') not in {'is_live', 'is_upcoming', 'post_live'}
            and not any('/shorts/' in str(meta.get(k,'')) for k in ['url','webpage_url','original_url']))

def merge_channel(state, channel, metadata, today, days, known):
    """Called only after a fully successful discovery; stable date sorting."""
    videos = state.setdefault('videos', {})
    initialized = state.setdefault('channels', {})
    candidates = sorted((m for m in metadata if eligible(m, today, days)),
                        key=lambda m: (m['upload_date'], m.get('timestamp') or 0), reverse=True)
    first = channel['handle'] not in initialized
    for index, meta in enumerate(candidates):
        vid = meta['id']
        if vid in videos:
            continue
        videos[vid] = {'id':vid, 'title':meta.get('title') or vid,
            'channel':channel['name'], 'handle':channel['handle'],
            'published':published(meta).isoformat(), 'duration':meta['duration'],
            'url':'https://www.youtube.com/watch?v='+vid, 'attempts':0,
            'status':'already_imported' if vid in known else
                     'baseline' if first and index >= 3 else 'pending'}
    initialized[channel['handle']] = today.isoformat()

def queue(state, today, days, limit):
    candidates=[]
    for v in state['videos'].values():
        if v['status'] not in {'pending','failed','blocked'}:
            continue
        if datetime.fromisoformat(v['published']).date() < today-timedelta(days=days):
            v['status']='expired'
            continue
        candidates.append(v)
    # Prefer untried items; failed ones cannot indefinitely occupy all ten slots.
    candidates.sort(key=lambda v:(v.get('attempts',0),v['published'],v['id']))
    return candidates[:limit]

def blocked(exc):
    return type(exc).__name__ in {'IpBlocked','RequestBlocked','TooManyRequests'} or any(
        term in str(exc).lower() for term in ['not a bot','429','page needs to be reloaded'])

def discover(channel, window):
    import yt_dlp
    opts={'quiet':True,'socket_timeout':20,'retries':0,'extract_flat':True,'playlistend':window}
    with yt_dlp.YoutubeDL(opts) as ydl:
        data=ydl.extract_info('https://www.youtube.com/'+channel['handle']+'/videos',download=False)
    if not data or 'entries' not in data:
        raise ValueError('No complete channel listing')
    records=[];seen=set()
    for e in data['entries']:
        if not e or not ID.fullmatch(str(e.get('id',''))):
            raise ValueError('Incomplete channel listing; initialization deferred')
        if e['id'] in seen:
            continue
        seen.add(e['id'])
        # Flat discovery often omits dates/duration. Resolve before age filtering.
        if published(e) is None or e.get('duration') is None:
            with yt_dlp.YoutubeDL({'quiet':True,'socket_timeout':20,'retries':0,'noplaylist':True}) as ydl:
                e=ydl.extract_info('https://www.youtube.com/watch?v='+e['id'],download=False)
            time.sleep(1)
        if not e or published(e) is None or e.get('duration') is None:
            raise ValueError('Unverified date or duration; initialization deferred')
        if e.get('uploader_id') and e['uploader_id'].casefold()!=channel['handle'].casefold():
            raise ValueError('Unexpected channel')
        records.append(e)
    return records

def caption_export(video, target):
    import requests
    from youtube_transcript_api import YouTubeTranscriptApi
    class TimedSession(requests.Session):
        def request(self,*a,**kw):
            kw.setdefault('timeout',30)
            return super().request(*a,**kw)
    destination=target/(video['id']+'.md')
    if destination.exists():
        # Recover an interrupted state save only for a matching, nonempty note.
        content=destination.read_text(encoding='utf-8')
        if 'video_id: "'+video['id']+'"' not in content or not re.search(r'^\[\d\d:\d\d:\d\d\] .+',content,re.M):
            raise ValueError('Existing file needs manual reconciliation')
        return destination
    api=YouTubeTranscriptApi(http_client=TimedSession())
    listing=api.list(video['id'])
    try:
        transcript=listing.find_manually_created_transcript(['de','en'])
    except Exception:
        transcript=listing.find_generated_transcript(['de','en'])
    parts=list(transcript.fetch())
    if not parts or not any(p.text.strip() for p in parts):
        raise ValueError('Empty transcript')
    front={'type':'transcript','status':'raw-unverified','video_id':video['id'],
           'title':video['title'],'creator':video['channel'],'source':video['url'],
           'published':video['published'],'duration_seconds':video['duration'],
           'imported':datetime.now(UTC).isoformat(),'language':transcript.language_code,
           'transcription_method':'youtube-auto-captions' if transcript.is_generated else 'youtube-manual-captions',
           'tags':['source/youtube'],'visual_verification':'pending'}
    lines=[]
    for p in parts:
        seconds=int(p.start)
        lines.append(f'[{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}] {p.text.strip()}')
    text='---\n'+'\n'.join(k+': '+json.dumps(v,ensure_ascii=False) for k,v in front.items())+'\n---\n\n# '+video['title']+'\n\nUngeprüfte Untertitel. Keine Chartprüfung oder aktuelle Handelsempfehlung.\n\n'+'\n\n'.join(lines)+'\n'
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Publish a complete file atomically without replacing an existing note.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink()
    return destination

def run(args):
    now=datetime.now(UTC); state_path=args.output/'state.json'
    state=load(state_path,{'version':1,'channels':{},'videos':{}})
    if state.get('version')!=1 or not isinstance(state.get('videos'),dict) or not isinstance(state.get('channels'),dict):
        raise ValueError('Invalid state; do not reset it')
    known=set(load(args.known_ids,[])) if args.known_ids else set()
    channels=load(args.channels,[])
    if not channels or any(not re.fullmatch(r'@[\w.\-]+',c.get('handle','')) for c in channels):
        raise ValueError('Invalid or missing channels')
    report={'run_at':now.isoformat(),'scan_errors':[],'created':[],'export_errors':[],'blocked':False,
            'settings':{'first_per_channel':3,'max_age_days':args.max_age_days,'max_per_run':args.max_per_run,'discovery_window':args.window}}
    try:
        for channel in channels:
            try:
                records=discover(channel,args.window)
                merge_channel(state,channel,records,now.date(),args.max_age_days,known)
                save(state_path,state)
            except Exception as exc:
                report['scan_errors'].append({'channel':channel['name'],'error':type(exc).__name__})
                if blocked(exc):
                    report['blocked']=True
                    break
        selected=queue(state,now.date(),args.max_age_days,args.max_per_run)
        if args.transcribe and not report['blocked']:
            for video in selected:
                video['attempts']+=1
                video['last_attempt']=datetime.now(UTC).isoformat()
                save(state_path,state)
                try:
                    path=caption_export(video,args.output/'vault/02_Trading/Briefings/Rohmaterial')
                    video.update(status='complete',file=str(path));report['created'].append(video['id'])
                except Exception as exc:
                    report['export_errors'].append({'id':video['id'],'error':type(exc).__name__})
                    video.update(status='blocked' if blocked(exc) else 'failed',error=type(exc).__name__)
                    report['blocked']=blocked(exc)
                save(state_path,state)
                if report['blocked']:
                    break
                time.sleep(4)
    finally:
        queue(state,now.date(),args.max_age_days,args.max_per_run)
        save(state_path,state)
        report['counts']={s:sum(v['status']==s for v in state['videos'].values()) for s in ['pending','complete','failed','blocked','expired','baseline','already_imported']}
        save(args.output/'last_run.json',report)
        pending=[v['url'] for v in state['videos'].values() if v['status'] in {'pending','failed','blocked'}]
        (args.output/'pending_links.txt').write_text('\n'.join(pending)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 2 if report['blocked'] or report['scan_errors'] or report['export_errors'] else 0

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channels',type=Path,default=Path('channels.json'))
    parser.add_argument('--output',type=Path,default=Path('market_video_import'))
    parser.add_argument('--known-ids',type=Path)
    parser.add_argument('--max-age-days',type=int,default=14)
    parser.add_argument('--max-per-run',type=int,default=10)
    parser.add_argument('--window',type=int,default=30)
    parser.add_argument('--transcribe',action='store_true',help='Fetch captions; default only scans')
    args=parser.parse_args()
    if args.max_age_days<1 or not 1<=args.max_per_run<=10 or args.window<3:
        parser.error('Age >=1, limit 1..10, discovery window >=3 required')
    # Linux/Colab/macOS: prevent two processes from losing queue updates.
    import fcntl
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output/'.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('Another import is already running for this output folder')
        raise SystemExit(run(args))
