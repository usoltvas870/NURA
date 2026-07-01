import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from admin_bot.config import AdminBotConfig

logger = logging.getLogger(__name__)

DOCKER_SOCK = "/var/run/docker.sock"

# Docker multiplexed log stream header is 8 bytes
DOCKER_LOG_HEADER_SIZE = 8


class DockerClient:
    def __init__(self, config: AdminBotConfig | None = None) -> None:
        self.config = config or AdminBotConfig()
        self._transport: httpx.AsyncHTTPTransport | None = None

    def _get_transport(self) -> httpx.AsyncHTTPTransport:
        if self._transport is None:
            self._transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCK)
        return self._transport

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        transport = self._get_transport()
        async with httpx.AsyncClient(transport=transport, timeout=30.0) as client:
            resp = await client.request(method, f"http://localhost{path}", **kwargs)
            resp.raise_for_status()
            return resp

    async def list_containers(self) -> list[dict]:
        if not os.path.exists(DOCKER_SOCK):
            logger.warning("Docker socket not available at %s", DOCKER_SOCK)
            return []

        try:
            resp = await self._request("GET", "/containers/json?all=true")
            raw = resp.json()
        except Exception as e:
            logger.exception("Failed to list containers: %s", e)
            return []

        result: list[dict] = []
        for c in raw:
            names = c.get("Names", [])
            name = ""
            for n in names:
                n = n.lstrip("/")
                if self.config.project_prefix in n:
                    name = n
                    break
            if not name:
                continue
            # extract service name: nura_app-api-1 -> api
            parts = name.split("-")
            svc_name = parts[1] if len(parts) >= 3 else name

            state = c.get("State", "unknown")
            status = c.get("Status", "unknown")
            health = ""

            # check health if available
            health_data = (c.get("Health") or {}).get("Status", "")
            if health_data:
                health = health_data

            result.append({
                "id": c["Id"],
                "name": svc_name,
                "full_name": name,
                "state": state,
                "status": status,
                "health": health,
            })
        return result

    async def get_container_id(self, service: str) -> str | None:
        containers = await self.list_containers()
        for c in containers:
            if c["name"] == service:
                return c["id"]
        return None

    async def get_container_logs(
        self,
        service: str,
        lines: int = 100,
        since_minutes: int | None = None,
    ) -> list[str]:
        container_id = await self.get_container_id(service)
        if not container_id:
            raise ValueError(f"Container for service '{service}' not found")

        params: dict[str, Any] = {
            "stdout": "true",
            "stderr": "true",
            "tail": lines,
            "timestamps": "false",
        }
        if since_minutes:
            since_ts = int((datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).timestamp())
            params["since"] = since_ts

        try:
            resp = await self._request(
                "GET",
                f"/containers/{container_id}/logs",
                params=params,
            )
            return self._parse_docker_multiplexed(resp.content)
        except Exception as e:
            logger.exception("Failed to get logs for %s: %s", service, e)
            return []

    def _parse_docker_multiplexed(self, raw_bytes: bytes) -> list[str]:
        lines: list[str] = []
        i = 0
        while i + DOCKER_LOG_HEADER_SIZE <= len(raw_bytes):
            size = int.from_bytes(raw_bytes[i + 4 : i + 8], "big")
            i += DOCKER_LOG_HEADER_SIZE
            if i + size > len(raw_bytes):
                break
            payload = raw_bytes[i : i + size]
            i += size
            try:
                text = payload.decode("utf-8", errors="replace")
            except Exception:
                continue
            for line in text.split("\n"):
                stripped = line.strip()
                if stripped:
                    lines.append(stripped)
        return lines

    async def restart_container(self, service: str) -> bool:
        container_id = await self.get_container_id(service)
        if not container_id:
            logger.error("Container for service '%s' not found", service)
            return False

        try:
            await self._request("POST", f"/containers/{container_id}/restart")
            logger.info("Container %s restarted successfully", service)
            return True
        except Exception as e:
            logger.exception("Failed to restart %s: %s", service, e)
            return False

    async def check_api_health(self) -> bool:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("http://localhost:8000/health")
            return resp.status_code == 200

    async def run_deploy(self) -> str:
        import subprocess  # noqa: S404

        commands = [
            ["git", "-C", "/opt/nura", "pull", "origin", "main"],
            ["docker", "compose", "-f", "/opt/nura/nura_app/docker-compose.yml", "up", "-d", "--build"],
        ]
        output_parts: list[str] = []
        for cmd in commands:
            logger.info("Running: %s", " ".join(cmd))
            try:
                result = subprocess.run(  # noqa: S602
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                out = result.stdout.strip()
                err = result.stderr.strip()
                if out:
                    output_parts.append(f"$ {' '.join(cmd)}\n{out}")
                if err:
                    output_parts.append(f"$ {' '.join(cmd)} [stderr]\n{err}")
                if result.returncode != 0:
                    output_parts.append(f"⚠️ Exit code: {result.returncode}")
            except subprocess.TimeoutExpired:
                output_parts.append(f"⏰ Timed out: {' '.join(cmd)}")
            except FileNotFoundError:
                output_parts.append(f"❌ Command not found: {cmd[0]}")
        return "\n\n".join(output_parts)

    async def clear_redis_cache(self) -> bool:
        try:
            import redis.asyncio as aioredis  # noqa: N812

            from core.config import settings

            r = aioredis.from_url(settings.redis_url)
            await r.flushdb()
            await r.aclose()
            logger.info("Redis cache cleared")
            return True
        except Exception as e:
            logger.exception("Failed to clear Redis cache: %s", e)
            return False

    async def run_db_query(self, sql: str) -> list[dict] | str:
        from core.database import get_async_sessionmaker
        from sqlalchemy import text

        session_factory = get_async_sessionmaker()
        async with session_factory() as session:
            result = await session.execute(text(sql))
            if result.returns_rows:
                rows = result.all()
                if not rows:
                    return []
                columns = list(result.keys())
                return [dict(zip(columns, row, strict=False)) for row in rows]
            return "Query executed (no rows returned)"
