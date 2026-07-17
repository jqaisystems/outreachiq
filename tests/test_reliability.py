import json
import os
import tempfile
import unittest
from unittest.mock import patch


class ScoreImportStatusGuardTests(unittest.TestCase):
    """Re-importing scores must never downgrade a progressed lead (Part 1a)."""

    def _run_import(self, tmp, leads, scored):
        import server
        prospects_path = os.path.join(tmp, "prospects.json")
        scored_path = os.path.join(tmp, "scored.json")
        with open(prospects_path, "w", encoding="utf-8") as f:
            json.dump(leads, f)
        # The endpoint reads scored.json from DATA_DIR directly.
        with open(scored_path, "w", encoding="utf-8") as f:
            json.dump(scored, f)

        with patch.object(server, "PROSPECTS_JSON", prospects_path), \
             patch.object(server, "DATA_DIR", tmp), \
             patch.object(server, "BACKUPS_DIR", os.path.join(tmp, "backups")):
            server.app.config["TESTING"] = True
            with server.app.test_client() as client:
                resp = client.post("/api/import-scores", json={})
                self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
            with open(prospects_path, encoding="utf-8") as f:
                return {p["id"]: p for p in json.load(f)}

    def test_sent_lead_status_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            leads = [
                {"id": "a", "name": "Sent Lead", "status": "sent", "priority": "warm"},
                {"id": "b", "name": "Replied Lead", "status": "replied", "priority": "hot"},
                {"id": "c", "name": "Fresh Lead", "status": "unscored", "priority": ""},
            ]
            scored = [
                {"id": "a", "score": 50, "priority": "cold"},
                {"id": "b", "score": 90, "priority": "hot"},
                {"id": "c", "score": 85, "priority": "hot"},
            ]
            by_id = self._run_import(tmp, leads, scored)
            # Progressed leads keep their lifecycle status...
            self.assertEqual(by_id["a"]["status"], "sent")
            self.assertEqual(by_id["b"]["status"], "replied")
            # ...but their score/priority still update.
            self.assertEqual(by_id["a"]["score"], 50)
            self.assertEqual(by_id["a"]["priority"], "cold")
            # A not-yet-progressed lead does take the new status.
            self.assertEqual(by_id["c"]["status"], "hot")


class AtomicSaveTests(unittest.TestCase):
    """_save() must not corrupt prospects.json if the write fails mid-way (Part 1b)."""

    def test_failed_write_leaves_previous_file_intact(self):
        import server
        with tempfile.TemporaryDirectory() as tmp:
            prospects_path = os.path.join(tmp, "prospects.json")
            good = [{"id": "x", "name": "Good"}]
            with open(prospects_path, "w", encoding="utf-8") as f:
                json.dump(good, f)

            with patch.object(server, "PROSPECTS_JSON", prospects_path), \
                 patch.object(server, "DATA_DIR", tmp), \
                 patch.object(server, "BACKUPS_DIR", os.path.join(tmp, "backups")):
                # Simulate a crash during serialization.
                with patch("server.json.dump", side_effect=RuntimeError("boom")):
                    with self.assertRaises(RuntimeError):
                        server._save([{"id": "y", "name": "Partial"}])

                # The original file must still be valid and unchanged.
                with open(prospects_path, encoding="utf-8") as f:
                    data = json.load(f)
                self.assertEqual(data, good)
                # No stray temp file left behind in a readable state.
                tmp_matches_good = False
                if os.path.exists(prospects_path + ".tmp"):
                    with open(prospects_path + ".tmp", encoding="utf-8") as tmp_f:
                        tmp_matches_good = json.loads(tmp_f.read() or "null") == good
                self.assertFalse(tmp_matches_good)


if __name__ == "__main__":
    unittest.main()
