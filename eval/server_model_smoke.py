"""Real-model integration smoke test on frozen historical evidence; not an accuracy benchmark."""
import json
import sys
import time
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app import config
from app.api import public_run_data
from app.graph import execute
from app.question_service import QuestionService
from app.schemas import AnalyzeQuestionRequest, ConfirmQuestionRequest, ImportedEvidence, RunRecord, QuestionFraming
from app.sources import import_evidence
from app.storage import RunStore
root=Path(__file__).resolve().parents[1]
store=RunStore(root/'data/model-smoke')
case=json.loads((root/'eval/suites/forecastlab-v1.json').read_text(encoding='utf-8'))['cases'][0]
report={'test':'real model integration, historical exercise, not calibrated accuracy','model':config.MODEL_NAME,'case_id':case['id']}
started=time.monotonic()
try:
 service=QuestionService(store)
 previous_path=root/'local-model-full-smoke.json'
 previous=json.loads(previous_path.read_text(encoding='utf-8')) if previous_path.exists() else {}
 if previous.get('case_id')==case['id'] and previous.get('model')==config.MODEL_NAME and previous.get('framing',{}).get('status')=='ready_for_confirmation':
  frame=QuestionFraming.model_validate(previous['framing']);report['preparation_cached']=True
 else:
  frame=service.analyze(AnalyzeQuestionRequest(question=case['question']))
 report['framing']=frame.model_dump(mode='json')
 report['preparation_calls']=[c.model_dump(mode='json') for c in store.list_calls(frame.draft_id)]
 if frame.status!='ready_for_confirmation':
  report['status']='needs_clarification'
 else:
  confirmation=service.confirm(frame.draft_id,ConfirmQuestionRequest(expected_revision=frame.revision,decisions=[{'premise_id':p.id,'user_review':'retained','treatment':'to_verify'} for p in frame.premises]))
  pack=json.loads((root/case['evidence_file']).read_text(encoding='utf-8'))
  retrieval=import_evidence([ImportedEvidence.model_validate({**x,'source_type':'exercise'}) for x in pack['evidence']],confirmation.question,store.directory)
  record=RunRecord(run_id='local_smoke_'+uuid4().hex[:8],question=confirmation.question,question_framing=confirmation.framing,confirmation_id=confirmation.confirmation_id,question_origin='confirmed',evidence_mode='import',model=config.MODEL_NAME,retrieval_result=retrieval,preparation_records=store.list_calls(frame.draft_id))
  store.save(record)
  print('RUN_CREATED',record.run_id,flush=True)
  execute(record,retrieval.evidence,store)
  final=store.get(record.run_id)
  report['status']=final.status
  report['run']=public_run_data(final)
except Exception as exc:
 report['status']='failed';report['error']=f'{type(exc).__name__}: {exc}'
finally:
 report['elapsed_seconds']=round(time.monotonic()-started,2)
 (root/'local-model-full-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print('SMOKE_RESULT',report['status'],report['elapsed_seconds'],flush=True)
