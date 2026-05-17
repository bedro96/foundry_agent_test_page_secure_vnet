---
name: typescript
display_name: TypeScript
description: >-
    TypeScript strict mode configuration with two tsconfigs: one for the Next.js app
    (esnext/bundler) and one for the custom Node server (CommonJS/ES2019). Covers path
    aliases, React types, API handler types, and server vs client typing rules.
user-invocable: true
---

# Skill: TypeScript

## Overview

The repo is fully TypeScript (strict mode), targeting **TS 5.x** with **two** `tsconfig`s:

* `tsconfig.json` — for the **Next.js app** (`app/`, `components/`, `middleware.ts`, ambient types). Module = `esnext`, resolution = `bundler`, JSX = `react-jsx`, `noEmit: true` (Next handles emission).
* `tsconfig.server.json` — for the **custom Node server**: compiles `server.ts` + `lib/**/*.ts` to **`dist/`** as **CommonJS / ES2019** (`module: commonjs`, `target: es2019`, `noEmit: false`, `outDir: dist`).

Both share strictness because `tsconfig.server.json` extends the base one.

## Conventions

### Path aliases

`@/*` → repo root (`./*`). Use it everywhere:

```ts
import { prisma } from "@/lib/prisma"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
```

`components.json` mirrors these aliases for the shadcn CLI (`@/components`, `@/components/ui`, `@/lib`, `@/lib/utils`, `@/hooks`).

### Strictness

`strict: true` is enabled. In practice this means:

* No implicit `any`. If you genuinely need it, type as `unknown` and narrow.
* `null`/`undefined` are part of the type system — handle them.
* Function parameters must be typed (or inferable from context).

### Server vs. client typing

* **Client components** (`"use client"`) import React types freely (`React.FC` is *not* used here — prefer typed function components).
* **Server-only modules** in `lib/` must compile under both `tsconfig.json` (Next) **and** `tsconfig.server.json` (CommonJS, ES2019, no JSX). Avoid in `lib/`:
  * Top-level `await`
  * `import.meta.url`
  * JSX
  * ESM-only syntax patterns that the CommonJS target won't support

### React types

* `React.ComponentPropsWithoutRef<"button">` for prop intersection with native elements (see `components/ui/button.tsx`).
* `React.forwardRef<HTMLButtonElement, Props>` for shadcn-style primitives.
* `Readonly<{ children: React.ReactNode }>` for layout/page props (see `app/layout.tsx`).

### API handler types

Use Next's `NextRequest`/`NextResponse`:

```ts
import { NextRequest, NextResponse } from "next/server"
export async function POST(req: NextRequest) { ... }
```

For request body parsing, type after `await req.json()`:

```ts
const body = (await req.json()) as { email?: string; password?: string }
if (!body.email || !body.password) return NextResponse.json({ error: "missing" }, { status: 400 })
```

### Error handling

* Wrap async work in `try/catch`; the caught value is `unknown` — narrow with `error instanceof Error` before using `.message`.
* Always log via `logError(err, { context })` from `@/lib/logger`, never bare `console.error` on the server.

### Avoid `any` in shared code

It's acceptable in interop shims (the `AsyncLocalStorage` polyfill in `server.ts` uses `(globalThis as any)`), but in `lib/` and `app/` use `unknown` + type guards or a precise interface.

## How-to: common tasks

### Add a new module to the server bundle

1. Create your file under `lib/<name>.ts`.
2. Use **CommonJS-compatible** TypeScript only (no JSX, no top-level `await`).
3. Import it from `server.ts` or another `lib/` module.
4. `npm run build` runs `tsc --project tsconfig.server.json` and will surface any incompatibility immediately.

### Type-check the whole project

```bash
npx tsc --noEmit                                    # type-check the Next app
npx tsc --project tsconfig.server.json --noEmit     # type-check the server bundle
```

(There is no dedicated `typecheck` npm script; ESLint via `npm run lint` catches a subset of issues but not type errors.)

### Lint

```bash
npm run lint
```

Uses the flat ESLint config (`eslint.config.mjs`) with `eslint-config-next`.

## Pitfalls

* **JSX in `lib/` won't compile** under `tsconfig.server.json` (`jsx: react`, target ES2019). Keep JSX out of `lib/` — even helper "format an element" functions belong in `components/`.
* **Path aliases in compiled server output.** `tsc` does **not** rewrite `@/*` aliases. The server bundle currently works because `lib/` files use relative imports among themselves (`./prisma`, `./logger`). Maintain that — don't introduce `@/lib/...` imports inside `lib/` or the compiled `dist/server.js` will fail at runtime.
* **`reference/` includes `.js` files** explicitly in `tsconfig.json` (`reference/iot-batch.js`, etc.). Don't accidentally remove them from `include`; they exist to keep TS happy when those JS files are imported.
* **Prisma types** require `npm run db:generate` after schema changes — otherwise you'll see "property does not exist on type" errors that are actually a stale generated client.
* **`"use client"` must be the literal first line.** Comments, blank lines, or imports above it disable the directive silently.

## References

* `tsconfig.json`, `tsconfig.server.json`
* `eslint.config.mjs`
* `server.ts` — example of `(globalThis as any)` interop
* `components/ui/button.tsx` — example of `forwardRef` + `VariantProps`
* TypeScript docs: <https://www.typescriptlang.org/docs/>
