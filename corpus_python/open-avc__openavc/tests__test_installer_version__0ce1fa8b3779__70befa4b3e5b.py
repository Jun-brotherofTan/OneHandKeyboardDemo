"""Tests for installer version propagation (A30).

setup.iss used to hardcode `#define MyAppVersion "0.4.1"` regardless of
the actual project version. Running `installer\\build.bat` locally
emitted `dist\\OpenAVC-Setup-0.4.1.exe` even when pyproject.toml said
0.10.3 — which broke the rollback cache logic (filenames didn't match
__version__) and confused anyone trying to test the installer locally.

The fix: build.bat reads pyproject.toml via installer/get-version.py and
passes the value through ISCC's `/DMyAppVersion=...` flag. setup.iss
guards its hardcoded define with `#ifndef MyAppVersion` so the CLI
override wins.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def test_get_version_helper_prints_pyproject_version():
    """installer/get-version.py is what build.bat invokes. It must print
    the version from pyproject.toml exactly so /DMyAppVersion=<output>
    yields a matching installer filename.
    """
    helper = REPO_ROOT / "installer" / "get-version.py"
    assert helper.exists(), "installer/get-version.py is missing"

    result = subprocess.run(
        [sys.executable, str(helper)],
        capture_output=True, text=True, check=True, cwd=REPO_ROOT,
    )
    helper_version = result.stdout.strip()

    # Read pyproject.toml directly for comparison.
    import tomllib
    with open(REPO_ROOT / "pyproject.toml", "rb") as fh:
        expected = tomllib.load(fh)["project"]["version"]

    assert helper_version == expected, (
        f"get-version.py printed '{helper_version}', "
        f"pyproject.toml says '{expected}'"
    )


def test_setup_iss_guards_version_define():
    """The hardcoded fallback in setup.iss must sit behind `#ifndef
    MyAppVersion` so build.bat's `/DMyAppVersion=...` override wins.
    Without the guard, ISCC's command-line define is silently re-overridden
    by the file's #define and we ship the stale fallback.
    """
    iss = (REPO_ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")

    # The define must be wrapped in #ifndef ... #endif
    pattern = re.compile(
        r"#ifndef\s+MyAppVersion\s*[\r\n]+#define\s+MyAppVersion\b.*?#endif",
        re.DOTALL,
    )
    assert pattern.search(iss), (
        "setup.iss must guard `#define MyAppVersion` with `#ifndef "
        "MyAppVersion ... #endif` so build.bat /D override wins."
    )

    # And the fallback should obviously be a placeholder, not a real
    # release version, so a forgotten /D produces a screaming filename.
    fallback_match = re.search(
        r'#define\s+MyAppVersion\s+"([^"]+)"', iss
    )
    assert fallback_match
    assert "dev" in fallback_match.group(1) or "0.0.0" in fallback_match.group(1), (
        f"setup.iss fallback `{fallback_match.group(1)}` looks like a real "
        f"version — should be a placeholder like 0.0.0-dev so an accidentally "
        f"un-/D'd build is obvious."
    )


def test_build_bat_passes_d_flag_and_uses_version_in_filename():
    """build.bat must read the helper's output into VERSION and pass it
    via ISCC /DMyAppVersion=%VERSION% — not run plain `iscc setup.iss`
    (which uses the file's fallback) and not hardcode the version anywhere.
    """
    src = (REPO_ROOT / "installer" / "build.bat").read_text(encoding="utf-8")

    assert "get-version.py" in src, "build.bat should invoke installer/get-version.py"
    assert "/DMyAppVersion=%VERSION%" in src, (
        "build.bat must pass /DMyAppVersion=%VERSION% to ISCC"
    )
    # The final-echo line should also use %VERSION%, not a hardcoded number.
    # Strip comment lines first — a `REM` line legitimately mentions the
    # fallback marker filename in human-readable form.
    code_only = "\n".join(
        line for line in src.splitlines()
        if not line.strip().lower().startswith("rem")
    )
    assert not re.search(r"OpenAVC-Setup-\d", code_only), (
        "build.bat shouldn't reference a literal version in any path/echo — "
        "use %VERSION% so the message tracks the actual build."
    )
