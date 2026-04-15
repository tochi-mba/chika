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
import secrets
import sys
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from api.session_manager import session_manager
from api.readme_html import README_HTML
from chika.core.device_store import DeviceStore
from chika.tools.shell_tool import ProcessRegistry
from chika.skills.spotify_skill import oauth as spotify_oauth

app = FastAPI(title="Chika v2", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

    # Send initial state
    await _send_session_info(engine, session_id)
    await _send_chat_list(engine)
    await _send_profile(engine)

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

            # ── Switch to existing chat ───────────────────────────────────────
            elif mtype == "switch_chat":
                chat_id = msg.get("chat_id", "").strip()
                if chat_id:
                    engine, session_id = session_manager.switch_device_chat(device_id, chat_id)
                    engine._workflow_engine.approval_handler = approval_handler
                    await _send_session_info(engine, session_id)
                    await _send_chat_list(engine)
                    await _send_profile(engine)

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
        recv_task.cancel()
        monitor_task.cancel()
        try:
            await asyncio.gather(recv_task, monitor_task, return_exceptions=True)
        except Exception:
            pass


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


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.server:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=True,
        reload_dirs=["chika", "api"],
    )
