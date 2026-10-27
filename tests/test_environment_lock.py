"""requirements.lock.txt (Task 15, D34 Scope B): exact pins that satisfy the floors declared in pyproject.toml.

Distinct from tests/test_pipeline.py::test_requirements_txt_mirrors_pyproject_dependencies (Task 14), which compares the package NAMES of requirements.txt with pyproject.toml; the lock has its own
name and is outside that test.
"""

from __future__ import annotations

import importlib.metadata as md
import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from curtailmit import run_manifest as rm

PROJECT = Path(__file__).resolve().parents[1]
LOCK = PROJECT / "requirements.lock.txt"


def _declared() -> list[Requirement]:
    meta = (PROJECT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"dependencies = \[(.*?)\]", meta, re.DOTALL).group(1) + re.search(r"dev = \[(.*?)\]", meta, re.DOTALL).group(1)
    return [Requirement(x) for x in re.findall(r'"([^"]+)"', block)]


def test_lock_file_exists_and_every_requirement_line_is_an_exact_pin():
    lines = [ln.split("#", 1)[0].strip() for ln in LOCK.read_text(encoding="utf-8").splitlines()]
    requirement_lines = [ln for ln in lines if ln]
    assert requirement_lines
    for ln in requirement_lines:
        assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9.!+_-]+( ; .+)?", ln), f"not an exact pin: {ln!r}"
    assert not any(op in ln.split(";")[0] for ln in requirement_lines for op in (">", "<", "~", "*", "!="))
    assert not any(ln.startswith("-e") or "git+" in ln for ln in requirement_lines)  # the package itself is installed with `pip install -e . --no-deps`


def test_every_declared_dependency_is_pinned_and_the_pin_satisfies_its_floor():
    pins = rm.parse_lock(LOCK)
    for req in _declared():
        name = re.sub(r"[-_.]+", "-", req.name).lower()
        assert name in pins, f"{req.name} (pyproject.toml) has no exact pin in requirements.lock.txt"
        assert req.specifier.contains(Version(pins[name]), prereleases=True), f"{req.name}=={pins[name]} violates the floor {req.specifier}"


def test_lock_header_states_the_tested_python_and_the_install_command():
    head = "\n".join(ln for ln in LOCK.read_text(encoding="utf-8").splitlines() if ln.startswith("#"))
    assert "Python 3.11" in head and "pip install -r requirements.lock.txt && pip install -e . --no-deps" in head
    assert "requires-python >= 3.10` has never been tested" in head


def test_lock_python_matches_the_interpreter_ci_uses():
    ci = (PROJECT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert set(re.findall(r'python-version: "([\d.]+)"', ci)) == {"3.11"}


def test_parse_lock_rejects_a_loose_line(tmp_path):
    bad = tmp_path / "lock.txt"
    bad.write_text("numpy>=1.26\n", encoding="utf-8")
    with pytest.raises(rm.RunManifestError, match="exact"):
        rm.parse_lock(bad)


def test_parse_lock_ignores_comments_and_markers(tmp_path):
    f = tmp_path / "lock.txt"
    f.write_text('# header\nNumPy==2.0.0  # inline\ncolorama==0.4.6 ; sys_platform == "win32"\n\n', encoding="utf-8")
    assert rm.parse_lock(f) == {"numpy": "2.0.0", "colorama": "0.4.6"}


def test_environment_report_flags_a_mismatch(tmp_path):
    f = tmp_path / "lock.txt"
    f.write_text("pytest==0.0.1\nnot-a-real-package-xyz==1.0\n", encoding="utf-8")
    rep = rm.environment_report(f)
    assert rep["environment_matches_lock"] is False and rep["mismatches"] == ["pytest"] and rep["packages"]["pytest"]["installed"] == md.version("pytest")
    assert rep["packages"]["not-a-real-package-xyz"]["installed"] is None and rep["lock_file"] == "lock.txt"
