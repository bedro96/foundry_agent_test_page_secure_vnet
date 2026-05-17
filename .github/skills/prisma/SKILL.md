---
name: prisma
display_name: Prisma (with MongoDB)
description: >-
    Prisma 5.22.0 ORM with MongoDB as the underlying database. Covers db push mode,
    ObjectId mapping, the PrismaClient singleton pattern for Next.js, schema conventions,
    and common query patterns.
user-invocable: true
---

# Skill: Prisma (with MongoDB)

## Overview

Persistence is handled by **Prisma 5.22.0** as the ORM, talking to **MongoDB** as the underlying database. Because MongoDB is a non-relational/document store, this project uses Prisma in **`db push`** mode (no SQL migration files) and IDs are MongoDB `ObjectId`s mapped to `_id`.

The Prisma client is wired as a **module-level singleton** to avoid the "too many clients" issue under Next.js dev hot-reload.

## Where it lives

| Path                                  | Purpose                                                              |
| ------------------------------------- | -------------------------------------------------------------------- |
| `prisma/schema.prisma`                | Single source of truth — datasource, generator, all models           |
| `lib/prisma.ts`                       | Singleton `PrismaClient` exported as `prisma`                        |
| `scripts/init-db.ts`                  | Seed/init script — `npm run db:init`                                 |
| `.env` / `.env.example`               | `DATABASE_URL` — MongoDB connection string                           |

## Schema highlights

```prisma
generator client {
  provider      = "prisma-client-js"
  binaryTargets = ["native", "linux-musl"]   // include musl for Alpine images
}

datasource db {
  provider = "mongodb"
  url      = env("DATABASE_URL")
}
```

Models defined: `User`, `Session`, `PasswordResetToken`, `Device`, `AuditLog`, `DeviceCommand`, `DeviceId`, `Telemetry`. All use `String @id @default(auto()) @map("_id") @db.ObjectId` for primary keys.

## The client singleton (`lib/prisma.ts`)

```ts
import { PrismaClient } from '@prisma/client'

const globalForPrisma = globalThis as unknown as { prisma: PrismaClient | undefined }

export const prisma = globalForPrisma.prisma ?? new PrismaClient()

if (process.env.NODE_ENV !== 'production') globalForPrisma.prisma = prisma
```

* **Always import `prisma` from `@/lib/prisma`.** Never `new PrismaClient()` anywhere else — Next dev hot-reload would leak connections and exhaust the MongoDB connection pool.
* In production the singleton is recreated only on cold start; in dev it's cached on `globalThis`.

## Conventions

### MongoDB-specific id pattern

Every model uses:

```prisma
id String @id @default(auto()) @map("_id") @db.ObjectId
```

Foreign-key fields use `@db.ObjectId` too:

```prisma
userId String @db.ObjectId
user   User   @relation(fields: [userId], references: [id], onDelete: Cascade)
```

Add `@@index([userId])` for any non-unique field you'll filter or join on — Mongo doesn't auto-index FKs.

### Timestamps

Use `createdAt DateTime @default(now())` and `updatedAt DateTime @updatedAt` consistently.

### Enum-like fields are strings

Because we're on MongoDB and prefer schema flexibility, "enum" values (e.g., `User.role`, `DeviceCommand.status`) are stored as plain `String` with a `@default(...)`. Validate them in application code before writing.

### Cascading deletes

Relations like `Session` and `PasswordResetToken` use `onDelete: Cascade` so deleting a `User` removes their sessions and reset tokens automatically. Mirror this for any new owned-relation.

### Don't return Prisma objects directly from APIs

Prisma returns `Date` and (potentially) `Decimal`/`BigInt`. Map to a JSON-safe shape before `NextResponse.json(...)`:

```ts
return NextResponse.json({
  id: device.id,
  createdAt: device.createdAt.toISOString(),
  ...
})
```

## How-to: common tasks

### Add or change a model

1. Edit `prisma/schema.prisma`.
2. Run `npm run db:push` to sync the change to MongoDB. (Mongo doesn't need migration files — `db push` is the only mode.)
3. Run `npm run db:generate` to regenerate the typed client (`@prisma/client`).
4. Update consuming code in `lib/` and `app/api/`.

### Inspect data

```bash
npm run db:studio    # opens Prisma Studio at http://localhost:5555
```

### Initialize / seed the DB

```bash
npm run db:init      # runs scripts/init-db.ts via tsx
```

Add seed data there; keep it idempotent (`upsert`, not `create`).

### Common query patterns

```ts
// Findfirst by unique field
const user = await prisma.user.findUnique({ where: { email } })

// Create with relation by id
await prisma.session.create({ data: { userId: user.id, token, expiresAt } })

// Atomic update + return
const updated = await prisma.device.update({
  where: { id },
  data: { lastSeenAt: new Date(), online: true },
})

// Pagination — skip/take with a stable orderBy
await prisma.telemetry.findMany({
  where: { deviceId },
  orderBy: { ts: 'desc' },
  skip: page * pageSize,
  take: pageSize,
})
```

## Pitfalls

* **`db push` is destructive-ish.** On MongoDB it doesn't drop collections, but it can drop indexes that no longer match. Always check the diff Prisma prints before confirming in a shared environment.
* **No `prisma migrate` for MongoDB** — don't try to run it; it isn't supported by the Mongo provider in Prisma 5.x.
* **Strings vs. ObjectIds.** When passing an id from a request, validate it (e.g., 24-char hex) before passing to Prisma; otherwise Prisma throws a low-level driver error.
* **Don't filter on un-indexed fields at scale.** Add `@@index([...])` in the schema for new query patterns.
* **The Alpine docker image needs the musl binary** — `binaryTargets = ["native", "linux-musl"]` in `schema.prisma` already covers this. If you ever switch base images, re-evaluate.
* **Connection pooling.** With Mongo Atlas, control pool size via the `?maxPoolSize=...` query param on `DATABASE_URL`, not in code.
* **Regenerate on schema change.** Forgetting `npm run db:generate` leaves `@prisma/client` types out of sync, producing confusing TS errors.

## References

* `prisma/schema.prisma`
* `lib/prisma.ts` — the singleton
* `scripts/init-db.ts` — seed example
* Prisma + MongoDB docs: <https://www.prisma.io/docs/orm/overview/databases/mongodb>
