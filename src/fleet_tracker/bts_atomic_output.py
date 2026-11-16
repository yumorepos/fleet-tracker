"""Safely publish small aggregate research JSON files without overwriting.

A temporary file is written, flushed, and atomically hard-linked into its
final name. This requires the temporary and destination files to share a
filesystem. FileExistsError is propagated when another writer wins a race.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


def write_json_new(output: Path, payload: dict) -> None:
    """Create a complete JSON report or fail without touching an existing file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".bts-report-", suffix=".json",
                                     dir=output.parent)
    temporary = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic no-clobber publication; os.replace() would violate the
        # promised refusal to overwrite when a competing writer races us.
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
