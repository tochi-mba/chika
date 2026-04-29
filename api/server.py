"""
Chika v2 FastAPI server.

- Binds to 0.0.0.0 — accessible on LAN and internet
- WebSocket /ws/ — full streaming event pipeline (device-owned sessions)
- REST endpoints for metadata and session state
- Optional API key auth via CHIKA_API_KEY env var
- Serves frontend/dist/ as static files in production
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# ── Windows event-loop policy ────────────────────────────────────────────────
# uvicorn on Windows defaults to the Selector event loop, which does NOT
# support subprocess creation. asyncio.create_subprocess_shell then raises
# `NotImplementedError` on EVERY shell_exec call from a WebSocket handler.
# Force the Proactor policy so shell commands actually work in the server.
# (No-op on non-Windows platforms.)
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from api.readme_html import README_HTML
from api.session_manager import session_manager
from chika.core.device_store import DeviceStore
from chika.skills.browser_skill import set_frontend_push
from chika.skills.browser_skill.extension_manager import extension_manager
from chika.skills.spotify_skill import oauth as spotify_oauth
from chika.tools.shell_tool import ProcessRegistry

app = FastAPI(title="Chika v2", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

# ── Auth ─────────────────────────────────────────────────────────────────────

async def require_auth(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency — reads Authorization: Bearer <key> header.
    Raises 401 if CHIKA_API_KEY is set and the header doesn't match.
    """
    required = config.CHIKA_API_KEY
    if not required:
        return  # auth disabled
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization[len("Bearer "):]
    if token != required:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ── Frontend socket registry (for broadcasting extension events) ──────────────
# All connected frontend WebSockets are tracked here so that browser tool
# events (watch triggers, extension status) can be pushed from outside the
# per-request handler (e.g. from the /ws/extension/ endpoint).

_frontend_sockets: set[WebSocket] = set()
_frontend_send_lock = asyncio.Lock()


async def push_to_all_frontend_sessions(event: dict) -> None:
    """Broadcast an event to every connected frontend WebSocket."""
    dead: set[WebSocket] = set()
    for ws in list(_frontend_sockets):
        try:
            await ws.send_json(event)
        except Exception:
            dead.add(ws)
    _frontend_sockets.difference_update(dead)


# Wire up browser skill so it can push watch events to the frontend.
set_frontend_push(push_to_all_frontend_sessions)


# ── Extension status broadcaster ──────────────────────────────────────────────

async def _on_extension_status(connected: bool) -> None:
    await push_to_all_frontend_sessions({
        "type":      "extension_status",
        "connected": connected,
    })


extension_manager.add_status_listener(_on_extension_status)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "provider": config.PROVIDER, "model": config.get_provider_config().model}


# ── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws/")
async def websocket_endpoint(
    websocket: WebSocket,
    token:  str = Query(default=""),
    device: str = Query(default=""),
):
    # ── Auth ──────────────────────────────────────────────────────────────────
    required = config.CHIKA_API_KEY
    if required and token != required:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    _frontend_sockets.add(websocket)

    # ── Device identification ─────────────────────────────────────────────────
    # device_id is an opaque token the client echoes back from the first
    # session_info event.  On first connection it's empty → we generate one.
    device_id = device.strip() if device.strip() else DeviceStore.new_device_id()
    is_new = not session_manager._device_store.exists(device_id)
    from chika.core.logger import log as _log
    _log.info("ws_connect", device_id=device_id, new_device=is_new)
    print(f"[WS] CONNECTED device={device_id} new={is_new}", flush=True)

    engine, session_id = session_manager.get_device_session(device_id)

    # ── Serialised send ───────────────────────────────────────────────────────
    send_lock = asyncio.Lock()

    async def send(data: dict) -> None:
        async with send_lock:
            await websocket.send_json(data)

    # ── Helper: push session state to frontend ────────────────────────────────
    async def _send_session_info(eng, sid: str) -> None:
        msgs = [
            {"role": m["role"], "text": m.get("content") or ""}
            for m in eng._history
            if m.get("role") in ("user", "assistant")
            and isinstance(m.get("content"), str)
            and m["content"].strip()
        ]
        p = eng._active_profile
        await send({
            "type":       "session_info",
            "device_id":  device_id,
            "session_id": sid,
            "title":      eng._title,
            "messages":   msgs,
            "profile":    p.name if p else "default",
            "workspace":  p.workspace if p else "",
        })

    async def _send_chat_list(eng) -> None:
        p = eng._active_profile
        profile_name = p.name if p else "default"
        chats = session_manager._chat_store.list_chats(profile_name)
        await send({"type": "chat_list", "chats": chats, "profile": profile_name})

    async def _send_profile(eng) -> None:
        p = eng._active_profile
        await send({
            "type":      "profile_info",
            "name":      p.name if p else "default",
            "workspace": p.workspace if p else "",
        })

    # ── Extension session linking ─────────────────────────────────────────────
    # Whenever this frontend tab's session changes, tell the extension so it
    # can route chat messages to the same conversation.
    def _recent_msgs(eng):
        return [
            {"role": m["role"], "text": m.get("content") or ""}
            for m in eng._history
            if m.get("role") in ("user", "assistant")
            and isinstance(m.get("content"), str)
            and m["content"].strip()
        ][-40:]  # last 40 messages (20 turns)

    async def _notify_extension_session(eng, sid: str) -> None:
        """Push current session identity + recent history to extension."""
        extension_manager.linked_session_id = sid
        p = eng._active_profile
        await extension_manager.send_raw({
            "type":       "linked_session",
            "session_id": sid,
            "title":      eng._title,
            "profile":    p.name if p else "default",
            "messages":   _recent_msgs(eng),
        })

    # Send initial state
    await _send_session_info(engine, session_id)
    await _send_chat_list(engine)
    await _send_profile(engine)
    await _notify_extension_session(engine, session_id)

    # ── Per-connection approval queue state ───────────────────────────────────
    # Futures: request_id → Future[{"approved": bool, "password": str}]
    # Resolved by _ws_recv_loop when an approval_response arrives.
    _approval_futures: dict[str, asyncio.Future] = {}

    # Lock ensures only ONE approval dialog is shown at a time.
    # Parallel workflow steps queue up and each waits its turn.
    _approval_lock = asyncio.Lock()

    # Non-approval WS messages are queued here; main loop drains this.
    _incoming: asyncio.Queue = asyncio.Queue()

    # Mutable container so _ws_recv_loop can cancel the current chat task.
    _current_chat: list = [None]  # _current_chat[0] = asyncio.Task | None

    pm = session_manager._profile_manager  # shorthand for password checks

    # ── Approval handler ──────────────────────────────────────────────────────
    async def approval_handler(
        request_id: str, tool: str, args: dict,
        step_id: str = "", message: str = "",
        approval_type: str = "confirm",
    ) -> bool:
        """Serialised approval: queues requests, shows one dialog at a time.

        Dynamically upgrades approval_type based on profile password state:
        - profile_switch  → verify_password if target has a password
        - profile_create  → set_password (offer optional password for new profile)
                            but verify_password if the profile already exists with a password
        - set_profile_password → set_password (comes from ToolDefinition)

        The workflow engine's approval_required event is suppressed in the
        forwarding loop; this handler is the sole sender at the right time.
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        _approval_futures[request_id] = fut

        # ── Dynamic type resolution ───────────────────────────────────────────
        actual_type    = approval_type
        actual_message = message

        if tool == "profile_switch":
            target = args.get("name", "")
            if target and pm.has_password(target):
                actual_type    = "verify_password"
                actual_message = f"Enter password to switch to profile '{target}'"

        elif tool == "profile_create":
            safe_name = args.get("name", "").strip().lower().replace(" ", "_")
            if pm.exists(safe_name) and pm.has_password(safe_name):
                # Already exists with a password → verify rather than set
                actual_type    = "verify_password"
                actual_message = (
                    f"Profile '{safe_name}' exists. Enter its password to switch."
                )
            else:
                # Brand-new profile — offer optional password
                actual_type    = "set_password"
                actual_message = (
                    f"Create profile '{safe_name}'."
                    " Optionally set a password (leave blank for none)."
                )

        elif tool == "set_profile_password":
            p = engine._active_profile
            name = p.name if p else "current profile"
            actual_type    = "set_password"
            actual_message = (
                f"Set or remove password for profile '{name}'."
                " Leave blank to remove the current password."
            )

        try:
            # Only one approval dialog shown at a time.
            async with _approval_lock:
                await send({
                    "type":          "approval_required",
                    "request_id":    request_id,
                    "tool":          tool,
                    "args":          args,
                    "step_id":       step_id,
                    "message":       actual_message,
                    "approval_type": actual_type,
                })
                # Await the future; CancelledError propagates cleanly.
                response: dict = await fut   # {"approved": bool, "password": str}

            # ── Post-approval side-effects ────────────────────────────────────
            if not response.get("approved", False):
                return False

            password = response.get("password", "")

            if actual_type == "set_password":
                if tool == "profile_create":
                    # Inject password into args so profile_create tool persists it.
                    args["_password"] = password
                elif tool == "set_profile_password":
                    p = engine._active_profile
                    if p and p.name != "default":
                        pm.set_password(p.name, password)
                # (Other set_password tools: no-op — password collected for UI only)

            elif actual_type == "verify_password":
                target = args.get("name", "")
                if not pm.verify_password(target, password):
                    try:
                        await send({
                            "type":       "error",
                            "message":    f"Wrong password for profile '{target}'.",
                            "error_code": "wrong_password",
                        })
                    except Exception:
                        pass
                    return False

            return True

        except asyncio.CancelledError:
            raise  # propagate so the chat task is properly cancelled
        except Exception:
            return False
        finally:
            _approval_futures.pop(request_id, None)

    engine._workflow_engine.approval_handler = approval_handler

    # ── ask_user question handler ─────────────────────────────────────────────
    # Futures: request_id → Future[{"choice": str, "choice_index": int, ...}]
    _question_futures: dict[str, asyncio.Future] = {}

    async def question_handler(
        *, request_id: str, question: str, options: list, header: str = "",
        multi_select: bool = False,
    ) -> dict:
        """Emit a user_question event and await the user's selection.

        Shape of response: {
          "choice": "<label>",           # single select
          "choice_index": N,
          "choices": ["a", "b"],          # multi select (if enabled)
          "choice_indices": [0, 1],
          "notes": "free-text notes"
        }
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        _question_futures[request_id] = fut
        try:
            await send({
                "type":         "user_question",
                "request_id":   request_id,
                "question":     question,
                "options":      options,
                "header":       header,
                "multi_select": multi_select,
            })
            return await fut
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return {"error": str(exc)}
        finally:
            _question_futures.pop(request_id, None)

    engine._workflow_engine.question_handler = question_handler

    # ── WS reader task ────────────────────────────────────────────────────────
    # Single reader — no other code touches websocket.receive_text() after this.
    async def _ws_recv_loop() -> None:
        try:
            while True:
                try:
                    raw = await websocket.receive_text()
                except Exception:
                    break
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                mtype = msg.get("type")

                if mtype == "ping":
                    # Respond inline — no need to go through the main loop.
                    try:
                        await send({"type": "pong"})
                    except Exception:
                        break

                elif mtype == "approval_response":
                    # Route to the waiting future — resolve with full payload dict.
                    rid = msg.get("request_id")
                    fut = _approval_futures.get(rid)
                    if fut and not fut.done():
                        fut.set_result({
                            "approved": bool(msg.get("approved", False)),
                            "password": str(msg.get("password", "")),
                        })

                elif mtype == "user_question_response":
                    # Route ask_user answer to the waiting future.
                    rid = msg.get("request_id")
                    fut = _question_futures.get(rid)
                    if fut and not fut.done():
                        choices = msg.get("choices") or []
                        choice_indices = msg.get("choice_indices") or []
                        fut.set_result({
                            "choice":         str(msg.get("choice", "")),
                            "choice_index":   int(msg.get("choice_index", -1)),
                            "choices":        [str(c) for c in choices],
                            "choice_indices": [int(i) for i in choice_indices],
                            "notes":          str(msg.get("notes", "")),
                        })

                else:
                    await _incoming.put(msg)

        finally:
            # WS is gone — cancel the running chat turn so it doesn't hang
            # waiting for an approval future that will never be resolved.
            task = _current_chat[0]
            if task and not task.done():
                task.cancel()
            # Cancel all outstanding approval futures.
            for fut in list(_approval_futures.values()):
                if not fut.done():
                    fut.cancel()
            _approval_futures.clear()
            # Wake up the main loop so it can exit cleanly.
            await _incoming.put({"type": "_disconnect"})

    # ── Background process monitor ────────────────────────────────────────────
    async def process_monitor() -> None:
        cursors: dict[int, list] = {}
        try:
            while True:
                await asyncio.sleep(0.2)
                for proc in ProcessRegistry.all():
                    pid = proc["pid"]
                    managed = ProcessRegistry.get(pid)
                    if managed is None:
                        continue
                    if pid not in cursors:
                        cursors[pid] = [0, 0, True]
                        try:
                            await send({"type": "shell_process_start", "pid": pid, "command": managed.command})
                        except Exception:
                            return
                    so_pos, se_pos, was_running = cursors[pid]
                    new_out = managed.stdout_buf[so_pos:]
                    if new_out:
                        cursors[pid][0] += len(new_out)
                        try:
                            await send({"type": "shell_output", "pid": pid, "stream": "stdout", "lines": new_out})
                        except Exception:
                            return
                    new_err = managed.stderr_buf[se_pos:]
                    if new_err:
                        cursors[pid][1] += len(new_err)
                        try:
                            await send({"type": "shell_output", "pid": pid, "stream": "stderr", "lines": new_err})
                        except Exception:
                            return
                    if was_running and not managed.running:
                        cursors[pid][2] = False
                        try:
                            await send({"type": "shell_process_done", "pid": pid, "exit_code": managed.exit_code})
                        except Exception:
                            return
        except asyncio.CancelledError:
            pass

    recv_task    = asyncio.create_task(_ws_recv_loop())
    monitor_task = asyncio.create_task(process_monitor())

    # ── Main message loop ─────────────────────────────────────────────────────
    try:
        while True:
            msg   = await _incoming.get()
            mtype = msg.get("type")

            if mtype == "_disconnect":
                break

            print(f"[WS] MSG session={session_id} type={mtype}", flush=True)

            # ── User chat message ─────────────────────────────────────────────
            if mtype == "user_message":
                text = msg.get("text", "").strip()
                if not text:
                    continue
                print(f"[WS] CHAT text={text[:60]!r}", flush=True)

                async def _run_chat(user_text: str) -> None:
                    try:
                        async for event in engine.chat(user_text):
                            etype = event.get("type", "")
                            # Suppress internal events.
                            # Also suppress approval_required — the approval_handler
                            # sends it at the right time (after acquiring the lock).
                            if etype.startswith("_") or etype == "approval_required":
                                continue
                            try:
                                await send(event)
                            except Exception:
                                return  # WS closed mid-stream
                            if etype == "chat_title":
                                try:
                                    await _send_chat_list(engine)
                                except Exception:
                                    pass
                            if (etype == "tool_result"
                                    and event.get("tool") in ("profile_switch", "profile_create")
                                    and not event.get("error")):
                                try:
                                    await _send_profile(engine)
                                    await _send_chat_list(engine)
                                except Exception:
                                    pass
                    except asyncio.CancelledError:
                        raise  # let the task be properly cancelled
                    except Exception as exc:
                        import traceback; traceback.print_exc()
                        _log.exc("chat_exception", device_id=device_id)
                        try:
                            await send({"type": "error", "message": str(exc)})
                            await send({"type": "done"})
                        except Exception:
                            pass

                task = asyncio.create_task(_run_chat(text))
                _current_chat[0] = task
                try:
                    await task
                except asyncio.CancelledError:
                    pass  # WS disconnected; _ws_recv_loop already cancelled the task
                except Exception as exc:
                    import traceback; traceback.print_exc()
                    try:
                        await send({"type": "error", "message": str(exc)})
                        await send({"type": "done"})
                    except Exception:
                        pass
                finally:
                    _current_chat[0] = None

            # ── Stop / cancel current generation ─────────────────────────────
            elif mtype == "stop":
                engine.cancel()

            # ── New chat ──────────────────────────────────────────────────────
            elif mtype == "new_chat":
                # Preserve the current profile — new chat, same user context
                current_profile = engine._active_profile
                engine, session_id = session_manager.new_chat_for_device(device_id)
                engine._workflow_engine.approval_handler = approval_handler
                if current_profile and current_profile.name != "default":
                    engine.switch_profile(current_profile)
                await _send_session_info(engine, session_id)
                await _send_chat_list(engine)
                await _send_profile(engine)
                await _notify_extension_session(engine, session_id)

            # ── Switch to existing chat ───────────────────────────────────────
            elif mtype == "switch_chat":
                chat_id = msg.get("chat_id", "").strip()
                if chat_id:
                    engine, session_id = session_manager.switch_device_chat(device_id, chat_id)
                    engine._workflow_engine.approval_handler = approval_handler
                    await _send_session_info(engine, session_id)
                    await _send_chat_list(engine)
                    await _send_profile(engine)
                    await _notify_extension_session(engine, session_id)

            # ── Delete a chat ─────────────────────────────────────────────────
            elif mtype == "delete_chat":
                chat_id = msg.get("chat_id", "").strip()
                if chat_id:
                    current_profile = engine._active_profile
                    profile_name = current_profile.name if current_profile else "default"
                    session_manager._chat_store.delete(profile_name, chat_id)
                    session_manager.delete(chat_id)
                    if chat_id == session_id:
                        engine, session_id = session_manager.new_chat_for_device(device_id)
                        engine._workflow_engine.approval_handler = approval_handler
                        # Keep the same profile after deletion
                        if current_profile and current_profile.name != "default":
                            engine.switch_profile(current_profile)
                        await _send_session_info(engine, session_id)
                        await _notify_extension_session(engine, session_id)
                    await _send_chat_list(engine)

            # ── Profile switch (from UI switcher) ─────────────────────────────
            elif mtype == "switch_profile_request":
                name = msg.get("name", "").strip().lower().replace(" ", "_")
                if not name:
                    continue
                exists = pm.exists(name)

                # Determine approval type based on password state
                if not exists:
                    req_type     = "set_password"
                    action_label = (
                        f"Create profile '{name}'."
                        " Optionally set a password (leave blank for none)."
                    )
                elif pm.has_password(name):
                    req_type     = "verify_password"
                    action_label = f"Enter password to switch to profile '{name}'"
                else:
                    req_type     = "confirm"
                    action_label = f"Switch to profile '{name}'"

                request_id = f"appr_ui_{name}_{int(asyncio.get_running_loop().time()*1000)}"
                ui_fut: asyncio.Future = asyncio.get_running_loop().create_future()
                _approval_futures[request_id] = ui_fut
                try:
                    await send({
                        "type":          "approval_required",
                        "request_id":    request_id,
                        "tool":          "profile_create" if not exists else "profile_switch",
                        "args":          {"name": name},
                        "step_id":       "ui_profile_switch",
                        "message":       action_label,
                        "approval_type": req_type,
                    })
                    response = await ui_fut   # {"approved": bool, "password": str}
                    approved = response.get("approved", False)
                    password = response.get("password", "")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    approved, password = False, ""
                finally:
                    _approval_futures.pop(request_id, None)

                if not approved:
                    continue

                # Verify password for existing profile
                if req_type == "verify_password" and not pm.verify_password(name, password):
                    try:
                        await send({
                            "type":       "error",
                            "message":    f"Wrong password for profile '{name}'.",
                            "error_code": "wrong_password",
                        })
                    except Exception:
                        pass
                    continue

                profile = pm.get_or_create(name)

                # Set password for new profile if provided
                if not exists and password:
                    pm.set_password(name, password)

                engine.switch_profile(profile)
                await _send_profile(engine)
                await _send_chat_list(engine)
                await send({"type": "profile_switch_done", "name": name})

            elif mtype == "reset":
                engine.reset()
                await send({"type": "reset_done", "session_id": session_id})

    except Exception:
        pass

    finally:
        _frontend_sockets.discard(websocket)
        recv_task.cancel()
        monitor_task.cancel()
        try:
            await asyncio.gather(recv_task, monitor_task, return_exceptions=True)
        except Exception:
            pass


# ── Extension WebSocket ───────────────────────────────────────────────────────
# Helper: extract recent chat history as [{role, text}] for extension popup
def _ext_recent_msgs(eng, limit: int = 40) -> list[dict]:
    return [
        {"role": m["role"], "text": m.get("content") or ""}
        for m in eng._history
        if m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str)
        and m["content"].strip()
    ][-limit:]


@app.websocket("/ws/extension/")
async def websocket_extension_endpoint(
    websocket: WebSocket,
    token: str = Query(default=""),
):
    """Dedicated command/control channel for the Chika Chrome extension.

    Handles two layers over one WebSocket:
      1. Browser RPC commands  (browser_command / browser_action_result)
      2. Extension chat turns  (extension_chat_message / ext_chat_*)

    Uses a separate reader task so approval/question responses can arrive
    while a chat streaming task is awaiting the LLM — exactly like /ws/.
    """
    required = config.CHIKA_API_KEY
    if required and token != required:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    await extension_manager.connect(websocket)

    await websocket.send_json({
        "type":             "extension_ready",
        "server_version":   "2.0",
        "protocol_version": 1,
    })

    # ── Keep-alive ping ───────────────────────────────────────────────────────
    async def _ping_loop() -> None:
        while extension_manager.connected:
            await asyncio.sleep(25)
            if not await extension_manager.send_raw({"type": "ping"}):
                break

    ping_task = asyncio.create_task(_ping_loop())

    # ── Shared state for extension chat ──────────────────────────────────────
    # Futures live here (outside the chat loop) so the reader task can resolve
    # them while a chat streaming task is running.
    _ext_approval_futures: dict[str, asyncio.Future] = {}
    _ext_question_futures: dict[str, asyncio.Future] = {}
    _ext_chat_task: list = [None]   # mutable container so closures can cancel

    # ── Approval / question handlers (routed over extension WS) ──────────────
    async def _ext_approval_handler(
        request_id: str, tool: str, args: dict,
        step_id: str = "", message: str = "",
        approval_type: str = "confirm",
    ) -> bool:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        _ext_approval_futures[request_id] = fut
        try:
            await extension_manager.send_raw({
                "type":          "approval_required",
                "request_id":    request_id,
                "tool":          tool,
                "args":          args,
                "step_id":       step_id,
                "message":       message or f"Allow: {tool}",
                "approval_type": approval_type,
            })
            resp = await asyncio.wait_for(fut, timeout=120.0)
            return resp.get("approved", False)
        except (TimeoutError, asyncio.CancelledError):
            return False
        except Exception:
            return False
        finally:
            _ext_approval_futures.pop(request_id, None)

    async def _ext_question_handler(
        *, request_id: str, question: str, options: list,
        header: str = "", multi_select: bool = False,
    ) -> dict:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        _ext_question_futures[request_id] = fut
        try:
            await extension_manager.send_raw({
                "type":         "user_question",
                "request_id":   request_id,
                "question":     question,
                "options":      options,
                "header":       header,
                "multi_select": multi_select,
            })
            return await asyncio.wait_for(fut, timeout=120.0)
        except (TimeoutError, asyncio.CancelledError):
            return {"error": "timeout"}
        except Exception as exc:
            return {"error": str(exc)}
        finally:
            _ext_question_futures.pop(request_id, None)

    # ── Incoming message queue (reader task → main loop) ─────────────────────
    _incoming: asyncio.Queue = asyncio.Queue()

    async def _ext_recv_loop() -> None:
        """Read all WebSocket messages into the queue so nothing blocks."""
        try:
            while True:
                try:
                    raw = await websocket.receive_text()
                except Exception:
                    break
                try:
                    _incoming.put_nowait(json.loads(raw))
                except Exception:
                    pass
        finally:
            await _incoming.put({"type": "_disconnect"})

    recv_task = asyncio.create_task(_ext_recv_loop())

    # ── Main dispatch loop ────────────────────────────────────────────────────
    try:
        while True:
            msg = await _incoming.get()
            msg_type = msg.get("type")

            if msg_type == "_disconnect":
                break

            # ── Browser RPC ───────────────────────────────────────────────────
            if msg_type == "browser_action_result":
                extension_manager.resolve(msg.get("request_id", ""), msg.get("result", {}))

            elif msg_type == "browser_action_error":
                extension_manager.reject(msg.get("request_id", ""), msg.get("error", "unknown_error"))

            elif msg_type == "browser_event":
                event_name = msg.get("event")
                if event_name == "watch_trigger":
                    asyncio.create_task(extension_manager.handle_watch_trigger(
                        msg.get("watch_id", ""), msg.get("data", {})))
                elif event_name == "watch_cancelled":
                    asyncio.create_task(extension_manager.handle_watch_cancelled(
                        msg.get("watch_id", ""), msg.get("reason", "unknown")))

            elif msg_type == "pong":
                pass

            # ── Extension identity ────────────────────────────────────────────
            elif msg_type == "extension_hello":
                ext_did = msg.get("device_id", "").strip()
                print(f"[EXT] extension_hello device={ext_did!r} linked_sid={extension_manager.linked_session_id!r}", flush=True)
                if ext_did:
                    extension_manager.linked_device_id = ext_did
                    # Always send linked_session on every hello — this covers
                    # SW-kill reconnects where the extension lost its session
                    # ID in memory, even though server still had linked_session_id
                    # set from before.  The extension needs the canonical session
                    # ID on every reconnect.
                    if not extension_manager.linked_session_id:
                        # No frontend has linked yet — give extension its own
                        # persistent device session.
                        ext_eng, ext_sid = session_manager.get_device_session(ext_did)
                        extension_manager.linked_session_id = ext_sid
                        print(f"[EXT] no prior session → created device session {ext_sid!r}", flush=True)
                    else:
                        # Reuse the already-linked session (e.g. frontend tab
                        # linked it while extension was disconnected).
                        ext_sid = extension_manager.linked_session_id
                        ext_eng = session_manager.get(ext_sid)
                        if ext_eng is None:
                            # Linked session expired — fall back to device session
                            ext_eng, ext_sid = session_manager.get_device_session(ext_did)
                            extension_manager.linked_session_id = ext_sid
                            print(f"[EXT] prior session expired → created device session {ext_sid!r}", flush=True)
                        else:
                            print(f"[EXT] reusing existing session {ext_sid!r}", flush=True)
                    p = ext_eng._active_profile
                    sent = await extension_manager.send_raw({
                        "type":       "linked_session",
                        "session_id": ext_sid,
                        "title":      ext_eng._title,
                        "profile":    p.name if p else "default",
                        "messages":   _ext_recent_msgs(ext_eng),
                    })
                    print(f"[EXT] linked_session sent={sent} sid={ext_sid!r}", flush=True)
                else:
                    print("[EXT] extension_hello missing device_id — ignored", flush=True)

            # ── Extension chat ────────────────────────────────────────────────
            elif msg_type == "extension_chat_message":
                text       = msg.get("text", "").strip()
                session_id_hint = msg.get("session_id", "").strip()
                ext_device = msg.get("device_id", "").strip()
                active_tab = msg.get("active_tab")  # {url, title, text?} from popup
                print(f"[EXT] extension_chat_message text={text[:40]!r} sid_hint={session_id_hint!r} device={ext_device!r}", flush=True)

                if not text:
                    continue

                # Cancel any running extension chat (shouldn't happen normally)
                if _ext_chat_task[0] and not _ext_chat_task[0].done():
                    _ext_chat_task[0].cancel()

                # Resolve engine: linked frontend session → extension own session
                ext_engine = None
                resolved_sid = session_id_hint or extension_manager.linked_session_id
                if resolved_sid:
                    ext_engine = session_manager.get(resolved_sid)
                if ext_engine is None and ext_device:
                    ext_engine, resolved_sid = session_manager.get_device_session(ext_device)
                    # Session hint was stale — update server state and re-notify
                    # extension so all future messages use the correct session.
                    if ext_engine is not None:
                        extension_manager.linked_session_id = resolved_sid
                        p = ext_engine._active_profile
                        await extension_manager.send_raw({
                            "type":       "linked_session",
                            "session_id": resolved_sid,
                            "title":      ext_engine._title,
                            "profile":    p.name if p else "default",
                            "messages":   _ext_recent_msgs(ext_engine),
                        })
                if ext_engine is None:
                    # No session at all — let the extension work standalone by
                    # creating a fresh device session rather than hard-failing.
                    if ext_device:
                        ext_engine, resolved_sid = session_manager.get_device_session(ext_device)
                        extension_manager.linked_session_id = resolved_sid
                        p = ext_engine._active_profile
                        await extension_manager.send_raw({
                            "type":       "linked_session",
                            "session_id": resolved_sid,
                            "title":      ext_engine._title,
                            "profile":    p.name if p else "default",
                            "messages":   _ext_recent_msgs(ext_engine),
                        })
                    else:
                        await extension_manager.send_raw({
                            "type":    "ext_chat_error",
                            "message": "Could not create a session — check the server is running.",
                        })
                        await extension_manager.send_raw({"type": "ext_chat_done"})
                        continue

                print(f"[EXT] resolved engine sid={resolved_sid!r} busy={ext_engine._chat_busy}", flush=True)
                if ext_engine._chat_busy:
                    await extension_manager.send_raw({
                        "type":       "ext_chat_error",
                        "message":    "Chika is busy — wait for the current response to finish.",
                        "error_code": "engine_busy",
                    })
                    await extension_manager.send_raw({"type": "ext_chat_done"})
                    continue

                # Enrich message with active-tab context so Claude knows what
                # page the user is looking at without having to call browser tools
                enriched_text = text
                if active_tab:
                    url   = active_tab.get("url", "")
                    title = active_tab.get("title", "")
                    tab_text = active_tab.get("text", "")  # optional page text snapshot
                    if url:
                        ctx_lines = [f"[Active browser tab: {title!r} — {url}]"]
                        if tab_text:
                            snippet = tab_text[:2000]
                            ctx_lines.append(f"[Page text snippet: {snippet!r}]")
                        enriched_text = "\n".join(ctx_lines) + "\n\n" + text

                # Wire extension approval/question handlers
                prev_approval = ext_engine._workflow_engine.approval_handler
                prev_question = ext_engine._workflow_engine.question_handler
                ext_engine._workflow_engine.approval_handler = _ext_approval_handler
                ext_engine._workflow_engine.question_handler = _ext_question_handler

                async def _run_ext_chat(
                    user_text: str, display_text: str, eng, _prev_a, _prev_q
                ) -> None:
                    try:
                        print(f"[EXT] _run_ext_chat starting text={user_text[:40]!r}", flush=True)
                        await extension_manager.send_raw({"type": "ext_chat_start"})
                        print("[EXT] ext_chat_start sent", flush=True)
                        # Tell the frontend a new turn has started from the extension
                        # so it can add the user message and open the streaming slot.
                        await push_to_all_frontend_sessions({
                            "type":      "ext_chat_turn",
                            "user_text": display_text,
                        })
                        async for event in eng.chat(user_text):
                            etype = event.get("type", "")
                            if etype.startswith("_") or etype == "approval_required":
                                continue
                            if etype == "done":
                                await extension_manager.send_raw({"type": "ext_chat_done"})
                            else:
                                await extension_manager.send_raw(event)
                            # Mirror to all frontend sockets so the main tab
                            # shows the extension's conversation turn in real time.
                            try:
                                await push_to_all_frontend_sessions(event)
                            except Exception:
                                pass
                    except asyncio.CancelledError:
                        print("[EXT] _run_ext_chat cancelled", flush=True)
                        raise
                    except Exception as exc:
                        print(f"[EXT] _run_ext_chat EXCEPTION: {exc}", flush=True)
                        import traceback; traceback.print_exc()
                        try:
                            await extension_manager.send_raw({
                                "type": "ext_chat_error", "message": str(exc)
                            })
                            await extension_manager.send_raw({"type": "ext_chat_done"})
                            # Also tell the frontend the turn ended with an error
                            await push_to_all_frontend_sessions({
                                "type": "error", "message": str(exc)
                            })
                            await push_to_all_frontend_sessions({"type": "done"})
                        except Exception:
                            pass
                    finally:
                        eng._workflow_engine.approval_handler = _prev_a
                        eng._workflow_engine.question_handler = _prev_q

                t = asyncio.create_task(
                    _run_ext_chat(enriched_text, text, ext_engine, prev_approval, prev_question)
                )
                _ext_chat_task[0] = t
                # Register with extension_manager so reconnect can cancel it
                # and avoid leaving _chat_busy=True on the shared engine.
                extension_manager.set_chat_task(t)
                t.add_done_callback(lambda _: extension_manager.set_chat_task(None))
                # Do NOT await here — fall through so the recv loop keeps running
                # and can handle approval_response / question_response messages
                # that arrive while the chat is streaming.

            # ── Extension approval response ───────────────────────────────────
            elif msg_type == "extension_approval_response":
                rid = msg.get("request_id", "")
                fut = _ext_approval_futures.get(rid)
                if fut and not fut.done():
                    fut.set_result({
                        "approved": bool(msg.get("approved", False)),
                        "password": str(msg.get("password", "")),
                    })

            # ── Extension question response ───────────────────────────────────
            elif msg_type == "extension_question_response":
                rid = msg.get("request_id", "")
                fut = _ext_question_futures.get(rid)
                if fut and not fut.done():
                    fut.set_result({
                        "choice":         str(msg.get("choice", "")),
                        "choice_index":   int(msg.get("choice_index", -1)),
                        "choices":        [str(c) for c in (msg.get("choices") or [])],
                        "choice_indices": [int(i) for i in (msg.get("choice_indices") or [])],
                        "notes":          str(msg.get("notes", "")),
                    })

    except Exception as _ext_exc:
        import traceback
        print(f"[EXT] FATAL extension WS handler: {_ext_exc}", flush=True)
        traceback.print_exc()
    finally:
        recv_task.cancel()
        ping_task.cancel()
        if _ext_chat_task[0] and not _ext_chat_task[0].done():
            _ext_chat_task[0].cancel()
        # Cancel any pending futures so handlers don't hang
        for fut in list(_ext_approval_futures.values()):
            if not fut.done():
                fut.cancel()
        for fut in list(_ext_question_futures.values()):
            if not fut.done():
                fut.cancel()
        try:
            await asyncio.gather(recv_task, ping_task, return_exceptions=True)
        except Exception:
            pass
        # Pass the websocket so disconnect() can detect if a newer connection
        # has already replaced this one and skip the teardown in that case.
        extension_manager.disconnect(websocket)


# ── REST — Extension status ───────────────────────────────────────────────────

@app.get("/api/extension/status")
async def extension_status(_: None = Depends(require_auth)):
    return {
        "connected":   extension_manager.connected,
        "watch_count": extension_manager.watch_count(),
    }


# ── REST — Profiles ──────────────────────────────────────────────────────────

@app.get("/api/profiles")
async def list_profiles(_: None = Depends(require_auth)):
    pm = session_manager._profile_manager
    return {"profiles": pm.list_profiles()}


# ── REST — Sessions ───────────────────────────────────────────────────────────

@app.get("/api/sessions")
async def list_sessions(_: None = Depends(require_auth)):
    return {"sessions": session_manager.list_sessions()}


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str, _: None = Depends(require_auth)):
    session_manager.delete(session_id)
    return {"deleted": session_id}


@app.post("/api/session/{session_id}/reset")
async def reset_session(session_id: str, _: None = Depends(require_auth)):
    engine = session_manager.get(session_id)
    if engine:
        engine.reset()
    return {"reset": session_id}


# ── REST — Session state ──────────────────────────────────────────────────────

@app.get("/api/session/{session_id}/variables")
async def get_variables(session_id: str, _: None = Depends(require_auth)):
    engine = session_manager.get(session_id)
    if not engine:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"variables": engine._vars.list_summary()}


@app.get("/api/session/{session_id}/memory")
async def get_memory(session_id: str, _: None = Depends(require_auth)):
    engine = session_manager.get(session_id)
    if not engine:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"memory": engine._memory.all_entries()}


@app.get("/api/session/{session_id}/history")
async def get_history(session_id: str, _: None = Depends(require_auth)):
    engine = session_manager.get(session_id)
    if not engine:
        raise HTTPException(status_code=404, detail="Session not found")
    # Strip system messages from the returned history (they're huge)
    history = [m for m in engine._history if m.get("role") != "system"]
    return {"history": history, "count": len(history)}


# ── REST — Registry metadata ──────────────────────────────────────────────────

@app.get("/api/tools")
async def get_tools(_: None = Depends(require_auth)):
    # Use a dummy session to get the registry
    engine = session_manager.get_or_create("__meta__")
    tools = []
    for name in engine._tools.names():
        t = engine._tools.get(name)
        if t:
            tools.append({"name": t.name, "description": t.description, "parameters": t.parameters})
    return {"tools": tools, "count": len(tools)}


@app.get("/api/skills")
async def get_skills(_: None = Depends(require_auth)):
    engine = session_manager.get_or_create("__meta__")
    return {"skills": engine._skills.list_skills()}


@app.get("/api/workflows")
async def get_workflows(_: None = Depends(require_auth)):
    engine = session_manager.get_or_create("__meta__")
    return {"workflows": list(engine._workflow_engine._sub_workflows.keys())}


@app.get("/api/config")
async def get_public_config(_: None = Depends(require_auth)):
    cfg = config.get_provider_config()
    return {
        "provider": cfg.provider,
        "model": cfg.model,
        "max_history_tokens": config.MAX_HISTORY_TOKENS,
        "max_tool_turns": config.MAX_TOOL_TURNS,
        "auth_enabled": bool(config.CHIKA_API_KEY),
    }


@app.get("/auth/spotify")
async def spotify_auth_start():
    """Redirect to Spotify authorization page."""
    if not spotify_oauth.CLIENT_ID:
        return HTMLResponse("<h2>CHIKA_SPOTIFY_CLIENT_ID not set in .env</h2>", status_code=400)
    url, _state, _verifier = spotify_oauth.build_auth_url()
    return RedirectResponse(url)


@app.get("/auth/spotify/callback")
async def spotify_auth_callback(code: str = Query(""), state: str = Query(""), error: str = Query("")):
    """Spotify OAuth callback — exchanges code for tokens."""
    if error:
        return HTMLResponse(f"""
        <html><body style="font-family:sans-serif;background:#0d0d0f;color:#e8e8f0;padding:40px">
        <h2>❌ Spotify authorization failed</h2><p>{error}</p>
        <a href="/" style="color:#6c63ff">← Back to Chika</a>
        </body></html>""")
    result = await spotify_oauth.exchange_code(code, state)
    if "error" in result:
        return HTMLResponse(f"""
        <html><body style="font-family:sans-serif;background:#0d0d0f;color:#e8e8f0;padding:40px">
        <h2>❌ Token exchange failed</h2><p>{result['error']}</p>
        <a href="/" style="color:#6c63ff">← Back to Chika</a>
        </body></html>""")
    return HTMLResponse("""
    <html><body style="font-family:sans-serif;background:#0d0d0f;color:#e8e8f0;padding:40px;text-align:center">
    <h2>✅ Spotify authorized successfully!</h2>
    <p style="color:#888;margin:16px 0">You can close this tab and return to Chika.</p>
    <script>setTimeout(() => window.close(), 2000)</script>
    <a href="/" style="color:#6c63ff">← Back to Chika</a>
    </body></html>""")


@app.get("/auth/spotify/status")
async def spotify_auth_status_endpoint():
    """Check Spotify auth status and return auth URL if needed."""
    status = spotify_oauth.auth_status()
    if not status["authorized"] and status.get("has_refresh"):
        await spotify_oauth.refresh_access_token()
        status = spotify_oauth.auth_status()
    if not status["authorized"]:
        try:
            url, _, _ = spotify_oauth.build_auth_url()
            status["auth_url"] = url
        except Exception:
            pass
    return status


# ── REST — Chat history ───────────────────────────────────────────────────────

@app.get("/api/profile/{profile_name}/chats")
async def list_profile_chats(profile_name: str, _: None = Depends(require_auth)):
    chats = session_manager._chat_store.list_chats(profile_name)
    return chats

@app.delete("/api/profile/{profile_name}/chats/{chat_id}")
async def delete_profile_chat(
    profile_name: str, chat_id: str, _: None = Depends(require_auth)
):
    deleted = session_manager._chat_store.delete(profile_name, chat_id)
    # Also remove from memory if loaded
    session_manager.delete(chat_id)
    return {"deleted": deleted, "id": chat_id}


# ── API docs ─────────────────────────────────────────────────────────────────

@app.get("/readme", include_in_schema=False)
async def api_readme():
    """Human-readable API documentation — no auth required."""
    return HTMLResponse(README_HTML)


# ── Static files (production) ─────────────────────────────────────────────────

_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
else:
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def frontend_not_built():
        return HTMLResponse("""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Chika — Build required</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #0a0a0a; color: #e5e5e5; display: flex;
           align-items: center; justify-content: center; min-height: 100vh; }
    .card { background: #141414; border: 1px solid #262626; border-radius: 12px;
            padding: 40px 48px; max-width: 520px; width: 100%; }
    h1 { font-size: 22px; font-weight: 600; color: #fff; margin-bottom: 8px; }
    p  { color: #888; font-size: 14px; line-height: 1.6; margin-bottom: 24px; }
    .step { background: #0a0a0a; border: 1px solid #262626; border-radius: 8px;
            padding: 16px 20px; margin-bottom: 12px; }
    .step code { font-family: 'SF Mono', Consolas, monospace; font-size: 13px;
                 color: #7dd3fc; display: block; margin-top: 6px; }
    .step span { font-size: 12px; color: #555; }
    .alt { margin-top: 24px; padding-top: 24px; border-top: 1px solid #262626; }
    .alt p { margin-bottom: 0; }
    a { color: #7dd3fc; text-decoration: none; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Frontend not built yet</h1>
    <p>The server is running but the Vue frontend hasn't been compiled. Build it once:</p>
    <div class="step">
      <span>1. Install Node dependencies</span>
      <code>cd frontend &amp;&amp; npm install</code>
    </div>
    <div class="step">
      <span>2. Build</span>
      <code>npm run build</code>
    </div>
    <div class="step">
      <span>3. Restart the server</span>
      <code>python api/server.py</code>
    </div>
    <div class="alt">
      <p>No Node.js? Use the <a href="#">CLI instead</a>: <code style="display:inline;color:#7dd3fc">chika</code> or <code style="display:inline;color:#7dd3fc">python chika.py</code></p>
    </div>
  </div>
</body>
</html>""")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.server:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=True,
        reload_dirs=["chika", "api"],
        # Force asyncio loop so our Proactor policy (set above) sticks.
        # Without this, uvicorn may select a different loop that can't
        # spawn subprocesses on Windows.
        loop="asyncio",
    )
