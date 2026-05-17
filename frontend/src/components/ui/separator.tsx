/**
 * 구분선 UI 컴포넌트.
 *
 * 수평 또는 수직 방향의 시각적 구분선을 렌더링합니다.
 * @module separator
 */
"use client"

import { Separator as SeparatorPrimitive } from "@base-ui/react/separator"

import { cn } from "@/lib/utils"

/**
 * 수평 또는 수직 방향의 시각적 구분선 컴포넌트.
 *
 * @param props - Separator 프리미티브 props (orientation 포함).
 * @returns 구분선 요소.
 */
function Separator({
  className,
  orientation = "horizontal",
  ...props
}: SeparatorPrimitive.Props) {
  return (
    <SeparatorPrimitive
      data-slot="separator"
      orientation={orientation}
      className={cn(
        "shrink-0 bg-border data-horizontal:h-px data-horizontal:w-full data-vertical:w-px data-vertical:self-stretch",
        className
      )}
      {...props}
    />
  )
}

export { Separator }
