"""
Qlik Instance Connection & Discovery Service (Cloud & On-Premises)
===================================================================
Establishes and verifies connections to Qlik Cloud (SaaS) and Qlik Sense
Enterprise on Windows (QSEoW / On-Premises) environments.
Zero external dependencies (pure Python standard library: urllib, ssl, json).
"""

import json
import os
import random
import socket
import ssl
import string
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


def generate_xrfkey(length: int = 16) -> str:
    """Generates a random alphanumeric string for QRS Xrfkey cross-site request validation."""
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))


class QlikConnectionService:
    """Manages connection health checks and application discovery across Qlik instances."""

    _can_reach_cloud: Optional[bool] = None

    @classmethod
    def can_reach_cloud(cls, host: Optional[str] = None) -> bool:
        """Quick non-blocking probe to determine if external Qlik Cloud network egress is active."""
        if cls._can_reach_cloud is not None:
            return cls._can_reach_cloud
        target_host = "eu.qlikcloud.com"
        if host:
            clean = host.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]
            if clean:
                target_host = clean
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.4)
                s.connect((target_host, 443))
            cls._can_reach_cloud = True
        except Exception:
            cls._can_reach_cloud = False
        return cls._can_reach_cloud

    @staticmethod
    def test_connection(instance: Dict[str, Any]) -> Dict[str, Any]:
        """
        Tests connection to a Qlik instance (Cloud or On-Premises).
        Returns connectivity status, version info, and latency in milliseconds.
        """
        env_type = instance.get("environment_type", "cloud").lower()
        qlik_host = (instance.get("qlik_host") or "").strip()
        auth_config = instance.get("auth_config", {})
        if isinstance(auth_config, str):
            try:
                auth_config = json.loads(auth_config)
            except Exception as e:
                print(f"API Fetch Error: {e}", flush=True)
                auth_config = {}

        start_time = time.time()

        if env_type == "cloud":
            return QlikConnectionService._test_cloud(qlik_host, auth_config, start_time)
        elif env_type == "on_prem":
            return QlikConnectionService._test_onprem(qlik_host, auth_config, start_time)
        else:
            return {
                "connected": False,
                "error": f"Unsupported environment type: '{env_type}'. Use 'cloud' or 'on_prem'.",
                "latency_ms": 0,
            }

    @staticmethod
    def _test_cloud(tenant_url: str, auth_config: Dict[str, Any], start_time: float) -> Dict[str, Any]:
        if not tenant_url:
            return {"connected": False, "error": "Tenant URL is required for Qlik Cloud.", "latency_ms": 0}

        # Clean tenant URL
        clean_url = tenant_url.replace("http://", "https://")
        if not clean_url.startswith("https://"):
            clean_url = f"https://{clean_url}"
        clean_url = clean_url.rstrip("/")

        api_key = (auth_config.get("api_key") or "").strip().strip("'\"")
        if not api_key:
            return {
                "connected": False,
                "error": "API Key (Bearer Token) is required for Qlik Cloud.",
                "latency_ms": 0,
            }

        if api_key.startswith("demo_") or "test" in api_key:
            elapsed = int((time.time() - start_time) * 1000)
            return {
                "connected": True,
                "environment_type": "cloud",
                "tenant_url": clean_url,
                "version": "Qlik Cloud SaaS (Test Mode)",
                "user": "Test Principal",
                "status_code": 200,
                "latency_ms": elapsed,
                "message": "Connection evaluated successfully (test mode).",
            }

        req_url = f"{clean_url}/api/v1/users/me"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "Enterprise-Qlik-to-Looker-Migrator/2.0",
        }

        try:
            req = urllib.request.Request(req_url, headers=headers)
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=6) as response:
                status_code = response.getcode()
                body = json.loads(response.read().decode("utf-8"))
                elapsed = int((time.time() - start_time) * 1000)
                user_name = body.get("name") or body.get("email") or body.get("id") or "API User"
                return {
                    "connected": True,
                    "environment_type": "cloud",
                    "tenant_url": clean_url,
                    "version": "Qlik Cloud SaaS v1.0",
                    "user": user_name,
                    "status_code": status_code,
                    "latency_ms": elapsed,
                    "message": f"Successfully authenticated as '{user_name}'.",
                }
        except urllib.error.HTTPError as e:
            elapsed = int((time.time() - start_time) * 1000)
            if e.code in (401, 403):
                return {
                    "connected": False,
                    "error": f"HTTP {e.code}: Authentication failed. Please verify your Qlik Cloud API key.",
                    "status_code": e.code,
                    "latency_ms": elapsed,
                }
            return {
                "connected": False,
                "error": f"HTTP {e.code}: {e.reason}",
                "status_code": e.code,
                "latency_ms": elapsed,
            }
        except Exception as e:
            elapsed = int((time.time() - start_time) * 1000)
            return {
                "connected": False,
                "error": f"Network unreachable: {str(e)}",
                "latency_ms": elapsed,
                "tip": "Direct outbound TCP port 443 to external Qlik Cloud tenants may be blocked by network firewalls or container sandboxes. If running in a restricted sandbox, consider running the CLI locally on a connected workstation or setting up an egress proxy.",
            }

    @staticmethod
    def _test_onprem(host: str, auth_config: Dict[str, Any], start_time: float) -> Dict[str, Any]:
        if not host:
            return {"connected": False, "error": "Host / IP is required for Qlik On-Premises.", "latency_ms": 0}

        clean_host = host.replace("https://", "").replace("http://", "").rstrip("/")
        qrs_port = int(auth_config.get("qrs_port") or 4242)
        engine_port = int(auth_config.get("engine_port") or 4747)
        cert_path = auth_config.get("cert_path")
        key_path = auth_config.get("key_path")
        ca_path = auth_config.get("ca_path")
        user_dir = auth_config.get("user_directory") or "INTERNAL"
        user_id = auth_config.get("user_id") or "sa_api"
        verify_ssl = bool(auth_config.get("verify_ssl", False))

        # Check for demo mode
        if clean_host.startswith("demo") or "internal.mock" in clean_host:
            elapsed = int((time.time() - start_time) * 1000)
            return {
                "connected": True,
                "environment_type": "on_prem",
                "host": clean_host,
                "qrs_port": qrs_port,
                "engine_port": engine_port,
                "version": "Qlik Sense Enterprise May 2024 Patch 4",
                "user": f"{user_dir}\\{user_id}",
                "latency_ms": max(elapsed, 15),
                "message": "Connected to Qlik Sense On-Premises QRS (Simulated Sandbox).",
            }

        # Check certificate files if provided
        if cert_path and not os.path.isfile(cert_path):
            return {
                "connected": False,
                "error": f"Client certificate file not found on disk: '{cert_path}'",
                "latency_ms": 0,
            }
        if key_path and not os.path.isfile(key_path):
            return {
                "connected": False,
                "error": f"Client certificate private key not found on disk: '{key_path}'",
                "latency_ms": 0,
            }

        xrfkey = generate_xrfkey(16)
        req_url = f"https://{clean_host}:{qrs_port}/qrs/about?xrfkey={xrfkey}"
        headers = {
            "X-Qlik-Xrfkey": xrfkey,
            "X-Qlik-User": f"UserDirectory={user_dir}; UserId={user_id}",
            "Accept": "application/json",
            "User-Agent": "Enterprise-Qlik-to-Looker-Migrator/2.0",
        }

        try:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            if not verify_ssl:
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE

            if cert_path and key_path:
                ssl_ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
            if ca_path and os.path.isfile(ca_path):
                ssl_ctx.load_verify_locations(cafile=ca_path)

            req = urllib.request.Request(req_url, headers=headers)
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=6) as response:
                status_code = response.getcode()
                body = json.loads(response.read().decode("utf-8"))
                elapsed = int((time.time() - start_time) * 1000)
                version = body.get("buildVersion") or body.get("version") or "QSEoW Cluster"
                return {
                    "connected": True,
                    "environment_type": "on_prem",
                    "host": clean_host,
                    "qrs_port": qrs_port,
                    "version": f"QSEoW {version}",
                    "user": f"{user_dir}\\{user_id}",
                    "latency_ms": elapsed,
                    "message": f"Successfully reached QRS /about on port {qrs_port}.",
                }
        except Exception as e:
            elapsed = int((time.time() - start_time) * 1000)
            return {
                "connected": False,
                "error": f"QRS connection error: {str(e)}",
                "latency_ms": elapsed,
                "tip": "Ensure the Qlik QRS port (4242) is open and mTLS client certificates exported from QMC are installed.",
            }

    @staticmethod
    def discover_apps_for_instance(instance: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Discovers all applications from the given Qlik instance.
        If live discovery cannot reach the endpoint, returns curated enterprise application profiles.
        """
        env_type = instance.get("environment_type", "cloud").lower()
        auth_config = instance.get("auth_config", {})
        if isinstance(auth_config, str):
            try:
                auth_config = json.loads(auth_config)
            except Exception as e:
                print(f"API Fetch Error: {e}", flush=True)
                auth_config = {}

        # 1. Try Live Discovery if credentials are configured
        if env_type == "cloud":
            api_key = (auth_config.get("api_key") or "").strip().strip("'\"")
            tenant_url = (instance.get("qlik_host") or "").strip().rstrip("/")
            if api_key.startswith("demo_") or "mock" in str(tenant_url).lower():
                return [
                    {
                        "app_id": "sample-sales-margin-001",
                        "name": "Enterprise Sales & Margin (Sample)",
                        "stream_or_space": "Finance",
                        "space_type": "managed",
                        "sheet_count": 3,
                        "widget_count": 21,
                        "extraction_status": "DISCOVERED",
                    }
                ]
            if api_key and not api_key.startswith("demo_") and "test" not in api_key.lower() and tenant_url:
                try:
                    clean_url = tenant_url.replace("http://", "https://")
                    if not clean_url.startswith("https://"):
                        clean_url = f"https://{clean_url}"
                    clean_url = clean_url.rstrip("/")

                    # Fetch Spaces to map spaceId to space name
                    spaces_map = {}
                    import ssl
                    ssl_ctx = ssl.create_default_context()
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = ssl.CERT_NONE
                    try:
                        req_spaces = urllib.request.Request(
                            f"{clean_url}/api/v1/spaces?limit=100",
                            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
                        )
                        with urllib.request.urlopen(req_spaces, context=ssl_ctx, timeout=6) as resp_s:
                            s_body = json.loads(resp_s.read().decode("utf-8"))
                            for sp in s_body.get("data", []):
                                spaces_map[sp.get("id")] = sp.get("name")
                    except Exception as e:
                        print(f"API Fetch Spaces Error: {e}", flush=True)

                    raw_items = []
                    last_api_err = None
                    # Try /api/v1/items?resourceType=app first
                    try:
                        req = urllib.request.Request(
                            f"{clean_url}/api/v1/items?resourceType=app&limit=100",
                            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
                        )
                        with urllib.request.urlopen(req, context=ssl_ctx, timeout=6) as resp:
                            body = json.loads(resp.read().decode("utf-8"))
                            raw_items = body.get("data", [])
                    except Exception as e:
                        last_api_err = e
                        print(f"API Fetch Items Error: {e}", flush=True)

                    # Fallback to /api/v1/apps if items was empty
                    if not raw_items:
                        try:
                            req_apps = urllib.request.Request(
                                f"{clean_url}/api/v1/apps?limit=100",
                                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
                            )
                            with urllib.request.urlopen(req_apps, context=ssl_ctx, timeout=6) as resp_a:
                                a_body = json.loads(resp_a.read().decode("utf-8"))
                                raw_items = a_body if isinstance(a_body, list) else a_body.get("data", [])
                        except Exception as e:
                            last_api_err = e
                            print(f"API Fetch Apps Error: {e}", flush=True)

                    if not raw_items and last_api_err:
                        raise RuntimeError(f"Network error querying Qlik Cloud APIs at '{clean_url}': {last_api_err}")

                    discovered = []
                    for item in raw_items:
                        app_id = item.get("resourceId") or item.get("id") or item.get("attributes", {}).get("id")
                        if not app_id:
                            continue
                        app_name = (
                            item.get("name")
                            or item.get("resourceAttributes", {}).get("name")
                            or item.get("attributes", {}).get("name")
                        )
                        if not app_name:
                            app_name = item.get("name") or f"App_{app_id[:8]}"

                        space_id = item.get("spaceId") or item.get("resourceAttributes", {}).get("spaceId")
                        is_personal = (not space_id) or (space_id not in spaces_map and len(str(space_id)) >= 20)
                        if is_personal:
                            space_name = "Personal"
                            space_type = "personal"
                        else:
                            space_name = spaces_map.get(space_id, "Personal")
                            space_type = "shared" if "shared" in space_name.lower() or space_name == "Trial" else "managed"

                        sheet_count = item.get("sheetCount") or item.get("resourceAttributes", {}).get("sheetCount") or 0
                        widget_count = item.get("widgetCount") or item.get("resourceAttributes", {}).get("widgetCount") or 0

                        discovered.append({
                            "app_id": app_id,
                            "name": app_name,
                            "stream_or_space": space_name,
                            "space_type": space_type,
                            "sheet_count": sheet_count,
                            "widget_count": widget_count,
                            "extraction_status": "DISCOVERED",
                            "is_live": True,
                        })
                    return discovered
                except Exception as e:
                    print(f"API Fetch Error: {e}", flush=True)
                    raise Exception(f"Failed to contact Qlik Cloud APIs to discover apps: {e}")

            return []

        elif env_type == "on_prem":
            clean_host = (instance.get("qlik_host") or "").replace("https://", "").replace("http://", "").rstrip("/")
            qrs_port = int(auth_config.get("qrs_port") or 4242)
            cert_path = auth_config.get("cert_path")
            key_path = auth_config.get("key_path")
            ca_path = auth_config.get("ca_path")
            user_dir = auth_config.get("user_directory") or "INTERNAL"
            user_id = auth_config.get("user_id") or "sa_api"
            verify_ssl = bool(auth_config.get("verify_ssl", False))

            if clean_host.startswith("demo") or "internal.mock" in clean_host:
                return [
                    {
                        "app_id": "onprem-treasury-001",
                        "name": "Treasury Liquidity Monitor (On-Premises)",
                        "stream_or_space": "Treasury",
                        "space_type": "stream",
                        "sheet_count": 6,
                        "widget_count": 25,
                        "extraction_status": "DISCOVERED",
                    }
                ]

            if not clean_host:
                return []

            try:
                xrfkey = generate_xrfkey(16)
                req_url = f"https://{clean_host}:{qrs_port}/qrs/app/full?xrfkey={xrfkey}"
                headers = {
                    "X-Qlik-Xrfkey": xrfkey,
                    "X-Qlik-User": f"UserDirectory={user_dir}; UserId={user_id}",
                    "Accept": "application/json",
                    "User-Agent": "Enterprise-Qlik-to-Looker-Migrator/2.0",
                }
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
                if cert_path and key_path and os.path.isfile(cert_path) and os.path.isfile(key_path):
                    ssl_ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
                if ca_path and os.path.isfile(ca_path):
                    ssl_ctx.load_verify_locations(cafile=ca_path)

                req = urllib.request.Request(req_url, headers=headers)
                with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as response:
                    raw_apps = json.loads(response.read().decode("utf-8"))

                discovered = []
                for app in raw_apps:
                    stream_obj = app.get("stream", {})
                    stream_name = stream_obj.get("name") if isinstance(stream_obj, dict) else None
                    is_published = app.get("published", False)
                    s_name = stream_name or ("Published" if is_published else "Work")
                    s_type = "stream" if stream_name else ("work" if not is_published else "stream")
                    discovered.append({
                        "app_id": app.get("id"),
                        "name": app.get("name") or f"App_{app.get('id', '')[:8]}",
                        "stream_or_space": s_name,
                        "space_type": s_type,
                        "sheet_count": 0,
                        "widget_count": 0,
                        "extraction_status": "DISCOVERED",
                        "is_live": True,
                    })
                return discovered
            except Exception as e:
                print(f"QRS /app/full Discovery Error: {e}", flush=True)
                raise Exception(f"Failed to contact Qlik On-Premises QRS to discover apps: {e}")

        # Return empty list if no apps or unsupported environment
        return []
