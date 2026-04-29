"""
ExtensionManager — singleton that owns the Chrome extension WebSocket.

Each browser action is a typed RPC:
  server  → extension : {type: "browser_command", request_id, action, args}
  extension → server  : {type: "browser_action_result", request_id, result}
                      | {type: "browser_action_error",  request_id, error}
                      | {type: "browser_event", event, ...}

Futures bridge the async gap: send_command() creates a Future, sends the
command, then awaits the Future.  resolve() / reject() settle it when the
extension replies.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import WebSocket

_log = logging.getLogger("extension_manager")

MAX_PENDING       = 100
MAX_WATCH_COUNT   = 10
MIN_DEBOUNCE_MS   = 200
MAX_DEBOUNCE_MS   = 60_000


class ExtensionManager:
    def __init__(self) -> None:
        self._ws:       WebSocket | None = None
        self._pending:  dict[str, asyncio.Future] = {}
        self._connected: bool = False
        self._send_lock = asyncio.Lock()

        # watch_id → async callback(watch_id, data)
        self._watch_callbacks: dict[str, Callable[[str, dict], Awaitable[None]]] = {}

        # Registered callbacks to fire when connection state changes
        # Callable receives (connected: bool)
        self._status_listeners: list[Callable[[bool], Awaitable[None]]] = []

        # Session linking — the extension's chat is routed to the most recently
        # active frontend session.  Set by server.py after each session_info push.
        self.linked_session_id: str = ""
        self.linked_device_id:  str = ""   # extension's own fallback device ID

        # The currently-running ext chat task.  Cancelled on reconnect to avoid
        # leaving a stale _chat_busy=True that blocks new messages.
        self._chat_task: asyncio.Task | None = None

    # ── Connection lifecycle ──────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self, ws: WebSocket) -> None:
        """Called when the extension's WebSocket connects."""
        if self._connected:
            # Close the old one gracefully before accepting the new connection.
            # (Extension restarted / reconnected.)
            self._cancel_all_pending("Extension reconnected — prior connection replaced")
        # Cancel any lingering chat task from a previous connection.
        # Without this, a stale _chat_busy=True on the shared engine would
        # silently reject the first message after every reconnect.
        if self._chat_task and not self._chat_task.done():
            self._chat_task.cancel()
            self._chat_task = None
        self._ws = ws
        self._connected = True
        _log.info("Extension connected")
        await self._notify_status(True)

    def disconnect(self, ws: WebSocket | None = None) -> None:
        """Called when the extension WebSocket closes.

        Pass the WebSocket that closed so we can guard against a stale handler
        tearing down a newer connection.  When two connections race (double-
        connect on SW restart), the old handler's finally fires AFTER the new
        handler has already called connect(); without the guard it would stomp
        self._ws = None and self._connected = False on the live new connection.
        """
        # If a specific ws is given and it's not our current one, it means a
        # newer connection has already taken over — do nothing.
        if ws is not None and ws is not self._ws:
            _log.info("Extension disconnect ignored — stale WS reference")
            return
        if not self._connected and self._ws is None:
            return  # already disconnected
        self._connected = False
        self._ws = None
        n = len(self._pending)
        self._cancel_all_pending("Extension disconnected")
        _log.info("Extension disconnected — %d pending commands cancelled", n)
        # Do NOT clear linked_session_id here — it is used by extension_hello on
        # reconnect to send the correct session back.  It is intentionally kept so
        # the extension resumes the same conversation after a SW restart.
        asyncio.get_event_loop().create_task(self._notify_status(False))

    def _cancel_all_pending(self, reason: str) -> None:
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(ConnectionError(reason))
        self._pending.clear()

    async def _notify_status(self, connected: bool) -> None:
        for cb in list(self._status_listeners):
            try:
                await cb(connected)
            except Exception:
                pass

    def add_status_listener(self, cb: Callable[[bool], Awaitable[None]]) -> None:
        self._status_listeners.append(cb)

    def remove_status_listener(self, cb: Callable[[bool], Awaitable[None]]) -> None:
        self._status_listeners.discard(cb) if hasattr(self._status_listeners, 'discard') else None
        try:
            self._status_listeners.remove(cb)
        except ValueError:
            pass

    # ── Command dispatch ──────────────────────────────────────────────────────

    async def send_command(
        self,
        action: str,
        args: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send a typed command to the extension and await the response.

        Returns a dict.  On error the dict contains {"error": ..., "message": ...}.
        This never raises — errors are returned as structured dicts so Claude
        can read them and respond naturally.
        """
        if not self._connected or self._ws is None:
            return {
                "error": "extension_not_connected",
                "message": (
                    "The Chika Chrome extension is not connected. "
                    "Install it from the extension/ directory and enable it in Chrome."
                ),
            }

        if len(self._pending) >= MAX_PENDING:
            return {
                "error": "too_many_pending",
                "message": "Extension command queue is full. Try again in a moment.",
            }

        request_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[request_id] = fut

        try:
            async with self._send_lock:
                await self._ws.send_json({
                    "type":       "browser_command",
                    "request_id": request_id,
                    "action":     action,
                    "args":       args,
                })
        except Exception as exc:
            self._pending.pop(request_id, None)
            self.disconnect()
            _log.warning("send_command failed: %s", exc)
            return {"error": "send_failed", "message": str(exc)}

        try:
            result = await asyncio.wait_for(fut, timeout=timeout)
            return result
        except TimeoutError:
            self._pending.pop(request_id, None)
            return {
                "error":   "timeout",
                "message": f"Browser action '{action}' timed out after {timeout}s.",
            }
        except ConnectionError as exc:
            return {"error": "extension_disconnected", "message": str(exc)}

    def resolve(self, request_id: str, result: dict[str, Any]) -> None:
        fut = self._pending.pop(request_id, None)
        if fut and not fut.done():
            fut.set_result(result)

    def reject(self, request_id: str, error: str) -> None:
        fut = self._pending.pop(request_id, None)
        if fut and not fut.done():
            fut.set_result({"error": error})

    def cancel_command(self, request_id: str) -> None:
        """Cancel an in-flight command (e.g. when a workflow is aborted)."""
        fut = self._pending.pop(request_id, None)
        if fut and not fut.done():
            fut.set_result({"error": "cancelled", "message": "Command cancelled by workflow engine"})

    def set_chat_task(self, task: asyncio.Task | None) -> None:
        """Register the currently-running ext chat task so it can be cancelled on reconnect."""
        self._chat_task = task

    # ── Watch callbacks ───────────────────────────────────────────────────────

    def register_watch_callback(
        self,
        watch_id: str,
        callback: Callable[[str, dict], Awaitable[None]],
    ) -> None:
        self._watch_callbacks[watch_id] = callback

    def unregister_watch(self, watch_id: str) -> None:
        self._watch_callbacks.pop(watch_id, None)

    def watch_count(self) -> int:
        return len(self._watch_callbacks)

    async def handle_watch_trigger(self, watch_id: str, data: dict) -> None:
        cb = self._watch_callbacks.get(watch_id)
        if cb:
            try:
                await cb(watch_id, data)
            except Exception as exc:
                _log.warning("watch callback error for %s: %s", watch_id, exc)

    async def handle_watch_cancelled(self, watch_id: str, reason: str) -> None:
        self.unregister_watch(watch_id)
        _log.info("Watch %s cancelled: %s", watch_id, reason)

    # ── Raw push (for keep-alive pong etc.) ──────────────────────────────────

    async def send_raw(self, data: dict) -> bool:
        """Fire-and-forget send.  Returns False if send failed."""
        if not self._connected or self._ws is None:
            return False
        try:
            async with self._send_lock:
                await self._ws.send_json(data)
            return True
        except Exception:
            self.disconnect()
            return False


# Module-level singleton — imported by both server.py and browser_skill/__init__.py
extension_manager = ExtensionManager()
