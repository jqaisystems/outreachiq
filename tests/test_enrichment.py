import unittest
import json
import os
import tempfile
from unittest.mock import Mock, patch

from enrich.audit import audit_lead, is_valid_email
from sources.firecrawl import _real_emails


class EnrichmentAuditTests(unittest.TestCase):
    def test_email_filter_rejects_image_false_positive(self):
        self.assertTrue(is_valid_email("hello@example.co"))
        self.assertFalse(is_valid_email("ed-drummond-1536x1536@2x-1024x863.jpg"))
        md = "Reach us at hello@example.co and ignore ed-drummond-1536x1536@2x-1024x863.jpg"
        self.assertEqual(_real_emails(md), ["hello@example.co"])

    def test_audit_reports_missing_decision_maker_and_linkedin(self):
        audit = audit_lead({
            "id": "1",
            "website": "https://example.com",
            "website_summary": "Example company",
            "contact_email": "hello@example.com",
            "contact_candidates": [{"email": "hello@example.com"}],
            "apollo_linkedin_url": "https://linkedin.com/company/example",
            "linkedin_candidates": [{"kind": "company", "url": "https://linkedin.com/company/example"}],
        })
        self.assertEqual(audit["status"], "partial")
        self.assertIn("decision_maker", audit["missing_fields"])
        self.assertIn("person_linkedin", audit["missing_fields"])


class ApolloClientTests(unittest.TestCase):
    @patch("sources.apollo.APOLLO_API_KEY", "key")
    @patch("sources.apollo.log_api_usage")
    @patch("sources.apollo.requests.post")
    def test_organization_enrich_maps_core_fields(self, post, _log):
        from sources.apollo import enrich_organization

        response = Mock()
        response.json.return_value = {
            "organization": {
                "id": "org_1",
                "estimated_num_employees": 12,
                "industry": "real estate",
                "founded_year": 2024,
                "annual_revenue_printed": "$1M-$10M",
                "keywords": ["luxury", "brokerage"],
                "linkedin_url": "https://linkedin.com/company/acme",
            }
        }
        response.raise_for_status.return_value = None
        post.return_value = response

        result = enrich_organization("https://acme.com", lead_id="lead_1")
        self.assertEqual(result["company_size"], 12)
        self.assertEqual(result["apollo_linkedin_url"], "https://linkedin.com/company/acme")
        self.assertEqual(result["apollo_keywords"], ["luxury", "brokerage"])
        self.assertIn("apollo_organization_raw", result)

    @patch("sources.apollo.APOLLO_API_KEY", "key")
    @patch("sources.apollo.log_api_usage")
    @patch("sources.apollo.requests.post")
    def test_people_enrich_skips_without_identifiers(self, post, _log):
        from sources.apollo import enrich_person

        result = enrich_person(website="https://acme.com", lead_id="lead_1")
        self.assertEqual(result, {})
        post.assert_not_called()


class SnapshotRouteTests(unittest.TestCase):
    def test_snapshot_routes_only_expose_referenced_local_files(self):
        import server

        with tempfile.TemporaryDirectory() as tmp:
            enrichment_dir = os.path.join(tmp, "enrichment")
            lead_dir = os.path.join(enrichment_dir, "lead_1")
            os.makedirs(lead_dir)
            snapshot_path = os.path.join(lead_dir, "snap_firecrawl.json")
            outside_path = os.path.join(tmp, "outside.json")
            payload = {
                "timestamp": "2026-05-08T00:00:00+00:00",
                "lead_id": "lead_1",
                "provider": "firecrawl",
                "endpoint": "scrape",
                "request_ref": "https://example.com",
                "normalized": {"website_summary": "Hello"},
            }
            with open(snapshot_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            with open(outside_path, "w", encoding="utf-8") as f:
                json.dump({"provider": "outside"}, f)

            fake_leads = [{
                "id": "lead_1",
                "name": "Lead 1",
                "enrichment_snapshot_refs": [snapshot_path, outside_path],
            }]

            with patch.object(server, "ENRICHMENT_DIR", enrichment_dir), patch.object(server, "_load", return_value=fake_leads):
                server.app.config["TESTING"] = True
                with server.app.test_client() as client:
                    listed = client.get("/api/enrichment/snapshots/lead_1")
                    self.assertEqual(listed.status_code, 200)
                    snapshots = listed.get_json()["snapshots"]
                    self.assertEqual(len(snapshots), 1)
                    self.assertEqual(snapshots[0]["id"], "snap_firecrawl.json")

                    detail = client.get("/api/enrichment/snapshots/lead_1/snap_firecrawl.json")
                    self.assertEqual(detail.status_code, 200)
                    self.assertEqual(detail.get_json()["snapshot"]["provider"], "firecrawl")

                    unknown = client.get("/api/enrichment/snapshots/lead_1/outside.json")
                    self.assertEqual(unknown.status_code, 404)


if __name__ == "__main__":
    unittest.main()
