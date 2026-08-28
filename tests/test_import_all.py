"""Import-time smoke test: every app module must import cleanly.

Much of the app lives in one large import cycle that only resolves because
cross-module references are runtime-only. The most likely regression class
is therefore import-time breakage (a module-level reference into a sibling
that isn't fully initialized yet, or an import-time side effect that needs
the app's startup sequence). This test imports every module under core/ and
_app_scripts/ — without launching Tk, mpv, or the web server — so that
breakage fails fast in CI instead of at show time.
"""

import importlib
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _all_app_modules():
    modules = []
    for base in ("core", "_app_scripts"):
        for root, dirs, files in os.walk(os.path.join(REPO_ROOT, base)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fname in sorted(files):
                if not fname.endswith(".py"):
                    continue
                rel = os.path.relpath(os.path.join(root, fname), REPO_ROOT)
                mod = rel[:-3].replace(os.sep, ".")
                if mod.endswith(".__init__"):
                    mod = mod[: -len(".__init__")]
                modules.append(mod)
    return modules


@pytest.mark.parametrize("module_name", _all_app_modules())
def test_module_imports(module_name):
    importlib.import_module(module_name)
