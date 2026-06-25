"""Status classification: liveness (the sampler `.lock` PID), not trace mtime.

A slow / write-buffered sampler (PGAS on a spatial model can take minutes per
sweep) legitimately goes a long time between trace writes. Status must come from
whether the process is alive, never from file staleness — otherwise a live run
is mislabeled "done".
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import camdl_watch.app as app


def _mkrun(store: Path, name: str, *, rows: int, lock_pid: int) -> Path:
    seed = store / name / "01-posterior-aaaa1111" / "seed_1-bbbb2222"
    (seed / "chain_1").mkdir(parents=True)
    tp = seed / "chain_1" / "trace.tsv"
    if rows:
        tp.write_text(
            "step\tlog_posterior\tR0\n"
            + "".join(f"{i}\t-5.0\t1.{i}\n" for i in range(rows))
        )
    else:
        tp.write_text("")  # burn-in: empty
    (seed / ".lock").write_text(str(lock_pid))
    (store / name / "fit.meta.json").write_text(
        json.dumps({"estimated": ["R0"], "resolved_priors": []})
    )
    (store / name / "fit.toml.original").write_text(
        '[stages.posterior]\nalgorithm="pgas"\nbackend="chain_binomial"\nburn_in=2000\n'
    )
    return tp


_DEAD_PID = 2147483646  # almost certainly not a live process


def test_live_slow_sampler_with_ancient_trace_is_running(tmp_path, monkeypatch):
    store = tmp_path / "fits"
    tp = _mkrun(store, "slow-aaaa", rows=72, lock_pid=os.getpid())
    ancient = time.time() - 3600  # 1 hour since last write — the bug trigger
    os.utime(tp, (ancient, ancient))
    monkeypatch.setattr(app, "STORE", store)
    app._RUNS.clear()
    app._refresh_registry()
    assert app._RUNS["slow-aaaa"].status.value == "running"


def test_finished_run_with_draws_is_done(tmp_path, monkeypatch):
    store = tmp_path / "fits"
    _mkrun(store, "fin-bbbb", rows=72, lock_pid=_DEAD_PID)
    monkeypatch.setattr(app, "STORE", store)
    app._RUNS.clear()
    app._refresh_registry()
    assert app._RUNS["fin-bbbb"].status.value == "done"


def _seed(store: Path, name: str) -> Path:
    return store / name / "01-posterior-aaaa1111" / "seed_1-bbbb2222"


def _write_progress(seed: Path, state, *, updated_at: float, pid: int = 12345) -> None:
    seed.mkdir(parents=True, exist_ok=True)
    (seed / "progress.json").write_text(
        json.dumps({"updated_at": int(updated_at), "pid": pid, "state": state})
    )


def _classify_one(store, name, monkeypatch):
    monkeypatch.setattr(app, "STORE", store)
    app._RUNS.clear()
    app._refresh_registry()
    return app._RUNS[name]


def test_heartbeat_burn_in_is_warming(tmp_path, monkeypatch):
    # Heartbeat wins over the .lock: dead PID but a FRESH burn-in heartbeat.
    store = tmp_path / "fits"
    _mkrun(store, "hb-warm", rows=0, lock_pid=_DEAD_PID)
    _write_progress(_seed(store, "hb-warm"),
                    {"running": {"phase": "burn_in", "step": 130, "total": 1000}},
                    updated_at=time.time())
    rs = _classify_one(store, "hb-warm", monkeypatch)
    assert rs.status.value == "warming"
    assert (rs.progress.step, rs.progress.total) == (130, 1000)


def test_heartbeat_sampling_is_running(tmp_path, monkeypatch):
    store = tmp_path / "fits"
    _mkrun(store, "hb-run", rows=50, lock_pid=_DEAD_PID)
    _write_progress(_seed(store, "hb-run"),
                    {"running": {"phase": "sampling", "step": 600, "total": 1000}},
                    updated_at=time.time())
    assert _classify_one(store, "hb-run", monkeypatch).status.value == "running"


def test_heartbeat_stale_running_is_stalled(tmp_path, monkeypatch):
    # Stale heartbeat -> presumed dead, even though the .lock PID is alive.
    store = tmp_path / "fits"
    _mkrun(store, "hb-stale", rows=50, lock_pid=os.getpid())
    _write_progress(_seed(store, "hb-stale"),
                    {"running": {"phase": "sampling", "step": 600, "total": 1000}},
                    updated_at=time.time() - 120)
    assert _classify_one(store, "hb-stale", monkeypatch).status.value == "stalled"


def test_heartbeat_terminal_done_and_failed(tmp_path, monkeypatch):
    # Terminal states win regardless of a live .lock / freshness.
    store = tmp_path / "fits"
    _mkrun(store, "hb-done", rows=50, lock_pid=os.getpid())
    _write_progress(_seed(store, "hb-done"), "done", updated_at=time.time())
    assert _classify_one(store, "hb-done", monkeypatch).status.value == "done"

    store2 = tmp_path / "fits2"
    _mkrun(store2, "hb-fail", rows=50, lock_pid=os.getpid())
    _write_progress(_seed(store2, "hb-fail"),
                    {"failed": {"reason": "nan in likelihood"}}, updated_at=time.time())
    rs = _classify_one(store2, "hb-fail", monkeypatch)
    assert rs.status.value == "failed"
    assert rs.progress.reason == "nan in likelihood"


def test_burn_in_death_is_stalled_not_done(tmp_path, monkeypatch):
    # No heartbeat (e.g. mh/ode): a run seen live in burn-in, then its sampler
    # dies with zero draws, must read 'stalled' (died) — never 'done' (a fit
    # that finishes always writes draws).
    store = tmp_path / "fits"
    _mkrun(store, "die-aaaa", rows=0, lock_pid=os.getpid())
    monkeypatch.setattr(app, "STORE", store)
    app._RUNS.clear()
    app._refresh_registry()
    assert app._RUNS["die-aaaa"].status.value == "warming"
    (_seed(store, "die-aaaa") / ".lock").write_text(str(_DEAD_PID))  # sampler dies
    app._refresh_registry()
    assert app._RUNS["die-aaaa"].status.value == "stalled"


def test_verdict_names_failing_check_not_blanket_not_converged():
    # An acceptance-only error must NOT read "not converged" (R̂ is fine); the
    # verdict names the actual failing check.
    from camdl_watch.state import ChainSummary, Finding, Severity
    acc_only = ChainSummary(
        stage="pgas", n_chains=4, rhat={"R0": 1.01}, ess={}, ess_per_chain={},
        findings=[Finding("acceptance_rate_unhealthy", Severity.ERROR,
                          "rate 90% outside healthy range [15%, 50%].", param="R0",
                          detail={"rate": 0.9})],
    )
    h = app._verdict_block_html(acc_only)
    assert "acceptance" in h and "not converged" not in h
    # An R̂ error does name R̂.
    rhat = ChainSummary(
        stage="pgas", n_chains=4, rhat={"R0": 1.6}, ess={}, ess_per_chain={},
        findings=[Finding("rhat_high", Severity.ERROR, "Rhat 1.6", param="R0",
                          detail={"rhat": 1.6})],
    )
    assert "R̂" in app._verdict_block_html(rhat)


def test_deleted_run_dir_is_dropped_not_zombied(tmp_path, monkeypatch):
    # A live run whose dir is pruned off disk must leave the registry — not
    # linger as a stale "[done]" with frozen draws and no summary.
    store = tmp_path / "fits"
    _mkrun(store, "prune-aaaa", rows=72, lock_pid=os.getpid())
    monkeypatch.setattr(app, "STORE", store)
    app._RUNS.clear()
    app._refresh_registry()
    assert app._RUNS["prune-aaaa"].status.value == "running"
    # user cleans the store
    import shutil
    shutil.rmtree(store / "prune-aaaa")
    app._refresh_registry()
    assert "prune-aaaa" not in app._RUNS  # zombie dropped, not reclassified done


def test_done_blurb_reports_completion_not_partial_sweep(tmp_path, monkeypatch):
    # A cleanly-done run's last sweep is target-1; the blurb must read as
    # complete, not a mid-run "2999/3000".
    store = tmp_path / "fits"
    _mkrun(store, "fin-sweep", rows=3000, lock_pid=_DEAD_PID)
    (store / "fin-sweep" / "fit.toml.original").write_text(
        '[stages.posterior]\nalgorithm="pgas"\nbackend="chain_binomial"\nsweeps=3000\n')
    _write_progress(_seed(store, "fin-sweep"), "done", updated_at=time.time())
    rs = _classify_one(store, "fin-sweep", monkeypatch)
    assert rs.status.value == "done"
    blurb = app._progress_blurb(rs)
    assert "3000 sweeps" in blurb and "/" not in blurb


def test_pick_prefers_live_stage_among_empty_siblings(tmp_path):
    # Two empty stage dirs (a relaunch): even when the dead one sorts first by
    # mtime, the live one is surfaced.
    from camdl_watch import ingest
    run = tmp_path / "cfg-deadbeef"
    dead = run / "02-posterior-bbbb2222" / "seed_1-bbbb"
    live = run / "01-posterior-aaaa1111" / "seed_1-aaaa"
    for sd, pid in ((dead, _DEAD_PID), (live, os.getpid())):
        (sd / "chain_1").mkdir(parents=True)
        (sd / "chain_1" / "trace.tsv").write_text("")
        (sd / ".lock").write_text(str(pid))
    # make the dead stage the most-recent so it would win the mtime tiebreak
    newer = time.time() + 100
    os.utime(dead / "chain_1" / "trace.tsv", (newer, newer))
    picked = ingest._pick_posterior_dir(run, include_warming=True)
    assert picked is not None and picked[1] == live  # the live seed dir, not the dead newer one


def test_live_burn_in_is_warming_dead_burn_in_hidden(tmp_path, monkeypatch):
    store = tmp_path / "fits"
    _mkrun(store, "warm-cccc", rows=0, lock_pid=os.getpid())   # live, no draws
    _mkrun(store, "dead-dddd", rows=0, lock_pid=_DEAD_PID)     # dead, no draws
    monkeypatch.setattr(app, "STORE", store)
    app._RUNS.clear()
    app._refresh_registry()
    assert app._RUNS["warm-cccc"].status.value == "warming"
    assert "dead-dddd" not in app._RUNS  # empty + dead stays hidden
