"""WebSocket hub for extension instances.

Several browser profiles may run the extension at once (the user's Chrome plus a test
Chromium, or two profiles). Each keeps its own connection; a task is routed to the
instance best placed to run it: logged in to the platform and holding a tab, then logged in,
then holding a tab, then the most recently connected.

Protocol (JSON, every message has `type`):

  backend -> extension
    hello          { heartbeat_s, backend_version }
    task.dispatch  { id, platform, action, params, strategy, timeout_ms }
    task.cancel    { id }
    record.set     { platform, enabled }
    ping           { ts }

  extension -> backend
    auth           { token, extension_version, actions }   token may be "" when the Origin header is trusted;
                                                        actions = {platform: [page action names this build implements]}
    task.result    { id, ok, payload | error: {code, message} }
    capture        { platform, url, method, status, body, ts, task_id? }
    tab.state      { platform, logged_in, tab_ids }
    pong           { ts }
    log            { level, msg, ... }               mirrored into backend logs
"""

from __future__ import annotations

import asyncio
import itertools
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from fastapi import WebSocket, WebSocketDisconnect

from ..logging_setup import get_logger
from ..models.errors import ErrorCode, SocialLensError

log = get_logger("ws")

CaptureHandler = Callable[[dict[str, Any]], Awaitable[None]]
_conn_ids = itertools.count(1)

# Every build implements these in the page script; platform actions are advertised on auth.
GENERIC_PAGE_ACTIONS = frozenset({"echo", "fetch", "wait_capture", "read_global", "navigate", "scroll_capture", "dom_probe", "list_captures", "find_scripts", "read_element", "click", "type"})


@dataclass
class ExtConn:
    ws: WebSocket
    id: str
    version: str | None
    auth_method: str
    origin: str
    connected_at: str
    last_pong: float
    seq: int
    actions: dict[str, list[str]] = field(default_factory=dict)
    tab_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    heartbeat_task: asyncio.Task | None = None

    async def send(self, msg: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.ws.send_json(msg)

    def logged_in(self, platform: str) -> bool:
        return bool(self.tab_states.get(platform, {}).get("logged_in"))

    def supports(self, platform: str, action: str) -> bool:
        return action in GENERIC_PAGE_ACTIONS or action in self.actions.get(platform, ())

    def tabs(self, platform: str) -> list[int]:
        return list(self.tab_states.get(platform, {}).get("tab_ids") or [])

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "extension_version": self.version,
            "auth_method": self.auth_method,
            "connected_at": self.connected_at,
            "last_pong_age_s": round(time.monotonic() - self.last_pong, 1),
            "platforms": self.tab_states,
            "actions": self.actions,
        }


class ExtensionHub:
    def __init__(
        self,
        token: str,
        heartbeat_s: float,
        auth_timeout_s: float,
        backend_version: str,
        allowed_origins: set[str] | None = None,
    ):
        self._token = token
        self._allowed_origins = allowed_origins or set()
        self._heartbeat_s = heartbeat_s
        self._auth_timeout_s = auth_timeout_s
        self._backend_version = backend_version

        self._conns: dict[str, ExtConn] = {}
        self._pending: dict[str, tuple[asyncio.Future, str]] = {}  # task_id -> (future, conn_id)

        self.recording: set[str] = set()
        self.capture_handler: CaptureHandler | None = None

    # ---- state -------------------------------------------------------------

    @property
    def online(self) -> bool:
        return bool(self._conns)

    def _latest(self) -> ExtConn | None:
        return max(self._conns.values(), key=lambda c: c.seq) if self._conns else None

    def status(self) -> dict[str, Any]:
        latest = self._latest()
        return {
            "online": self.online,
            "connections": [c.describe() for c in sorted(self._conns.values(), key=lambda c: c.seq)],
            # Convenience fields describing the most recent instance.
            "extension_version": latest.version if latest else None,
            "auth_method": latest.auth_method if latest else None,
            "connected_at": latest.connected_at if latest else None,
            "last_pong_age_s": round(time.monotonic() - latest.last_pong, 1) if latest else None,
            "pending_tasks": len(self._pending),
        }

    @property
    def tab_states(self) -> dict[str, dict[str, Any]]:
        """Aggregated over all instances: logged_in if any is, tabs unioned."""
        out: dict[str, dict[str, Any]] = {}
        for c in self._conns.values():
            for platform, st in c.tab_states.items():
                agg = out.setdefault(platform, {"logged_in": False, "tab_ids": []})
                agg["logged_in"] = agg["logged_in"] or bool(st.get("logged_in"))
                agg["tab_ids"] = sorted(set(agg["tab_ids"]) | set(st.get("tab_ids") or []))
        return out

    def logged_in(self, platform: str) -> bool | None:
        state = self.tab_states.get(platform)
        return None if state is None else bool(state.get("logged_in"))

    def pick(self, platform: str, action: str = "echo", instance: str | None = None) -> ExtConn | None:
        if not self._conns:
            return None
        if instance:
            # Explicit pin (dev scripts keep their test browser separate from the user's).
            c = self._conns.get(instance)
            return c if c and (platform == "_system" or c.supports(platform, action)) else None
        if platform == "_system":
            return self._latest()
        capable = [c for c in self._conns.values() if c.supports(platform, action)]
        if not capable:
            return None

        def rank(c: ExtConn) -> tuple[int, int, int]:
            return (int(c.logged_in(platform)), int(bool(c.tabs(platform))), c.seq)

        return max(capable, key=rank)

    # ---- connection lifecycle ---------------------------------------------

    async def handle(self, ws: WebSocket) -> None:
        await ws.accept()
        try:
            first = await asyncio.wait_for(ws.receive_json(), timeout=self._auth_timeout_s)
        except (asyncio.TimeoutError, WebSocketDisconnect, ValueError):
            await ws.close(code=4001, reason="auth required")
            return
        origin = ws.headers.get("origin", "")
        origin_ok = origin in self._allowed_origins
        token_ok = bool(first.get("token")) and first.get("token") == self._token
        if first.get("type") != "auth" or not (origin_ok or token_ok):
            log.warning("extension auth rejected", origin=origin, had_token=bool(first.get("token")))
            await ws.close(code=4003, reason="unknown origin and bad token")
            return

        seq = next(_conn_ids)
        conn = ExtConn(
            ws=ws,
            id=f"ext{seq}",
            version=first.get("extension_version"),
            auth_method="origin" if origin_ok else "token",
            origin=origin,
            connected_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            last_pong=time.monotonic(),
            seq=seq,
            actions={k: list(v) for k, v in (first.get("actions") or {}).items() if isinstance(v, list)},
        )
        self._conns[conn.id] = conn
        log.info("extension connected", conn=conn.id, extension_version=conn.version, auth=conn.auth_method, instances=len(self._conns))

        try:
            await conn.send({"type": "hello", "heartbeat_s": self._heartbeat_s, "backend_version": self._backend_version})
            for platform in self.recording:
                await conn.send({"type": "record.set", "platform": platform, "enabled": True})
            conn.heartbeat_task = asyncio.create_task(self._heartbeat_loop(conn))
            while True:
                msg = await ws.receive_json()
                await self._on_message(conn, msg)
        except WebSocketDisconnect as e:
            log.info("extension disconnected", conn=conn.id, code=e.code)
        except Exception as e:  # noqa: BLE001
            log.error("extension connection error", conn=conn.id, error=repr(e))
        finally:
            await self._remove(conn, reason="disconnected")

    async def _remove(self, conn: ExtConn, reason: str) -> None:
        if self._conns.pop(conn.id, None) is None:
            return
        if conn.heartbeat_task:
            conn.heartbeat_task.cancel()
        for task_id, (fut, cid) in list(self._pending.items()):
            if cid == conn.id:
                self._pending.pop(task_id, None)
                if not fut.done():
                    fut.set_exception(SocialLensError(ErrorCode.EXTENSION_OFFLINE, f"extension {reason}"))
        try:
            await conn.ws.close()
        except Exception:  # noqa: BLE001
            pass
        log.info("extension removed", conn=conn.id, reason=reason, instances=len(self._conns))

    async def _heartbeat_loop(self, conn: ExtConn) -> None:
        try:
            while conn.id in self._conns:
                await asyncio.sleep(self._heartbeat_s)
                if time.monotonic() - conn.last_pong > self._heartbeat_s * 2.5:
                    log.warning("extension heartbeat lost", conn=conn.id)
                    await self._remove(conn, reason="heartbeat lost")
                    return
                await conn.send({"type": "ping", "ts": time.time()})
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            log.warning("heartbeat error", conn=conn.id, error=repr(e))

    # ---- messaging ---------------------------------------------------------

    async def broadcast(self, msg: dict[str, Any]) -> None:
        for c in list(self._conns.values()):
            try:
                await c.send(msg)
            except Exception:  # noqa: BLE001
                pass

    async def _on_message(self, conn: ExtConn, msg: dict[str, Any]) -> None:
        mtype = msg.get("type")
        if mtype == "pong":
            conn.last_pong = time.monotonic()
        elif mtype == "task.result":
            entry = self._pending.pop(msg.get("id", ""), None)
            if entry is None:
                return
            fut, _ = entry
            if fut.done():
                return
            if msg.get("ok"):
                fut.set_result(msg.get("payload"))
            else:
                err = msg.get("error") or {}
                fut.set_exception(
                    SocialLensError(
                        err.get("code", ErrorCode.EXTENSION_ERROR),
                        err.get("message", "extension reported failure"),
                        err.get("details"),
                    )
                )
        elif mtype == "tab.state":
            platform = msg.get("platform")
            if platform:
                conn.tab_states[platform] = {
                    "logged_in": bool(msg.get("logged_in")),
                    "tab_ids": list(msg.get("tab_ids") or []),
                }
        elif mtype == "capture":
            if self.capture_handler:
                await self.capture_handler(msg)
        elif mtype == "log":
            level = str(msg.get("level", "info")).lower()
            fields = {k: v for k, v in msg.items() if k not in ("type", "level", "msg")}
            getattr(log, level if level in ("debug", "info", "warning", "error") else "info")(
                f"[ext] {msg.get('msg', '')}", conn=conn.id, **fields
            )
        else:
            log.debug("unknown message from extension", mtype=mtype, conn=conn.id)

    async def dispatch(self, task_msg: dict[str, Any], timeout_s: float) -> Any:
        instance = (task_msg.get("params") or {}).get("_instance")
        conn = self.pick(task_msg.get("platform", "_system"), task_msg.get("action", "echo"), instance)
        if conn is None:
            if instance:
                raise SocialLensError(ErrorCode.EXTENSION_OFFLINE, f"extension instance {instance} is not connected or lacks the action")
            if self._conns:
                raise SocialLensError(
                    ErrorCode.UNSUPPORTED,
                    f"no connected extension build implements {task_msg.get('platform')}.{task_msg.get('action')}; reload the extension in chrome://extensions",
                )
            raise SocialLensError(ErrorCode.EXTENSION_OFFLINE, "extension is not connected")
        task_id = task_msg["id"]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[task_id] = (fut, conn.id)
        log.debug("task routed", task_id=task_id, conn=conn.id)
        try:
            await conn.send({"type": "task.dispatch", **task_msg})
            return await asyncio.wait_for(fut, timeout=timeout_s)
        except asyncio.TimeoutError:
            await self.cancel(task_id)
            raise SocialLensError(ErrorCode.TIMEOUT, f"task {task_id} timed out after {timeout_s}s")
        finally:
            self._pending.pop(task_id, None)

    async def cancel(self, task_id: str) -> None:
        entry = self._pending.pop(task_id, None)
        if entry is None:
            return
        fut, cid = entry
        conn = self._conns.get(cid)
        if conn:
            try:
                await conn.send({"type": "task.cancel", "id": task_id})
            except Exception:  # noqa: BLE001
                pass
        if not fut.done():
            fut.cancel()

    async def set_recording(self, platform: str, enabled: bool) -> None:
        if enabled:
            self.recording.add(platform)
        else:
            self.recording.discard(platform)
        await self.broadcast({"type": "record.set", "platform": platform, "enabled": enabled})
