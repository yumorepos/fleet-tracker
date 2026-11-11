"""Disabled collector workflow must remain inert until explicitly approved."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/".github/workflows/nightly-collection.yml"

class DisabledCollectionContract(unittest.TestCase):
    def test_workflow_is_manual_only_read_only_and_noop(self):
        content=WORKFLOW.read_text(encoding="utf-8")
        active="\n".join(line for line in content.splitlines()
                         if line.strip() and not line.lstrip().startswith("#"))
        self.assertIn("workflow_dispatch:",active)
        self.assertIn("contents: read",active)
        self.assertIn("No scheduled fleet collection is configured.",active)
        for forbidden in ("schedule:", "push:", "contents: write",
                          "OPENSKY_", "git push", "secrets.", "uv run"):
            self.assertNotIn(forbidden,active,forbidden)

    def test_source_audit_documentation_distinguishes_current_and_historic_status(self):
        kpi=(ROOT/"docs/BTS_DELTA_PILOT_2025_RESULTS.md").read_text()
        tail=(ROOT/"docs/BTS_TAIL_SEQUENCE_2025_RESULTS.md").read_text()
        for doc in (kpi,tail):
            self.assertIn("https://github.com/yumorepos/fleet-tracker/pull/11",doc)
            self.assertIn("https://yumorepos.github.io/airline-operations.html",doc)
        self.assertIn("current status",kpi.lower())
        self.assertIn("current source status",tail.lower())
        self.assertIn("historical",tail.lower())

if __name__=="__main__":
    unittest.main()
