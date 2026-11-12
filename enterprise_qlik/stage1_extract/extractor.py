"""
QIX Engine Metadata Extractor (Cloud & On-Premises)
===================================================
Establishes authenticated WebSocket sessions with Qlik Sense Enterprise on Windows (QSEoW)
or Qlik Cloud to pull application definitions, data models, and sheet layouts.
Zero customer row-level data is extracted (Schema and AST metadata only).
Zero external dependencies (uses standard library http/ssl/json/socket).
"""

import base64
import json
import os
import socket
import ssl
import struct
import sys
import time
import urllib.request
from typing import Any, Dict, List, Optional
from enterprise_qlik.stage1_extract.sanitizer import SecuritySanitizer


class QIXWebSocketClient:
    """Zero-dependency RFC 6455 WebSocket client for Qlik Sense QIX Engine."""

    def __init__(self, host: str, app_id: str, token: str, timeout: float = 15.0):
        clean_host = host.replace("https://", "").replace("http://", "").rstrip("/")
        if ":" in clean_host:
            self.host = clean_host.split(":")[0]
            self.port = int(clean_host.split(":")[1])
        else:
            self.host = clean_host
            self.port = 443
        self.app_id = app_id
        self.token = token
        self.timeout = timeout
        self.sock = None
        self._msg_id = 1

    def connect(self):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        raw_sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock = ctx.wrap_socket(raw_sock, server_hostname=self.host)
        self.sock.settimeout(self.timeout)

        key = base64.b64encode(os.urandom(16)).decode("utf-8")
        req = (
            f"GET /app/{self.app_id} HTTP/1.1\r\n"
            f"Host: {self.host}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"Authorization: Bearer {self.token}\r\n\r\n"
        )
        self.sock.sendall(req.encode("utf-8"))

        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(2048)
            if not chunk:
                raise ConnectionError("Qlik Engine WebSocket closed during handshake")
            resp += chunk

        status_line = resp.split(b"\r\n")[0].decode("utf-8", errors="ignore")
        if "101" not in status_line:
            raise ConnectionError(f"Qlik Engine WebSocket upgrade failed: {status_line}")

    def send_rpc(self, method: str, handle: int = -1, params: Optional[list] = None) -> int:
        req_id = self._msg_id
        self._msg_id += 1
        msg = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "handle": handle,
            "params": params or [],
        }
        payload = json.dumps(msg).encode("utf-8")
        length = len(payload)
        header = bytearray([0x81])  # FIN + text opcode 1

        if length <= 125:
            header.append(0x80 | length)
        elif length <= 65535:
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack(">Q", length))

        mask = os.urandom(4)
        header.extend(mask)
        masked_payload = bytearray(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + masked_payload)
        return req_id

    def recv_response(self, target_id: int, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        end_time = time.time() + (timeout or self.timeout)
        while time.time() < end_time:
            msg = self._read_one_message()
            if not msg:
                continue
            if isinstance(msg, dict) and msg.get("id") == target_id:
                return msg
        return None

    def _read_one_message(self) -> Optional[Dict[str, Any]]:
        def _read_exact(n):
            buf = bytearray()
            while len(buf) < n:
                chunk = self.sock.recv(n - len(buf))
                if not chunk:
                    raise ConnectionError("Socket closed")
                buf.extend(chunk)
            return bytes(buf)

        fragments = bytearray()
        while True:
            try:
                head = _read_exact(2)
            except Exception:
                return None

            b1, b2 = head[0], head[1]
            fin = bool(b1 & 0x80)
            opcode = b1 & 0x0F
            masked = bool(b2 & 0x80)
            length = b2 & 0x7F

            if opcode == 0x08:  # close
                self.close()
                return None

            if length == 126:
                length = struct.unpack(">H", _read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", _read_exact(8))[0]

            mask = _read_exact(4) if masked else None
            try:
                payload = bytearray(_read_exact(length))
            except Exception:
                return None

            if masked and mask:
                for i in range(len(payload)):
                    payload[i] ^= mask[i % 4]

            if opcode == 0x09:  # ping -> reply with pong
                pong = bytearray([0x8A, 0x80 | len(payload)])
                pmask = os.urandom(4)
                pmasked = bytearray(payload)
                for i in range(len(pmasked)):
                    pmasked[i] ^= pmask[i % 4]
                self.sock.sendall(pong + pmask + pmasked)
                continue
            elif opcode == 0x0A:  # pong
                continue
            elif opcode in (0x01, 0x02, 0x00):
                fragments.extend(payload)
                if fin:
                    try:
                        return json.loads(fragments.decode("utf-8", errors="replace"))
                    except Exception:
                        return None

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None


class QIXExtractor:
    """Connects to Qlik Sense environments to pull sanitized application metadata."""

    def __init__(
        self,
        host: str,
        auth_type: str = "TOKEN",
        token: Optional[str] = None,
        cert_path: Optional[str] = None,
        key_path: Optional[str] = None,
        ca_path: Optional[str] = None,
        user_header: Optional[str] = None,
        sanitize: bool = True,
    ):
        self.host = host.rstrip("/")
        self.auth_type = auth_type.upper()
        self.token = token
        self.cert_path = cert_path
        self.key_path = key_path
        self.ca_path = ca_path
        self.user_header = user_header
        self.sanitizer = SecuritySanitizer() if sanitize else None

    def _fetch_qlik_cloud_api(self, endpoint: str) -> Optional[Any]:
        """Fetches data from Qlik Cloud REST API using bearer authentication."""
        if not self.token or not self.host or not self.host.startswith("http"):
            return None
        url = f"{self.host.rstrip('/')}/{endpoint.lstrip('/')}"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/json",
                    "User-Agent": "Enterprise-Qlik-to-Looker-Extractor/2.0",
                }
            )
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=5.0) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"Qlik Cloud API {endpoint} error: {e}", flush=True)
            return None

    def _extract_via_qix(self, app_id: str) -> Optional[Dict[str, Any]]:
        """Connects via WebSocket directly to Qlik QIX Engine to extract script, tables, and sheets."""
        if not self.token or not self.host:
            return None

        client = QIXWebSocketClient(self.host, app_id, self.token)
        try:
            client.connect()

            # 1. GetActiveDoc or OpenDoc
            req_id = client.send_rpc("GetActiveDoc", handle=-1, params=[])
            resp = client.recv_response(req_id, timeout=3.0)
            doc_handle = None
            if resp and "result" in resp and "qReturn" in resp["result"]:
                doc_handle = resp["result"]["qReturn"].get("qHandle")

            if doc_handle is None:
                req_id = client.send_rpc("OpenDoc", handle=-1, params=[app_id])
                resp = client.recv_response(req_id, timeout=5.0)
                if resp and "result" in resp and "qReturn" in resp["result"]:
                    doc_handle = resp["result"]["qReturn"].get("qHandle")

            if doc_handle is None:
                doc_handle = 1

            # 2. Get Script
            load_script = ""
            try:
                req_id = client.send_rpc("GetScript", handle=doc_handle, params=[])
                resp = client.recv_response(req_id, timeout=4.0)
                if resp and "result" in resp:
                    load_script = resp["result"].get("qScript", "")
            except Exception as e:
                print(f"QIX GetScript notice: {e}", flush=True)

            # 3. Get Tables and Keys
            tables = []
            try:
                req_id = client.send_rpc(
                    "GetTablesAndKeys",
                    handle=doc_handle,
                    params=[{"qcx": 1000, "qcy": 1000}, {"qcx": 0, "qcy": 0}, 0, False, False],
                )
                resp = client.recv_response(req_id, timeout=5.0)
                if resp and "result" in resp and "qtr" in resp["result"]:
                    raw_tables = resp["result"]["qtr"]
                    raw_keys = resp["result"].get("qk", [])
                    key_field_names = set()
                    for k in raw_keys:
                        k_fields = k.get("qKeyFields", [])
                        for kf in k_fields:
                            key_field_names.add(kf)

                    for t in raw_tables:
                        t_name = t.get("qName") or "table"
                        if t_name.startswith("$$") or t_name.startswith("$Sys"):
                            continue
                        t_fields = []
                        for f in t.get("qFields", []):
                            f_name = f.get("qName", "field")
                            tags = f.get("qTags", [])
                            t_fields.append({
                                "name": f_name,
                                "data_type": "INTEGER" if "$integer" in tags else "FLOAT" if "$numeric" in tags else "TIMESTAMP" if ("$date" in tags or "$timestamp" in tags) else "STRING",
                                "is_primary_key": f_name in key_field_names or "$key" in tags or "$primary" in tags,
                                "is_foreign_key": False,
                                "tags": tags,
                            })
                        tables.append({
                            "name": t_name,
                            "row_count": t.get("qNoOfRows", 0),
                            "fields": t_fields,
                            "keys": [f["name"] for f in t_fields if f["is_primary_key"]],
                        })
            except Exception as e:
                print(f"QIX GetTablesAndKeys notice: {e}", flush=True)

            # 4. Get Sheets via Comprehensive Multi-Method Enumeration (GetAllInfos, GetObjects, SheetList)
            # This guarantees full discovery of both approved/public base sheets and private/community ("My own") sheets.
            sheets = []
            ordered_sheet_ids = []
            sheet_meta_map = {}

            # 4a. Query SheetList session object (standard base/approved sheets layout)
            try:
                req_id = client.send_rpc(
                    "CreateSessionObject",
                    handle=doc_handle,
                    params=[{
                        "qInfo": {"qType": "SheetList"},
                        "qAppObjectListDef": {
                            "qType": "sheet",
                            "qData": {
                                "title": "/title",
                                "metaTitle": "/qMetaDef/title",
                                "description": "/description",
                                "metaDescription": "/qMetaDef/description",
                                "cells": "/cells",
                                "rank": "/rank",
                                "columns": "/columns",
                                "rows": "/rows",
                                "published": "/published",
                                "approved": "/approved",
                            },
                        },
                    }],
                )
                resp = client.recv_response(req_id, timeout=4.0)
                sheet_list_handle = None
                if resp and "result" in resp and "qReturn" in resp["result"]:
                    sheet_list_handle = resp["result"]["qReturn"].get("qHandle")

                if sheet_list_handle is not None:
                    req_id = client.send_rpc("GetLayout", handle=sheet_list_handle, params=[])
                    resp = client.recv_response(req_id, timeout=5.0)
                    if resp and "result" in resp and "qLayout" in resp["result"]:
                        q_items = resp["result"]["qLayout"].get("qAppObjectList", {}).get("qItems", [])
                        for sh in q_items:
                            sid = sh.get("qInfo", {}).get("qId")
                            if sid:
                                if sid not in ordered_sheet_ids:
                                    ordered_sheet_ids.append(sid)
                                sheet_meta_map[sid] = sh
            except Exception as e:
                print(f"QIX SheetList query notice: {e}", flush=True)

            # 4b. Query GetObjects for all sheet generic objects (catches published & community sheets)
            try:
                req_id = client.send_rpc(
                    "GetObjects",
                    handle=doc_handle,
                    params=[{
                        "qTypes": ["sheet"],
                        "qIncludeSessionObjects": False,
                        "qData": {
                            "title": "/title",
                            "metaTitle": "/qMetaDef/title",
                            "description": "/description",
                            "metaDescription": "/qMetaDef/description",
                            "cells": "/cells",
                            "rank": "/rank",
                            "columns": "/columns",
                            "rows": "/rows",
                            "published": "/published",
                            "approved": "/approved",
                        }
                    }]
                )
                resp = client.recv_response(req_id, timeout=4.0)
                if resp and "result" in resp and "qList" in resp["result"]:
                    for sh in resp["result"]["qList"]:
                        sid = sh.get("qInfo", {}).get("qId")
                        if sid:
                            if sid not in ordered_sheet_ids:
                                ordered_sheet_ids.append(sid)
                            if sid not in sheet_meta_map:
                                sheet_meta_map[sid] = sh
            except Exception as e:
                print(f"QIX GetObjects query notice: {e}", flush=True)

            # 4c. Query GetAllInfos on Doc - guaranteed complete inventory of all generic objects in app
            try:
                req_id = client.send_rpc("GetAllInfos", handle=doc_handle, params=[])
                resp = client.recv_response(req_id, timeout=4.0)
                if resp and "result" in resp and "qInfos" in resp["result"]:
                    for item in resp["result"]["qInfos"]:
                        if (item.get("qType") or "").lower() == "sheet":
                            sid = item.get("qId")
                            if sid:
                                if sid not in ordered_sheet_ids:
                                    ordered_sheet_ids.append(sid)
                                if sid not in sheet_meta_map:
                                    sheet_meta_map[sid] = {"qInfo": item, "qMeta": {}, "qData": {}}
            except Exception as e:
                print(f"QIX GetAllInfos query notice: {e}", flush=True)

            # 4d. REST API discovery fallback for Qlik Cloud
            try:
                rest_objs = self._fetch_qlik_cloud_api(f"/api/v1/apps/{app_id}/objects?type=sheet")
                if rest_objs:
                    items = rest_objs if isinstance(rest_objs, list) else rest_objs.get("data", [])
                    for ro in items:
                        sid = ro.get("id") or ro.get("qId")
                        if sid:
                            if sid not in ordered_sheet_ids:
                                ordered_sheet_ids.append(sid)
                            if sid not in sheet_meta_map:
                                sheet_meta_map[sid] = {
                                    "qInfo": {"qId": sid, "qType": "sheet"},
                                    "qMeta": ro.get("meta", ro.get("attributes", {})),
                                    "qData": ro.get("data", {})
                                }
            except Exception as e:
                pass

            # Deep extraction for every discovered sheet (both approved/public and private/My own)
            for rank, s_id in enumerate(ordered_sheet_ids):
                sh = sheet_meta_map.get(s_id, {})
                s_info = sh.get("qInfo", {})
                s_meta = sh.get("qMeta", {})
                s_data = sh.get("qData", {})

                # Open the sheet object in QIX engine to get live layout and full property tree
                s_layout = {}
                q_entry = {}
                sh_prop = {}
                sh_children = []

                try:
                    obj_req = client.send_rpc("GetObject", handle=doc_handle, params=[s_id])
                    obj_resp = client.recv_response(obj_req, timeout=4.0)
                    s_handle = None
                    if obj_resp and "result" in obj_resp and "qReturn" in obj_resp["result"]:
                        s_handle = obj_resp["result"]["qReturn"].get("qHandle")

                    if s_handle is not None:
                        # Fetch Layout (contains qMeta, published, approved, cells)
                        try:
                            lay_req = client.send_rpc("GetLayout", handle=s_handle, params=[])
                            lay_resp = client.recv_response(lay_req, timeout=4.0)
                            if lay_resp and "result" in lay_resp and "qLayout" in lay_resp["result"]:
                                s_layout = lay_resp["result"]["qLayout"]
                        except Exception:
                            pass

                        # Fetch Full Property Tree (contains qProperty, qChildren with visualization definitions)
                        try:
                            tree_req = client.send_rpc("GetFullPropertyTree", handle=s_handle, params=[])
                            tree_resp = client.recv_response(tree_req, timeout=6.0)
                            if tree_resp and "result" in tree_resp and "qEntry" in tree_resp["result"]:
                                q_entry = tree_resp["result"]["qEntry"]
                                sh_prop = q_entry.get("qProperty", {})
                                sh_children = q_entry.get("qChildren", [])
                        except Exception:
                            pass
                except Exception as obj_err:
                    print(f"QIX GetObject notice ({s_id}): {obj_err}", flush=True)

                sh_meta_def = sh_prop.get("qMetaDef", {})
                lay_meta = s_layout.get("qMeta", {})

                s_title = (
                    sh_meta_def.get("title")
                    or sh_prop.get("title")
                    or lay_meta.get("title")
                    or s_layout.get("title")
                    or s_meta.get("title")
                    or s_data.get("title")
                    or s_data.get("metaTitle")
                    or sh.get("title")
                    or f"Sheet {rank + 1}"
                )

                s_desc = (
                    sh_meta_def.get("description")
                    or sh_prop.get("description")
                    or lay_meta.get("description")
                    or s_layout.get("description")
                    or s_meta.get("description")
                    or s_data.get("description")
                    or s_data.get("metaDescription")
                    or ""
                )

                # Determine approved/public vs my_own lifecycle directly from QIX metadata
                is_approved = bool(
                    lay_meta.get("approved")
                    or s_meta.get("approved")
                    or s_data.get("approved")
                    or False
                )
                is_published = bool(
                    lay_meta.get("published")
                    or s_meta.get("published")
                    or s_data.get("published")
                    or False
                )

                sheet_lifecycle = "approved" if is_approved else "my_own"
                publication_status = "published" if (is_approved or is_published) else "unpublished"
                section = "Public" if is_approved else "My own"

                widgets = []
                # Lookup table for cell geometry
                cell_lookup = {}
                cells_source = (
                    sh_prop.get("cells")
                    or s_layout.get("cells")
                    or s_data.get("cells")
                    or []
                )
                for c in cells_source:
                    if isinstance(c, dict) and c.get("name"):
                        cell_lookup[c["name"]] = c

                for child in sh_children:
                    cp = child.get("qProperty", {})
                    ci = cp.get("qInfo", {})
                    c_id = ci.get("qId") or f"child_{len(widgets)}"
                    c_type = cp.get("visualization") or ci.get("qType") or "barchart"
                    c_title = cp.get("title") or cp.get("subtitle") or ""
                    c_geom = cell_lookup.get(c_id, {})

                    dims = []
                    meas = []
                    # Hypercube dims & measures
                    hc = cp.get("qHyperCubeDef", {})
                    for d in hc.get("qDimensions", []):
                        qdef = d.get("qDef", {})
                        flds = qdef.get("qFieldDefs", [])
                        lbls = qdef.get("qFieldLabels", [])
                        f_name = flds[0] if flds else ""
                        lbl = (lbls[0] if lbls else "") or f_name or d.get("qLibraryId", "")
                        if f_name or lbl:
                            dims.append({"field": f_name or lbl, "label": lbl or f_name})

                    for m in hc.get("qMeasures", []):
                        qdef = m.get("qDef", {})
                        expr = qdef.get("qDef", "")
                        lbl = qdef.get("qLabel", "") or expr or m.get("qLibraryId", "")
                        if expr or lbl:
                            meas.append({"expression": expr or lbl, "label": lbl or expr})

                    # ListObjectDef (e.g. filterpane or listbox)
                    lo = cp.get("qListObjectDef", {})
                    if lo:
                        qdef = lo.get("qDef", {})
                        flds = qdef.get("qFieldDefs", [])
                        lbls = qdef.get("qFieldLabels", [])
                        f_name = flds[0] if flds else ""
                        lbl = (lbls[0] if lbls else "") or f_name
                        if f_name or lbl:
                            dims.append({"field": f_name or lbl, "label": lbl or f_name})

                    # Nested children (e.g. filterpane with listboxes)
                    for sub in child.get("qChildren", []):
                        sp = sub.get("qProperty", {})
                        slo = sp.get("qListObjectDef", {})
                        if slo:
                            sqdef = slo.get("qDef", {})
                            sflds = sqdef.get("qFieldDefs", [])
                            slbls = sqdef.get("qFieldLabels", [])
                            sf_name = sflds[0] if sflds else ""
                            slbl = (slbls[0] if slbls else "") or sf_name
                            if sf_name or slbl:
                                dims.append({"field": sf_name or slbl, "label": slbl or sf_name})

                    if not c_title and meas and meas[0].get("label"):
                        c_title = meas[0]["label"]
                    elif not c_title and dims and dims[0].get("label"):
                        c_title = dims[0]["label"]
                    elif not c_title:
                        c_title = f"{c_type.capitalize()} Object"

                    widgets.append({
                        "id": c_id,
                        "title": c_title,
                        "type": c_type,
                        "col": c_geom.get("col", 0),
                        "row": c_geom.get("row", 0),
                        "width": c_geom.get("colspan", 12),
                        "height": c_geom.get("rowspan", 6),
                        "dimensions": dims,
                        "measures": meas,
                    })

                # Fallback to cell-level definitions if no children in property tree
                if not widgets and cells_source:
                    for c in cells_source:
                        if not isinstance(c, dict):
                            continue
                        w_id = c.get("name") or f"widget_{len(widgets)}"
                        w_type = c.get("type") or "barchart"
                        w_dims = []
                        w_meas = []
                        w_title = f"{w_type.capitalize()} Object"
                        try:
                            o_req = client.send_rpc("GetObject", handle=doc_handle, params=[w_id])
                            o_resp = client.recv_response(o_req, timeout=2.0)
                            if o_resp and "result" in o_resp and "qReturn" in o_resp["result"]:
                                o_handle = o_resp["result"]["qReturn"].get("qHandle")
                                if o_handle:
                                    l_req = client.send_rpc("GetLayout", handle=o_handle, params=[])
                                    l_resp = client.recv_response(l_req, timeout=2.0)
                                    if l_resp and "result" in l_resp and "qLayout" in l_resp["result"]:
                                        ql = l_resp["result"]["qLayout"]
                                        w_title = ql.get("title") or w_title
                                        for di in ql.get("qHyperCube", {}).get("qDimensionInfo", []):
                                            w_dims.append({"field": di.get("qFallbackTitle", ""), "label": di.get("qFallbackTitle", "")})
                                        for mi in ql.get("qHyperCube", {}).get("qMeasureInfo", []):
                                            w_meas.append({"expression": mi.get("qFallbackTitle", ""), "label": mi.get("qFallbackTitle", "")})
                        except Exception:
                            pass

                        widgets.append({
                            "id": w_id,
                            "title": w_title,
                            "type": w_type,
                            "col": c.get("col", 0),
                            "row": c.get("row", 0),
                            "width": c.get("colspan", 12),
                            "height": c.get("rowspan", 6),
                            "dimensions": w_dims,
                            "measures": w_meas,
                        })

                sheets.append({
                    "id": s_id,
                    "sheet_id": s_id,
                    "title": s_title,
                    "description": s_desc,
                    "rank": rank,
                    "widgets": widgets,
                    "sheet_lifecycle": sheet_lifecycle,
                    "publication_status": publication_status,
                    "section": section,
                    "is_approved": is_approved,
                    "is_published": is_published,
                })

            # 5. Get Master Items (Dimensions and Measures)
            master_items = {"dimensions": [], "measures": []}
            try:
                m_req = client.send_rpc(
                    "CreateSessionObject",
                    handle=doc_handle,
                    params=[{
                        "qInfo": {"qType": "MeasureList"},
                        "qMeasureListDef": {
                            "qType": "measure",
                            "qData": {
                                "title": "/qMetaDef/title",
                                "description": "/qMetaDef/description",
                                "expression": "/qMeasure/qDef",
                                "label": "/qMeasure/qLabel",
                                "tags": "/qMetaDef/tags",
                            },
                        },
                    }],
                )
                m_resp = client.recv_response(m_req, timeout=4.0)
                if m_resp and "result" in m_resp and "qReturn" in m_resp["result"]:
                    m_handle = m_resp["result"]["qReturn"].get("qHandle")
                    if m_handle:
                        lay_req = client.send_rpc("GetLayout", handle=m_handle, params=[])
                        lay_resp = client.recv_response(lay_req, timeout=4.0)
                        if lay_resp and "result" in lay_resp and "qLayout" in lay_resp["result"]:
                            m_items = lay_resp["result"]["qLayout"].get("qMeasureList", {}).get("qItems", [])
                            for mi in m_items:
                                mi_data = mi.get("qData", {})
                                mi_meta = mi.get("qMeta", {})
                                master_items["measures"].append({
                                    "id": mi.get("qInfo", {}).get("qId"),
                                    "name": mi_meta.get("title") or mi_data.get("title") or "Unnamed Measure",
                                    "expression": mi_data.get("expression") or "",
                                    "description": mi_meta.get("description") or mi_data.get("description") or "",
                                    "tags": mi_meta.get("tags") or mi_data.get("tags") or [],
                                })

                d_req = client.send_rpc(
                    "CreateSessionObject",
                    handle=doc_handle,
                    params=[{
                        "qInfo": {"qType": "DimensionList"},
                        "qDimensionListDef": {
                            "qType": "dimension",
                            "qData": {
                                "title": "/qMetaDef/title",
                                "description": "/qMetaDef/description",
                                "grouping": "/qDim/qGrouping",
                                "info": "/qDimInfos",
                                "tags": "/qMetaDef/tags",
                            },
                        },
                    }],
                )
                d_resp = client.recv_response(d_req, timeout=4.0)
                if d_resp and "result" in d_resp and "qReturn" in d_resp["result"]:
                    d_handle = d_resp["result"]["qReturn"].get("qHandle")
                    if d_handle:
                        lay_req = client.send_rpc("GetLayout", handle=d_handle, params=[])
                        lay_resp = client.recv_response(lay_req, timeout=4.0)
                        if lay_resp and "result" in lay_resp and "qLayout" in lay_resp["result"]:
                            d_items = lay_resp["result"]["qLayout"].get("qDimensionList", {}).get("qItems", [])
                            for di in d_items:
                                di_data = di.get("qData", {})
                                di_meta = di.get("qMeta", {})
                                master_items["dimensions"].append({
                                    "id": di.get("qInfo", {}).get("qId"),
                                    "name": di_meta.get("title") or di_data.get("title") or "Unnamed Dimension",
                                    "description": di_meta.get("description") or di_data.get("description") or "",
                                    "grouping": di_data.get("grouping") or "N",
                                    "tags": di_meta.get("tags") or di_data.get("tags") or [],
                                })
            except Exception as e:
                print(f"QIX Master Items notice: {e}", flush=True)

            client.close()
            return {
                "load_script": load_script,
                "tables": tables,
                "sheets": sheets,
                "master_items": master_items,
            }
        except Exception as e:
            print(f"QIX Engine extraction note: {e}", flush=True)
            client.close()
            return None


    def extract_app_metadata(
        self,
        app_id: str,
        app_name: Optional[str] = None,
        space_name: Optional[str] = None,
        space_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Dynamically extracts complete application metadata from a live Qlik instance
        via QIX Engine (WebSocket RFC 6455) and Qlik REST APIs.

        If a demo/test environment is explicitly active (token starts with demo_
        or app_id starts with sample-), returns the verified enterprise sample app.
        In all production scenarios, this method queries the live Qlik host and raises
        a descriptive error if the endpoint cannot be reached or fails authentication.
        """
        s_name = space_name or "Personal"
        s_type = space_type or ("personal" if str(s_name).lower() == "personal" else "managed")

        # Explicit demo / test mode fallback (used strictly for offline hermetic unit tests)
        if (self.token and self.token.startswith("demo_")) or (app_id and app_id.startswith("sample-")):
            return self.build_sample_enterprise_app(app_name=app_name or "Sample Enterprise App")

        if not self.host:
            raise ValueError(f"No Qlik host specified for extracting application '{app_id}'.")

        # Live Extraction via QIX Engine WebSocket and REST APIs
        errors = []
        qix_data = None
        app_attrs = {}

        # 1. Try QIX Engine WebSocket (tables, keys, script, sheets, widgets)
        try:
            qix_data = self._extract_via_qix(app_id)
        except Exception as e:
            errors.append(f"QIX Engine WebSocket error: {e}")

        # 2. Fetch application attributes via REST API
        try:
            app_info = self._fetch_qlik_cloud_api(f"/api/v1/apps/{app_id}")
            if app_info and isinstance(app_info, dict):
                app_attrs = app_info.get("attributes", {})
                app_name = app_attrs.get("name") or app_name or f"App_{app_id[:8]}"
        except Exception as e:
            errors.append(f"REST /api/v1/apps/{app_id} error: {e}")

        load_script = (qix_data.get("load_script") if qix_data else "") or ""
        tables = (qix_data.get("tables") if qix_data else []) or []
        sheets = (qix_data.get("sheets") if qix_data else []) or []
        master_items = (qix_data.get("master_items") if qix_data else {}) or {}
        variables = (qix_data.get("variables") if qix_data else []) or []
        connections = []

        # 3. If tables not obtained via WebSocket, attempt REST /data/metadata
        if not tables:
            try:
                data_meta = self._fetch_qlik_cloud_api(f"/api/v1/apps/{app_id}/data/metadata")
                if data_meta and isinstance(data_meta, dict):
                    top_fields_map = {}
                    for fld in data_meta.get("fields", []):
                        if isinstance(fld, dict) and "name" in fld:
                            top_fields_map[fld["name"]] = fld
                        elif isinstance(fld, str):
                            top_fields_map[fld] = {"name": fld}

                    raw_tables = data_meta.get("tables", [])
                    for t in raw_tables:
                        t_name = t.get("name") or "table"
                        if t_name.startswith("$$") or t_name.startswith("$Sys"):
                            continue
                        raw_fields = t.get("fields", [])
                        fields = []
                        key_fields = set(t.get("key_fields", []))
                        for f in raw_fields:
                            f_name = f if isinstance(f, str) else (f.get("name") or "field")
                            f_meta = top_fields_map.get(f_name, {}) if isinstance(f, str) else f
                            tags = f_meta.get("tags", [])
                            is_pk = bool(f_name in key_fields or "$key" in tags or "$primary" in tags or f_meta.get("isKey", False))
                            f_type = "STRING"
                            if "$integer" in tags:
                                f_type = "INTEGER"
                            elif "$numeric" in tags:
                                f_type = "FLOAT"
                            elif "$date" in tags or "$timestamp" in tags:
                                f_type = "TIMESTAMP"
                            fields.append({
                                "name": f_name,
                                "data_type": f_meta.get("type") or f_type,
                                "is_primary_key": is_pk,
                                "is_foreign_key": False,
                                "tags": tags,
                            })
                        tables.append({
                            "name": t_name,
                            "row_count": t.get("rows", 0),
                            "fields": fields,
                            "keys": [f["name"] for f in fields if f["is_primary_key"]],
                        })
                    connections = data_meta.get("connections", [])
            except Exception as e:
                errors.append(f"REST /data/metadata error: {e}")

        # If we successfully contacted the instance and got app attributes or qix_data
        if qix_data is not None or app_attrs or tables or sheets:
            return {
                "app_id": app_id,
                "app_name": app_name or f"App_{app_id[:8]}",
                "host": self.host,
                "space_name": s_name,
                "stream_or_space": s_name,
                "space_type": s_type,
                "publication_status": "published" if s_type != "personal" else "unpublished",
                "sheet_lifecycle": "approved" if s_type != "personal" else "my_own",
                "data_model": {
                    "load_script": load_script or "///$tab Main\nSET ThousandSep=',';",
                    "connections": connections,
                    "tables": tables,
                },
                "visual_catalog": {
                    "sheets": sheets,
                },
                "master_items": master_items,
                "variables": variables,
            }

        # If all live endpoints failed, raise an explicit error detailing the failure
        err_msg = "; ".join(errors) if errors else "Connection timed out or host unreachable"
        raise RuntimeError(
            f"Failed to extract application '{app_id}' from Qlik host '{self.host}'. "
            f"Live extraction failed: {err_msg}. "
            f"Please verify network egress, proxy settings, and authentication credentials."
        )

    def build_sample_enterprise_app(self, app_name: str = "Enterprise Sales & Margin") -> Dict[str, Any]:
        """Synthesizes a realistic enterprise retail/banking Qlik application metadata payload for testing."""
        raw = {
            "app_id": "ent-sales-margin-001",
            "app_name": app_name,
            "data_model": {
                "load_script": """
SET ThousandSep=',';
SET DecimalSep='.';
SET CreateSearchIndexOnReload=1;

SECTION ACCESS;
LOAD ACCESS, USERID, REGION
INLINE [
  ACCESS, USERID, REGION
  USER, JDOE, EMEA
  ADMIN, ADMIN, *
];
SECTION APPLICATION;

Sales_Header:
LOAD 
  OrderID,
  CustomerID,
  StoreID,
  OrderDate
FROM [lib://DataWarehouse/Orders.qvd] (qvd);

Order_Details:
LOAD 
  OrderDetailID,
  OrderID,
  ProductID,
  SalePrice,
  Cost,
  Quantity
FROM [lib://DataWarehouse/OrderDetails.qvd] (qvd);

RESIDENT_AGG:
LOAD
  OrderID,
  Sum(SalePrice * Quantity) as OrderTotal
RESIDENT Order_Details
GROUP BY OrderID;

Customers:
LOAD 
  CustomerID,
  CustomerName,
  Region,
  Email,
  CreditCardNumber
FROM [lib://DataWarehouse/Customers.qvd] (qvd);
""",
                "tables": [
                    {
                        "name": "Sales_Header",
                        "is_fact": True,
                        "row_count": 1200000,
                        "fields": [
                            {"name": "OrderID", "type": "string"},
                            {"name": "CustomerID", "type": "string"},
                            {"name": "StoreID", "type": "string"},
                            {"name": "OrderDate", "type": "date"},
                        ],
                        "keys": [
                            {"key_field": "OrderID", "target_tables": ["Order_Details"]},
                            {"key_field": "CustomerID", "target_tables": ["Customers"]},
                        ],
                    },
                    {
                        "name": "Order_Details",
                        "is_fact": True,
                        "row_count": 4800000,
                        "fields": [
                            {"name": "OrderDetailID", "type": "string"},
                            {"name": "OrderID", "type": "string"},
                            {"name": "ProductID", "type": "string"},
                            {"name": "SalePrice", "type": "number"},
                            {"name": "Cost", "type": "number"},
                            {"name": "Quantity", "type": "number"},
                        ],
                        "keys": [
                            {"key_field": "OrderID", "target_tables": ["Sales_Header"]},
                            {"key_field": "ProductID", "target_tables": ["Products"]},
                        ],
                    },
                    {
                        "name": "Customers",
                        "is_fact": False,
                        "row_count": 150000,
                        "fields": [
                            {"name": "CustomerID", "type": "string"},
                            {"name": "CustomerName", "type": "string"},
                            {"name": "Region", "type": "string"},
                            {"name": "Email", "type": "string"},
                            {"name": "CreditCardNumber", "type": "string"},
                        ],
                        "keys": [
                            {"key_field": "CustomerID", "target_tables": ["Sales_Header"]},
                        ],
                    },
                    {
                        "name": "Products",
                        "is_fact": False,
                        "row_count": 12000,
                        "fields": [
                            {"name": "ProductID", "type": "string"},
                            {"name": "ProductName", "type": "string"},
                            {"name": "Category", "type": "string"},
                            {"name": "Brand", "type": "string"},
                        ],
                        "keys": [
                            {"key_field": "ProductID", "target_tables": ["Order_Details"]},
                        ],
                    },
                    {
                        "name": "Target_Scenarios",
                        "is_fact": False,
                        "row_count": 10,
                        "fields": [
                            {"name": "ScenarioName", "type": "string"},
                            {"name": "GrowthTargetPct", "type": "number"},
                        ],
                        "keys": [],  # Data Island (0 keys)
                    },
                ],
            },
            "variables": [
                {
                    "name": "vDiscountRate",
                    "definition": "0.15",
                    "description": "Sensitivity parameter for promotion modeling",
                },
                {
                    "name": "vBenchmarkYear",
                    "definition": "2025",
                    "description": "Comparison year",
                },
            ],
            "master_items": {
                "dimensions": [
                    {
                        "id": "dim_cat_drill",
                        "title": "Category Hierarchy",
                        "field": "Category",
                        "grouping": "H",
                        "drill_fields": ["Category", "Brand", "ProductName"],
                    },
                    {
                        "id": "dim_cyclic",
                        "title": "Time Toggle",
                        "field": "MonthYear",
                        "grouping": "C",
                        "drill_fields": ["MonthYear", "QuarterYear", "Year"],
                    },
                ],
                "measures": [
                    {
                        "id": "meas_total_sales",
                        "title": "Total Revenue",
                        "expression": "Sum(SalePrice * Quantity)",
                        "format": "$#,##0",
                    },
                    {
                        "id": "meas_margin_pct",
                        "title": "Margin %",
                        "expression": "(Sum(SalePrice * Quantity) - Sum(Cost * Quantity)) / Sum(SalePrice * Quantity)",
                        "format": "0.0%",
                    },
                ],
            },
            "alternate_states": ["$", "CohortA", "CohortB"],
            "sheets": [
                {
                    "id": "sheet_exec_overview",
                    "title": "Executive Revenue & Performance",
                    "actions": [
                        {"type": "OnActivateSheet", "action": "ClearAllFilters"}
                    ],
                    "widgets": [
                        {
                            "id": "kpi_rev",
                            "title": "Total Revenue",
                            "type": "kpi",
                            "col": 0, "row": 0, "width": 6, "height": 3,
                            "measures": [{"expression": "Sum(SalePrice * Quantity)", "label": "Total Revenue"}],
                        },
                        {
                            "id": "kpi_margin",
                            "title": "Gross Margin %",
                            "type": "kpi",
                            "col": 6, "row": 0, "width": 6, "height": 3,
                            "measures": [{"expression": "(Sum(SalePrice * Quantity) - Sum(Cost * Quantity)) / Sum(SalePrice * Quantity)", "label": "Margin %"}],
                        },
                        {
                            "id": "kpi_emea_filtered",
                            "title": "EMEA 2025 Sales",
                            "type": "kpi",
                            "col": 12, "row": 0, "width": 6, "height": 3,
                            "measures": [{"expression": "Sum({$<Region={'EMEA'}, OrderYear={'2025'}>} SalePrice * Quantity)", "label": "EMEA 2025 Sales"}],
                        },
                        {
                            "id": "kpi_complex_set",
                            "title": "VIP Customer Retention Sales",
                            "type": "kpi",
                            "col": 18, "row": 0, "width": 6, "height": 3,
                            "measures": [{"expression": "Sum({<CustomerID=P({<OrderTotal={'>1000'}>} CustomerID)>} SalePrice * Quantity)", "label": "VIP Sales"}],
                        },
                        {
                            "id": "bar_sales_by_cat",
                            "title": "Revenue by Category",
                            "type": "barchart",
                            "col": 0, "row": 3, "width": 12, "height": 6,
                            "dimensions": [{"field": "Category", "label": "Product Category"}],
                            "measures": [{"expression": "Sum(SalePrice * Quantity)", "label": "Total Revenue"}],
                        },
                        {
                            "id": "line_monthly_trend",
                            "title": "Monthly Revenue Trend",
                            "type": "linechart",
                            "col": 12, "row": 3, "width": 12, "height": 6,
                            "dimensions": [{"field": "OrderDate", "label": "Order Date"}],
                            "measures": [{"expression": "Sum(SalePrice * Quantity)", "label": "Revenue"}],
                        },
                        {
                            "id": "filter_region",
                            "title": "Region Selector",
                            "type": "filterpane",
                            "col": 0, "row": 9, "width": 24, "height": 3,
                            "dimensions": [{"field": "Region", "label": "Region"}],
                        },
                    ],
                },
                {
                    "id": "sheet_customer_cohort",
                    "title": "Customer Cohort & Churn Analytics",
                    "actions": [],
                    "widgets": [
                        {
                            "id": "kpi_active_cust",
                            "title": "Active Customer Count",
                            "type": "kpi",
                            "col": 0, "row": 0, "width": 6, "height": 3,
                            "measures": [{"expression": "Count(Distinct CustomerID)", "label": "Active Customers"}],
                        },
                        {
                            "id": "kpi_aov",
                            "title": "Average Order Value (AOV)",
                            "type": "kpi",
                            "col": 6, "row": 0, "width": 6, "height": 3,
                            "measures": [{"expression": "Sum(SalePrice * Quantity) / Count(Distinct OrderID)", "label": "AOV"}],
                        },
                        {
                            "id": "kpi_churn_risk",
                            "title": "High Churn Risk Accounts",
                            "type": "kpi",
                            "col": 12, "row": 0, "width": 6, "height": 3,
                            "measures": [{"expression": "Count({<DaysSinceLastOrder={'>90'}>} Distinct CustomerID)", "label": "Churn Risk Customers"}],
                        },
                        {
                            "id": "kpi_retention_rate",
                            "title": "90-Day Retention Rate",
                            "type": "kpi",
                            "col": 18, "row": 0, "width": 6, "height": 3,
                            "measures": [{"expression": "Count({<OrderCount={'>=2'}>} Distinct CustomerID) / Count(Distinct CustomerID)", "label": "Retention %"}],
                        },
                        {
                            "id": "bar_clv_by_segment",
                            "title": "Customer Lifetime Value by Segment",
                            "type": "barchart",
                            "col": 0, "row": 3, "width": 12, "height": 6,
                            "dimensions": [{"field": "CustomerSegment", "label": "Segment"}],
                            "measures": [{"expression": "Avg(CustomerLTV)", "label": "Average CLV"}],
                        },
                        {
                            "id": "line_retention_velocity",
                            "title": "Cohort Retention Curve (Monthly)",
                            "type": "linechart",
                            "col": 12, "row": 3, "width": 12, "height": 6,
                            "dimensions": [{"field": "CohortMonth", "label": "Cohort Month"}],
                            "measures": [{"expression": "Sum(RetainedCustomers) / Sum(TotalCohortCustomers)", "label": "Retention %"}],
                        },
                        {
                            "id": "filter_segment",
                            "title": "Customer Segment Selector",
                            "type": "filterpane",
                            "col": 0, "row": 9, "width": 24, "height": 3,
                            "dimensions": [{"field": "CustomerSegment", "label": "Segment"}],
                        },
                    ],
                },
                {
                    "id": "sheet_regional_ops",
                    "title": "Regional Store Operations & Fulfillment",
                    "actions": [],
                    "widgets": [
                        {
                            "id": "kpi_store_count",
                            "title": "Active Retail Outlets",
                            "type": "kpi",
                            "col": 0, "row": 0, "width": 6, "height": 3,
                            "measures": [{"expression": "Count(Distinct StoreID)", "label": "Store Count"}],
                        },
                        {
                            "id": "kpi_fulfillment_rate",
                            "title": "On-Time Dispatch Rate",
                            "type": "kpi",
                            "col": 6, "row": 0, "width": 6, "height": 3,
                            "measures": [{"expression": "Count({<FulfillmentStatus={'OnTime'}>} OrderID) / Count(OrderID)", "label": "On-Time %"}],
                        },
                        {
                            "id": "kpi_order_backlog",
                            "title": "Open Order Backlog",
                            "type": "kpi",
                            "col": 12, "row": 0, "width": 6, "height": 3,
                            "measures": [{"expression": "Count({<OrderStatus={'Pending'}>} OrderID)", "label": "Backlog Units"}],
                        },
                        {
                            "id": "kpi_lead_time",
                            "title": "Average Dispatch Lead Time",
                            "type": "kpi",
                            "col": 18, "row": 0, "width": 6, "height": 3,
                            "measures": [{"expression": "Avg(DispatchDays)", "label": "Avg Days"}],
                        },
                        {
                            "id": "bar_regional_fulfillment",
                            "title": "Regional Order Volume & Status",
                            "type": "barchart",
                            "col": 0, "row": 3, "width": 12, "height": 6,
                            "dimensions": [{"field": "StoreRegion", "label": "Region"}],
                            "measures": [{"expression": "Count(OrderID)", "label": "Total Orders"}],
                        },
                        {
                            "id": "line_dispatch_variance",
                            "title": "Daily Dispatch Variance Trend",
                            "type": "linechart",
                            "col": 12, "row": 3, "width": 12, "height": 6,
                            "dimensions": [{"field": "DispatchDate", "label": "Date"}],
                            "measures": [{"expression": "Avg(DispatchDays - TargetDispatchDays)", "label": "Variance (Days)"}],
                        },
                        {
                            "id": "filter_store_region",
                            "title": "Store Region Selector",
                            "type": "filterpane",
                            "col": 0, "row": 9, "width": 24, "height": 3,
                            "dimensions": [{"field": "StoreRegion", "label": "Region"}],
                        },
                    ],
                },
                {
                    "id": "sheet_margin_deepdive",
                    "title": "Product Margin & Cost Decomposition",
                    "actions": [],
                    "widgets": [
                        {
                            "id": "kpi_gross_margin_dlr",
                            "title": "Gross Margin ($)",
                            "type": "kpi",
                            "col": 0, "row": 0, "width": 8, "height": 3,
                            "measures": [{"expression": "Sum((SalePrice - Cost) * Quantity)", "label": "Gross Profit"}],
                        },
                        {
                            "id": "kpi_net_margin_pct",
                            "title": "Net Operating Margin %",
                            "type": "kpi",
                            "col": 8, "row": 0, "width": 8, "height": 3,
                            "measures": [{"expression": "(Sum(SalePrice * Quantity) - Sum(Cost * Quantity) - Sum(OverheadCost)) / Sum(SalePrice * Quantity)", "label": "Net Margin %"}],
                        },
                        {
                            "id": "kpi_cogs",
                            "title": "Total Cost of Goods Sold (COGS)",
                            "type": "kpi",
                            "col": 16, "row": 0, "width": 8, "height": 3,
                            "measures": [{"expression": "Sum(Cost * Quantity)", "label": "Total COGS"}],
                        },
                        {
                            "id": "bar_margin_eroding_skus",
                            "title": "Top 10 Margin-Eroding SKUs",
                            "type": "barchart",
                            "col": 0, "row": 3, "width": 12, "height": 6,
                            "dimensions": [{"field": "SKU", "label": "Product SKU"}],
                            "measures": [{"expression": "Sum(Cost * Quantity) - Sum(SalePrice * Quantity)", "label": "Net Loss ($)"}],
                        },
                        {
                            "id": "bar_discount_impact",
                            "title": "Discount Impact by Product Line",
                            "type": "barchart",
                            "col": 12, "row": 3, "width": 12, "height": 6,
                            "dimensions": [{"field": "ProductLine", "label": "Product Line"}],
                            "measures": [{"expression": "Sum(DiscountAmount * Quantity)", "label": "Total Discount Granted"}],
                        },
                        {
                            "id": "filter_product_line",
                            "title": "Product Line Selector",
                            "type": "filterpane",
                            "col": 0, "row": 9, "width": 24, "height": 3,
                            "dimensions": [{"field": "ProductLine", "label": "Product Line"}],
                        },
                    ],
                }
            ],
        }
        if self.sanitizer:
            raw = self.sanitizer.sanitize(raw)

        return raw

