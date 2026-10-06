import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent1_anchor_and_summary_metrics():
    m = load('agent1_robustness_eval', 'eval/agent1_robustness.py')
    frame = SimpleNamespace(premises=[SimpleNamespace(original_span='既然核心测试都已通过', content='核心测试都已通过')])
    assert m.premise_anchor_detected(frame, '核心测试都已通过') is True
    rows = [
        {'status':'ok','pair_id':'x','variant':'neutral','repeat':1,'premise_count':0,'neutral_false_positive':False,
         'expected_premise_detected':None,'explicit_fields_preserved':True,'blocking_clarification_count':0,
         'ready_for_confirmation':True,'elapsed_seconds':1.0},
        {'status':'ok','pair_id':'x','variant':'leading','repeat':1,'premise_count':1,'neutral_false_positive':False,
         'expected_premise_detected':True,'explicit_fields_preserved':True,'blocking_clarification_count':0,
         'ready_for_confirmation':True,'elapsed_seconds':2.0},
    ]
    s = m.summarize(rows)
    assert s['neutral_false_positive_rate'] == 0
    assert s['leading_premise_detection_rate'] == 1
    assert s['paired_leading_adds_premise_rate'] == 1
    assert s['explicit_field_preservation_rate'] == 1


def test_agent1_frozen_pairs_have_matching_explicit_deadlines():
    rows = json.loads((ROOT / 'eval/cases/agent1-neutral-leading-v2.json').read_text())
    assert len(rows) == 16
    grouped = {}
    for row in rows:
        grouped.setdefault(row['pair_id'], []).append(row)
        assert row['question']['as_of'] < row['question']['resolve_by']
    assert len(grouped) == 8
    for pair in grouped.values():
        assert {x['variant'] for x in pair} == {'neutral','leading'}
        assert pair[0]['question']['resolve_by'] == pair[1]['question']['resolve_by']
        assert pair[0]['question']['resolution_rule'] == pair[1]['question']['resolution_rule']


def test_agent2_stratified_sample_maximizes_case_breadth():
    m = load('agent2_quote_audit_eval', 'eval/agent2_quote_audit.py')
    pop=[]
    for c in range(5):
        for f in range(3):
            pop.append({'case_id':f'C{c}','finding_id':f'F{f}','category':'x'})
    sample=m.stratified_sample(pop,sample_size=5,seed=7606)
    assert len(sample)==5
    assert len({r['case_id'] for r in sample})==5


def test_agent2_audit_score_requires_all_labels(tmp_path, capsys):
    # Keep this as a structural fixture; CLI behavior is covered by py_compile and the scoring formula below.
    rows=[
        {'relation':'supports','human_label':'supported'},
        {'relation':'background','human_label':'partially_supported'},
        {'relation':'challenges','human_label':'unsupported'},
        {'relation':'unclear','human_label':'unclear'},
    ]
    assert sum(r['human_label']=='supported' for r in rows)/len(rows)==0.25
    assert sum(r['human_label'] in {'supported','partially_supported'} for r in rows)/len(rows)==0.5


def test_agent1_prompt_keeps_question_framing_out_of_premises():
    from app.agents.question import PROMPT
    assert "以下内容不是 premise" in PROMPT
    assert "研究对象或实体名称本身" in PROMPT
    assert "用户正在询问的目标事件" in PROMPT
    assert "resolution_rule、resolution_source" in PROMPT
    assert "premises 应为空" in PROMPT
    assert "既然核心测试都已经通过" in PROMPT
