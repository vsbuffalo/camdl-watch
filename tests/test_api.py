"""API tests — the typed JSON projection of the run store.

Each test points ``CAMDL_WATCH_STORE`` at a freshly-built golden store *before*
importing the FastAPI app (so ``current_store()`` reads it) and drives the app
through Starlette's ``TestClient``. The golden store carries the full
``docs``/``schema`` sidecar, so these assert the doc-labelled posterior contract
the first frontend screen (a forest plot) depends on.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from tests.fixtures.make_golden_store import RUN_DIR, build


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient over the app, pointed at a golden store in ``tmp_path``."""
    build(tmp_path)
    monkeypatch.setenv("CAMDL_WATCH_STORE", str(tmp_path))
    # current_store() reads the env fresh per request, so importing once is fine.
    from camdl_watch.api.app import app

    return TestClient(app)


def test_health_sees_the_store(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["runs"] == 1


def test_list_runs_one_documented_run(client):
    r = client.get("/api/runs")
    assert r.status_code == 200
    runs = r.json()
    assert len(runs) == 1
    run = runs[0]
    assert run["run_id"] == RUN_DIR
    assert run["has_docs"] is True
    assert run["n_params"] == 6
    assert run["n_chains"] == 2
    assert run["status"] == "done"
    assert run["algorithm"] == "pgas"
    assert run["backend"] == "chain_binomial"


def test_run_detail_schema_streams_and_dimensions(client):
    runs = client.get("/api/runs").json()
    run_id = runs[0]["run_id"]
    r = client.get(f"/api/runs/{run_id}")
    assert r.status_code == 200
    detail = r.json()

    streams = {s["name"]: s for s in detail["streams"]}
    assert "cases" in streams
    assert streams["cases"]["index_dims"] == ["patch"]
    assert streams["cases"]["likelihood"] == "neg_binomial"

    dims = {d["name"]: d for d in detail["dimensions"]}
    assert "patch" in dims
    assert dims["patch"]["levels"] == ["Bo", "Bombali"]

    assert detail["available_streams"] == ["cases"]
    assert detail["target_sweeps"] == 600
    assert detail["estimated"] == [
        "beta", "sigma", "gamma", "rho", "k_raw_Bo", "k_raw_Bombali",
    ]


def test_run_detail_404(client):
    r = client.get("/api/runs/does-not-exist")
    assert r.status_code == 404


def test_posterior_doc_labelled_params(client):
    runs = client.get("/api/runs").json()
    run_id = runs[0]["run_id"]
    r = client.get(f"/api/runs/{run_id}/posterior", params={"warmup_pct": 50})
    assert r.status_code == 200
    body = r.json()

    assert body["warmup_pct"] == 50
    assert body["n_tail"] > 0
    params = {p["name"]: p for p in body["params"]}
    assert list(params) == [
        "beta", "sigma", "gamma", "rho", "k_raw_Bo", "k_raw_Bombali",
    ]

    beta = params["beta"]
    assert beta["symbol"] == "β"
    assert beta["reference"] == "Anderson & May 1991"
    assert "transmission" in beta["description"]
    assert beta["prior"] == "LogNormal(μ=-0.6, σ=0.4)"
    assert beta["source"] == "fit_toml"

    # Expanded coordinate resolves to its base (k_raw) doc block.
    k_bo = params["k_raw_Bo"]
    assert k_bo["symbol"] == "k"
    assert k_bo["prior"] == "Normal(μ=0, σ=1)"
    assert k_bo["bounds"] == [-5.0, 5.0]

    # rho is documented but has no @ref.
    assert params["rho"]["symbol"] == "ρ"
    assert params["rho"]["reference"] is None
    assert params["rho"]["prior"] == "Beta(α=3, β=6)"

    # Every param ships finite, ordered quantiles and an R̂/ESS (camdl summary).
    for p in body["params"]:
        assert p["q05"] <= p["q25"] <= p["q50"] <= p["q75"] <= p["q95"]
        for key in ("mean", "sd", "q05", "q50", "q95"):
            assert isinstance(p[key], float)
        assert p["rhat"] is not None
        assert p["ess"] is not None


def test_posterior_404(client):
    r = client.get("/api/runs/nope/posterior")
    assert r.status_code == 404
