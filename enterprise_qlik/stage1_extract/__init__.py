"""
Stage 1: Source Extraction & Canonical Intermediate Representation (IR) Compiler
================================================================================
Completely standalone stage that connects to Qlik (Cloud or On-Prem), sanitizes PII,
analyzes 3-Tier feature compatibility gaps, and compiles the open-contract Canonical IR.

Stage 1 has ZERO dependencies on Looker, LookML, or downstream target code generators.
"""

from enterprise_qlik.stage1_extract.extractor import QIXExtractor
from enterprise_qlik.stage1_extract.sanitizer import SecuritySanitizer
from enterprise_qlik.stage1_extract.compatibility import CompatibilityAnalyzer
from enterprise_qlik.stage1_extract.ir_compiler import CanonicalIRCompiler

__all__ = [
    "QIXExtractor",
    "SecuritySanitizer",
    "CompatibilityAnalyzer",
    "CanonicalIRCompiler",
]
