"""
Security & PII Sanitizer for Qlik Metadata Extraction
=====================================================
Performs automated redaction of sensitive personal data, customer identifiers,
and infrastructure secrets from Qlik metadata trees, expressions, and load scripts.
Designed for Tier-1 regulated environments (Banking, Insurance, Telecom).
Zero external dependencies (Standard Library only).
"""

import re
from typing import Any, Dict, List, Set


class SecuritySanitizer:
    """Recursively scans and redacts PII and secrets from Qlik metadata payloads."""

    PATTERNS = {
        "CREDIT_CARD": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
        "IBAN": re.compile(r"\b[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{7}([A-Z0-9]?){0,16}\b"),
        "SSN_US": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b"),
        "IPV4": re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"),
        "BEARER_TOKEN": re.compile(r"(?i)\b(?:bearer|token|api_?key|secret)[\s:=]+['\"]?([A-Za-z0-9_\-\.]{20,})['\"]?"),
        "CONNECTION_PASSWORD": re.compile(r"(?i)(?:password|pwd)[\s:=]+['\"]?([^;'\"]+)['\"]?"),
    }

    SENSITIVE_FIELD_NAMES: Set[str] = {
        "ssn", "socialsecurity", "creditcard", "cardnumber", "cvv", "cvc",
        "pin", "password", "secret", "privatekey", "taxid", "nationalid"
    }

    def __init__(self, mask_emails: bool = True, mask_ips: bool = False):
        self.mask_emails = mask_emails
        self.mask_ips = mask_ips
        self.redaction_count = 0

    def sanitize(self, data: Any) -> Any:
        """Entrypoint to sanitize arbitrary python data structures (dict, list, str)."""
        if isinstance(data, dict):
            return self._sanitize_dict(data)
        elif isinstance(data, list):
            return [self.sanitize(item) for item in data]
        elif isinstance(data, str):
            return self._sanitize_string(data)
        return data

    def _sanitize_dict(self, d: Dict[str, Any]) -> Dict[str, Any]:
        clean: Dict[str, Any] = {}
        for k, v in d.items():
            normalized_key = re.sub(r"[^a-zA-Z0-9]", "", k.lower())
            if any(s in normalized_key for s in self.SENSITIVE_FIELD_NAMES):
                clean[k] = "[REDACTED_SENSITIVE_FIELD]"
                self.redaction_count += 1
                continue
            clean[k] = self.sanitize(v)
        return clean

    def _sanitize_string(self, text: str) -> str:
        if not text:
            return text

        def redact_token(m):
            self.redaction_count += 1
            return m.group(0).replace(m.group(1), "[REDACTED_SECRET]")

        def redact_pwd(m):
            self.redaction_count += 1
            return m.group(0).replace(m.group(1), "[REDACTED_PASSWORD]")

        result = self.PATTERNS["BEARER_TOKEN"].sub(redact_token, text)
        result = self.PATTERNS["CONNECTION_PASSWORD"].sub(redact_pwd, result)

        if self.PATTERNS["SSN_US"].search(result):
            result = self.PATTERNS["SSN_US"].sub("[REDACTED_SSN]", result)
            self.redaction_count += 1

        def mask_cc(match):
            val = re.sub(r"[\s-]", "", match.group(0))
            if 13 <= len(val) <= 16 and val.isdigit():
                self.redaction_count += 1
                return f"[REDACTED_CARD_...{val[-4:]}]"
            return match.group(0)

        result = self.PATTERNS["CREDIT_CARD"].sub(mask_cc, result)

        if self.PATTERNS["IBAN"].search(result):
            result = self.PATTERNS["IBAN"].sub("[REDACTED_IBAN]", result)
            self.redaction_count += 1

        if self.mask_emails and self.PATTERNS["EMAIL"].search(result):
            result = self.PATTERNS["EMAIL"].sub("[REDACTED_EMAIL]", result)
            self.redaction_count += 1

        if self.mask_ips and self.PATTERNS["IPV4"].search(result):
            result = self.PATTERNS["IPV4"].sub("[REDACTED_IP]", result)
            self.redaction_count += 1

        return result
