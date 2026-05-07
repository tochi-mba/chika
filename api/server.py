"""
Chika v2 FastAPI server.

- Binds to 0.0.0.0 — accessible on LAN and internet
- WebSocket /ws/ — full streaming event pipeline (device-owned sessions)
- WebSocket /ws/extension/ — Chrome extension command/control channel
- REST endpoints organised in api/routes/ via APIRouter
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
#
# Both ``set_event_loop_policy`` and ``WindowsProactorEventLoopPolicy``
# are deprecated in Python 3.14+ and slated for removal in 3.16. The
# replacement is to pass a ``loop_factory`` to ``asyncio.Runner`` /
# ``asyncio.run``, but uvicorn manages its own loop lifecycle and
# doesn't expose a factory hook — so we still need the policy call
# until uvicorn ships a forward-compat option. Silence the warning so
# CI logs stay clean; revisit when we bump uvicorn or Python ≥ 3.16.
if sys.platform == "win32":
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass

from fastapi import FastAPI, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
import api.settings_store as settings_store
from api.broadcast import _frontend_sockets, _frontend_sockets_lock
from api.session_manager import session_manager
from chika.core.device_store import DeviceStore
from chika.core.logger import log as _log
from chika.tools.shell_tool import ProcessRegistry

from api.routes import health as health_routes
from api.routes import profiles as profiles_routes
from api.routes import sessions as sessions_routes
from api.routes import registry as registry_routes
from api.routes import config as config_routes
from api.routes import env as env_routes
from api.routes import settings as settings_routes
from api.routes import chat_history as chat_history_routes
from api.routes import docs as docs_routes
from api.routes import shells as shells_routes
from api.routes import skill_ui as skill_ui_routes
from api.routes import static as static_routes
# Per-skill routes/websockets/CLI come from the skill packages
# themselves — we walk them at boot rather than importing each by name.
from chika.skills import (
    iter_skill_routers,
    iter_skill_websocket_registrars,
)

app = FastAPI(title="Chika v2", version="2.0.0")

# Initialise runtime settings from env-var defaults.
# Disk value wins on restart; env var only seeds the first-ever write.
settings_store.init({"autonomy": config.AUTONOMY_MODE})

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PUT", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

# ── REST routes ───────────────────────────────────────────────────────────────
# Core platform routes — health, profiles, sessions, etc. — live in
# api/routes/. Skill-specific routes (spotify connect, pet selection,
# extension status...) live INSIDE the skill folder and mount via the
# skill walk below.
app.include_router(health_routes.router)
app.include_router(profiles_routes.router)
app.include_router(sessions_routes.router)
app.include_router(registry_routes.router)
app.include_router(config_routes.router)
app.include_router(env_routes.router)
app.include_router(settings_routes.router)
app.include_router(chat_history_routes.router)
app.include_router(docs_routes.router)
app.include_router(shells_routes.router)
app.include_router(skill_ui_routes.router)

# Auto-mount any router exposed by a skill via ``register_routes()``.
# Each skill folder owns its full HTTP surface — drop the skill,
# the routes go with it.
for _skill_name, _skill_router in iter_skill_routers():
    app.include_router(_skill_router)  # type: ignore[arg-type]

# Same for websockets — skills own their own ``@app.websocket(...)``
# endpoints via ``register_websocket(app)``.
for _skill_name, _ws_register in iter_skill_websocket_registrars():
    try:
        _ws_register(app)  # type: ignore[operator]
    except Exception as _exc:  # pragma: no cover - boot-time guard
        _log.info("skill.ws.register.failed", skill=_skill_name, error=str(_exc))
# Static mount happens AFTER WebSocket handlers so Starlette's routing table
# has the specific /ws/* paths registered before the catch-all StaticFiles "/".


# ── WebSocket /ws/ ─────────────────────────────────────────────────────────────

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
    async with _frontend_sockets_lock:
        _frontend_sockets.add(websocket)

    # ── Device identification ─────────────────────────────────────────────────
    # device_id is an opaque token the client echoes back from the first
    # session_info event.  On first connection it's empty → we generate one.
    device_id = device.strip() if device.strip() else DeviceStore.new_device_id()
    is_new = not session_manager._device_store.exists(device_id)
    _log.info("ws.connect", device_id=device_id, new_device=is_new)

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
            "profile":    p.name if p else "unknown",
            "workspace":  p.workspace if p else "",
        })

    async def _send_chat_list(eng) -> None:
        p = eng._active_profile
        profile_name = p.name if p else "unknown"
        chats = session_manager._chat_store.list_chats(profile_name)
        await send({"type": "chat_list", "chats": chats, "profile": profile_name})

    async def _send_profile(eng) -> None:
        p = eng._active_profile
        await send({
            "type":      "profile_info",
            "name":      p.name if p else "unknown",
            "workspace": p.workspace if p else "",
            "pet_id":    (p.pet_id if p else None),
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
        ][-40:]

    async def _notify_extension_session(eng, sid: str) -> None:
        """Fire the session-linked event so any skill that cares
        (notably the browser/extension integration) can react —
        push session info to its own surface, log it, etc. The
        server doesn't know which skills consume the event; the
        discovery bus handles fan-out."""
        from chika.skills import fire_session_linked
        await fire_session_linked(eng, sid)

    # Send initial state
    await _send_session_info(engine, session_id)
    await _send_chat_list(engine)
    await _send_profile(engine)
    await send({"type": "settings_info", **settings_store.all_settings()})
    await _notify_extension_session(engine, session_id)

    # ── Per-connection approval queue state ───────────────────────────────────
    # Futures: request_id → Future[{"approved": bool, "password": str}]
    # Resolved by _ws_recv_loop when an approval_response arrives.
    _approval_futures: dict[str, asyncio.Future] = {}

    # Lock ensures only ONE approval dialog is shown at a time.
    _approval_lock = asyncio.Lock()

    # Non-approval WS messages are queued here; main loop drains this.
    _incoming: asyncio.Queue = asyncio.Queue()

    # Mutable container so _ws_recv_loop can cancel the current chat task.
    _current_chat: list = [None]

    pm = session_manager._profile_manager

    # ── Approval handler ──────────────────────────────────────────────────────
    async def approval_handler(
        request_id: str, tool: str, args: dict,
        step_id: str = "", message: str = "",
        approval_type: str = "confirm",
    ) -> bool | dict:
        """Serialised approval: queues requests, shows one dialog at a time.

        Return shape varies by ``approval_type``:
          * ``confirm`` / ``verify_password`` / ``set_password`` → bool
          * ``workspace_scope`` → ``{"scope": ..., "reason": ...}``
          * ``plan_review``     → ``{"action": ..., "feedback": ..., "reason": ...}``
        """
        if settings_store.get_tool_permission(tool) == "skip":
            return True

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        _approval_futures[request_id] = fut

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
                actual_type    = "verify_password"
                actual_message = f"Profile '{safe_name}' exists. Enter its password to switch."
            else:
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
                response: dict = await fut

            # Workspace-scope approvals carry a tri-state choice
            # ('session' / 'once' / 'deny') the WorkspacePolicy uses
            # to decide how long the grant survives. Return the dict
            # shape the policy expects rather than the legacy bool.
            if actual_type == "workspace_scope":
                scope = (response.get("scope") or "deny").lower()
                if scope not in ("session", "once", "deny"):
                    scope = "deny"
                return {
                    "scope":  scope,
                    "reason": response.get("reason") or "",
                }

            # plan_review approvals carry a structured action +
            # feedback the engine's _request_plan_approval consumes.
            if actual_type == "plan_review":
                action = (response.get("action") or
                          ("approve" if response.get("approved") else "deny")).lower()
                if action not in ("approve", "edit", "deny"):
                    action = "deny"
                return {
                    "action":   action,
                    "feedback": response.get("feedback") or "",
                    "reason":   response.get("reason") or "",
                }

            if not response.get("approved", False):
                return False

            password = response.get("password", "")[:1024]

            if actual_type == "set_password":
                if tool == "profile_create":
                    args["_password"] = password
                elif tool == "set_profile_password":
                    p = engine._active_profile
                    if p and p.name != "default":
                        pm.set_password(p.name, password)

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
            raise
        except Exception:
            return False
        finally:
            _approval_futures.pop(request_id, None)

    engine._workflow_engine.approval_handler = approval_handler

    # Wire the workspace-scope policy onto the file-write tools so writes
    # outside the active profile's workspace trigger the same approval
    # channel (with the tri-state session/once/deny picker rendered by
    # ApprovalModal). The policy lives per session so grants don't bleed
    # across users.
    try:
        from chika.core.workspace_policy import WorkspacePolicy
        from chika.tools import file_tools as _ft
        if engine._active_profile:
            _policy = WorkspacePolicy(
                workspace=str(engine._active_profile.workspace),
            )
            _ft.configure_workspace_policy(_policy, approval_handler)
    except Exception:
        # Policy wiring is best-effort — never block a session because
        # the workspace path is weird or the policy module fails to load.
        pass

    # ── ask_user question handler ─────────────────────────────────────────────
    _question_futures: dict[str, asyncio.Future] = {}

    async def question_handler(
        *, request_id: str, question: str, options: list, header: str = "",
        multi_select: bool = False,
    ) -> dict:
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
                    try:
                        await send({"type": "error", "message": "Invalid JSON"})
                    except Exception:
                        break
                    continue

                mtype = msg.get("type")

                if mtype == "ping":
                    try:
                        await send({"type": "pong"})
                    except Exception:
                        break

                elif mtype == "approval_response":
                    rid = msg.get("request_id")
                    fut = _approval_futures.get(rid)
                    if fut and not fut.done():
                        fut.set_result({
                            "approved": bool(msg.get("approved", False)),
                            "password": str(msg.get("password", "")),
                            # Workspace-scope: carries the user's
                            # session/once/deny choice through to the
                            # WorkspacePolicy.
                            "scope":    str(msg.get("scope", "")),
                            # plan_review: action + (feedback | reason).
                            # Approval handler unpacks these into the
                            # ``{action, feedback, reason}`` dict the
                            # engine's _request_plan_approval expects.
                            "action":   str(msg.get("action", "")),
                            "feedback": str(msg.get("feedback", "")),
                            "reason":   str(msg.get("reason", "")),
                        })

                elif mtype == "user_question_response":
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
            # WS is gone — cancel the running chat turn so it doesn't hang.
            task = _current_chat[0]
            if task and not task.done():
                task.cancel()
            for fut in list(_approval_futures.values()):
                if not fut.done():
                    fut.cancel()
            _approval_futures.clear()
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

            _log.info("ws.message", session_id=session_id, msg_type=mtype)

            # ── User chat message ─────────────────────────────────────────────
            if mtype == "user_message":
                text = msg.get("text", "").strip()
                if not text:
                    continue
                _log.info("ws.chat", text=text[:60])

                async def _run_chat(user_text: str) -> None:
                    try:
                        async for event in engine.chat(user_text):
                            etype = event.get("type", "")
                            # Suppress internal events and approval_required —
                            # the approval_handler sends it at the right time.
                            if etype.startswith("_") or etype == "approval_required":
                                continue
                            try:
                                # Validate every outbound event against
                                # the typed contract. Strict=False so a
                                # validation failure logs a warning but
                                # still flows the event — observability,
                                # not gatekeeping. Strict=True is used
                                # in tests/test_event_contract.py.
                                from api.models import validate_event
                                event = validate_event(event, strict=False)
                                await send(event)
                            except Exception:
                                return
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
                        raise
                    except Exception as exc:
                        _log.exc("ws.chat_exception", device_id=device_id)
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
                    pass
                except Exception as exc:
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
                current_profile = engine._active_profile
                engine, session_id = session_manager.new_chat_for_device(device_id)
                engine._workflow_engine.approval_handler = approval_handler
                # Carry the previous chat's profile across the new
                # chat so the user doesn't get bounced back to the
                # bootstrap profile every time they hit "new chat".
                if current_profile:
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
                    profile_name = current_profile.name if current_profile else "unknown"
                    session_manager._chat_store.delete(profile_name, chat_id)
                    session_manager.delete(chat_id)
                    if chat_id == session_id:
                        engine, session_id = session_manager.new_chat_for_device(device_id)
                        engine._workflow_engine.approval_handler = approval_handler
                        if current_profile:
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
                    response = await ui_fut
                    approved = response.get("approved", False)
                    password = response.get("password", "")[:1024]
                except asyncio.CancelledError:
                    raise
                except Exception:
                    approved, password = False, ""
                finally:
                    _approval_futures.pop(request_id, None)

                if not approved:
                    continue

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
        async with _frontend_sockets_lock:
            _frontend_sockets.discard(websocket)
        recv_task.cancel()
        monitor_task.cancel()
        try:
            await asyncio.gather(recv_task, monitor_task, return_exceptions=True)
        except Exception:
            pass




# Mount static files last so WebSocket routes take priority over the catch-all.
static_routes.mount(app)


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
        loop="asyncio",
    )
