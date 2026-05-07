"""``/ws/extension/`` WebSocket endpoint — owned by the browser skill.

This file used to live in ``api/server.py`` (220 lines that knew far
too much about the extension's wire protocol). Moving it here makes
the browser skill genuinely self-contained — drop ``browser_skill/``
and the extension WS endpoint disappears with it.

The ``register(app)`` entry point is what the server's skill walker
calls at boot. It:

  1. Wires ``set_frontend_push`` so the skill can push watch events
     back to every connected frontend.
  2. Adds a status listener so the frontend's connection chip can
     reflect the extension's connect/disconnect.
  3. Attaches the ``@app.websocket("/ws/extension/")`` handler that
     speaks the full hello/chat/approval/question protocol.

Anything outside this folder needs to import ``chika.skills.browser_skill``
to GET this functionality — and then it's mounted via the standard
skill discovery path. No bespoke wiring elsewhere.
"""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from fastapi import Query, WebSocket

import api.settings_store as settings_store
from api.broadcast import push_to_all_frontend_sessions
from api.session_manager import session_manager
from chika.core.logger import log as _log
from chika.skills.browser_skill import set_frontend_push
from chika.skills.browser_skill.extension_manager import extension_manager

if TYPE_CHECKING:
    from fastapi import FastAPI


def _ext_recent_msgs(eng, limit: int = 40) -> list[dict]:
    """Pull the last ``limit`` user/assistant turns out of an engine's
    history for the ``linked_session`` payload — keeps the extension's
    chat panel in sync with what the user has already said."""
    return [
        {"role": m["role"], "text": m.get("content") or ""}
        for m in eng._history
        if m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str)
        and m["content"].strip()
    ][-limit:]


def register(app: FastAPI) -> None:
    """Skill discovery entry point. Wire frontend push, the extension
    status listener, and attach the WS endpoint to ``app``.

    Idempotent — calling twice is a no-op for the listener (the list
    is a set under the hood) and replaces the WS handler with itself.
    """
    # Frontend push hook so the skill can broadcast watch events back
    # to every open chat tab. Used by the watch_trigger / watch_cancelled
    # paths inside ``extension_manager``.
    set_frontend_push(push_to_all_frontend_sessions)

    async def _on_extension_status(connected: bool) -> None:
        await push_to_all_frontend_sessions({
            "type":      "extension_status",
            "connected": connected,
        })
        if connected:
            # Heartbeat: stamp ``~/.chika/extension_active.json`` so
            # subsequent ``chika install-extension`` invocations + the
            # doctor can tell the extension is genuinely active.
            try:
                from chika._cli.extension_detect import write_heartbeat
                write_heartbeat()
            except Exception:
                pass

    extension_manager.add_status_listener(_on_extension_status)

    @app.websocket("/ws/extension/")
    async def websocket_extension_endpoint(  # noqa: C901 — protocol handler is naturally branchy
        websocket: WebSocket,
        token: str = Query(default=""),
    ):
        """Dedicated command/control channel for the Chika Chrome extension."""
        import config
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

        async def _ping_loop() -> None:
            while extension_manager.connected:
                await asyncio.sleep(25)
                if not await extension_manager.send_raw({"type": "ping"}):
                    break

        ping_task = asyncio.create_task(_ping_loop())

        _ext_approval_futures: dict[str, asyncio.Future] = {}
        _ext_question_futures: dict[str, asyncio.Future] = {}
        _ext_chat_task: list = [None]

        async def _ext_approval_handler(
            request_id: str, tool: str, args: dict,
            step_id: str = "", message: str = "",
            approval_type: str = "confirm",
        ) -> bool:
            if settings_store.get_tool_permission(tool) == "skip":
                return True

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

        _incoming: asyncio.Queue = asyncio.Queue()

        async def _ext_recv_loop() -> None:
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

        try:
            while True:
                msg      = await _incoming.get()
                msg_type = msg.get("type")

                if msg_type == "_disconnect":
                    break

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

                elif msg_type == "extension_hello":
                    ext_did = msg.get("device_id", "").strip()
                    _log.info("ext.hello", device_id=ext_did, linked_sid=extension_manager.linked_session_id)
                    if ext_did:
                        extension_manager.linked_device_id = ext_did
                        if not extension_manager.linked_session_id:
                            ext_eng, ext_sid = session_manager.get_device_session(ext_did)
                            extension_manager.linked_session_id = ext_sid
                            _log.info("ext.session_new", device_id=ext_did, session_id=ext_sid)
                        else:
                            ext_sid = extension_manager.linked_session_id
                            ext_eng = session_manager.get(ext_sid)  # type: ignore[assignment]
                            if ext_eng is None:
                                ext_eng, ext_sid = session_manager.get_device_session(ext_did)
                                extension_manager.linked_session_id = ext_sid
                                _log.info("ext.session_expired", device_id=ext_did, session_id=ext_sid)
                            else:
                                _log.info("ext.session_reuse", session_id=ext_sid)
                        p = ext_eng._active_profile
                        sent = await extension_manager.send_raw({
                            "type":       "linked_session",
                            "session_id": ext_sid,
                            "title":      ext_eng._title,
                            "profile":    p.name if p else "unknown",
                            "messages":   _ext_recent_msgs(ext_eng),
                        })
                        _log.info("ext.session_linked", sent=sent, session_id=ext_sid)
                    else:
                        _log.info("ext.hello_missing_device")

                elif msg_type == "extension_chat_message":
                    text            = msg.get("text", "").strip()
                    session_id_hint = msg.get("session_id", "").strip()
                    ext_device      = msg.get("device_id", "").strip()
                    active_tab      = msg.get("active_tab")
                    _log.info("ext.chat_message", text=text[:40], sid_hint=session_id_hint, device_id=ext_device)

                    if not text:
                        continue

                    if _ext_chat_task[0] and not _ext_chat_task[0].done():
                        _ext_chat_task[0].cancel()

                    ext_engine   = None
                    resolved_sid = session_id_hint or extension_manager.linked_session_id
                    if resolved_sid:
                        ext_engine = session_manager.get(resolved_sid)
                    if ext_engine is None and ext_device:
                        ext_engine, resolved_sid = session_manager.get_device_session(ext_device)
                        if ext_engine is not None:
                            extension_manager.linked_session_id = resolved_sid
                            p = ext_engine._active_profile
                            await extension_manager.send_raw({
                                "type":       "linked_session",
                                "session_id": resolved_sid,
                                "title":      ext_engine._title,
                                "profile":    p.name if p else "unknown",
                                "messages":   _ext_recent_msgs(ext_engine),
                            })
                    if ext_engine is None:
                        if ext_device:
                            ext_engine, resolved_sid = session_manager.get_device_session(ext_device)
                            extension_manager.linked_session_id = resolved_sid
                            p = ext_engine._active_profile
                            await extension_manager.send_raw({
                                "type":       "linked_session",
                                "session_id": resolved_sid,
                                "title":      ext_engine._title,
                                "profile":    p.name if p else "unknown",
                                "messages":   _ext_recent_msgs(ext_engine),
                            })
                        else:
                            await extension_manager.send_raw({
                                "type":    "ext_chat_error",
                                "message": "Could not create a session — check the server is running.",
                            })
                            await extension_manager.send_raw({"type": "ext_chat_done"})
                            continue

                    _log.info("ext.engine_resolved", session_id=resolved_sid, busy=ext_engine._chat_busy)
                    if ext_engine._chat_busy:
                        await extension_manager.send_raw({
                            "type":       "ext_chat_error",
                            "message":    "Chika is busy — wait for the current response to finish.",
                            "error_code": "engine_busy",
                        })
                        await extension_manager.send_raw({"type": "ext_chat_done"})
                        continue

                    enriched_text = text
                    if active_tab:
                        url      = active_tab.get("url", "")
                        title    = active_tab.get("title", "")
                        tab_text = (active_tab.get("text") or "")[:2000]
                        if url:
                            ctx_lines = [f"[Active browser tab: {title!r} — {url}]"]
                            if tab_text:
                                ctx_lines.append(f"[Page text snippet: {tab_text!r}]")
                            enriched_text = "\n".join(ctx_lines) + "\n\n" + text

                    prev_approval = ext_engine._workflow_engine.approval_handler
                    prev_question = ext_engine._workflow_engine.question_handler
                    ext_engine._workflow_engine.approval_handler = _ext_approval_handler
                    ext_engine._workflow_engine.question_handler = _ext_question_handler

                    async def _run_ext_chat(
                        user_text: str, display_text: str, eng, _prev_a, _prev_q
                    ) -> None:
                        try:
                            _log.info("ext.chat_start", text=user_text[:40])
                            await extension_manager.send_raw({"type": "ext_chat_start"})
                            _log.info("ext.chat_start_sent")
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
                                try:
                                    await push_to_all_frontend_sessions(event)
                                except Exception:
                                    pass
                        except asyncio.CancelledError:
                            _log.info("ext.chat_cancelled")
                            raise
                        except Exception as exc:
                            _log.exc("ext.chat_error")
                            try:
                                await extension_manager.send_raw({
                                    "type": "ext_chat_error", "message": str(exc)
                                })
                                await extension_manager.send_raw({"type": "ext_chat_done"})
                                await push_to_all_frontend_sessions({"type": "error", "message": str(exc)})
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
                    extension_manager.set_chat_task(t)
                    t.add_done_callback(lambda _: extension_manager.set_chat_task(None))

                elif msg_type == "extension_approval_response":
                    rid = msg.get("request_id", "")
                    fut = _ext_approval_futures.get(rid)
                    if fut and not fut.done():
                        fut.set_result({
                            "approved": bool(msg.get("approved", False)),
                            "password": str(msg.get("password", "")),
                        })

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

        except Exception:
            _log.exc("ext.fatal")
        finally:
            recv_task.cancel()
            ping_task.cancel()
            if _ext_chat_task[0] and not _ext_chat_task[0].done():
                _ext_chat_task[0].cancel()
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
            extension_manager.disconnect(websocket)
