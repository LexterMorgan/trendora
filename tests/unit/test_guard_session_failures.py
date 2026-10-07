"""Session-level guard regressions: swallowed violations fail the pytest run.

Each test spawns an isolated pytest subprocess with a temporary probe file
under ``tests/`` so the real conftest chain (guard install, unit fixture,
sessionfinish check) applies. Probes neutralize the resolver original first,
so even a broken guard cannot cause external I/O: a broken guard shows up as
an exit code of 0 where the parent demands nonzero.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_TESTS_DIR = REPO_ROOT / "tests"
_UNIT_DIR = _TESTS_DIR / "unit"

_PROBE_PRELUDE = '''\
import socket

from tests.io_guards import GUARDS

def _fake_resolver(*args, **kwargs):
    raise RuntimeError("resolver must not be reached")

try:
    GUARDS.originals["getaddrinfo"] = _fake_resolver
except Exception:
    socket.getaddrinfo = _fake_resolver

try:
    socket.getaddrinfo("guard-collection-probe.invalid", 80)
except Exception:
    pass
'''

COLLECTION_WITH_TEST = _PROBE_PRELUDE + "\n\ndef test_placeholder():\n    assert True\n"
COLLECTION_WITHOUT_TEST = _PROBE_PRELUDE

BODY_PROBE = '''\
import socket

from tests.io_guards import GUARDS

def _fake_resolver(*args, **kwargs):
    raise RuntimeError("resolver must not be reached")

try:
    GUARDS.originals["getaddrinfo"] = _fake_resolver
except Exception:
    socket.getaddrinfo = _fake_resolver

def test_body_violation_survives_being_caught():
    try:
        socket.getaddrinfo("guard-body-probe.invalid", 80)
    except Exception:
        pass
'''

TEARDOWN_PROBE = '''\
import socket

import pytest

from tests.io_guards import GUARDS

def _fake_resolver(*args, **kwargs):
    raise RuntimeError("resolver must not be reached")

try:
    GUARDS.originals["getaddrinfo"] = _fake_resolver
except Exception:
    socket.getaddrinfo = _fake_resolver

@pytest.fixture
def violation_in_teardown():
    yield
    try:
        socket.getaddrinfo("guard-teardown-probe.invalid", 80)
    except Exception:
        pass

def test_teardown_probe(violation_in_teardown):
    assert True
'''

CLEAN_PROBE = '''\
def test_clean_control():
    assert True
'''

COLLECTION_MARKER = "unexpected I/O recorded outside any test"
BODY_MARKER = "unexpected I/O attempted during unit test"


def _run_probe(path: Path, source: str, *args: str) -> subprocess.CompletedProcess:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {
            "TRENDORA_TEST_DATABASE_URL",
            "TRENDORA_TEST_DISPOSABLE_PG_URL",
            "TRENDORA_LIVE_SMOKE",
        }
    }
    path.write_text(source, encoding="utf-8")
    try:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                str(path),
                *args,
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        path.unlink(missing_ok=True)


def test_caught_collection_io_fails_a_collect_only_run() -> None:
    proc = _run_probe(
        _TESTS_DIR / "test_zz_guard_collection_probe.py",
        COLLECTION_WITH_TEST,
        "--collect-only",
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert COLLECTION_MARKER in output, output


def test_caught_collection_io_fails_a_run_with_no_tests_executed() -> None:
    proc = _run_probe(
        _TESTS_DIR / "test_zz_guard_collection_probe.py",
        COLLECTION_WITHOUT_TEST,
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert COLLECTION_MARKER in output, output


def test_caught_test_body_io_fails_the_run() -> None:
    proc = _run_probe(_UNIT_DIR / "test_zz_guard_body_probe.py", BODY_PROBE)
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert BODY_MARKER in output, output


def test_caught_teardown_io_fails_the_run() -> None:
    proc = _run_probe(_UNIT_DIR / "test_zz_guard_teardown_probe.py", TEARDOWN_PROBE)
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert BODY_MARKER in output, output


def test_clean_probe_still_exits_zero() -> None:
    proc = _run_probe(_UNIT_DIR / "test_zz_guard_clean_probe.py", CLEAN_PROBE)
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    assert COLLECTION_MARKER not in output, output
    assert BODY_MARKER not in output, output
