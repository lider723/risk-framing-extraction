from . import contracts as core

def check1(a,p,cs):
    errs=[];seen=[];pids=[]
    for entry in a['candidate_assessments']:
        seen.append(entry['candidate_id'])
        if not entry['propositions']:errs.append('Each supplied candidate requires at least one explicit proposition decision')
        for pr in entry['propositions']:
            pids.append(pr['proposition_id'])
            if not pr['proposition'].strip() or not pr['reason'].strip():errs.append('Missing proposition/reason')
            if pr['decision']=='confirmed':
                u={'unit_id':'U01','source_candidates':[entry['candidate_id']],'confirmed':True,'ambiguity':'none','resolved_reference':'',**{k:pr[k] for k in ['justification','risk_claim_spans','necessary_context_spans']}}
                dec={'candidate_id':entry['candidate_id'],'proposition':pr['proposition'],'decision':'confirmed','unit_ids':['U01'],'reason':pr['reason']}
                errs+=core.confirmation_errors({'record_id':a['record_id'],'units':[u],'candidate_decisions':[dec],'context_requests':[]},p,[c for c in cs if c['candidate_id']==entry['candidate_id']],{k:[v] for k,v in p.items()})
    if len(seen)!=len(set(seen)) or set(seen)!={c['candidate_id'] for c in cs}:errs.append('Candidate assessments must cover every supplied candidate exactly once')
    if len(pids)!=len(set(pids)):errs.append('Proposition IDs must be unique')
    return errs

def flatten(a):return [{'candidate_id':entry['candidate_id'],**pr} for entry in a['candidate_assessments'] for pr in entry['propositions'] if pr['decision']=='confirmed']

def derive(a1,a2):
    confirmed={p['proposition_id']:p for p in flatten(a1)};mapping={};units=[]
    for i,u in enumerate(a2['units'],1):
        uid=f'U{i:02d}';cids=[]
        for pid in u['merged_proposition_ids']:
            if pid in confirmed:cids.append(confirmed[pid]['candidate_id']);mapping[pid]=uid
        units.append({'unit_id':uid,'source_candidates':list(dict.fromkeys(cids)),'confirmed':True,'ambiguity':'none','resolved_reference':'',**{k:u[k] for k in ['justification','risk_claim_spans','necessary_context_spans']}})
    decisions=[]
    for entry in a1['candidate_assessments']:
        for pr in entry['propositions']:
            decisions.append({'candidate_id':entry['candidate_id'],'proposition':pr['proposition'],'decision':pr['decision'],'unit_ids':[mapping[pr['proposition_id']]] if pr['proposition_id'] in mapping else [],'reason':pr['reason']})
    return {'record_id':a1['record_id'],'units':units,'candidate_decisions':decisions,'context_requests':[]}

def check2(a1,a2,p,cs):
    known={q['proposition_id'] for q in flatten(a1)};used=[pid for u in a2['units'] for pid in u['merged_proposition_ids']];unresolved=a2['unresolved_proposition_ids'];errs=[]
    if any(not u['merged_proposition_ids'] for u in a2['units']):errs.append('Every unit needs a confirmed proposition source')
    if len(used)!=len(set(used)) or set(used)&set(unresolved):errs.append('Every confirmed proposition must occur once, not in two units or both unresolved and exported')
    if set(used)|set(unresolved)!=known:errs.append('Missing/unknown confirmed proposition IDs; cannot silently discard or invent claims')
    if not errs and not unresolved:
        errs+=core.confirmation_errors(derive(a1,a2),p,cs,{k:[v] for k,v in p.items()})
    return errs
