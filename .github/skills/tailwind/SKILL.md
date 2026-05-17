---
name: tailwind
display_name: Tailwind CSS v3
description: >-
    Tailwind CSS v3.4.x configuration with class-strategy dark mode, shadcn theme tokens
    as CSS variables via hsl(var(--token)), PostCSS with autoprefixer, and the cn() helper
    combining clsx and tailwind-merge.
user-invocable: true
---

# Skill: Tailwind CSS v3

## Overview

Styling is built on **Tailwind CSS v3.4.x** (note: **v3**, not v4 — config still lives in JS, not in `@theme`). The configuration uses the **class-strategy dark mode**, scans `app/`, `components/`, and `pages/`, and exposes the shadcn theme tokens as CSS variables consumed via `hsl(var(--token))`. PostCSS handles processing with `autoprefixer`.

## Where it lives

| Path                  | Purpose                                                                       |
| --------------------- | ----------------------------------------------------------------------------- |
| `tailwind.config.ts`  | Tailwind config — `darkMode`, content globs, theme `extend` (colors, radius, animations) |
| `postcss.config.mjs`  | PostCSS plugins (`tailwindcss`, `autoprefixer`)                               |
| `app/globals.css`     | `@tailwind base/components/utilities` + CSS variables for `:root` and `.dark` |
| `lib/utils.ts`        | The `cn(...)` helper combining `clsx` and `tailwind-merge`                    |

## How the theme works

1. `app/globals.css` defines CSS variables such as `--background: 0 0% 100%;` (note: **HSL channels without the `hsl()` wrapper**) on `:root` and overrides them on `.dark`.
2. `tailwind.config.ts` maps semantic Tailwind color names to those variables: `primary: "hsl(var(--primary))"`. So `bg-primary` resolves to `hsl(var(--primary))` at runtime.
3. `next-themes` toggles a `class="dark"` on `<html>` (via `ThemeProvider` `attribute="class"` in `app/layout.tsx`), which swaps the variable values — instantly retheming the entire UI without re-renders.

### Available semantic tokens

`background`, `foreground`, `card`, `card-foreground`, `popover`, `popover-foreground`, `primary`, `primary-foreground`, `secondary`, `secondary-foreground`, `muted`, `muted-foreground`, `accent`, `accent-foreground`, `destructive`, `destructive-foreground`, `border`, `input`, `ring`, plus chart colors `chart-1` … `chart-5`. There is also `--radius` (used by `rounded-lg/md/sm` in the theme `extend`).

## Conventions

### Use semantic tokens, not literal palette colors

* ✅ `bg-primary text-primary-foreground`, `border-border`, `text-muted-foreground`
* ❌ `bg-blue-600 text-white` — breaks dark mode and breaks design consistency.

The only acceptable use of literal palette colors is for things genuinely unrelated to theme (e.g., a temporary debug border in dev).

### Always merge classes through `cn(...)`

```tsx
import { cn } from "@/lib/utils"

<div className={cn("rounded-md p-4", isActive && "bg-primary", className)} />
```

`cn` runs `clsx` (handles falsy / arrays / objects) and `twMerge` (resolves conflicts so `p-2 p-4` correctly becomes `p-4`).

### Dark-mode-aware utilities

The class strategy means you can prefix any utility with `dark:`:

```tsx
<div className="bg-card text-card-foreground dark:shadow-lg" />
```

You almost never need `dark:` for color when using semantic tokens (the variable already swaps).

### Responsive breakpoints

Stick to Tailwind defaults (`sm`, `md`, `lg`, `xl`, `2xl`). Don't add custom breakpoints unless absolutely necessary; if you do, document them in `tailwind.config.ts` next to the existing config.

### Animations

`tailwind.config.ts` extends `keyframes` and `animation` (e.g., `accordion-down`, `accordion-up`). Add new animations there rather than inlining `@keyframes` in CSS files.

### Content globs

Tailwind only generates utilities for classes it can find in:

```
./pages/**/*.{js,ts,jsx,tsx,mdx}
./components/**/*.{js,ts,jsx,tsx,mdx}
./app/**/*.{js,ts,jsx,tsx,mdx}
```

If you add a top-level folder containing JSX with Tailwind classes, **add it to `content`** in `tailwind.config.ts` or those classes will be purged out of the production build.

## How-to: common tasks

### Add a new theme color

1. Add a CSS variable to `app/globals.css` under both `:root` and `.dark`:
   ```css
   :root  { --info: 210 90% 50%; --info-foreground: 0 0% 100%; }
   .dark  { --info: 210 90% 60%; --info-foreground: 0 0% 100%; }
   ```
2. Map it in `tailwind.config.ts` `theme.extend.colors`:
   ```ts
   info: {
     DEFAULT: "hsl(var(--info))",
     foreground: "hsl(var(--info-foreground))",
   },
   ```
3. Use as `bg-info text-info-foreground`.

### Override a single component's spacing

Pass `className` last so `tailwind-merge` overrides earlier conflicting utilities:

```tsx
<Button className="px-8" />  // overrides the variant's default px
```

### Tweak the corner radius globally

Change `--radius` in `app/globals.css` (e.g., `--radius: 0.75rem;`). All `rounded-lg/md/sm` utilities derive from it via `tailwind.config.ts`.

## Pitfalls

* **Don't write `hsl(...)` in the CSS variable value.** The variables store **HSL channels only** (e.g., `222.2 47.4% 11.2%`); the wrapper `hsl(...)` is added in `tailwind.config.ts`. Wrapping in CSS vars breaks the alpha shorthand `bg-primary/90`.
* **`tailwind.config.ts` — not v4 syntax.** This project pins Tailwind 3.x. Don't introduce v4-only features (`@theme`, the new Vite plugin, `@plugin` directives, etc.) without a deliberate version upgrade.
* **Class purging.** A className constructed dynamically by string concatenation won't be detected. Either write the full class literal or list dynamic candidates in a `safelist`.
* **`@apply` in CSS files** — fine in `app/globals.css` for `@layer base/components` rules, but prefer utility classes in JSX whenever possible; `@apply` makes refactoring harder.
* **PostCSS config is ESM (`.mjs`).** If you add plugins, keep the file ESM.

## References

* `tailwind.config.ts`
* `postcss.config.mjs`
* `app/globals.css` — CSS variables and `@layer base`
* `lib/utils.ts` — the `cn` helper
* Tailwind v3 docs: <https://v3.tailwindcss.com/docs>
* `tailwind-merge`: <https://github.com/dcastil/tailwind-merge>
