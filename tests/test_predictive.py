"""Predictive-artifact reader tests. No ``camdl fit predict`` output exists in
the reference store, so these use synthetic TSV fixtures written to a tmp dir,
matching camdl's on-disk column layout (predict.rs renderer):

* predictive/<stream>.tsv:
    time | <dims…> | horizon | treatment | rhat_max | ess_min | n_draws | q05 … q95
* observed/<stream>.tsv:
    time | <dims…> | value
"""

from __future__ import annotations

from pathlib import Path

import pytest

from camdl_watch import predictive

_PRED_HEADER = (
    "time\tpatch\thorizon\ttreatment\trhat_max\tess_min\tn_draws"
    "\tq05\tq25\tq50\tq75\tq95\n"
)
_PRED_ROWS = (
    "0\tBo\tfree_forward\tcounterfactual\t1.01\t820\t2000\t0.5\t1.2\t2.0\t2.8\t3.6\n"
    "1\tBo\tfree_forward\tcounterfactual\t1.01\t815\t2000\t0.6\t1.4\t2.3\t3.1\t4.0\n"
)
_OBS = "time\tpatch\tvalue\n0\tBo\t2\n1\tBo\t\n"  # second row: an observed hole


def _write_predict(run_dir: Path, stream: str = "cases") -> None:
    (run_dir / "predictive").mkdir(parents=True, exist_ok=True)
    (run_dir / "observed").mkdir(parents=True, exist_ok=True)
    (run_dir / "predictive" / f"{stream}.tsv").write_text(_PRED_HEADER + _PRED_ROWS)
    (run_dir / "observed" / f"{stream}.tsv").write_text(_OBS)


def test_discover_streams_union(tmp_path: Path):
    _write_predict(tmp_path, "cases")
    # An observed-only stream still surfaces (union of both dirs).
    (tmp_path / "observed" / "deaths.tsv").write_text("time\tvalue\n0\t1\n")
    assert predictive.discover_streams(tmp_path) == ["cases", "deaths"]


def test_discover_streams_absent_is_empty(tmp_path: Path):
    # No predictive/observed dirs at all (a fit that was never predicted).
    assert predictive.discover_streams(tmp_path) == []


def test_read_predictive_columns_and_values(tmp_path: Path):
    _write_predict(tmp_path)
    series = predictive.read_predictive(tmp_path, "cases")
    assert series is not None
    assert series.stream == "cases"
    df = series.table
    assert df.height == 2
    # The renderer's column layout round-trips faithfully.
    assert df.columns == [
        "time", "patch", "horizon", "treatment", "rhat_max", "ess_min",
        "n_draws", "q05", "q25", "q50", "q75", "q95",
    ]
    assert df["q50"].to_list() == [2.0, 2.3]
    assert df["patch"].to_list() == ["Bo", "Bo"]


def test_read_observed_columns_and_hole(tmp_path: Path):
    _write_predict(tmp_path)
    series = predictive.read_observed(tmp_path, "cases")
    assert series is not None
    assert series.stream == "cases"
    df = series.table
    assert df.columns == ["time", "patch", "value"]
    # The hole (empty cell) reads back as a null.
    assert df["value"].to_list() == [2, None]


def test_read_absent_stream_is_none(tmp_path: Path):
    _write_predict(tmp_path, "cases")
    assert predictive.read_predictive(tmp_path, "nope") is None
    assert predictive.read_observed(tmp_path, "nope") is None
    # And an entirely un-predicted run.
    empty = tmp_path / "empty_run"
    empty.mkdir()
    assert predictive.read_predictive(empty, "cases") is None
    assert predictive.read_observed(empty, "cases") is None


def test_empty_file_is_none(tmp_path: Path):
    (tmp_path / "predictive").mkdir()
    (tmp_path / "predictive" / "cases.tsv").write_text("")  # 0 bytes -> NoDataError
    assert predictive.read_predictive(tmp_path, "cases") is None
