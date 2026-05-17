/**
 * 텍스트 영역(Textarea) UI 컴포넌트.
 *
 * 여러 줄 텍스트 입력을 위한 스타일이 적용된 textarea를 제공합니다.
 * `forwardRef`를 사용하여 외부에서 ref 접근이 가능합니다.
 * @module textarea
 */
import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * 여러 줄 텍스트 입력을 위한 Textarea 컴포넌트.
 *
 * `React.forwardRef`로 래핑되어 외부에서 DOM ref에 접근할 수 있습니다.
 *
 * @param props - 표준 textarea 요소 props.
 * @param ref - 외부에서 전달되는 ref.
 * @returns 스타일이 적용된 textarea 요소.
 */
const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.ComponentProps<"textarea">
>(({ className, ...props }, ref) => {
  return (
    <textarea
      ref={ref}
      data-slot="textarea"
      className={cn(
        "flex field-sizing-content min-h-16 w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-base transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 md:text-sm dark:bg-input/30 dark:disabled:bg-input/80 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40",
        className
      )}
      {...props}
    />
  )
})

Textarea.displayName = "Textarea"

export { Textarea }
