"""Fail-closed content checks for concert cuts and subtitles.

Audio evidence comes from the original, including both sides of the cut. A
studio lyric absent from a live performance is never by itself a missing line.
Reports bind the source, range, reference lyrics, actual subtitles and evidence;
changing any of these requires a new check. Workers receive a frozen copy bound
to the exact subtitle assets they encode.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

from workflow.live.paths import Concert, read_json, write_json

VERSION = 1
REPORT = 'reports/content_check.json'
EVIDENCE = 'reports/source_lyrics_evidence.json'
REVIEW = 'reports/boundary_review.json'
ASSETS = ('landscape.ass', 'portrait.ass', 'watermark.json')


def audit_enabled():
    from workflow.live.paths import ROOT
    return read_json(ROOT/'delivery_defaults.json',{}).get('content_audit_before_render',False) is True


def prepared_report(concert,item):
    """Freeze existing production inputs; this is not a new content audit."""
    from workflow.paths import render_subtitle
    d=concert.song_dir(item);policy=selection(concert,item)
    subtitle=render_subtitle(d)
    data={'concert':concert.slug,'song':item['name'],'source':source_identity(policy['source']),
          'slice':policy['slice'],'subtitle':file_hash(subtitle),
          'watermark':file_hash(d/'watermark.json') if (d/'watermark.json').is_file() else None}
    return {'mode':'prepared_preview','status':'not_requested','input':data,'fingerprint':digest(data)}


def verify_production(concert,item,original_report):
    return (prepared_report(concert,item) if original_report.get('mode')=='prepared_preview'
            else require_passed(concert,item))


class ContentCheckFailed(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_identity(path):
    path = Path(path).resolve()
    st = path.stat()
    return {'path': str(path), 'size': st.st_size, 'mtime_ns': st.st_mtime_ns,
            'ctime_ns': st.st_ctime_ns, 'inode': st.st_ino, 'device': st.st_dev}


def selection(concert, item):
    d = concert.song_dir(item)
    policy = read_json(concert.dir / 'vertical_source.json', {}).get('songs', {}).get(item['name'])
    if policy:
        return policy
    info = read_json(d / 'song.json', {})
    source = info.get('source_file') or concert.load('info', {}).get('source_file')
    if not source or not info.get('slice'):
        raise ContentCheckFailed('缺少可核查的原片或曲目范围')
    return {'source': source, 'slice': info['slice']}


def inputs(concert, item):
    d = concert.song_dir(item)
    policy = selection(concert, item)
    references = {it['name']: file_hash(concert.song_dir(it) / 'lyrics.txt')
                  for it in source_items(concert, item)}
    info = read_json(d / 'song.json', {})
    return {'version': VERSION, 'concert': concert.slug, 'song': item['name'],
            'source': source_identity(policy['source']), 'slice': policy['slice'],
            'prepared_slice': info.get('slice'),
            'prepared_source': info.get('source_file'),
            'references': references,
            'subtitles': {str(p.relative_to(d)): file_hash(p) for p in
                          [d / 'subs/lines.json', d / 'subs/translation/result.json',
                           *sorted((d / 'subs').glob('lyrics*.ass'))] if p.is_file()},
            'evidence': file_hash(d / EVIDENCE) if (d / EVIDENCE).is_file() else None,
            'review': file_hash(d / REVIEW) if (d / REVIEW).is_file() else None}


def boundary_identity(concert, item):
    data = inputs(concert, item)
    return {k: data[k] for k in ('version', 'concert', 'song', 'source', 'slice', 'references')}


def source_items(concert, item):
    """Only performances from this original can be neighboring songs.

    The singles catalog contains unrelated originals and legacy entries. Their
    missing lyrics or selection must not block a checked, independent MV.
    """
    original = Path(selection(concert, item)['source']).resolve()
    result = []
    for candidate in concert.song_items():
        try:
            candidate_source = Path(selection(concert, candidate)['source']).resolve()
        except (ContentCheckFailed, OSError, ValueError, KeyError):
            if candidate['name'] == item['name']:
                raise
            continue
        if candidate_source == original:
            result.append(candidate)
    return result


def norm(text):
    return ' '.join(re.findall(r"[^\W_]+(?:['’][^\W_]+)?", (text or '').casefold()))


def lyric_references(concert, items=None):
    result = {}
    for it in concert.song_items() if items is None else items:
        lines = [norm(s) for s in (concert.song_dir(it) / 'lyrics.txt').read_text().splitlines()
                 if s.strip() and not s.lstrip().startswith('[')]
        result[it['name']] = [line for line in
            lines + [' '.join(lines[i:i+2]) for i in range(len(lines)-1)]
            if len(line.split()) >= 4 and len(line) >= 18]
    return result


def identify(words, references, current):
    """Specific multiword evidence, independent of forced subtitle alignment."""
    from rapidfuzz import fuzz, process
    def score(query, reference, *, score_cutoff=0):
        scorer = fuzz.ratio if len(reference) < len(query) else fuzz.partial_ratio
        return scorer(query, reference, score_cutoff=score_cutoff)
    matches = []
    short = {}
    for name, lines in references.items():
        for line in lines:
            if 4 <= len(line.split()) <= 5 and len(set(line.split())) >= 4:
                short.setdefault(line,set()).add(name)
    for i in range(len(words)):
        for size in (4,5):
            chunk=words[i:i+size]
            if len(chunk)!=size or chunk[-1]['e']-chunk[0]['s']>12:
                continue
            text=norm(' '.join(w['w'] for w in chunk))
            owners=short.get(text,set())
            if len(owners)==1:
                matches.append({'owner':next(iter(owners)), 'start':chunk[0]['s'],
                    'end':chunk[-1]['e'],'text':text,'score':100.0,'words':chunk})
    for i in range(len(words)):
        chunk = words[i:i+8]
        if len(chunk) < 5 or chunk[-1]['s'] - chunk[0]['s'] > 18:
            continue
        text = norm(' '.join(w['w'] for w in chunk))
        if len(set(text.split())) < 4 or len(text) < 20:
            continue
        scores = {}
        best_lines = {}
        for name, lines in references.items():
            best = process.extractOne(text, lines, scorer=score)
            scores[name] = best[1] if best else 0
            best_lines[name] = best[0] if best else ''
        rank = sorted(scores, key=scores.get, reverse=True)
        owner = rank[0]
        other = max((v for n, v in scores.items() if n != owner), default=0)
        if scores[owner] < 90 or scores[owner] - other < 7:
            continue
        reference=best_lines[owner].split()
        matched=[w for w in chunk if any(token in reference or any(
                 len(token)>2 and len(r)>2 and fuzz.ratio(token,r)>=85 for r in reference)
                 for token in norm(w['w']).split())]
        matches.append({'owner': owner, 'start': chunk[0]['s'], 'end': chunk[-1]['e'],
                        'text': text, 'score': round(scores[owner], 2), 'words': matched})
    return matches


def analyze(span, words, references, current, units, alternate_reads=None):
    """Return concrete missing/cross-song/subtitle errors, never a studio checklist."""
    from rapidfuzz import fuzz
    start, end = span
    found = identify(words, references, current)
    issues = []
    seen = set()
    for m in found:
        usable = [w for w in m['words'] if len(norm(w['w'])) > 1 and
                  norm(w['w']) not in {'oh','ooh','ah','uh','yeah','hey','shh','mm','woah'}]
        if m['owner'] == current:
            outside = [w for w in usable if w['e'] < start-.35 or w['s'] > end+.35]
            if outside:
                kind = 'missing_head' if outside[0]['e'] < start else 'missing_tail'
            else:
                inside = [w for w in usable if start <= w['s'] < end]
                if not inside:
                    continue
                a, b = inside[0]['s']-start, inside[-1]['e']-start
                nearby = [u for u in units if not u.get('dropped') and
                          u['end']/1000 >= a-1 and u['start']/1000 <= b+1]
                displayed = norm(' '.join(u['orig'] for u in nearby))
                actual = norm(' '.join(w['w'] for w in inside))
                # Check when each distinctive word is actually visible. A window
                # may span two lines, a refrain repeat or optional backing words.
                stop={'the','a','an','of','in','on','and','or','is','it','to','you','your',
                      'my','me','we','i','he','her','his','be','that','for','with'}
                relevant=[w for w in inside if norm(w['w']) not in stop]
                supported=0
                for w in relevant:
                    visible=' '.join(u['orig'] for u in units if not u.get('dropped') and
                        u['start']/1000 <= w['e']-start+1.0
                        and u['end']/1000 >= w['s']-start-1.0)
                    tokens=norm(visible).split()
                    if any(token in tokens or any(fuzz.ratio(token,t)>=82 for t in tokens)
                           for token in norm(w['w']).split()):
                        supported+=1
                if relevant and supported/len(relevant)>=.75:
                    continue
                if not relevant and displayed and fuzz.partial_ratio(actual,displayed)>=72:
                    continue
                kind = 'missing_subtitle'
        else:
            inside = [w for w in usable if start+.35 < w['s'] < end-.35]
            if len(inside) < 3:
                continue
            kind = 'cross_song'
        key = (kind, m['owner'], int(m['start']//5))
        if key in seen:
            continue
        seen.add(key)
        issues.append({'kind': kind, 'owner': m['owner'], 'start': round(m['start'], 3),
                       'end': round(m['end'], 3), 'heard': m['text'], 'score': m['score']})
    for u in units:
        if u.get('dropped') or u.get('type') != '歌词':
            continue
        text = norm(u['orig'])
        if len(set(text.split())) < 4:
            continue
        a,b = start+u['start']/1000, start+u['end']/1000
        heard = norm(' '.join(w['w'] for w in words if a-.7 <= w['s'] <= b+.7))
        supported=bool(heard) and fuzz.partial_ratio(text, heard)>=55
        if not supported:
            independent_support=set()
            for alternative in alternate_reads or []:
                alt=norm(' '.join(w['w'] for w in alternative.get('words',[]) if a-.7<=w['s']<=b+.7))
                if (alternative.get('origin')=='independent_saved_vocal_asr' and
                        alternative.get('original_source') and alternative.get('cache_sha256') and
                        len(alt.split())>=3 and fuzz.partial_ratio(text,alt)>=85):
                    independent_support.add(alternative['cache_sha256'])
                if len(alt.split())>=3 and fuzz.partial_ratio(text,alt)>=85 and (
                        not heard or u.get('mms_score',0)>=.15):
                    supported=True
                    break
            if len(independent_support)>=2:
                supported=True
        if not supported:
            issues.append({'kind':'unsupported_subtitle','unit':u['i'],'start':round(a,3),
                           'end':round(b,3),'displayed':u['orig'],'heard':heard})
    return issues, found


def supported_vocal_disagreement(issue, units, lines):
    """A noisy mix read cannot alone establish a wrong forced lyric.

    Keep a visible warning when the saved independent vocal read, supported by
    three recognition passes, is compatible. A wholly unrelated phrase (e.g.
    clap your hands versus you're an animal) still fails this check.
    """
    from rapidfuzz import fuzz
    if issue['kind']!='unsupported_subtitle':return None
    unit=next((u for u in units if u['i']==issue['unit']),None)
    if unit is None:return None
    stop={'a','an','the','i','you','your',"you're","i'm",'we','they','he','she','me','my',
          'our','their','to','of','at','and','or','but','is','are','it','that','this','with',
          'without','in','on','for','by','oh','yeah','uh','huh'}
    distinctive=set(norm(unit['orig']).split())-stop
    for line in lines:
        heard=norm(line.get('qwen',''));displayed=norm(unit['orig'])
        if (line.get('removed') or abs(line.get('start_ms',-10000)-unit['start'])>150 or
                norm(line.get('text',''))!=displayed or not line.get('anchor') or
                float(line.get('conf') or 0)<.55 or len({s for s in line.get('agree',[])
                    if re.fullmatch(r'A\d+',s)})<3):continue
        tokens=heard.split()
        matched=sum(any(fuzz.ratio(word,token)>=82 for token in tokens) for word in distinctive)
        agrees=(matched>=len(distinctive) if len(distinctive)<=2 else
                matched>=2 and matched/len(distinctive)>=.5)
        if (distinctive and agrees and len(tokens)>=3 and len(heard)>=len(displayed)*.5):
            return {'kind':'asr_disagreement','unit':unit['i'],'id':issue.get('id'),
                'displayed':unit['orig'],'mix_heard':issue['heard'],'vocal_heard':line['qwen'],
                'reason':'混音识别与已保存的多遍人声识别有分歧；人声读法支持当前字幕，保留待复核提示，未认定为确定错词。',
                'vocal_passes':line['agree'],'human_approved':False}
    return None


def check(concert, item):
    d = concert.song_dir(item)
    data = inputs(concert, item)
    identity = boundary_identity(concert, item)
    evidence = read_json(d / EVIDENCE, {})
    review = read_json(d / REVIEW, {})
    problems = []
    warnings = []
    for finding in review.get('findings', []):
        if finding.get('status') != 'resolved':
            problems.append({'kind': 'unresolved_review_finding',
                             'finding': finding})
    if data['prepared_slice'] != data['slice']:
        problems.append({'kind': 'prepared_slice_mismatch'})
    if (not data['prepared_source'] or
            Path(data['prepared_source']).resolve() != Path(data['source']['path'])):
        problems.append({'kind': 'prepared_source_mismatch'})
    if evidence.get('input') != identity:
        problems.append({'kind': 'missing_or_stale_source_evidence'})
    contexts = evidence.get('contexts', [])
    a, b = data['slice']
    expected_start = max(0, a-35)
    # End of original is the only valid exception to a 35-second guard band.
    source_end = evidence.get('source_duration', 0)
    expected_end = min(b+35, source_end) if source_end else b+35
    cursor = expected_start
    for context in sorted(contexts, key=lambda x:x['start']):
        if context.get('status') != 'ok' or context['start'] > cursor+.25:
            continue
        cursor = max(cursor, context['end'])
    if cursor < expected_end-.25:
        problems.append({'kind': 'incomplete_source_coverage', 'covered_to': cursor,
                         'required_to': expected_end})
    units = read_json(d / 'subs/translation/result.json', {}).get('units', [])
    if not units or len(data['subtitles']) < 3:
        problems.append({'kind': 'missing_subtitles'})
    duration = b-a
    for u in units:
        if u.get('dropped'):
            continue
        if u['start'] < 0 or u['end'] <= u['start'] or u['end'] > duration*1000+1:
            problems.append({'kind': 'subtitle_out_of_range', 'unit': u['i']})
        if u.get('type') not in ('语气词',) and not (u.get('v3_final') or u.get('v2_final')):
            problems.append({'kind': 'missing_translation', 'unit': u['i']})
    # Validate the actual file selected for burning, not just its JSON sidecar.
    try:
        import pysubs2
        from workflow.paths import render_subtitle
        from workflow.subtitle_spelling import display_english
        events=[e for e in pysubs2.load(str(render_subtitle(d))) if not e.is_comment
                and e.style!='Note' and e.plaintext.strip() and not e.plaintext.startswith('《')]
        if not events:
            raise ValueError('没有可显示的歌词/讲话字幕')
        for event in events:
            if event.start<0 or event.end<=event.start or event.end>duration*1000+20:
                problems.append({'kind':'rendered_subtitle_out_of_range','start':event.start,'end':event.end})
        for u in units:
            if u.get('dropped') or u.get('type') == '语气词':
                continue
            candidates=[e for e in events if abs(e.start-u['start'])<=100
                        and norm(e.plaintext.splitlines()[0])==norm(display_english(u['orig']))]
            translation = u.get('v3_final') or u.get('v2_final') or ''
            # Letter chants legitimately retain Latin text in both versions.
            # Compare the chosen translation, rather than requiring a Han glyph
            # in every event (which rejected the correctly spelled HOT TO GO).
            if not candidates or not any(norm(translation) and norm(translation) in norm(e.plaintext)
                                         for e in candidates):
                problems.append({'kind':'rendered_subtitle_mismatch','unit':u['i']})
    except (OSError,ValueError,TypeError) as exc:
        problems.append({'kind':'invalid_rendered_subtitle','error':str(exc)})
    alternatives=[r for r in evidence.get('alternate_reads',[]) if
        r.get('origin')!='independent_saved_vocal_asr' or r.get('original_source')==data['source']]
    issues, found = analyze(data['slice'], evidence.get('words', []),
                            lyric_references(concert, source_items(concert, item)), item['name'], units,
                            alternatives)
    if not any(m['owner'] == item['name'] for m in found):
        problems.append({'kind': 'insufficient_lyric_evidence'})
    # Reviewed exceptions must cite exact observed evidence, not a blanket waiver.
    resolutions = review.get('resolutions', []) if review.get('input') == identity else []
    source_lines=read_json(d/'subs/lines.json',[])
    for issue in issues:
        issue['id'] = digest(issue)
        resolved = next((r for r in resolutions if r.get('issue_id') == issue['id'] and
                         r.get('reason') and r.get('evidence')), None)
        if resolved:
            issue['resolution'] = resolved
        else:
            disagreement=supported_vocal_disagreement(issue,units,source_lines)
            if disagreement:warnings.append(disagreement)
            else:problems.append(issue)
    music = review.get('music', {})
    if (review.get('input') != identity or music.get('status') != 'passed' or
            not music.get('start_reason') or not music.get('end_reason') or not music.get('evidence')):
        problems.append({'kind': 'music_boundaries_not_verified'})
    result = {'version': VERSION, 'status': 'passed' if not problems else 'failed',
              'input': data, 'fingerprint': digest(data), 'issues': problems,
              'warnings':warnings,'human_approved':False,
              'detections': issues, 'checks': {'original_audio_coverage': not any(
                  p['kind'] in ('missing_or_stale_source_evidence','incomplete_source_coverage') for p in problems),
                  'lyrics_and_cross_song': not any(p['kind'] in ('missing_head','missing_tail','cross_song',
                      'missing_subtitle','insufficient_lyric_evidence','unsupported_subtitle',
                      'unresolved_review_finding') for p in problems),
                  'subtitles': not any(p['kind'] in ('missing_subtitles','subtitle_out_of_range',
                      'missing_translation','missing_subtitle','unsupported_subtitle','invalid_rendered_subtitle',
                      'rendered_subtitle_out_of_range','rendered_subtitle_mismatch',
                      'unresolved_review_finding') for p in problems),
                  'music_boundaries': not any(p['kind']=='music_boundaries_not_verified' for p in problems)}}
    write_json(d / REPORT, result)
    return result


def require_passed(concert, item):
    d = concert.song_dir(item)
    report = read_json(d / REPORT, {})
    try:
        current = inputs(concert, item)
    except (OSError, ValueError, KeyError) as exc:
        raise ContentCheckFailed(f'{item["name"]}：内容检查输入缺失：{exc}') from exc
    if (report.get('version') != VERSION or report.get('status') != 'passed' or
            report.get('fingerprint') != digest(current) or report.get('input') != current or
            set(report.get('checks', {})) != {'original_audio_coverage','lyrics_and_cross_song','subtitles','music_boundaries'} or
            not all(v is True for v in report['checks'].values()) or report.get('issues')):
        raise ContentCheckFailed(f'{item["name"]}：歌词完整性/串歌/字幕或音乐边界检查未通过或已过期，禁止出成片。'
                                f'请运行 python -m workflow.content_check {concert.slug} {item["name"]}')
    return report


def check_for_render(concert, item):
    """Re-run deterministic checks on current evidence before production work."""
    require_no_hold(concert,item)
    if not audit_enabled():return prepared_report(concert,item)
    evidence=read_json(concert.song_dir(item)/EVIDENCE,{})
    if evidence.get('input') != boundary_identity(concert,item):
        from workflow.source_lyrics import capture
        group=source_items(concert,item)
        if any(r['failed'] for r in capture(concert,items=group)):
            raise ContentCheckFailed('原片识别未全部成功，禁止将失败片段当作静音并制作')
    result=check(concert,item)
    if result.get('warnings'):
        print(f'{item["name"]}：{len(result["warnings"])} 处混音/人声识别分歧保留复核提示，未认定为确定错词',flush=True)
    return require_passed(concert,item)


def require_no_hold(concert, item):
    hold=read_json(concert.dir/'production_hold.json',{})
    if hold.get('active') and (not hold.get('songs') or item['name'] in hold['songs']):
        raise ContentCheckFailed(hold.get('reason') or '等待人工审核，禁止出成片')


def job_certificate(report, folder, source_sha256):
    if report.get('mode')=='prepared_preview':
        return {'version':VERSION,'mode':'prepared_preview','status':'not_requested',
                'fingerprint':report['fingerprint'],'concert':report['input']['concert'],
                'song':report['input']['song'],'slice':report['input']['slice'],
                'source_identity':report['input']['source'],'source_sha256':source_sha256,
                'assets':{name:file_hash(Path(folder)/name) for name in ASSETS}}
    if report.get('status') != 'passed':
        raise ContentCheckFailed('不能为未通过内容检查的任务生成制作凭据')
    return {'version': VERSION, 'status': 'passed', 'fingerprint': report['fingerprint'],
            'concert': report['input']['concert'], 'song': report['input']['song'],
            'slice': report['input']['slice'], 'source_sha256': source_sha256,
            'source_identity': report['input']['source'],
            'checks': report['checks'], 'assets': {name:file_hash(Path(folder)/name) for name in ASSETS}}


def require_job(policy, folder, source=None):
    cert = policy.get('content_check', {})
    prepared=cert.get('mode')=='prepared_preview'
    if prepared:
        if (cert.get('status')!='not_requested' or cert.get('slice')!=policy.get('slice') or
                not cert.get('fingerprint') or not cert.get('concert') or not cert.get('song') or
                len(cert.get('source_sha256',''))!=64 or set(cert.get('assets',{}))!=set(ASSETS)):
            raise ContentCheckFailed('制作任务输入记录不完整')
    elif (cert.get('version') != VERSION or cert.get('status') != 'passed' or
            cert.get('slice') != policy.get('slice') or not cert.get('fingerprint') or
            not cert.get('concert') or not cert.get('song') or
            len(cert.get('source_sha256', '')) != 64 or
            set(cert.get('checks', {})) != {'original_audio_coverage','lyrics_and_cross_song','subtitles','music_boundaries'} or
            not all(v is True for v in cert['checks'].values()) or set(cert.get('assets', {})) != set(ASSETS)):
        raise ContentCheckFailed('任务缺少当前范围的歌词完整性/串歌检查凭据，禁止编码')
    # Local workers and direct exports must also honor a hold added after
    # dispatch. Remote workers have a frozen job; the coordinator checks again
    # before installing their outputs.
    current_concert = Concert(cert['concert'])
    if current_concert.setlist.is_file():
        current_item = current_concert.item(cert['song'])
        require_no_hold(current_concert, current_item)
        fresh = (prepared_report(current_concert,current_item) if prepared else
                 require_passed(current_concert,current_item))
        if fresh['fingerprint'] != cert['fingerprint']:
            raise ContentCheckFailed('任务准备后分割或字幕已变更，禁止交付旧版本')
    for name in ASSETS:
        p = Path(folder)/name
        if not p.is_file() or file_hash(p) != cert['assets'][name]:
            raise ContentCheckFailed(f'任务字幕或水印已变更：{name}，禁止编码')
    if source is not None and source_identity(source) != cert.get('source_identity'):
        # Remote replicas have different paths/stat values; verify their bytes.
        from workflow.concert_delivery import source_digest
        if source_digest(Path(source)) != cert['source_sha256']:
            raise ContentCheckFailed('任务原片与通过检查的版本不同，禁止编码')
    return cert


def require_directory(directory):
    if not audit_enabled():return None
    directory = Path(directory)
    report = read_json(directory / REPORT, {})
    data = report.get('input', {})
    if not data.get('concert') or not data.get('song'):
        raise ContentCheckFailed('曲目没有通过歌词完整性/串歌检查，禁止出成片')
    c = Concert(data['concert'])
    item = c.item(data['song'])
    if c.song_dir(item).resolve() != directory.resolve():
        raise ContentCheckFailed('内容检查记录不属于当前曲目目录')
    require_no_hold(c,item)
    return require_passed(c,item)


def require_spec(spec):
    if not audit_enabled():return None
    parts = spec.split(':')
    if parts[0] == 'song':
        c = Concert(parts[1])
        return check_for_render(c, c.item(parts[2]))
    # Singles registered in the review library use the same checked entry point.
    c = Concert('singles')
    try:
        item = c.item(parts[1])
    except KeyError as exc:
        raise ContentCheckFailed('该单曲尚未登记并通过内容检查，禁止出成片') from exc
    return check_for_render(c, item)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('concert')
    parser.add_argument('songs', nargs='*')
    parser.add_argument('--capture', action='store_true', help='先独立识别原片及切点外上下文，按原片缓存')
    args = parser.parse_args()
    c = Concert(args.concert)
    if args.capture:
        from workflow.source_lyrics import capture
        if any(r['failed'] for r in capture(c)):
            raise SystemExit('原片识别有失败片段，不能将其当静音并通过检查')
    items = [c.item(n) for n in args.songs] if args.songs else c.song_items()
    failed = []
    for item in items:
        result = check(c, item)
        print(item['name'], result['status'], len(result['issues']), flush=True)
        if result['status'] != 'passed':
            failed.append(item['name'])
    if failed:
        raise SystemExit('内容检查未通过：' + ', '.join(failed))


if __name__ == '__main__':
    main()
