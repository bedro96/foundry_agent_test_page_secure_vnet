---
name: shadcn
display_name: shadcn/ui
description: >-
    UI components built on shadcn/ui with Radix UI primitives, Tailwind CSS styling,
    and class-variance-authority (cva) variants. Covers component patterns (forwardRef,
    asChild, cn), theming, dark mode, and the shadcn CLI workflow.
user-invocable: true
---

# Skill: shadcn/ui

## Overview

The UI is built on **shadcn/ui** components — copy-pasted, fully owned React components built on top of **Radix UI primitives**, styled with **Tailwind CSS**, with variants powered by **`class-variance-authority` (cva)**. Components are *not* installed as a runtime dependency; they live in `components/ui/` and are owned by this repo. Icons come from **`lucide-react`**.

The shadcn config (`components.json`) selects the **`new-york`** style with **`neutral`** base color, **CSS variables** enabled, **RSC** support on, and **TSX**.

## Where it lives

| Path                            | Purpose                                                          |
| ------------------------------- | ---------------------------------------------------------------- |
| `components.json`               | shadcn CLI configuration (style, aliases, icon library)          |
| `components/ui/`                | All shadcn primitives owned by this repo                         |
| `components/`                   | App-level composite components (e.g., `admin-nav.tsx`, `chart-area-interactive.tsx`, `mode-toggle.tsx`, `theme-provider.tsx`, `device-grid.tsx`) |
| `lib/utils.ts`                  | The shared `cn(...)` helper — `twMerge(clsx(...))`               |
| `app/globals.css`               | CSS variables that drive the theme tokens (light + dark)         |

### Currently installed primitives

`components/ui/` contains: `alert-dialog`, `button`, `card`, `chart`, `dialog`, `hover-card`, `input`, `label`, `select`, `separator`, `switch`, `table`. Anything else needs to be added with the shadcn CLI.

## Conventions

### Component shape (mirror `button.tsx`)

```tsx
import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const fooVariants = cva("base classes here", {
  variants: { variant: { default: "...", outline: "..." } },
  defaultVariants: { variant: "default" },
})

export interface FooProps
  extends React.ComponentPropsWithoutRef<"div">,
    VariantProps<typeof fooVariants> {}

const Foo = React.forwardRef<HTMLDivElement, FooProps>(
  ({ className, variant, ...props }, ref) => (
    <div ref={ref} className={cn(fooVariants({ variant, className }))} {...props} />
  ),
)
Foo.displayName = "Foo"

export { Foo, fooVariants }
```

Patterns to maintain:

* **`cva` for variants** — never inline conditional class strings; declare them once.
* **`cn(...)` always wraps** the final className so user-supplied `className` props can override.
* **`React.forwardRef`** for every primitive that wraps a DOM element.
* **`asChild` + `<Slot>`** when the component should optionally render its child instead of the default element (see `Button`).
* **Named exports**, not default exports.
* Set `displayName` on the forwarded component.

### Icons

* Import from `lucide-react`: `import { Plus, Trash2 } from "lucide-react"`.
* `components/ui/button.tsx` already includes `[&_svg]:size-4 [&_svg]:shrink-0` so SVGs sized via the CSS auto-rule. Don't pass explicit `size` props unless overriding.

### Aliases (from `components.json`)

* `@/components` → general components
* `@/components/ui` → shadcn primitives
* `@/lib` → utilities
* `@/lib/utils` → `cn` helper
* `@/hooks` → custom hooks (`components/hooks/`)

Use these aliases — never relative paths into `components/ui/`.

### Theming / colors

All colors come from CSS variables (e.g., `bg-primary`, `text-muted-foreground`). The variable values live in `app/globals.css` under `:root` (light) and `.dark` (dark). See the [tailwind skill](../tailwind/SKILL.md) for the full theme-token list.

**Do not** hard-code colors like `bg-blue-500` in shadcn primitives — it breaks dark mode. Use the semantic tokens (`primary`, `secondary`, `accent`, `destructive`, `muted`, `border`, `input`, `ring`, `background`, `foreground`, `card`, `popover`, `chart-1`…`chart-5`).

### Dark mode

Dark mode uses the **class strategy** (`darkMode: ["class"]` in `tailwind.config.ts`) and is wired via **`next-themes`** (`ThemeProvider` in `components/theme-provider.tsx`, mounted in `app/layout.tsx` with `attribute="class"`). Use `useTheme()` from `next-themes` inside client components; the toggle is `components/mode-toggle.tsx`.

## How-to: common tasks

### Add a new shadcn primitive

Use the shadcn CLI so the file lands with current upstream conventions for our config (`new-york` / RSC / neutral / CSS variables / TSX):

```bash
npx shadcn@latest add <component>     # e.g. tabs, tooltip, popover, sheet, sonner
```

The CLI reads `components.json`, drops the file into `components/ui/`, and may add Radix peer deps. Verify:

1. The new file imports `cn` from `@/lib/utils` (not a relative path).
2. New Radix dependencies were installed and committed in `package.json` / `pnpm-lock.yaml`.
3. The component uses CSS variable tokens (no hard-coded colors).

### Add a custom variant to an existing primitive

Edit the `cva(...)` block in the relevant `components/ui/<name>.tsx`. Add the new variant key, then update consumers. Keep `defaultVariants` stable to avoid breaking existing call sites.

### Build a composite component

Composite components (page-specific assemblies) go in `components/<name>.tsx`, *not* in `components/ui/`. They import primitives from `@/components/ui/...` and may add `"use client"` if interactive.

## Pitfalls

* **`components/ui/*` files are owned by this repo.** If you re-run the shadcn CLI for a component that already exists, review the diff carefully — you may lose local modifications.
* **`radix-ui` and individual `@radix-ui/react-*` packages** are both in `package.json`. New shadcn components typically pull individual `@radix-ui/react-*` peers; that's fine, just ensure they're installed.
* **Don't use `clsx` directly** for conditional Tailwind classes that may conflict — always go through `cn(...)` so `tailwind-merge` resolves duplicates.
* **`asChild` cloning** with `Slot` only works when the child is a single React element. Wrapping multiple children will throw at runtime.
* **Server components can render shadcn primitives** as long as the primitive itself doesn't use hooks. Most current primitives are client-friendly only because Radix uses hooks under the hood — when in doubt, mark the consuming page `"use client"`.

## References

* `components.json` — shadcn config
* `components/ui/button.tsx` — canonical example of the `cva` + `forwardRef` + `asChild` pattern
* `lib/utils.ts` — the `cn` helper
* `components/mode-toggle.tsx`, `components/theme-provider.tsx` — theme integration
* shadcn/ui docs: <https://ui.shadcn.com>
