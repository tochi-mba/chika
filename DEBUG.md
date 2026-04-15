# Debug Mode — Agent Instrumentation Guide

Show this file to Claude at the start of a session when you need bug-assisted debugging.

---

## How it works

This project has a lightweight debug logging system for agent-assisted debugging:

1. **Activate** — set `debugMode: true` in `src/zadarDemo.VueSPA/src/core/config/appConfig.ts`
2. **Instrument** — Claude adds `dlog()` calls wrapped in `#region agent-debug` marker blocks
3. **Reproduce** — run the app and trigger the bug; logs stream to `debug.log`
4. **Read & Fix** — Claude reads `debug.log`, diagnoses, and fixes the issue
5. **Verify** — Claude asks you to rerun; reads the new log to confirm the fix is working
6. **Cleanup** — only after verification passes: Claude removes all `#region agent-debug` blocks and sets `debugMode: false`

---

## Frontend logger

File: `src/zadarDemo.VueSPA/src/core/utils/debugLogger.ts`

```ts
import { dlog, dlogWarn, dlogError } from '@/core/utils/debugLogger';

// #region agent-debug
dlog('ComponentName', 'event description', { relevantState });
// #endregion agent-debug
```

- Only fires when `appConfig.debugMode === true`
- POSTs each entry to `/debug/log` → backend writes to `debug.log`
- Also logs to the browser console under `[DEBUG:Tag]`

---

## Backend endpoint

File: `src/zadarDemo.Web.Mvc/Controllers/DebugLogController.cs`

- `POST /debug/log` — append a log entry (dev only, no auth)
- `DELETE /debug/log` — clear the log file

The log file is written to:
```
src/zadarDemo.Web.Mvc/debug.log
```
(`debug.log` and `*.log` are in `.gitignore` — will never be committed)

---

## Log format

```
[2026-03-14T10:23:45.123Z] [LOG] [AgentTag] message content here
[2026-03-14T10:23:45.456Z] [ERROR] [AgentTag] {"prop":"value","count":3}
```

---

## Instrumentation convention

All instrumentation Claude adds is wrapped in region markers so it can be found and removed in bulk:

**TypeScript / Vue:**
```ts
// #region agent-debug
dlog('Tag', 'description', value);
// #endregion agent-debug
```

**C#:**
```csharp
#region agent-debug
_logger.LogDebug("[AgentTag] {Message}", someValue);
#endregion
```

---

## Cleanup

Cleanup only happens **after verification** — not immediately after the fix:

1. Claude applies the fix
2. Claude asks you to rerun and reproduce the original scenario
3. Claude reads the updated `debug.log` to confirm the fix is working correctly
4. Only then: Claude greps for `#region agent-debug`, removes every marked block, sets `debugMode: false`

You can also trigger cleanup manually by asking: *"clean up all debug instrumentation"*

---

## Quick reference for Claude

| Action | What to do |
|---|---|
| Add instrumentation | Wrap `dlog()` calls in `// #region agent-debug` blocks |
| Read the log | Read `src/zadarDemo.Web.Mvc/debug.log` |
| Clear the log | `DELETE /debug/log` or delete the file manually |
| Remove instrumentation | Only after verify step: grep `#region agent-debug`, remove all matching blocks |
| Toggle on/off | `appConfig.debugMode = true/false` |
