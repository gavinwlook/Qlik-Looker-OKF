"""
Enterprise Migration Web Studio Server
======================================
Provides HTTP API endpoints and UI asset hosting.
Zero external dependencies (uses standard library http.server).
"""

from enterprise_qlik.web.server import run_server

__all__ = ["run_server"]
