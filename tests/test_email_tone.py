import json
import os
import tempfile
import unittest
from unittest.mock import patch

from email_tone import audit_email_tone, audit_many_email_tones
from email_repair import generated_variants, word_count


class EmailToneAuditTests(unittest.TestCase):
    def test_bad_greeting_and_word_count_are_flagged(self):
        body = "Hi The,\n\n" + " ".join(["Specific"] * 81) + "\n\nWorth a conversation?"
        audit = audit_email_tone({
            "id": "lead_1",
            "name": "The Lab Athletic Club",
            "email_variants": [{"label": "A", "body": body}],
        })
        codes = {flag["code"] for flag in audit["variant_checks"][0]["flags"]}
        self.assertEqual(audit["status"], "risky")
        self.assertIn("bad_greeting", codes)
        self.assertIn("over_80_words", codes)

    def test_banned_style_is_flagged(self):
        audit = audit_email_tone({
            "id": "lead_1",
            "name": "Acme",
            "decision_maker": "Sarah Chen",
            "email_variants": [{
                "label": "A",
                "body": "Hi Sarah,\n\nYour brand is weak, so I can help with a 15-minute call. See example.com.\n\nCan we schedule?",
            }],
        })
        codes = {flag["code"] for flag in audit["variant_checks"][0]["flags"]}
        self.assertEqual(audit["status"], "risky")
        self.assertIn("portfolio_in_body", codes)
        self.assertIn("hard_cta", codes)
        self.assertIn("diagnosis_language", codes)

    def test_credential_dump_is_flagged(self):
        audit = audit_email_tone({
            "id": "lead_1",
            "name": "Acme",
            "decision_maker": "Sarah Chen",
            "review_count": 12,
            "email_variants": [{
                "label": "A",
                "body": "Hi Sarah,\n\nAcme has 12 reviews in London. I have 12+ years, 1,200+ brands, and 40+ countries behind my work.\n\nWorth a conversation?",
            }],
        })
        codes = {flag["code"] for flag in audit["variant_checks"][0]["flags"]}
        self.assertEqual(audit["status"], "risky")
        self.assertIn("credential_dump", codes)

    def test_repair_generated_variants_include_contextual_intro(self):
        cases = [
            (
                {
                    "id": "finance",
                    "name": "Clear Wealth",
                    "industry": "finance",
                    "review_count": 12,
                    "city": "London",
                },
                "I'm Jo\u00e3o, a brand identity designer helping specialist firms sharpen perception.",
            ),
            (
                {
                    "id": "real_estate",
                    "name": "Prime Luxury Properties",
                    "industry": "real estate",
                    "review_count": 20,
                    "city": "Dubai",
                },
                "I'm Jo\u00e3o, a brand identity designer working with property and luxury firms.",
            ),
            (
                {
                    "id": "architecture",
                    "name": "Northline Architects",
                    "industry": "architecture",
                    "review_count": 8,
                    "city": "Zurich",
                },
                "I'm Jo\u00e3o, a brand identity designer for design-led and built-environment firms.",
            ),
            (
                {
                    "id": "agency",
                    "name": "Small Creative Studio",
                    "industry": "marketing",
                    "search_mode": "agency_partner",
                    "partner_lane": True,
                    "review_count": 5,
                    "city": "London",
                },
                "I'm Jo\u00e3o, a senior brand identity specialist available for overflow identity work.",
            ),
        ]

        for lead, intro in cases:
            with self.subTest(lead=lead["id"]):
                variants = generated_variants(lead)
                self.assertEqual(len(variants), 3)
                for variant in variants:
                    self.assertIn(intro, variant["body"])
                    # First sentence is about the prospect, never about the sender.
                    after_greeting = variant["body"].split("\n\n", 1)[1]
                    self.assertFalse(after_greeting.startswith("I'm Jo"))
                    self.assertLessEqual(word_count(variant["body"]), 80)
                audit = audit_email_tone({**lead, "email_variants": variants})
                severities = {f["severity"] for f in audit["flags"]}
                self.assertNotIn("risky", severities)
                # A generated fallback may carry the informational
                # review-count-only flag (it has no richer evidence to use),
                # but no fingerprint phrases, retired subjects, or artifacts.
                codes = {f["code"] for f in audit["flags"]}
                self.assertLessEqual(codes, {"review_count_only"})

    def test_repair_generated_variants_use_existing_human_hook(self):
        variants = generated_variants({
            "id": "studio_rotterdam",
            "name": "Studio Rotterdam",
            "decision_maker": "Federico Billeter",
            "industry": "architecture",
            "review_count": 2,
            "city": "Zurich",
            "email_variants": [{
                "label": "A",
                "body": "Hi Federico,\n\nStudio Rotterdam's 2 reviews and mix of architecture, interiors, scenography, furniture, and objects give it a distinctive creative range. I'm Jo\u00e3o, a brand identity designer for design-led and built-environment firms. A clearer identity could make that range feel intentional rather than broad.\n\nIs this on your radar?",
            }],
        })

        self.assertIn(
            "your work crosses architecture, interiors, scenography, furniture, and objects",
            variants[0]["body"],
        )
        self.assertTrue(variants[0]["body"].split("\n\n", 1)[1].startswith("At Studio Rotterdam"))
        self.assertIn("I'm Jo\u00e3o", variants[0]["body"])
        self.assertLessEqual(word_count(variants[0]["body"]), 80)

    def test_repair_generated_variants_ignore_self_referential_hooks(self):
        variants = generated_variants({
            "id": "fitness",
            "name": "The Lab Athletic Club",
            "industry": "sports",
            "niche": "Sports & Entertainment",
            "review_count": 395,
            "city": "Los Angeles",
            "email_variants": [{
                "label": "A",
                "body": "Hi team,\n\nI'm Jo\u00e3o, a brand identity designer helping specialist firms sharpen perception. The Lab Athletic Club caught my eye because i have helped established service brands turn a good reputation into a clearer visual identity, so the first.\n\nWith 395 reviews, there is already real trust behind it. A clearer identity could make that trust and energy easier to feel before someone visits.\n\nIs this something you've been thinking about?",
            }],
        })

        self.assertNotIn("i have helped", variants[0]["body"])
        self.assertIn("fitness clients judge energy, trust, and professionalism", variants[0]["body"])

    def test_repair_greeting_ignores_company_fragments(self):
        variants = generated_variants({
            "id": "design_studio",
            "name": "Design Studio VOID",
            "decision_maker": "Design",
            "industry": "design",
            "review_count": 3,
            "city": "Porto",
        })

        self.assertTrue(all(variant["body"].startswith("Hi team,") for variant in variants))

    def test_repair_greeting_ignores_space_fragment(self):
        variants = generated_variants({
            "id": "space_design",
            "name": "4Space Design",
            "decision_maker": "Space",
            "industry": "architecture",
            "review_count": 59,
            "city": "Dubai",
        })

        self.assertTrue(all(variant["body"].startswith("Hi team,") for variant in variants))
        self.assertNotIn("portfolio", variants[0]["body"].lower())

    def test_repeated_phrase_batch_is_flagged(self):
        leads = []
        for index in range(3):
            leads.append({
                "id": f"lead_{index}",
                "name": f"Company {index}",
                "review_count": 12,
                "email_variants": [{
                    "label": "A",
                    "body": f"Hi team,\n\nI came across Company {index} and noticed 12 reviews. That detail could anchor a stronger first impression.\n\nWorth a conversation?",
                }],
            })
        summary = audit_many_email_tones(leads)
        self.assertEqual(summary["counts"]["needs_review"], 3)
        self.assertTrue(any(flag["code"] == "repeated_phrase" for flag in summary["leads"][0]["flags"]))

    def test_ai_checker_does_not_flag_normal_words_with_ai_letters(self):
        audit = audit_email_tone({
            "id": "lead_1",
            "name": "Hotel Vitznauerhof",
            "priority": "cold",
            "industry": "hospitality",
            "review_count": 302,
            "email_variants": [{
                "label": "A",
                "body": "Hi team,\n\nHotel Vitznauerhof has 302 reviews and a strong guest email experience.\n\nWorth a conversation?",
            }],
        })
        codes = {flag["code"] for flag in audit["variant_checks"][0]["flags"]}
        self.assertNotIn("ai_overused", codes)
        self.assertNotIn("ai_needs_fit", codes)

    def test_email_import_adds_tone_audit(self):
        import server

        with tempfile.TemporaryDirectory() as tmp:
            prospects_path = os.path.join(tmp, "prospects.json")
            written_path = os.path.join(tmp, "written.json")
            with open(prospects_path, "w", encoding="utf-8") as f:
                json.dump([{
                    "id": "lead_1",
                    "name": "The Lab Athletic Club",
                    "status": "warm",
                    "priority": "warm",
                }], f)
            with open(written_path, "w", encoding="utf-8") as f:
                json.dump([{
                    "id": "lead_1",
                    "variants": [{
                        "label": "A",
                        "approach": "observation",
                        "subject": "Quick thought",
                        "body": "Hi The,\n\nThe Lab has 395 reviews in Los Angeles.\n\nWorth a conversation?",
                    }],
                }], f)

            with patch.object(server, "DATA_DIR", tmp), \
                    patch.object(server, "PROSPECTS_JSON", prospects_path), \
                    patch.object(server, "log_api_usage"):
                server.app.config["TESTING"] = True
                with server.app.test_client() as client:
                    response = client.post("/api/email/import")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.get_json()["tone"]["risky"], 1)

            with open(prospects_path, "r", encoding="utf-8") as f:
                prospects = json.load(f)
            audit = prospects[0]["tone_audit"]
            self.assertEqual(audit["status"], "risky")
            codes = {flag["code"] for flag in audit["variant_checks"][0]["flags"]}
            self.assertIn("bad_greeting", codes)

    def test_email_tone_audit_route_is_read_only_summary(self):
        import server

        fake_leads = [{
            "id": "lead_1",
            "name": "The Lab Athletic Club",
            "status": "drafted",
            "priority": "warm",
            "email_variants": [{
                "label": "A",
                "body": "Hi The,\n\nThe Lab has 395 reviews in Los Angeles.\n\nWorth a conversation?",
            }],
        }]

        with patch.object(server, "_load", return_value=fake_leads):
            server.app.config["TESTING"] = True
            with server.app.test_client() as client:
                response = client.get("/api/email/tone-audit")
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertEqual(payload["note"], "Local email tone audit, no API usage")
                self.assertEqual(payload["counts"]["risky"], 1)
                self.assertIn("common_flags", payload)

    def test_review_queue_returns_unsent_drafts_that_need_work(self):
        import server

        fake_leads = [
            {
                "id": "lead_1",
                "name": "The Lab Athletic Club",
                "status": "drafted",
                "priority": "warm",
                "score": 74,
                "email_variants": [{
                    "label": "A",
                    "body": "Hi The,\n\nThe Lab has 395 reviews in Los Angeles.\n\nWorth a conversation?",
                }],
            },
            {
                "id": "lead_2",
                "name": "Already Sent",
                "status": "sent",
                "priority": "warm",
                "email_variants": [{
                    "label": "A",
                    "body": "Hi team,\n\nAlready Sent has 20 reviews in Lisbon.\n\nWorth a conversation?",
                }],
            },
        ]

        with patch.object(server, "_load", return_value=fake_leads):
            server.app.config["TESTING"] = True
            with server.app.test_client() as client:
                response = client.get("/api/email/review-queue")
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertEqual(payload["note"], "Local review queue, no API usage")
                self.assertEqual(payload["count"], 1)
                self.assertEqual(payload["leads"][0]["id"], "lead_1")
                codes = {flag["code"] for flag in payload["leads"][0]["review_flags"]}
                self.assertIn("missing_contact_email", codes)
                self.assertIn("bad_greeting", codes)

                with_contacted = client.get("/api/email/review-queue?include_contacted=1")
                self.assertEqual(with_contacted.status_code, 200)
                self.assertEqual(with_contacted.get_json()["count"], 2)

    def test_repair_export_writes_focused_to_write_payload(self):
        import server

        with tempfile.TemporaryDirectory() as tmp:
            prospects_path = os.path.join(tmp, "prospects.json")
            with open(prospects_path, "w", encoding="utf-8") as f:
                json.dump([{
                    "id": "lead_1",
                    "name": "The Lab Athletic Club",
                    "status": "drafted",
                    "priority": "warm",
                    "email_variants": [
                        {
                            "label": "A",
                            "approach": "observation",
                            "subject": "Quick thought",
                            "body": "Hi team,\n\nThe Lab has 395 reviews in Los Angeles.\n\nWorth a conversation?",
                        },
                        {
                            "label": "B",
                            "approach": "peer",
                            "subject": "A similar brand",
                            "body": "Hi The,\n\nThe Lab has 395 reviews in Los Angeles and AI tools can help.\n\nWorth a conversation?",
                        },
                    ],
                }], f)

            with patch.object(server, "DATA_DIR", tmp), patch.object(server, "PROSPECTS_JSON", prospects_path):
                server.app.config["TESTING"] = True
                with server.app.test_client() as client:
                    response = client.post("/api/email/repair-export", json={
                        "id": "lead_1",
                        "variant_index": 1,
                        "action": "fix_greeting",
                    })
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.get_json()["note"], "Local repair export, no API usage")

                    invalid = client.post("/api/email/repair-export", json={
                        "id": "lead_1",
                        "variant_index": 1,
                        "action": "unknown",
                    })
                    self.assertEqual(invalid.status_code, 400)

            with open(os.path.join(tmp, "to_write.json"), "r", encoding="utf-8") as f:
                payload = json.load(f)
            self.assertEqual(len(payload), 1)
            item = payload[0]
            self.assertTrue(item["repair_mode"])
            self.assertEqual(item["repair_action"], "fix_greeting")
            self.assertEqual(item["repair_variant_index"], 1)
            self.assertEqual(item["repair_variant"]["label"], "B")
            self.assertEqual(len(item["existing_variants"]), 2)
            self.assertIn("repair_output_contract", item)

    def test_send_gate_blocks_missing_email_and_bad_greeting(self):
        import server

        fake_leads = [{
            "id": "lead_1",
            "name": "The Lab Athletic Club",
            "status": "drafted",
            "priority": "warm",
            "email_variants": [{
                "label": "A",
                "body": "Hi The,\n\nThe Lab has 395 reviews in Los Angeles.\n\nWorth a conversation?",
            }],
        }]

        with patch.object(server, "_load", return_value=fake_leads):
            server.app.config["TESTING"] = True
            with server.app.test_client() as client:
                response = client.post("/api/email/send-gate", json={
                    "id": "lead_1",
                    "variant_index": 0,
                    "action": "gmail",
                })
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertFalse(payload["allowed"])
                codes = {flag["code"] for flag in payload["blocks"]}
                self.assertIn("missing_contact_email", codes)
                self.assertIn("bad_greeting", codes)
                self.assertEqual(payload["note"], "Local send gate, no API usage")

    def test_send_gate_warns_for_duplicate_previously_used_email(self):
        import server

        fake_leads = [
            {
                "id": "lead_1",
                "name": "New Lead",
                "status": "drafted",
                "priority": "warm",
                "contact_email": "hello@example.com",
                "linkedin_profiles": [{"name": "Sarah Chen", "url": "https://linkedin.com/in/sarah"}],
                "email_variants": [{
                    "label": "A",
                    "body": "Hi team,\n\nNew Lead has 22 reviews in Lisbon.\n\nWorth a conversation?",
                }],
            },
            {
                "id": "lead_2",
                "name": "Already Contacted",
                "status": "sent",
                "priority": "warm",
                "contact_email": "hello@example.com",
            },
        ]

        with patch.object(server, "_load", return_value=fake_leads):
            server.app.config["TESTING"] = True
            with server.app.test_client() as client:
                response = client.post("/api/email/send-gate", json={
                    "id": "lead_1",
                    "variant_index": 0,
                    "action": "copy",
                })
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertTrue(payload["allowed"])
                self.assertTrue(payload["requires_override"])
                codes = {flag["code"] for flag in payload["warnings"]}
                self.assertIn("duplicate_contact_email", codes)

    def test_outcome_endpoint_records_prepared_sent_and_reply(self):
        import server

        with tempfile.TemporaryDirectory() as tmp:
            prospects_path = os.path.join(tmp, "prospects.json")
            with open(prospects_path, "w", encoding="utf-8") as f:
                json.dump([{
                    "id": "lead_1",
                    "name": "Outcome Lead",
                    "status": "drafted",
                    "priority": "warm",
                    "contact_email": "hello@example.com",
                    "email_variants": [
                        {
                            "label": "A",
                            "approach": "observation",
                            "subject": "Variant A",
                            "body": "Hi team,\n\nOutcome Lead has 24 reviews in Porto.\n\nWorth a conversation?",
                        },
                        {
                            "label": "B",
                            "approach": "peer",
                            "subject": "Variant B",
                            "body": "Hi team,\n\nOutcome Lead has 24 reviews in Porto.\n\nIs this on your radar?",
                        },
                    ],
                }], f)

            with patch.object(server, "PROSPECTS_JSON", prospects_path), patch.object(server, "DATA_DIR", tmp):
                server.app.config["TESTING"] = True
                with server.app.test_client() as client:
                    prepared = client.post("/api/email/outcome", json={
                        "id": "lead_1",
                        "event": "prepared",
                        "variant_index": 1,
                        "channel": "gmail",
                    })
                    self.assertEqual(prepared.status_code, 200)
                    self.assertEqual(prepared.get_json()["lead"]["last_send_variant_label"], "B")

                    sent = client.post("/api/email/outcome", json={
                        "id": "lead_1",
                        "event": "sent",
                        "variant_index": 1,
                        "channel": "gmail",
                    })
                    self.assertEqual(sent.status_code, 200)
                    sent_lead = sent.get_json()["lead"]
                    self.assertEqual(sent_lead["status"], "sent")
                    self.assertEqual(sent_lead["variant_sent_label"], "B")
                    self.assertEqual(sent_lead["send_channel"], "gmail")

                    replied = client.post("/api/email/outcome", json={
                        "id": "lead_1",
                        "event": "reply",
                        "reply_type": "positive",
                        "reply_notes": "Asked for examples.",
                    })
                    self.assertEqual(replied.status_code, 200)
                    reply_lead = replied.get_json()["lead"]
                    self.assertEqual(reply_lead["status"], "replied")
                    self.assertEqual(reply_lead["reply_type"], "positive")
                    self.assertEqual(reply_lead["reply_notes"], "Asked for examples.")

    def test_update_status_can_undo_sent_and_clear_sent_metadata(self):
        import server

        with tempfile.TemporaryDirectory() as tmp:
            prospects_path = os.path.join(tmp, "prospects.json")
            with open(prospects_path, "w", encoding="utf-8") as f:
                json.dump([{
                    "id": "lead_undo",
                    "name": "Undo Lead",
                    "status": "sent",
                    "date_sent": "2026-05-11",
                    "variant_sent_index": 1,
                    "variant_sent_label": "B",
                    "variant_sent_approach": "peer",
                    "variant_sent_subject": "Subject",
                    "send_channel": "gmail",
                    "sent_recorded_at": "2026-05-11T12:00:00+00:00",
                }], f)

            with patch.object(server, "PROSPECTS_JSON", prospects_path), patch.object(server, "DATA_DIR", tmp):
                server.app.config["TESTING"] = True
                with server.app.test_client() as client:
                    response = client.post("/api/update-status", json={
                        "id": "lead_undo",
                        "status": "drafted",
                        "clear_sent": True,
                    })
                    self.assertEqual(response.status_code, 200)
                    saved = response.get_json()["lead"]
                    self.assertEqual(saved["status"], "drafted")
                    self.assertIsNone(saved["date_sent"])
                    self.assertIsNone(saved["variant_sent_index"])
                    self.assertEqual(saved["variant_sent_label"], "")
                    self.assertEqual(saved["send_channel"], "")

    def test_bulk_repair_writes_written_json_for_unsent_review_drafts(self):
        import server

        with tempfile.TemporaryDirectory() as tmp:
            prospects_path = os.path.join(tmp, "prospects.json")
            with open(prospects_path, "w", encoding="utf-8") as f:
                json.dump([
                    {
                        "id": "lead_1",
                        "name": "Hotel Vitznauerhof",
                        "status": "drafted",
                        "priority": "warm",
                        "review_count": 302,
                        "city": "Vitznau",
                        "industry": "hospitality",
                        "email_variants": [{
                            "label": "A",
                            "approach": "observation",
                            "subject": "Quick thought",
                            "body": "Hi Hotel,\n\nI came across Hotel Vitznauerhof and noticed 302 reviews. I help with AI tools.\n\nWorth a conversation?",
                        }],
                    },
                    {
                        "id": "lead_2",
                        "name": "Already Sent",
                        "status": "sent",
                        "priority": "warm",
                        "review_count": 20,
                        "city": "Porto",
                        "email_variants": [{
                            "label": "A",
                            "body": "Hi team,\n\nAlready Sent has 20 reviews in Porto.\n\nWorth a conversation?",
                        }],
                    },
                ], f)

            with patch.object(server, "PROSPECTS_JSON", prospects_path), patch.object(server, "DATA_DIR", tmp):
                server.app.config["TESTING"] = True
                with server.app.test_client() as client:
                    response = client.post("/api/email/bulk-repair", json={})
                    self.assertEqual(response.status_code, 200)
                    payload = response.get_json()
                    self.assertEqual(payload["note"], "Local bulk repair, no API usage. Click Import Emails to apply.")
                    self.assertEqual(payload["count"], 1)

            with open(os.path.join(tmp, "written.json"), "r", encoding="utf-8") as f:
                written = json.load(f)
            self.assertEqual(len(written), 1)
            self.assertEqual(written[0]["id"], "lead_1")
            self.assertEqual(len(written[0]["variants"]), 3)
            self.assertTrue(written[0]["variants"][0]["body"].startswith("Hi team,"))
            self.assertNotIn("AI tools", written[0]["variants"][0]["body"])


if __name__ == "__main__":
    unittest.main()
