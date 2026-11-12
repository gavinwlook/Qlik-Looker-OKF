import unittest
from enterprise_qlik.stage1_extract.sanitizer import SecuritySanitizer

class TestSecuritySanitizer(unittest.TestCase):
    def setUp(self):
        self.sanitizer = SecuritySanitizer(mask_emails=True, mask_ips=True)

    def test_redact_credit_cards(self):
        text = "Customer card is 4532-1234-5678-9012 for billing."
        clean = self.sanitizer.sanitize(text)
        self.assertIn("[REDACTED_CARD_...9012]", clean)
        self.assertNotIn("4532-1234-5678-9012", clean)

    def test_redact_ssn(self):
        text = "Taxpayer SSN: 123-45-6789 verified."
        clean = self.sanitizer.sanitize(text)
        self.assertIn("[REDACTED_SSN]", clean)
        self.assertNotIn("123-45-6789", clean)

    def test_redact_email(self):
        text = "Send reports to finance-lead@acme-corp.com on Monday."
        clean = self.sanitizer.sanitize(text)
        self.assertIn("[REDACTED_EMAIL]", clean)
        self.assertNotIn("finance-lead@acme-corp.com", clean)

    def test_redact_secrets_and_passwords(self):
        text = "CONNECT TO db; password='SuperSecretPassword123!';"
        clean = self.sanitizer.sanitize(text)
        self.assertIn("[REDACTED_PASSWORD]", clean)
        self.assertNotIn("SuperSecretPassword123!", clean)

    def test_nested_dictionary_sanitization(self):
        payload = {
            "app": "Finance App",
            "creditcard": "9999888877776666",
            "meta": {
                "admin_email": "admin@bank.corp",
                "notes": "Token: Bearer abcd1234efgh5678ijklmnop"
            }
        }
        clean = self.sanitizer.sanitize(payload)
        self.assertEqual(clean["creditcard"], "[REDACTED_SENSITIVE_FIELD]")
        self.assertIn("[REDACTED_EMAIL]", clean["meta"]["admin_email"])
        self.assertIn("[REDACTED_SECRET]", clean["meta"]["notes"])

if __name__ == "__main__":
    unittest.main()
