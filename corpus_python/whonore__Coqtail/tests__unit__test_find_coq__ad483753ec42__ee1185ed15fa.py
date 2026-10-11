"""Roqc executable resolution unit tests."""

import os
from pathlib import Path

from xmlInterface import find_coq


def mock_rocq_exe(name: str, path: Path, *, set_path: bool = False) -> Path:
    """Create a fake Rocq executable."""
    exe = path / name
    exe.touch(mode=0o777)
    if set_path:
        os.environ["PATH"] = f"{path}"
    return exe


def test_coqc_path(tmp_path: Path) -> None:
    """Default to coqc if it's found on $PATH."""
    exe = mock_rocq_exe("coqc", tmp_path, set_path=True)
    assert find_coq(None, None) == str(exe)


def test_rocq_path(tmp_path: Path) -> None:
    """Default to rocq if it's found on $PATH."""
    exe = mock_rocq_exe("rocq", tmp_path, set_path=True)
    assert find_coq(None, None) == str(exe)


def test_override_path(tmp_path: Path) -> None:
    """Search `coq_path` instead of $PATH if provided."""
    exe = mock_rocq_exe("rocq", tmp_path)
    assert find_coq(str(tmp_path), None) == str(exe)


def test_override_prog(tmp_path: Path) -> None:
    """Search for `coq_prog` if provided."""
    exe = mock_rocq_exe("my-rocq", tmp_path, set_path=True)
    assert find_coq(None, "my-rocq") == str(exe)
