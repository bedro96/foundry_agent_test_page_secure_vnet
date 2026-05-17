/**
 * 폼 레이블 UI 컴포넌트.
 *
 * 입력 필드와 연결되는 접근 가능한 레이블을 제공합니다.
 * @module label
 */
"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * 폼 입력 필드에 연결되는 레이블 컴포넌트.
 *
 * @param props - 표준 label 요소 props.
 * @returns 스타일이 적용된 label 요소.
 */
function Label({ className, ...props }: React.ComponentProps<"label">) {
  return (
    <label
      data-slot="label"
      className={cn(
        "flex items-center gap-2 text-sm leading-none font-medium select-none group-data-[disabled=true]:pointer-events-none group-data-[disabled=true]:opacity-50 peer-disabled:cursor-not-allowed peer-disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
}

export { Label }
