import json
import os
import tempfile
import unittest
from unittest.mock import patch


class ProspectingUpgradeTests(unittest.TestCase):
    def test_google_places_search_paginates_requested_limits(self):
        from sources import google_places

        def make_place(index):
            return {
                "id": f"place-{index}",
                "displayName": {"text": f"Place {index}"},
                "formattedAddress": "1 Example Street, London, UK",
                "addressComponents": [
                    {"types": ["locality"], "longText": "London"},
                    {"types": ["country"], "longText": "United Kingdom"},
                ],
                "businessStatus": "OPERATIONAL",
            }

        self.assertIn("nextPageToken", google_places._FIELD_MASK)

        for requested, expected_page_sizes in (
            (5, [5]),
            (10, [10]),
            (20, [20]),
            (40, [20, 20]),
            (60, [20, 20, 20]),
        ):
            with self.subTest(limit=requested):
                page_sizes = []
                next_index = 0

                def fake_fetch(query, page_size, page_token):
                    nonlocal next_index
                    page_sizes.append(page_size)
                    start = next_index
                    next_index += page_size
                    payload = {
                        "places": [make_place(i) for i in range(start, next_index)]
                    }
                    if next_index < requested:
                        payload["nextPageToken"] = f"token-{next_index}"
                    return payload

                with patch.object(google_places, "GOOGLE_PLACES_API_KEY", "test-key"), \
                    patch.object(google_places, "_fetch_page", side_effect=fake_fetch):
                    results = google_places.search(
                        query="wealth management",
                        location="London, UK",
                        industry="finance",
                        limit=requested,
                    )

                self.assertEqual(len(results), requested)
                self.assertEqual(page_sizes, expected_page_sizes)

    def test_recommendations_endpoint_includes_monthly_refresh(self):
        import server

        with patch.object(server, "_load", return_value=[]):
            server.app.config["TESTING"] = True
            with server.app.test_client() as client:
                res = client.get("/api/prospecting/recommendations")

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("recommendations", data)
        self.assertIn("monthly_refresh", data)
        self.assertIn("service_mixes", data)
        self.assertEqual(data["services"][0]["key"], "branding")
        self.assertEqual(data["service_mixes"][0]["key"], "smart_mix")

    @patch("sources.google_places.search")
    @patch("server.enrich_lead")
    def test_search_endpoint_forwards_selected_result_limits(self, enrich, gp_search):
        import server

        gp_search.return_value = []
        enrich.side_effect = lambda lead: lead

        with tempfile.TemporaryDirectory() as tmp:
            prospects_path = os.path.join(tmp, "prospects.json")
            with open(prospects_path, "w", encoding="utf-8") as f:
                json.dump([], f)

            with patch.object(server, "DATA_DIR", tmp), patch.object(server, "PROSPECTS_JSON", prospects_path):
                server.app.config["TESTING"] = True
                with server.app.test_client() as client:
                    for selected in (5, 10, 20, 40, 60):
                        with self.subTest(limit=selected):
                            gp_search.reset_mock()
                            res = client.post("/api/search", json={
                                "industry": "finance",
                                "location": "London, UK",
                                "limit": selected,
                            })
                            self.assertEqual(res.status_code, 200)
                            self.assertEqual(gp_search.call_args.kwargs["limit"], selected)

    @patch("sources.google_places.search")
    @patch("server.enrich_lead")
    def test_agency_partner_search_adds_context_and_filters_motion(self, enrich, gp_search):
        import server

        gp_search.return_value = [
            {
                "id": "agency-1",
                "name": "Northstar Brand Studio",
                "industry": "agency",
                "niche": "Marketing & Design Agencies",
                "region": "UK",
                "city": "London",
                "country": "United Kingdom",
                "website": "https://northstar.example",
                "review_count": 12,
                "rating": 4.8,
            },
            {
                "id": "motion-1",
                "name": "Peak Motion Graphics",
                "industry": "agency",
                "niche": "Marketing & Design Agencies",
                "region": "UK",
                "city": "London",
                "country": "United Kingdom",
                "website": "https://motion.example",
                "review_count": 5,
                "rating": 4.6,
            },
        ]
        enrich.side_effect = lambda lead: lead

        with tempfile.TemporaryDirectory() as tmp:
            prospects_path = os.path.join(tmp, "prospects.json")
            with open(prospects_path, "w", encoding="utf-8") as f:
                json.dump([], f)

            with patch.object(server, "DATA_DIR", tmp), patch.object(server, "PROSPECTS_JSON", prospects_path):
                server.app.config["TESTING"] = True
                with server.app.test_client() as client:
                    res = client.post("/api/search", json={
                        "service_focus": "branding",
                        "search_mode": "agency_partner",
                        "market_preset": "premium_global",
                        "industry": "agency",
                        "location": "London, UK",
                        "limit": 10,
                        "exclude_motion": True,
                    })

            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["added"], 1)
            self.assertEqual(data["filtered_motion"], 1)

            with open(prospects_path, "r", encoding="utf-8") as f:
                prospects = json.load(f)

        self.assertEqual(len(prospects), 1)
        self.assertEqual(prospects[0]["search_mode"], "agency_partner")
        self.assertTrue(prospects[0]["partner_lane"])
        self.assertEqual(prospects[0]["service_focus"], "branding")
        self.assertEqual(prospects[0]["service_mix"], "smart_mix")
        self.assertEqual(prospects[0]["primary_service"], "branding")
        self.assertEqual(prospects[0]["secondary_services"], ["web_design"])
        self.assertEqual(prospects[0]["outreach_angle"], "Agency overflow support for identity and web design.")

    @patch("sources.google_places.search")
    @patch("server.enrich_lead")
    def test_smart_mix_direct_construction_adds_web_and_print_support(self, enrich, gp_search):
        import server

        gp_search.return_value = [
            {
                "id": "builder-1",
                "name": "Foundry Custom Homes",
                "industry": "construction",
                "niche": "Construction",
                "region": "Texas",
                "city": "Austin",
                "country": "USA",
                "website": "https://foundry.example",
                "review_count": 4,
                "rating": 4.7,
            },
        ]
        enrich.side_effect = lambda lead: lead

        with tempfile.TemporaryDirectory() as tmp:
            prospects_path = os.path.join(tmp, "prospects.json")
            with open(prospects_path, "w", encoding="utf-8") as f:
                json.dump([], f)

            with patch.object(server, "DATA_DIR", tmp), patch.object(server, "PROSPECTS_JSON", prospects_path):
                server.app.config["TESTING"] = True
                with server.app.test_client() as client:
                    res = client.post("/api/search", json={
                        "service_focus": "branding",
                        "service_mix": "smart_mix",
                        "search_mode": "direct_client",
                        "market_preset": "premium_global",
                        "industry": "construction",
                        "location": "Austin, USA",
                        "limit": 5,
                    })

            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["secondary_services"], ["web_design", "editorial_print"])
            self.assertEqual(data["service_mix"], "smart_mix")

            with open(prospects_path, "r", encoding="utf-8") as f:
                prospects = json.load(f)

        self.assertEqual(prospects[0]["primary_service"], "branding")
        self.assertEqual(prospects[0]["secondary_services"], ["web_design", "editorial_print"])
        self.assertEqual(
            prospects[0]["outreach_angle"],
            "Brand identity with supporting website and proposal materials.",
        )

    def test_score_export_includes_partner_scoring_context(self):
        import server

        lead = {
            "id": "agency-1",
            "name": "Northstar Brand Studio",
            "industry": "agency",
            "niche": "Marketing & Design Agencies",
            "city": "London",
            "country": "United Kingdom",
            "region": "UK",
            "website": "https://northstar.example",
            "status": "unscored",
            "score": 0,
            "search_mode": "agency_partner",
            "service_focus": "branding",
            "partner_lane": True,
            "rating": 4.8,
            "review_count": 12,
        }

        with tempfile.TemporaryDirectory() as tmp:
            prospects_path = os.path.join(tmp, "prospects.json")
            with open(prospects_path, "w", encoding="utf-8") as f:
                json.dump([lead], f)

            with patch.object(server, "DATA_DIR", tmp), patch.object(server, "PROSPECTS_JSON", prospects_path):
                server.app.config["TESTING"] = True
                with server.app.test_client() as client:
                    res = client.post("/api/score/export")

                with open(os.path.join(tmp, "to_score.json"), "r", encoding="utf-8") as f:
                    exported = json.load(f)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(exported[0]["search_mode"], "agency_partner")
        self.assertEqual(exported[0]["service_mix"], "smart_mix")
        self.assertEqual(exported[0]["secondary_services"], ["web_design"])
        self.assertIn("service_guidance", exported[0])
        self.assertIn("overflow", exported[0]["scoring_context"])

    def test_email_export_includes_smart_mix_context(self):
        import server

        lead = {
            "id": "builder-1",
            "name": "Foundry Custom Homes",
            "industry": "construction",
            "niche": "Construction",
            "city": "Austin",
            "country": "USA",
            "region": "Texas",
            "website": "https://foundry.example",
            "status": "warm",
            "score": 68,
            "priority": "warm",
            "search_mode": "direct_client",
            "service_focus": "branding",
            "service_mix": "smart_mix",
            "search_query": "custom home builder property developer construction company",
            "rating": 4.7,
            "review_count": 4,
        }

        with tempfile.TemporaryDirectory() as tmp:
            prospects_path = os.path.join(tmp, "prospects.json")
            with open(prospects_path, "w", encoding="utf-8") as f:
                json.dump([lead], f)

            with patch.object(server, "DATA_DIR", tmp), patch.object(server, "PROSPECTS_JSON", prospects_path):
                server.app.config["TESTING"] = True
                with server.app.test_client() as client:
                    res = client.post("/api/email/export")

                with open(os.path.join(tmp, "to_write.json"), "r", encoding="utf-8") as f:
                    exported = json.load(f)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(exported[0]["service_mix"], "smart_mix")
        self.assertEqual(exported[0]["primary_service"], "branding")
        self.assertEqual(exported[0]["secondary_services"], ["web_design", "editorial_print"])
        self.assertIn("at most one supporting service", exported[0]["service_guidance"])
        self.assertEqual(
            exported[0]["outreach_angle"],
            "Brand identity with supporting website and proposal materials.",
        )


if __name__ == "__main__":
    unittest.main()
