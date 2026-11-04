"""Integration regressions written before repository consolidation (2026-11-04)."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'data/participant-pack'
MANIFEST = ROOT / 'docs/integration-sources.json'



def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def run_import(expression, paths):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('MEL_', 'FARMERLOOP_', 'PYTHONPATH'))}
    env.update(PYTHONPATH=os.pathsep.join(str(p) for p in paths), AWS_EC2_METADATA_DISABLED='true', MEL_ALLOW_PAID_INFERENCE='false')
    return subprocess.check_output([sys.executable, '-c', expression], cwd='/private/tmp', env=env, text=True).strip()


def test_primary_pack_default_and_module_isolation():
    actual = run_import('from mel_agent.config import Settings; import mel_agent; print(Settings(_env_file=None).participant_pack_dir.resolve()); print(mel_agent.__file__)', [ROOT/'src'])
    pack, module = actual.splitlines()
    assert Path(pack) == PACK
    assert Path(module).is_relative_to(ROOT/'src')


def test_kevin_pack_default_and_module_isolation():
    actual = run_import('from mel_agent import config; import mel_agent; print(config.PACK.resolve()); print(mel_agent.__file__)', [ROOT/'prototypes/kevin'])
    pack, module = actual.splitlines()
    assert Path(pack) == PACK
    assert Path(module).is_relative_to(ROOT/'prototypes/kevin')


def test_farmerloop_pack_default_and_module_isolation():
    actual = run_import('from farmerloop.config import PARTICIPANT_PACK; import farmerloop; print(PARTICIPANT_PACK.resolve()); print(farmerloop.__file__)', [ROOT/'farmerloop/src'])
    pack, module = actual.splitlines()
    assert Path(pack) == PACK
    assert Path(module).is_relative_to(ROOT/'farmerloop/src')


def test_shared_schemas_unchanged_and_complete():
    commit = next(s['commit'] for s in json.loads(MANIFEST.read_text())['sources'] if s['ref'] == 'origin/kevin/mockup')
    schema_paths = git('ls-tree', '-r', '--name-only', commit, 'data/participant-pack/json/schemas').decode().splitlines()
    assert len(schema_paths) == 6
    for path in schema_paths:
        assert (ROOT/path).read_bytes() == git('show', f'{commit}:{path}')
        schema = json.loads((ROOT/path).read_text())
        assert '$schema' in schema


def test_uploaded_documents_remain_intact():
    commit = next(s['commit'] for s in json.loads(MANIFEST.read_text())['sources'] if s['ref'] == 'origin/main')
    paths = git('ls-tree', '-r', '--name-only', commit, 'docs/Digital Green Foundation').decode().splitlines()
    real_docs = [p for p in paths if not Path(p).name.startswith('~$')]
    assert len(real_docs) == 2
    for path in real_docs:
        assert (ROOT/path).read_bytes() == git('show', f'{commit}:{path}')
        with zipfile.ZipFile(ROOT/path) as doc:
            assert len(doc.read('word/document.xml')) > 1000


def test_every_contributor_source_preserved_or_explicitly_accounted_for():
    """Every source entry verifies pinned Git bytes and destination hash."""
    manifest = json.loads(MANIFEST.read_text())
    sources = manifest['sources']
    assert len(sources) >= 4
    destinations = set()
    for source in sources:
        commit = source['commit']
        assert len(commit) == 40
        assert source['files']
        for entry in source['files']:
            original = git('show', f"{commit}:{entry['source']}")
            assert hashlib.sha256(original).hexdigest() == entry['sha256']
            dest = ROOT / entry['destination']
            destinations.add(entry['destination'])
            assert dest.is_file(), f'missing source: {dest}'
            if entry.get('modified'):
                assert entry.get('reason', '').strip(), f'change needs rationale: {dest}'
            else:
                assert dest.read_bytes() == original, f'undeclared change: {dest}'
    assert any(p.startswith('prototypes/kevin/') for p in destinations)
    assert any(p.startswith('farmerloop/') for p in destinations)
    assert any(p.startswith('src/mel_agent/') for p in destinations)


def test_no_unique_branch_source_blob_is_lost():
    manifest = json.loads(MANIFEST.read_text())
    preserved = {entry['sha256'] for source in manifest['sources'] for entry in source['files']}
    for source in manifest['sources']:
        files = git('ls-tree', '-r', '--name-only', source['commit']).decode().splitlines()
        for file in files:
            original = git('show', f"{source['commit']}:{file}")
            assert hashlib.sha256(original).hexdigest() in preserved, f"unaccounted source: {source['ref']}:{file}"
