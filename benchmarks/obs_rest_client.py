"""Lightweight OBS REST API client using requests with V2 signature authentication.

This client is intentionally minimal — only the operations needed for benchmarking.
It uses the OBS V2 signature (HMAC-SHA1) for authentication.

Reference: https://support.huaweicloud.com/api-obs/obs_04_0010.html
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class OBSRestClient:
    """Minimal OBS REST API client with V2 signature auth."""

    def __init__(self, access_key: str, secret_key: str, endpoint: str):
        self.access_key = access_key
        self.secret_key = secret_key
        # endpoint like "https://obs.cn-north-4.myhuaweicloud.com"
        # Extract scheme and host for virtual-host style URLs
        self.endpoint = endpoint.rstrip("/")
        if "://" in self.endpoint:
            self.scheme, self.host = self.endpoint.split("://", 1)
        else:
            self.scheme, self.host = "https", self.endpoint
        self.session = requests.Session()
        self.session.trust_env = False  # Ignore proxy env vars
        retry = Retry(total=3, backoff_factor=0.3,
                      status_forcelist=[408, 429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=10)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.timeout = 60

    def _sign(
        self,
        method: str,
        bucket: str,
        key: str = "",
        headers: Optional[Dict[str, str]] = None,
        content_md5: str = "",
        content_type: str = "",
    ) -> Dict[str, str]:
        """Generate OBS V2 signature and return signed headers.

        StringToSign = HTTP-Verb + "\\n" +
                       Content-MD5 + "\\n" +
                       Content-Type + "\\n" +
                       Date + "\\n" +
                       CanonicalizedOBSHeaders +
                       CanonicalizedResource
        """
        date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        headers = dict(headers or {})

        # Build canonicalized OBS headers
        obs_headers = {}
        for k, v in headers.items():
            lower_k = k.lower()
            if lower_k.startswith("x-obs-"):
                obs_headers[lower_k] = v.strip()

        canonical_obs_headers = ""
        if obs_headers:
            for k in sorted(obs_headers):
                canonical_obs_headers += f"{k}:{obs_headers[k]}\n"

        # Build canonicalized resource (virtual-host style: /{bucket}/{key})
        resource = f"/{bucket}/"
        if key:
            resource += key

        string_to_sign = (
            f"{method}\n"
            f"{content_md5}\n"
            f"{content_type}\n"
            f"{date}\n"
            f"{canonical_obs_headers}"
            f"{resource}"
        )

        signature = base64.b64encode(
            hmac.new(
                self.secret_key.encode("utf-8"),
                string_to_sign.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("utf-8")

        headers["Date"] = date
        headers["Authorization"] = f"OBS {self.access_key}:{signature}"
        if content_type:
            headers["Content-Type"] = content_type
        if content_md5:
            headers["Content-MD5"] = content_md5

        return headers

    def _url(self, bucket: str, key: str = "") -> str:
        """Build the request URL using virtual-host style.

        OBS requires: https://{bucket}.{host}/{key}
        """
        base = f"{self.scheme}://{bucket}.{self.host}"
        if key:
            return f"{base}/{quote(key, safe='/')}"
        return base

    def put_object(self, bucket: str, key: str, data: bytes) -> requests.Response:
        """PUT an object."""
        content_type = "application/octet-stream"
        headers = self._sign("PUT", bucket, key, content_type=content_type)
        headers["Content-Length"] = str(len(data))
        resp = self.session.put(
            self._url(bucket, key), data=data, headers=headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp

    def get_object(self, bucket: str, key: str) -> bytes:
        """GET an object, return its bytes."""
        headers = self._sign("GET", bucket, key)
        resp = self.session.get(
            self._url(bucket, key), headers=headers, timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.content

    def head_object(self, bucket: str, key: str) -> Dict[str, str]:
        """HEAD an object, return response headers."""
        headers = self._sign("HEAD", bucket, key)
        resp = self.session.head(
            self._url(bucket, key), headers=headers, timeout=self.timeout,
        )
        resp.raise_for_status()
        return dict(resp.headers)

    def delete_object(self, bucket: str, key: str) -> requests.Response:
        """DELETE an object."""
        headers = self._sign("DELETE", bucket, key)
        resp = self.session.delete(
            self._url(bucket, key), headers=headers, timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp

    def list_objects(
        self, bucket: str, prefix: str = "", max_keys: int = 1000
    ) -> List[Dict[str, Any]]:
        """List objects in a bucket with optional prefix.

        Returns a list of dicts with 'Key', 'Size', 'LastModified'.
        """
        headers = self._sign("GET", bucket)
        params = {"prefix": prefix, "max-keys": str(max_keys)}
        resp = self.session.get(
            self._url(bucket), headers=headers, params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()

        # Parse XML response
        import xml.etree.ElementTree as ET

        root = ET.fromstring(resp.text)
        # OBS uses a default namespace
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        objects = []
        for contents in root.findall(f"{ns}Contents"):
            key_elem = contents.find(f"{ns}Key")
            size_elem = contents.find(f"{ns}Size")
            modified_elem = contents.find(f"{ns}LastModified")
            if key_elem is not None:
                obj = {"Key": key_elem.text}
                if size_elem is not None:
                    obj["Size"] = int(size_elem.text)
                if modified_elem is not None:
                    obj["LastModified"] = modified_elem.text
                objects.append(obj)

        return objects

    def copy_object(
        self, bucket: str, src_key: str, dst_key: str
    ) -> requests.Response:
        """Copy an object within the same bucket using x-obs-copy-source."""
        extra_headers = {
            "x-obs-copy-source": f"/{bucket}/{src_key}",
        }
        headers = self._sign(
            "PUT", bucket, dst_key, headers=extra_headers
        )
        headers["Content-Length"] = "0"
        resp = self.session.put(
            self._url(bucket, dst_key), headers=headers, data=b"",
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp

    def exists(self, bucket: str, key: str) -> bool:
        """Check if an object exists (HEAD, check status)."""
        headers = self._sign("HEAD", bucket, key)
        resp = self.session.head(
            self._url(bucket, key), headers=headers, timeout=self.timeout,
        )
        return resp.status_code == 200

    def mkdir(self, bucket: str, key: str) -> requests.Response:
        """Create a directory marker (empty object with trailing slash)."""
        if not key.endswith("/"):
            key = key + "/"
        content_type = "application/x-directory"
        headers = self._sign("PUT", bucket, key, content_type=content_type)
        headers["Content-Length"] = "0"
        resp = self.session.put(
            self._url(bucket, key), data=b"", headers=headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp
