#!/usr/bin/env python3
"""Recompute saved semantic judgments offline; no model calls or new judgments."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from risk_units.scoring import pair, metric


def score_row(row, aliases):
    if row['status'] != 'OK':
        return None
    units, refs = row['units'], row['references']
    assert len({x['unit_id'] for x in units}) == len(units), 'Duplicate unit ID'
    assert all(x['validity'] in ('supported','boundary','context','unsupported') for x in units)
    edges = {g: [u['unit_id'] for u in units if u['validity'] == 'supported' and set(sig) & set(u['claims'])]
             for g, sig in refs.items()}
    pairs = pair(edges)
    group = lambda k: aliases.get(k, k)
    found = {group(k) for u in units if u['validity'] == 'supported' for k in u['claims']}
    seen, duplicates, mixed = set(), 0, 0
    for u in units:
        if u['validity'] != 'supported':
            continue
        groups = {group(k) for k in u['claims']}
        duplicates += bool(groups & seen)
        mixed += len(groups) > 1
        seen |= groups
    return {**metric(len(refs), len(units), len(pairs)),
            'content_covered': sum(bool({group(k) for k in sig} & found) for sig in refs.values()),
            'duplicates': duplicates, 'mixed': mixed,
            **{k: sum(u['validity'] == k for u in units) for k in ('unsupported','boundary','context')},
            'severe_attribution': sum(bool(u.get('severe_attribution_error')) for u in units),
            'condition_errors': sum(bool(u.get('condition_error')) for u in units)}


def replay(bundle):
    output = {}
    renamed = {'content_covered_reference_items':'content_covered', 'duplicate_supported_units':'duplicates',
               'mixed_units':'mixed', 'unsupported_units':'unsupported', 'boundary_units':'boundary',
               'context_only_units':'context', 'severe_attribution_errors':'severe_attribution'}
    for name in ('round1','round2'):
        data = bundle[name]
        rows = data['rows']
        keys = [(r['condition'],r['record_id'],r['repeat']) for r in rows]
        assert len(set(keys)) == len(keys), 'Repeated result key'
        ids = set(data['common_complete_ids'])
        summaries = []
        for expected in data['expected_summaries']:
            cond = expected['condition']
            selected = [r for r in rows if r['condition'] == cond and r['repeat'] == 1 and r['record_id'] in ids]
            assert len(selected) == len(ids) and all(r['status'] == 'OK' for r in selected), 'Common denominator invalid'
            scored = [score_row(r, data['aliases']) for r in selected]
            total = Counter()
            for s in scored:
                total.update({k:v for k,v in s.items() if k not in ('precision','recall','f1')})
            summary = {'condition': cond, 'articles': len(selected),
                       **metric(total['gold'],total['pred'],total['TP']),
                       **{k:total[k] for k in ('content_covered','duplicates','mixed','unsupported','boundary','context','severe_attribution','condition_errors')}}
            for key,value in expected.items():
                target = renamed.get(key,key)
                if target in summary:
                    assert summary[target] == value, (name,cond,key,summary[target],value)
            summaries.append(summary)
        output[name] = {'summaries':summaries,
                        'incomplete':[{k:r[k] for k in ('condition','record_id','status')} for r in rows if r['status']!='OK'],
                        'saved_article_runs':len(rows), 'common_complete_articles':len(ids)}
    return output


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',type=Path,default=ROOT/'reports/scoring_replay.json')
    args = ap.parse_args()
    if not args.input.is_file():
        ap.error('Missing saved-judgment file; no data is downloaded or fabricated.')
    results = replay(json.loads(args.input.read_text(encoding='utf-8')))
    print('Existing llm_assisted judgments only; no API, no new semantic adjudication.')
    for name,result in results.items():
        print('\n'+name+' (common complete articles='+str(result['common_complete_articles'])+')')
        print('condition   Gold Pred TP FP FN   P%    R%   F1%  content')
        for s in result['summaries']:
            print('{condition:10} {gold:4} {pred:4} {TP:2} {FP:2} {FN:2} {precision:6.1%} {recall:6.1%} {f1:6.1%} {content_covered}/{gold}'.format(**s))
        print('Incomplete, excluded from semantic denominator:',result['incomplete'])
    print('\nREPLAY PASS: all exported historical summary counts and metrics reproduced.')


if __name__ == '__main__':
    main()
