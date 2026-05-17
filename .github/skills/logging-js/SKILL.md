---
name: logging-js
display_name: Logging (Winston + Daily Rotate)
description: >-
    Server-side logging with Winston 3.19 and winston-daily-rotate-file. Covers console
    and rotated JSON file transports, exported helpers (logInfo, logError, logAudit),
    audit logging to MongoDB, and conventions for structured metadata.
user-invocable: true
---

# Skill: Logging (Winston + Daily Rotate)

## Overview

Server-side logging uses **Winston 3.19** with **`winston-daily-rotate-file`**. Logs are written both to the console (colorized, human-readable) and to **rotated JSON files under `logs/`**. A separate **audit log** is persisted to MongoDB (`AuditLog` model) for security-relevant events. The UI exposes a real-time log viewer at `/server-logs/` backed by `app/api/server-logs/`.

## Where it lives

| Path                                  | Purpose                                                          |
| ------------------------------------- | ---------------------------------------------------------------- |
| `lib/logger.ts`                       | Winston config + exported helpers (`logInfo`, `logError`, …)     |
| `logs/`                               | Daily-rotated log files (gitignored, auto-created at boot)       |
| `app/server-logs/`                    | UI page for viewing logs                                         |
| `app/api/server-logs/`                | API for tailing/searching logs                                   |
| `prisma/schema.prisma` → `AuditLog`   | Persistent audit trail for sensitive actions                     |

## Log levels

```
error (0) | warn (1) | info (2) | http (3) | debug (4)
```

with colors `red | yellow | green | magenta | blue`. Use the lowest severity that fits — most app activity is `info`; HTTP request logs are `http`; recoverable issues are `warn`; failures are `error`.

## Exported helpers (use these — not `console.log`)

From `lib/logger.ts`:

| Helper                                                                | Use for                                                  |
| --------------------------------------------------------------------- | -------------------------------------------------------- |
| `logInfo(message: string, meta?: Record<string, unknown>)`            | Routine successful events                                |
| `logWarn(message: string, meta?: Record<string, unknown>)`            | Recoverable problems, deprecations, retries              |
| `logError(error: Error, context?: Record<string, unknown>)`           | Caught exceptions and failed operations                  |
| `logDebug(message: string, meta?: Record<string, unknown>)`           | Verbose diagnostics (silenced in production by default)  |
| `logRequest(req)`                                                     | Inbound HTTP request logging at `http` level             |
| `logAudit(...)`                                                       | Security-relevant events → `AuditLog` collection in DB   |

### Always pass structured metadata

```ts
logInfo('device connected', { deviceId, ip: req.ip })
logError(err as Error, { route: 'POST /api/devices', userId: session?.userId })
```

The file transport uses `winston.format.json()` so structured fields are queryable. Avoid string interpolation that hides values — `logInfo(\`device \${id} connected\`)` is harder to grep than `logInfo('device connected', { id })`.

## Conventions

### Console vs. file

* **Console**: timestamped, colorized, single-line (`consoleFormat` in `lib/logger.ts`). Good for `docker logs` and dev.
* **File** (`logs/application-YYYY-MM-DD.log`): JSON lines, includes stack traces (`format.errors({ stack: true })`), zipped after rotation, capped at `maxSize: '20m'`.

Both transports run in production. Don't disable the console transport — container orchestration (Kubernetes, Docker) collects stdout.

### Use `logError` with the actual `Error`

```ts
try { ... } catch (err) {
  logError(err as Error, { context: 'doing X' })
}
```

Don't pass a string — the file transport expects an `Error` so it can attach the stack via `format.errors({ stack: true })`.

### Audit logging

For any **state-changing security-relevant action** (login, logout, password change/reset, role change, device creation/deletion, admin overrides), call `logAudit(...)` so it's recorded in the `AuditLog` MongoDB collection — file logs rotate and disappear, the audit trail must persist.

### Don't log secrets

Never log:

* Passwords (plaintext or hashed)
* JWT tokens, session cookies, password-reset tokens
* IoT Hub or Event Hub connection strings
* Full request bodies that may contain credentials

If you need to log a request body for diagnostics, redact known sensitive keys first.

### HTTP request logging

Use `logRequest(req)` at the start of route handlers (or in middleware) for traceability. Don't double-log — the file already includes timestamp, method, and URL.

## How-to: common tasks

### Log inside an API handler

```ts
import { logInfo, logError } from '@/lib/logger'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    logInfo('creating device', { name: body.name })
    const device = await prisma.device.create({ data: body })
    return NextResponse.json(device)
  } catch (err) {
    logError(err as Error, { route: 'POST /api/devices' })
    return NextResponse.json({ error: 'internal' }, { status: 500 })
  }
}
```

### Tail logs locally

```bash
tail -f logs/application-$(date +%F).log | jq .
```

(Files are JSON lines; pipe through `jq` for readability.)

### View logs in the UI

Navigate to `/server-logs/` (admin-gated). It hits `app/api/server-logs/` which streams the rotated file contents.

### Add a new audit event

1. Pick a stable event name (e.g., `'user.role.change'`).
2. Call `logAudit(...)` with the actor, subject, and a metadata object.
3. If the event needs querying, ensure `AuditLog` has appropriate indexes in `prisma/schema.prisma`.

## Pitfalls

* **`console.log` in `lib/` and `app/api/`** bypasses rotation, formatting, and filtering. Use the helpers — the only acceptable `console.*` calls are early-boot ones in `server.ts` *before* the logger is ready.
* **The `logs/` directory is created at startup** with `path.join(process.cwd(), 'logs')`. Make sure the container/user has write permission to `process.cwd()`.
* **Log volume.** `info`-level chatter on hot paths (per-message inside the IoT consumer, per-WebSocket-frame) will produce massive files. Use `debug` for high-volume diagnostics and gate it via `NODE_ENV` if needed.
* **Don't pass non-serializable fields** in metadata (functions, sockets, Prisma transaction handles). The JSON formatter will either drop them silently or throw.
* **Rotated files are zipped.** Tools that grep `logs/*.log` won't find historical matches — use `zgrep` on the `.gz` archives.
* **The audit log is append-only.** Never `delete` from `AuditLog` — if entries become inaccurate, add a corrective entry.

## References

* `lib/logger.ts`
* `prisma/schema.prisma` → `AuditLog` model
* `app/server-logs/`, `app/api/server-logs/`
* Winston docs: <https://github.com/winstonjs/winston>
* `winston-daily-rotate-file`: <https://github.com/winstonjs/winston-daily-rotate-file>
