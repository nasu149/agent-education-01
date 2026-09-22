"""Synthetic write probe used by monitoring and post-remediation verification.

The business application is intentionally unchanged. This probe exercises the existing
CRUD API by creating and immediately deleting a short-lived member record.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx


async def synthetic_write_probe(
    app_base_url: str,
    *,
    timeout_seconds: float = 4.0,
) -> dict[str, Any]:
    """Verify that the application can perform a real database write.

    The probe uses only the existing public CRUD API:
    POST /api/members -> DELETE /api/members/{id}.

    A unique email avoids collisions. If the POST transaction fails, PostgreSQL rolls
    it back, so no synthetic member remains. If creation succeeds, deletion is attempted
    immediately before the probe is considered healthy.
    """

    marker = uuid.uuid4().hex[:12]
    payload = {
        "name": "Synthetic Health Check",
        "department": "training-monitor",
        "email": f"health-check-{marker}@example.local",
    }

    base = app_base_url.rstrip("/")
    create_url = f"{base}/api/members"

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            create = await client.post(create_url, json=payload)
        except httpx.HTTPError as exc:
            return {
                "healthy": False,
                "stage": "create",
                "status_code": None,
                "error": type(exc).__name__,
                "detail": str(exc),
            }

        create_body = create.text[:2000]
        if create.status_code != 201:
            return {
                "healthy": False,
                "stage": "create",
                "status_code": create.status_code,
                "body": create_body,
            }

        try:
            created = create.json()
            member_id = int(created["id"])
        except (ValueError, TypeError, KeyError):
            return {
                "healthy": False,
                "stage": "create-response",
                "status_code": create.status_code,
                "body": create_body,
                "detail": "POST succeeded but response did not contain an integer id",
            }

        delete_url = f"{base}/api/members/{member_id}"
        try:
            delete = await client.delete(delete_url)
        except httpx.HTTPError as exc:
            return {
                "healthy": False,
                "stage": "delete",
                "status_code": None,
                "created_member_id": member_id,
                "error": type(exc).__name__,
                "detail": str(exc),
            }

        if delete.status_code != 200:
            return {
                "healthy": False,
                "stage": "delete",
                "status_code": delete.status_code,
                "created_member_id": member_id,
                "body": delete.text[:2000],
            }

    return {
        "healthy": True,
        "stage": "complete",
        "status_code": 200,
        "created_member_id": member_id,
        "email": payload["email"],
    }
