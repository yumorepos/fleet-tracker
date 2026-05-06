"""Hash check guarding the pristine retrofit module copy.

src/fleet_tracker/classify/retrofit.py is a verbatim copy of the upstream
fleet-retrofit-tracker desktop snapshot. If anyone edits it (intentionally
or accidentally), this test fails loudly so the change gets caught at
review time rather than silently drifting from upstream.

If you intended to update the file (because upstream itself moved), also
update RETROFIT_SHA256 below to match the new content.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# Captured from the 2026-05-05 desktop snapshot copy.
# When upstream moves and you re-sync, recompute with:
#   shasum -a 256 src/fleet_tracker/classify/retrofit.py
RETROFIT_SHA256 = "0eac87ea4546e4f88b61a9df17b333c24c3ec2181c819e157c9464c805935b9c"


def _retrofit_path() -> Path:
    return Path(__file__).parent.parent / "src" / "fleet_tracker" / "classify" / "retrofit.py"


def test_retrofit_module_is_pristine():
    path = _retrofit_path()
    assert path.exists(), f"retrofit.py not found at {path}"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == RETROFIT_SHA256, (
        f"retrofit.py has been modified. SHA256 is {digest}, expected {RETROFIT_SHA256}.\n"
        "This file is a pristine copy of the upstream fleet-retrofit-tracker snapshot.\n"
        "If you intentionally re-synced from upstream, update RETROFIT_SHA256 in this test.\n"
        "Otherwise, revert your changes; edits belong upstream, not in this copy.\n"
        "See docs/DESIGN.md §3."
    )
