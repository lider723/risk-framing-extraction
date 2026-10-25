from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'scripts'))
sys.dont_write_bytecode=True
from risk_units import common,contracts,two_stage
from offline_check import candidates,messages
class ContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=json.loads((ROOT/'examples/synthetic_cases.json').read_text(encoding='utf-8'))
        cls.schema=json.loads((ROOT/'schemas/confirmation_v5.json').read_text())['confirmation']
    def errors(self,c):
        p=c['article'];a=c['output']
        return common.validate(a,self.schema)+contracts.confirmation_errors(a,p,candidates(c),{k:[v] for k,v in p.items()})
    def test_all_synthetic_cases(self):
        for c in self.cases:
            with self.subTest(c=c['record_id']):self.assertEqual(self.errors(c),[])
    def test_no_corpus_examples(self):self.assertTrue(all(c['record_id'].startswith('SYNTHETIC_') for c in self.cases))
    def test_one_candidate_can_map_to_many_units(self):
        c=self.cases[4];self.assertEqual(len(c['output']['candidate_decisions'][0]['unit_ids']),2);self.assertEqual(self.errors(c),[])
    def test_many_candidates_can_map_to_one_unit(self):self.assertGreater(len(self.cases[4]['output']['units'][0]['source_candidates']),1)
    def test_same_quote_different_harms_not_collapsed(self):
        us=self.cases[4]['output']['units'];self.assertEqual(us[0]['risk_claim_spans'],us[1]['risk_claim_spans']);self.assertEqual(len(contracts.final_projection(self.cases[4]['output'])['risk_units']),2)
    def test_unknown_candidate_rejected(self):
        c=deepcopy(self.cases[4]);c['output']['units'][0]['source_candidates'].append('C99');self.assertTrue(self.errors(c))
    def test_missing_candidate_decision_rejected(self):
        c=deepcopy(self.cases[4]);c['output']['candidate_decisions'].pop();self.assertTrue(self.errors(c))
    def test_non_verbatim_rejected(self):
        c=deepcopy(self.cases[0]);c['output']['units'][0]['risk_claim_spans'][0]['quote']+=' invented';self.assertTrue(self.errors(c))
    def test_wrong_paragraph_rejected(self):
        c=deepcopy(self.cases[0]);c['output']['units'][0]['risk_claim_spans'][0]['paragraph_id']='P999';self.assertTrue(self.errors(c))
    def test_schema_extra_field_rejected(self):
        c=deepcopy(self.cases[0]);c['output']['extra']=1;self.assertTrue(self.errors(c))
    def test_synthetic_message_contains_full_context(self):
        m=messages(self.cases[4]);self.assertIn('complete',m[1]['content']);self.assertIn('[P005]',m[1]['content'])
    def test_context_requests_expand_and_require_review(self):
        p={'P%03d'%i:'Original paragraph %d.'%i for i in range(1,6)};cs=[{'candidate_id':'C01','paragraph_id':'P003','quote':p['P003']}];ctx=contracts.ContextController(p,cs)
        ctx.expand([{'scope':'paragraph_and_neighbors','source_candidates':['C01']}],1)
        self.assertEqual(ctx.full_paragraphs,{'P002','P003','P004'});self.assertEqual(ctx.status,'pending')
        ctx.expand([{'scope':'article','source_candidates':['C01']}],2);self.assertEqual(ctx.status,'pending')
        ctx.accept_review_round(2);self.assertEqual(ctx.status,'complete');self.assertEqual(set(ctx.allowed()),set(p))
    def test_unique_original_quote_slice_repair_is_logged(self):
        a={'risk_claim_spans':[{'paragraph_id':'P001','quote':'A  specific consequence.'}]};p={'P001':'A specific consequence.'}
        restored,repairs,checks=contracts.restore_quotes(a,p)
        self.assertFalse(checks[0]['raw_verbatim']);self.assertEqual(restored['risk_claim_spans'][0]['quote'],p['P001']);self.assertEqual(len(repairs),1)
    def test_final_projection_retains_context(self):
        c=self.cases[4];self.assertEqual(contracts.final_projection(c['output'])['risk_units'][0]['necessary_context_spans'],c['output']['units'][0]['necessary_context_spans'])
if __name__=='__main__':unittest.main()
