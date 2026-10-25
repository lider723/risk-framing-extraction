#!/usr/bin/env python3
"""Check real contracts on synthetic examples only; no API or credential reads."""
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.dont_write_bytecode=True
from risk_units import common,contracts
def candidates(case):
    if 'candidates' in case:return case['candidates']
    return [{'candidate_id':cid,'paragraph_id':pid,'quote':q,'proposition':'Synthetic input'} for cid,pid,q in re.findall(r'--- (C\d+) ---\nPreceding:.*?\nTarget \[(P\d+)\]: ([^\n]+)',case['input'])]
def messages(case):
    cs=candidates(case);p=case['article'];folder=ROOT/'prompts/v5_baseline'
    return [{'role':'system','content':(folder/'v5_call3_system.txt').read_text(encoding='utf-8')},{'role':'user','content':contracts.render((folder/'v5_call3_user.txt').read_text(encoding='utf-8'),record_id=case['record_id'],context_review_status='complete',candidate_context_package=common.local_package(cs,p),additional_context_package='\n'.join('['+pid+'] '+text for pid,text in p.items()))}]
def main():
    cases=json.loads((ROOT/'examples/synthetic_cases.json').read_text(encoding='utf-8'));schema=json.loads((ROOT/'schemas/confirmation_v5.json').read_text())['confirmation']
    for case in cases:
        assert case['record_id'].startswith('SYNTHETIC_')
        p=case['article'];out=case['output'];errors=common.validate(out,schema)+contracts.confirmation_errors(out,p,candidates(case),{k:[v] for k,v in p.items()})
        assert not errors,(case['record_id'],errors)
        assert len(messages(case))==2
    print('PASS:',len(cases),'synthetic cases; schemas, exact quotes and candidate/unit mappings. No API calls.')
    print('Structural compliance is not semantic accuracy or an experimental performance result.')
if __name__=='__main__':main()
