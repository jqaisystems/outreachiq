import json
import os
import tempfile
import unittest
from unittest.mock import patch


class FavoriteLeadTests(unittest.TestCase):
    def test_favorite_route_adds_note_and_order(self):
        import server

        with tempfile.TemporaryDirectory() as tmp:
            prospects_path = os.path.join(tmp, "prospects.json")
            with open(prospects_path, "w", encoding="utf-8") as f:
                json.dump([
                    {
                        "id": "lead_1",
                        "name": "First Lead",
                        "status": "warm",
                        "priority": "warm",
                    },
                    {
                        "id": "lead_2",
                        "name": "Existing Favorite",
                        "status": "hot",
                        "priority": "hot",
                        "is_favorite": True,
                        "favorite_order": 3,
                        "favorited_at": "2026-05-01T10:00:00+00:00",
                    },
                ], f)

            with patch.object(server, "PROSPECTS_JSON", prospects_path), patch.object(server, "DATA_DIR", tmp):
                server.app.config["TESTING"] = True
                with server.app.test_client() as client:
                    response = client.post("/api/leads/lead_1/favorite", json={
                        "is_favorite": True,
                        "favorite_note": "Revise positioning before sending.",
                    })
                    self.assertEqual(response.status_code, 200)
                    payload = response.get_json()
                    self.assertEqual(payload["favorite_count"], 2)
                    self.assertTrue(payload["lead"]["is_favorite"])
                    self.assertEqual(payload["lead"]["favorite_note"], "Revise positioning before sending.")
                    self.assertEqual(payload["lead"]["favorite_order"], 4)

                    favorites = client.get("/api/favorites")
                    self.assertEqual(favorites.status_code, 200)
                    data = favorites.get_json()
                    self.assertEqual(data["count"], 2)
                    self.assertEqual(data["leads"][0]["id"], "lead_1")

    def test_favorite_route_removes_from_list_but_keeps_note(self):
        import server

        with tempfile.TemporaryDirectory() as tmp:
            prospects_path = os.path.join(tmp, "prospects.json")
            with open(prospects_path, "w", encoding="utf-8") as f:
                json.dump([{
                    "id": "lead_1",
                    "name": "Saved Lead",
                    "status": "drafted",
                    "priority": "warm",
                    "is_favorite": True,
                    "favorite_note": "Check later.",
                    "favorite_order": 1,
                    "favorited_at": "2026-05-01T10:00:00+00:00",
                }], f)

            with patch.object(server, "PROSPECTS_JSON", prospects_path), patch.object(server, "DATA_DIR", tmp):
                server.app.config["TESTING"] = True
                with server.app.test_client() as client:
                    response = client.post("/api/leads/lead_1/favorite", json={"is_favorite": False})
                    self.assertEqual(response.status_code, 200)
                    lead = response.get_json()["lead"]
                    self.assertFalse(lead["is_favorite"])
                    self.assertEqual(lead["favorite_note"], "Check later.")

                    favorites = client.get("/api/favorites")
                    self.assertEqual(favorites.get_json()["count"], 0)


if __name__ == "__main__":
    unittest.main()
