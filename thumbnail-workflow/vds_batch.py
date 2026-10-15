"""Frozen-template episode numbering; no OpenAI calls, keys or Photoshop."""
import argparse
import hashlib
import html
import json
import re
import time
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SIZES = {'16x9': (1920, 1080), '9x16': (1080, 1920)}


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def save(p, obj):
    with Path(p).open('x', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def folder_name(name):
    name = unicodedata.normalize('NFC', name)
    if not name or name != name.strip() or name.endswith('.') or re.search(r'[<>:"/\\|?*\x00-\x1f]', name):
        raise ValueError('Unsafe series folder; do not silently rename VDS identity')
    if re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', name):
        raise ValueError('Reserved series folder')
    return name


def episode_number(name):
    text = unicodedata.normalize('NFC', name)
    m = re.search(r'(?:tập|tap|episode|ep|第)[ _.-]*(\d+)', text, re.I)
    if not m:
        m = re.match(r'^(\d{1,3})(?:[ _.-]|集|$)', text)
    return int(m[1]) if m else None


def classify(files):
    """One film inventory of metadata, not a count of all arbitrary files."""
    by_episode, unknown = {}, []
    for f in files:
        name = f.get('name', f.get('title', ''))
        mime = f.get('mimeType', f.get('mime_type', '')) or ''
        if f.get('trashed') or not (mime.startswith('video/') or re.search(r'\.(mp4|mkv|mov|webm|m4v)$', name, re.I)):
            continue
        if re.search(r'(?:phan|phần|part|hot|clip)[ _.-]*\d+', name, re.I):
            unknown.append({'id': f.get('id'), 'name': name, 'reason': 'part_needs_explicit_mapping'})
            continue
        n = episode_number(name)
        if n is None or not 1 <= n <= 999:
            unknown.append({'id': f.get('id'), 'name': name, 'reason': 'episode_unresolved'})
        else:
            by_episode.setdefault(n, []).append(f)
    duplicates = {str(n): [f.get('id') for f in fs] for n, fs in by_episode.items() if len(fs) > 1}
    episodes = [{'episode': n, 'part': 0, 'source_file_id': fs[0].get('id'),
                 'source_name': fs[0].get('name', fs[0].get('title'))}
                for n, fs in sorted(by_episode.items()) if len(fs) == 1]
    missing = sorted(set(range(1, max(by_episode, default=0)+1)) - set(by_episode))
    return {'episodes': episodes, 'duplicates': duplicates, 'unknown': unknown, 'missing': missing}


def target_name(item, ratio):
    n, part = item['episode'], item.get('part', 0)
    return f'TAP_{n:03d}' + (f'_PHAN_{part:03d}' if part else '') + f'_{ratio}.jpg'


def validate(job):
    folder_name(job['series_folder'])
    if job.get('mode') not in ('have_original', 'find_original'):
        raise ValueError('Choose have_original or find_original')
    if not job.get('source', {}).get('verified'):
        raise ValueError('Verify original image matches this series first')
    if not job.get('inventory_complete'):
        raise ValueError('Drive pagination must finish before batch numbering')
    if job.get('unresolved'):
        raise ValueError('Resolve duplicate/unknown mappings before preparation')
    if not job.get('episodes'):
        raise ValueError('No confirmed episodes')
    seen = set()
    for ep in job['episodes']:
        n, part = ep['episode'], ep.get('part', 0)
        if type(n) is not int or not 1 <= n <= 999 or type(part) is not int or not 0 <= part <= 999:
            raise ValueError('Invalid episode or part')
        key = (n, part)
        if key in seen:
            raise ValueError('Duplicate episode/part')
        seen.add(key)
    for ratio, size in SIZES.items():
        t = job['templates'][ratio]
        with Image.open(t['path']) as im:
            if im.size != size:
                raise ValueError('Template dimensions must match final dimensions')
        x, y, w, h = t['badge_box']
        if not (0 <= x < x+w <= 1 and 0 <= y < y+h <= 1):
            raise ValueError('Badge box outside safe canvas')
    ImageFont.truetype(job['font'], 32)


def signature(job):
    content = {'job': job, 'font_hash': sha(job['font']),
               'template_hashes': {r: sha(job['templates'][r]['path']) for r in SIZES}}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def check_image(p, size):
    with Image.open(p) as im:
        im.load()
        if im.format != 'JPEG' or im.mode != 'RGB' or im.size != size:
            raise ValueError('Invalid JPEG dimensions/mode')
    if Path(p).stat().st_size > 2_000_000:
        raise ValueError('JPEG exceeds 2 MB')


def render(job, ep, ratio, target):
    t = job['templates'][ratio]
    with Image.open(t['path']) as im:
        canvas = im.convert('RGB')
    draw = ImageDraw.Draw(canvas)
    W, H = canvas.size
    x, y, bw, bh = t['badge_box']
    box = tuple(round(v) for v in (x*W, y*H, (x+bw)*W, (y+bh)*H))
    label = f"TẬP {ep['episode']:03d}" + (f" • P{ep['part']:03d}" if ep.get('part') else '')
    for fs in range(int(bh*H*.65), 17, -1):
        font = ImageFont.truetype(job['font'], fs)
        stroke = max(2, fs//18)
        bb = draw.textbbox((0, 0), label, font=font, stroke_width=stroke)
        if bb[2]-bb[0] <= (box[2]-box[0])*.88 and bb[3]-bb[1] <= (box[3]-box[1])*.8:
            break
    else:
        raise ValueError('Episode label does not fit approved box')
    draw.rounded_rectangle(box, radius=max(8, int(bh*H*.15)), fill='#d91921', outline='#090909', width=4)
    px = (box[0]+box[2]-(bb[2]-bb[0]))/2-bb[0]
    py = (box[1]+box[3]-(bb[3]-bb[1]))/2-bb[1]
    draw.text((px, py), label, font=font, fill='#ffef2d', stroke_width=stroke, stroke_fill='#090909')
    with Path(target).open('xb') as f:
        canvas.save(f, 'JPEG', quality=92, optimize=True)
    check_image(target, SIZES[ratio])


def prepare(job, run):
    validate(job)
    run = Path(run)
    run.mkdir(parents=True, exist_ok=False)
    save(run/'job.json', job)
    save(run/'prepared.json', {'signature': signature(job), 'status': 'pending_template_review'})
    samples = run/'samples'
    samples.mkdir()
    ordered = sorted(job['episodes'], key=lambda e:(e['episode'], e.get('part',0)))
    chosen = {0, len(ordered)//2, len(ordered)-1}
    body = ['<!doctype html><meta charset="utf-8"><h1>Duyệt mẫu chung và vùng số tập</h1>']
    for i in sorted(chosen):
        for ratio in SIZES:
            target = samples/target_name(ordered[i], ratio)
            render(job, ordered[i], ratio, target)
            url = 'samples/'+target.name
            body.append(f'<a href="{html.escape(url)}"><img style="max-width:45%;max-height:700px" src="{html.escape(url)}"></a>')
    with (run/'review.html').open('x', encoding='utf-8') as f:
        f.write(''.join(body))
    save(run/'sample-hashes.json', {p.name: sha(p) for p in samples.glob('*.jpg')})
    return run/'review.html'


def current(run):
    run = Path(run)
    job = load(run/'job.json')
    validate(job)
    digest = signature(job)
    if digest != load(run/'prepared.json')['signature']:
        raise ValueError('Template/font/job changed; prepare a new run and review again')
    for name, expected in load(run/'sample-hashes.json').items():
        if sha(run/'samples'/name) != expected:
            raise ValueError('Review sample changed')
    return job, digest


def approve(run, reviewer):
    if not reviewer.strip():
        raise ValueError('Reviewer required')
    _, sig = current(run)
    save(Path(run)/'approval.json', {'signature':sig, 'reviewer':reviewer,
        'time':datetime.now(timezone.utc).isoformat(), 'approved':True})


def verify(run):
    run = Path(run)
    job, sig = current(run)
    approval = load(run/'approval.json')
    if approval.get('signature') != sig or approval.get('approved') is not True:
        raise ValueError('Approval missing or stale')
    receipt = load(run/'result.json')
    if receipt['signature'] != sig or receipt['errors']:
        raise ValueError('Incomplete or stale batch')
    expected = {f'PHIM_{r}.jpg' for r in SIZES} | {target_name(e,r) for e in job['episodes'] for r in SIZES}
    actual = {f['name'] for f in receipt['files']}
    if actual != expected:
        raise ValueError('Batch coverage mismatch')
    root = run/'THUMBNAILS'/job['series_folder']
    if {p.name for p in root.glob('*.jpg')} != expected:
        raise ValueError('Unexpected/missing JPEG in final directory')
    for f in receipt['files']:
        p = root/f['name']
        if sha(p) != f['sha256']:
            raise ValueError('Final JPEG changed')
        check_image(p, SIZES[f['ratio']])
    return receipt


def batch(run, max_files=None):
    run = Path(run)
    job, sig = current(run)
    approval = load(run/'approval.json') if (run/'approval.json').exists() else {}
    if approval.get('signature') != sig or approval.get('approved') is not True:
        raise ValueError('Explicit human template approval required')
    if (run/'result.json').exists():
        return verify(run)
    root = run/'THUMBNAILS'/job['series_folder']
    checkpoints = sorted(run.glob('progress-*.json'))
    if checkpoints:
        previous = load(checkpoints[-1])
        if previous['signature'] != sig:
            raise ValueError('Stale batch checkpoint')
        files = previous['files']
        for f in files:
            if sha(root/f['name']) != f['sha256']:
                raise ValueError('Checkpoint file changed')
    else:
        root.mkdir(parents=True, exist_ok=False)
        files = []
    tasks = [(f'PHIM_{r}.jpg', r, None) for r in SIZES]
    tasks += [(target_name(e,r),r,e) for e in job['episodes'] for r in SIZES]
    errors = []
    done = {f['name'] for f in files}
    tasks = [t for t in tasks if t[0] not in done]
    remaining = len(tasks)
    if max_files is not None:
        if max_files < 1:raise ValueError('Positive batch limit required')
        tasks = tasks[:max_files]
    started = time.monotonic()
    for name, ratio, ep in tasks:
        target = root/name
        for attempt in range(1,4):
            try:
                if target.exists():
                    raise FileExistsError('Never replace an existing thumbnail')
                if ep:
                    render(job, ep, ratio, target)
                else:
                    with Image.open(job['templates'][ratio]['path']) as im, target.open('xb') as f:
                        im.convert('RGB').save(f,'JPEG',quality=92,optimize=True)
                    check_image(target, SIZES[ratio])
                raw = target.read_bytes()
                files.append({'name':name,'ratio':ratio,'sha256':sha(target),
                    'md5':hashlib.md5(raw).hexdigest(),'bytes':len(raw),
                    'relative_path':f"THUMBNAILS/{job['series_folder']}/{name}"})
                save(run/f'progress-{len(files):06d}.json', {'signature':sig,'files':files})
                break
            except (OSError, ValueError) as exc:
                # Failed partial files are retained; never overwrite/delete to retry.
                if target.exists() or attempt==3:
                    errors.append({'name':name,'error':type(exc).__name__,'attempts':attempt})
                    break
    result = {'signature':sig,'files':files,'errors':errors,'ai_calls':0,
              'elapsed_seconds':time.monotonic()-started,'status':'ready_to_upload' if not errors else 'failed'}
    if not errors and remaining > len(tasks):
        result['status'] = 'in_progress'
        return result
    save(run/'result.json', result)
    if not errors:
        verify(run)
        save(run/'upload-plan.json', {'drive_root_id':job['drive_root_id'],
            'series_folder':job['series_folder'],'files':files,'conflict_policy':'same_checksum_skip_else_stop'})
        with zipfile.ZipFile(run/'THUMBNAILS.zip','x',zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(root/f['name'], f['relative_path'])
    return result


def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest='action',required=True)
    s=sub.add_parser('scan');s.add_argument('--inventory',required=True)
    s=sub.add_parser('prepare');s.add_argument('--job',required=True);s.add_argument('--run',required=True)
    for name in ('approve','render','verify'):
        s=sub.add_parser(name);s.add_argument('--run',required=True)
        if name=='approve':s.add_argument('--reviewer',required=True)
        if name=='render':s.add_argument('--limit',type=int,default=40)
    a=p.parse_args()
    if a.action=='scan': result=classify(load(a.inventory))
    elif a.action=='prepare':result=str(prepare(load(a.job),a.run))
    elif a.action=='approve':approve(a.run,a.reviewer);result='approved'
    elif a.action=='render':result=batch(a.run,a.limit)
    else:result=verify(a.run)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if isinstance(result,dict) and result.get('errors'):raise SystemExit(1)


if __name__=='__main__':
    main()
