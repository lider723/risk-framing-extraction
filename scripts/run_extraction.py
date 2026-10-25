#!/usr/bin/env python3
"""Portable historical v5 runner. Default: no API, no key access and no writes."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from risk_units import prep, pipeline as core


def output_location(value):
    path = value.resolve()
    local = (ROOT / 'local_only').resolve()
    if local != ROOT/'local_only' or path == local or local not in path.parents:
        raise ValueError('Output must be a new subdirectory inside local_only/ (ignored by Git).')
    return path


def read_articles(path):
    if not path.is_file():
        raise ValueError('Input missing. Obtain an authorized development package; no automatic download or synthetic substitution.')
    rows = prep.read_jsonl(path)
    ids = [str(a['record_id']) for a in rows]
    if not rows or len(set(ids)) != len(ids):
        raise ValueError('Input is empty or has duplicate record IDs.')
    for a in rows:
        if not re.fullmatch(r'[A-Za-z0-9_-]+',str(a['record_id'])):
            raise ValueError('Unsafe record ID; only letters, digits, underscore and hyphen allowed.')
        prep.paragraph_map(a)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--inputs', type=Path)
    ap.add_argument('--record-id', action='append')
    ap.add_argument('--output-dir', type=Path, default=ROOT/'local_only/runs/v5_portable')
    ap.add_argument('--run',action='store_true')
    ap.add_argument('--max-api-calls',type=int,default=0)
    ap.add_argument('--pause-seconds',type=float,default=1.0)
    ap.add_argument('--retry-errors',action='store_true')
    args = ap.parse_args()
    if args.run and (args.max_api_calls <= 0 or args.pause_seconds < 0):
        ap.error('--run requires an explicit positive --max-api-calls and non-negative pause.')
    if not args.inputs:
        if args.run:
            ap.error('--run requires --inputs with authorized development articles.')
        print('OFFLINE ONLY; no data read, no key read, no API and no output files. Use --inputs to preview an authorized input.')
        return
    try:
        output = output_location(args.output_dir)
        all_rows = read_articles(args.inputs)
        unknown = set(args.record_id or []) - {str(a['record_id']) for a in all_rows}
        if unknown:
            raise ValueError('Requested record ID absent from input: '+str(sorted(unknown)))
        rows = [a for a in all_rows if not args.record_id or str(a['record_id']) in args.record_id]
    except (ValueError,KeyError) as exc:
        ap.error(str(exc))
    templates = {f'call{n}_{role}':(ROOT/'prompts/v5_baseline'/f'v5_call{n}_{role}.txt').read_text(encoding='utf-8')
                 for n in (1,2,3) for role in ('system','user')}
    schemas = core.load(ROOT/'schemas/confirmation_v5.json')
    core.ENDPOINT = os.environ.get('AI_RISK_BASE_URL') or 'https://api.vveai.com/v1'
    preview = {'api_enabled':args.run,'model':core.MODEL,'endpoint':core.ENDPOINT,'articles':[str(a['record_id']) for a in rows],
               'planned_discovery_chunks_approximate':sum(len(prep.paragraph_chunks(prep.paragraph_map(a))) for a in rows)}
    print(json.dumps(preview,ensure_ascii=False,indent=2))
    if not args.run:
        print('Approximate chunk count only; exact historical tokenizer is loaded only for explicit execution. No files written.')
        return
    # Optional dependencies/credential are not imported or accessed by default.
    import tiktoken
    cache = ROOT/'local_only/tokenizer_cache'
    cache.mkdir(parents=True,exist_ok=True)
    os.environ['TIKTOKEN_CACHE_DIR'] = str(cache)
    prep.TOKENIZER = tiktoken.encoding_for_model(core.MODEL)
    source_hashes = {p.relative_to(ROOT).as_posix():core.sha(p) for folder in ('src','scripts') for p in (ROOT/folder).rglob('*.py')}
    identity = {'adapter_version':'portable_v5_2026-10-25_v1','model':core.MODEL,'endpoint':core.ENDPOINT,'temperature':0,
                'selected_article_sha256':core.digest(rows),'input_file_sha256':core.sha(args.inputs),
                'prompt_sha256':{k:core.hashlib.sha256(v.encode()).hexdigest() for k,v in templates.items()},
                'schema_sha256':core.digest(schemas),'code_sha256':source_hashes,'max_context_rounds':6}
    path = output/'portable_manifest.json'
    if path.exists() and core.load(path) != identity:
        raise core.StopRun('Run identity differs; choose a fresh local_only output directory.')
    core.save(path,identity)
    client = core.Client(output,schemas,args.max_api_calls,args.pause_seconds,args.retry_errors)
    # Preserve the historical two protocol probes before transmitting any article.
    for kind,empty in (('candidate',{'record_id':'protocol-check','candidates':[]}),
                       ('confirmation',{'record_id':'protocol-check','units':[],'candidate_decisions':[],'context_requests':[]})):
        probe = client.stage(f'protocol/{kind}.json',[{'role':'system','content':'Return exactly the requested JSON object.'},
                             {'role':'user','content':json.dumps(empty)}],kind,'protocol-check')
        if probe['status'] != 'OK':
            raise core.StopRun('Strict-schema protocol check failed.')
    for a in rows:
        if core.digest(read_articles(args.inputs)) != core.digest(all_rows):
            raise core.StopRun('Input changed during execution.')
        rid = str(a['record_id']); result_path = output/'results'/f'{rid}.json'
        if result_path.exists():
            prior = core.load(result_path)
            if prior['status']=='OK' or not args.retry_errors:
                print(rid,prior['status'],'saved result reused');continue
            core.save(output/'result_revisions'/f'{rid}_{core.digest(prior)[:12]}.json',prior)
        result = core.extract_article(client,a,templates,6)
        core.save(result_path,result)
        print(rid,result['status'],flush=True)


if __name__ == '__main__':
    try:
        main()
    except core.StopRun as exc:
        print('SERVICE_PAUSED:',exc,file=sys.stderr)
        raise SystemExit(2)
