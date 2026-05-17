---
name: authentication-js
display_name: Authentication & Security
description: >-
    JWT-based server-issued HTTP-only cookie sessions signed with jose, persisted in MongoDB
    via Prisma. Covers CSRF protection via csrf-csrf, rate limiting, role-based access,
    password hashing with bcryptjs, and session management.
user-invocable: true
---

# Skill: Authentication & Security

## Overview

Authentication is **JWT-based, server-issued, HTTP-only cookie sessions**, signed with **`jose`** and persisted in MongoDB via Prisma. Passwords are hashed with **`bcryptjs`**. Cross-cutting protections are layered on top:

* **CSRF** via `csrf-csrf` (token-based, double-submit cookie pattern), wired in `middleware.ts`.
* **Rate limiting** via `express-rate-limit`-compatible logic in `lib/rate-limit.ts` + a Node-only background cleanup in `lib/rate-limit-node.ts`.
* **Role-based access**: `User.role` is `"user"` (default) or `"admin"`; admin checks happen in route handlers.
* **`iron-session`** is also installed and available for any flow that needs a stateless encrypted cookie (currently used selectively).
* **`next-auth` v5 beta** is present in `package.json` but **the primary auth flow is the custom JWT in `lib/auth.ts`**, not NextAuth.

## Where it lives

| Path                       | Purpose                                                                  |
| -------------------------- | ------------------------------------------------------------------------ |
| `lib/auth.ts`              | `createToken`, `verifyToken`, password helpers, session cookie constants |
| `lib/csrf.ts`              | `csrfProtection` middleware + `shouldBypassCSRF` allowlist               |
| `lib/rate-limit.ts`        | Per-route rate limiter factories, `shouldBypassRateLimit`                |
| `lib/rate-limit-node.ts`   | Background interval that cleans up rate-limit entries                    |
| `lib/request.ts`           | Helpers for reading auth context out of a `NextRequest`                  |
| `middleware.ts`            | Wires CSRF + rate-limit ahead of every route                             |
| `app/api/auth/*`           | Login, signup, logout, password-reset endpoints                          |
| `app/login/`, `app/signup/`| UI pages                                                                 |

## Session model

* JWT signed with **HS256**, secret from `process.env.JWT_SECRET` (`lib/auth.ts`).
* Payload: `{ userId, email, role }`.
* Lifetime: **7 days** (`SESSION_DURATION` and `setExpirationTime('7d')`).
* Cookie name: **`session`** (`SESSION_COOKIE_NAME`), **HTTP-only**, set by the login route handler.
* Server-side `Session` rows in MongoDB allow forced revocation (delete the row → next `verifyToken` lookup fails).

## Conventions

### Issue a session

Inside a route handler (e.g., `app/api/auth/login/route.ts`):

```ts
const token = await createToken({ userId, email, role })
await prisma.session.create({ data: { userId, token, expiresAt: new Date(Date.now() + 7*24*60*60*1000) } })

const res = NextResponse.json({ ok: true })
res.cookies.set('session', token, {
  httpOnly: true,
  secure: process.env.NODE_ENV === 'production',
  sameSite: 'lax',
  path: '/',
  maxAge: 7 * 24 * 60 * 60,
})
return res
```

### Read the current user

In any server route handler:

```ts
const token = req.cookies.get('session')?.value
const session = token ? await verifyToken(token) : null
if (!session) return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
```

For admin-gated endpoints, additionally check `session.role === 'admin'` and return **403** if not.

### Hash and verify passwords

```ts
import bcrypt from 'bcryptjs'
const hash = await bcrypt.hash(plaintext, 10)
const ok   = await bcrypt.compare(plaintext, user.password)
```

Always hash on write; never store plaintext, never log either value.

### CSRF

* All **state-changing requests from the browser** (POST/PUT/PATCH/DELETE) require a valid CSRF token, validated by `csrfProtection` in `middleware.ts`.
* Routes that are explicitly public (e.g., webhooks, certain WebSocket upgrade paths, the IoT-device ingest endpoints) must be added to `shouldBypassCSRF` in `lib/csrf.ts`.
* **Never disable CSRF globally.** Add a single specific path to the bypass list and document why.

### Rate limiting

* `lib/rate-limit.ts` exports per-route limiter factories used by `middleware.ts` (`rateLimiters`).
* Tune windows/limits by editing the factory parameters; do **not** instantiate ad-hoc limiters elsewhere.
* `lib/rate-limit-node.ts` runs an interval that prunes expired buckets — it's imported once at the top of `server.ts`. Don't import it into edge/middleware code.

### Password reset flow

* `PasswordResetToken` model stores a one-time token with `expiresAt` and `used` flag.
* On reset request: create a fresh token (cryptographically random), email/return it, mark `used=false`.
* On reset submit: `findUnique({ where: { token } })`, check `used === false && expiresAt > now`, update password, set `used = true`.
* Never reuse tokens. Never reveal whether an email exists (return the same response either way).

## How-to: common tasks

### Add a new authenticated API route

```ts
// app/api/foo/route.ts
import { NextRequest, NextResponse } from 'next/server'
import { verifyToken } from '@/lib/auth'
import { logError } from '@/lib/logger'

export async function GET(req: NextRequest) {
  try {
    const session = await verifyToken(req.cookies.get('session')?.value ?? '')
    if (!session) return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
    // ... business logic ...
    return NextResponse.json({ ok: true })
  } catch (err) {
    logError(err as Error, { route: 'GET /api/foo' })
    return NextResponse.json({ error: 'internal' }, { status: 500 })
  }
}
```

### Make a route admin-only

After `verifyToken`, add:

```ts
if (session.role !== 'admin') return NextResponse.json({ error: 'forbidden' }, { status: 403 })
```

### Add a public ingest endpoint that can't carry CSRF

1. Add the path to `shouldBypassCSRF` in `lib/csrf.ts`.
2. Authenticate it some *other* way (signed token in the URL, mTLS, IoT Hub managed identity, etc.).
3. Apply a stricter rate limit in `lib/rate-limit.ts`.

## Pitfalls

* **`JWT_SECRET` has a fallback** (`'your-secret-key-change-this-in-production'`). Production deployments **must** set a real secret — verify it's present at boot or refuse to start.
* **Cookies are not automatically secure in dev.** Don't change the conditional `secure: NODE_ENV === 'production'` — testing over plain HTTP in dev requires `secure: false`.
* **Token ≠ session row.** A valid JWT whose `Session` row was deleted should be rejected; ensure new flows that check auth also confirm the row when revocation matters (long-lived sessions, admin actions).
* **Don't trust `req.headers['x-forwarded-for']` blindly** for rate limiting — only when behind a known proxy. Configure trust accordingly in `lib/rate-limit.ts`.
* **`bcryptjs` is pure JS** (slower than native `bcrypt`). Cost factor 10 is the current trade-off; raising it without measurement will slow logins.
* **Two auth systems coexist:** `next-auth` v5 beta is in deps but the canonical flow is `lib/auth.ts`. Don't introduce NextAuth handlers without coordinating — having both active will produce two competing session cookies.

## References

* `lib/auth.ts`
* `lib/csrf.ts`, `lib/rate-limit.ts`, `lib/rate-limit-node.ts`
* `lib/request.ts`
* `middleware.ts`
* `app/api/auth/*`
* `prisma/schema.prisma` — `User`, `Session`, `PasswordResetToken` models
* `jose` docs: <https://github.com/panva/jose>
