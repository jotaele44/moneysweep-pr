"""Denominator and false-readiness regressions, not genealogy findings."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from moneysweep.investigation.lenses import GATES, LENS_IDS, summarize_registry, validate_registry
from server.backend import investigation_api


@pytest.fixture
def registry():
    return json.loads(Path('registry/investigation_lenses_v1.json').read_text())


def test_all_lenses_are_accounted_without_certification(registry):
    result = summarize_registry(registry)
    assert result['declared_lenses'] == result['required_lenses'] == 24
    assert result['states']['implementation_state']['UNATTEMPTED'] == 24
    assert result['readiness'] == 'UNRESOLVED'
    assert set(lens['id'] for lens in registry['lenses']) == set(LENS_IDS)


@pytest.mark.parametrize('mutation', ['empty','missing','duplicate','unknown','wrong_repo','bad_revision','unknown_field','no_sources','no_test','no_gates','waiver','pass_without_evidence','false_ready','invalid_type'])
def test_invalid_registry_fails_closed(registry, mutation):
    lens = registry['lenses'][0]
    if mutation == 'empty': registry['lenses'] = []
    elif mutation == 'missing': registry['lenses'].pop()
    elif mutation == 'duplicate': registry['lenses'][1] = copy.deepcopy(lens)
    elif mutation == 'unknown': lens['id'] = 'invented'
    elif mutation == 'wrong_repo': registry['repository'] = 'jotaele44/thehub-pr'
    elif mutation == 'bad_revision': registry['source_revision'] = 'main'
    elif mutation == 'unknown_field': lens['certified'] = True
    elif mutation == 'no_sources': lens['source_families'] = []
    elif mutation == 'no_test': lens['falsification'] = ' '
    elif mutation == 'no_gates': lens['gates'].pop('identity')
    elif mutation == 'waiver': lens['gates']['identity']['state'] = 'N/A'
    elif mutation == 'pass_without_evidence': lens['gates']['identity']['state'] = 'PASS'
    elif mutation == 'false_ready': lens['implementation_state'] = 'PASS'
    elif mutation == 'invalid_type': lens['gates']['identity']['state'] = []
    with pytest.raises(ValueError): validate_registry(registry)


def test_declared_pass_is_not_independent_verification(registry):
    for lens in registry['lenses']:
        for gate in GATES:
            lens['gates'][gate] = {'state':'PASS','evidence_refs':['test:declared-only']}
        lens['implementation_state'] = lens['source_coverage_state'] = lens['finding_state'] = 'PASS'
    assert summarize_registry(registry)['readiness'] == 'UNRESOLVED'


def test_api_returns_exact_registry_hash():
    app = FastAPI()
    app.include_router(investigation_api.router)
    response = TestClient(app).get('/investigation/lenses')
    assert response.status_code == 200
    body = response.json()
    assert body['provenance']['sha256'] == hashlib.sha256(investigation_api.REGISTRY_PATH.read_bytes()).hexdigest()
    assert body['summary']['readiness'] == 'UNRESOLVED'
    assert TestClient(app).post('/investigation/lenses', json={}).status_code == 405


@pytest.mark.parametrize('content', [None, '{}', '{', '[]'])
def test_missing_or_corrupt_registry_is_not_zero_results(tmp_path, monkeypatch, content):
    path = tmp_path / 'lenses.json'
    if content is not None: path.write_text(content)
    monkeypatch.setattr(investigation_api, 'REGISTRY_PATH', path)
    app = FastAPI()
    app.include_router(investigation_api.router)
    response = TestClient(app).get('/investigation/lenses')
    assert response.status_code == 503
    assert 'lenses' not in response.json()


def test_core_dashboard_composition_exposes_read_only_registry():
    from server.backend.main import app
    response = TestClient(app).get('/investigation/lenses')
    assert response.status_code == 200
    assert response.json()['summary']['declared_lenses'] == 24
