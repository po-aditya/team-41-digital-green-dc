"""Regression tests specified before Kevin API/inference hardening."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from mel_agent import api

TOKEN = 'independent-test-operator-token'

@pytest.mark.parametrize('method,path,payload', [
    ('get', '/v1/surveys/unknown', None),
    ('get', '/v1/follow-ups', None),
    ('post', '/v1/surveys', {}),
    ('post', '/v1/surveys/unknown/responses', {}),
])
def test_api_auth_fails_closed_and_accepts_operator(monkeypatch, method, path, payload):
    client = TestClient(api.app)
    kwargs = {'json':payload} if payload is not None else {}
    monkeypatch.delenv('KEVIN_OPERATOR_TOKEN', raising=False)
    assert getattr(client, method)(path, **kwargs).status_code == 503
    monkeypatch.setenv('KEVIN_OPERATOR_TOKEN', 'short')
    assert getattr(client, method)(path, **kwargs).status_code == 503
    monkeypatch.setenv('KEVIN_OPERATOR_TOKEN', TOKEN)
    assert getattr(client, method)(path, **kwargs).status_code == 401
    assert getattr(client, method)(path, headers={'X-Operator-Token':'wrong'}, **kwargs).status_code == 401
    allowed = getattr(client, method)(path, headers={'X-Operator-Token':TOKEN}, **kwargs)
    assert allowed.status_code not in (401,403,503)


def test_health_remains_public_without_credentials(monkeypatch):
    monkeypatch.delenv('KEVIN_OPERATOR_TOKEN', raising=False)
    assert TestClient(api.app).get('/health').status_code == 200


@pytest.mark.parametrize('opt_in', ['', 'false', '0', 'yes', 'TRUE '])
def test_paid_inference_refused_before_client_creation(opt_in):
    root = Path(api.__file__).resolve().parent.parent
    env = {k:v for k,v in os.environ.items() if not k.startswith(('MEL_', 'AWS_'))}
    env.update(PYTHONPATH=str(root), MEL_ALLOW_PAID_INFERENCE=opt_in, AWS_EC2_METADATA_DISABLED='true')
    result = subprocess.run([sys.executable, '-c', '''
from mel_agent import llm
calls=[]
def blocked():
    calls.append(True)
    raise AssertionError('client construction attempted')
llm._client=blocked
try:
    llm.call_tool('mock', '', '', 'test', '', {}, llm.Usage())
except RuntimeError:
    assert not calls
else:
    raise AssertionError('no refusal')
'''], cwd='/private/tmp', env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout+result.stderr


def test_explicit_inference_opt_in_reaches_mock_client():
    root = Path(api.__file__).resolve().parent.parent
    env = {k:v for k,v in os.environ.items() if not k.startswith(('MEL_', 'AWS_'))}
    env.update(PYTHONPATH=str(root), MEL_ALLOW_PAID_INFERENCE='true', AWS_EC2_METADATA_DISABLED='true')
    result = subprocess.run([sys.executable, '-c', '''
from mel_agent import llm
class MockClient:
    def converse(self, **kwargs):
        return {'usage':{'inputTokens':1,'outputTokens':1},'output':{'message':{'content':[{'toolUse':{'input':{'ok':True}}}]}}}
llm._client=lambda:MockClient()
assert llm.call_tool('mock','','','test','',{},llm.Usage()) == {'ok':True}
'''], cwd='/private/tmp', env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout+result.stderr
