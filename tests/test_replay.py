import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
spec = importlib.util.spec_from_file_location('replay_scores',ROOT/'scripts/replay_scores.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReplayTests(unittest.TestCase):
    def test_saved_both_rounds(self):
        output = module.replay(json.loads((ROOT/'reports/scoring_replay.json').read_text()))
        self.assertEqual(output['round1']['common_complete_articles'],14)
        self.assertEqual(output['round2']['common_complete_articles'],12)
        self.assertEqual(len(output['round1']['incomplete']),2)

    def test_mixed_covers_two_but_one_tp(self):
        row={'status':'OK','references':{'U01':['jobs'],'U02':['war']},
             'units':[{'unit_id':'U01','validity':'supported','claims':['jobs','war']}]}
        result=module.score_row(row,{})
        self.assertEqual((result['TP'],result['content_covered'],result['mixed']),(1,2,1))

    def test_duplicate_not_second_tp(self):
        row={'status':'OK','references':{'U01':['jobs']},'units':[
            {'unit_id':u,'validity':'supported','claims':['jobs']} for u in ('U01','U02')]}
        result=module.score_row(row,{})
        self.assertEqual((result['TP'],result['FP'],result['duplicates']),(1,1,1))

    def test_failure_is_not_zero_risk(self):
        self.assertIsNone(module.score_row({'status':'PARTIAL'},{}))

    def test_default_runner_no_key_or_output(self):
        result=subprocess.run([sys.executable,str(ROOT/'scripts/run_extraction.py')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('OFFLINE ONLY',result.stdout)

    def test_run_needs_cap_before_data_or_key(self):
        result=subprocess.run([sys.executable,str(ROOT/'scripts/run_extraction.py'),'--run'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('--max-api-calls',result.stderr)

    def test_protect_output_and_missing_data(self):
        spec2=importlib.util.spec_from_file_location('run_extraction',ROOT/'scripts/run_extraction.py')
        runner=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(runner)
        with self.assertRaises(ValueError):runner.output_location(ROOT/'prompts')
        with self.assertRaises(ValueError):runner.read_articles(ROOT/'local_only/missing.jsonl')

    def test_historical_pipeline_synthetic_mock(self):
        from risk_units import pipeline, prep
        case=json.loads((ROOT/'examples/synthetic_cases.json').read_text())[0]
        quote=case['article']['P001']
        article={'record_id':case['record_id'],'title':'Synthetic title',
                 'paragraph_numbered_article':'[P001] '+quote}
        templates={f'call{n}_{role}':(ROOT/'prompts/v5_baseline'/f'v5_call{n}_{role}.txt').read_text()
                   for n in (1,2,3) for role in ('system','user')}
        class FakeClient:
            output=ROOT/'local_only/fake_never_written'
            calls=[]
            def stage(self,relative,messages,kind,rid):
                self.calls.append((relative,messages,kind))
                if kind=='candidate':
                    cs=[{'candidate_id':'C01','paragraph_id':'P001','quote':quote,'proposition':'Synthetic input'}] if 'call1' in relative else []
                    answer={'record_id':rid,'candidates':cs}
                else:answer=deepcopy(case['output'])
                return {'status':'OK','answer':answer,'content':json.dumps(answer)}
        client=FakeClient()
        with patch.object(pipeline,'save') as saved:
            result=pipeline.extract_article(client,article,templates,6)
        self.assertEqual(result['status'],'OK')
        self.assertEqual(len(result['answer']['risk_units']),1)
        self.assertTrue(result['discovery_stages_complete'])
        self.assertEqual(len([c for c in client.calls if c[2]=='confirmation']),3)
        self.assertIn('CONTEXT_REVIEW_STATUS: complete',client.calls[-1][1][1]['content'])
        self.assertTrue(saved.called)
        self.assertIsNone(prep.TOKENIZER)


if __name__=='__main__':unittest.main()
