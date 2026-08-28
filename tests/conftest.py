"""Shared pytest setup: make the repo root importable.

The app is run from the repo root (guess_the_anime.py chdirs there), so all
imports are rooted at the repo. Tests must see the same layout regardless of
where pytest is invoked from.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
