/**
 * 카드 UI 컴포넌트 모음.
 *
 * Card, CardHeader, CardTitle, CardDescription, CardAction,
 * CardContent, CardFooter로 구성된 컴포저블 카드 레이아웃입니다.
 * @module card
 */
import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * 카드 컨테이너 컴포넌트.
 *
 * @param props - div props와 선택적 `size` ("default" | "sm").
 * @returns 카드 컨테이너 요소.
 */
function Card({
  className,
  size = "default",
  ...props
}: React.ComponentProps<"div"> & { size?: "default" | "sm" }) {
  return (
    <div
      data-slot="card"
      data-size={size}
      className={cn(
        "group/card flex flex-col gap-4 overflow-hidden rounded-xl bg-card py-4 text-sm text-card-foreground ring-1 ring-foreground/10 has-data-[slot=card-footer]:pb-0 has-[>img:first-child]:pt-0 data-[size=sm]:gap-3 data-[size=sm]:py-3 data-[size=sm]:has-data-[slot=card-footer]:pb-0 *:[img:first-child]:rounded-t-xl *:[img:last-child]:rounded-b-xl",
        className
      )}
      {...props}
    />
  )
}

/**
 * 카드 헤더 영역 컴포넌트.
 *
 * @param props - div 요소의 표준 props.
 * @returns 카드 헤더 요소.
 */
function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-header"
      className={cn(
        "group/card-header @container/card-header grid auto-rows-min items-start gap-1 rounded-t-xl px-4 group-data-[size=sm]/card:px-3 has-data-[slot=card-action]:grid-cols-[1fr_auto] has-data-[slot=card-description]:grid-rows-[auto_auto] [.border-b]:pb-4 group-data-[size=sm]/card:[.border-b]:pb-3",
        className
      )}
      {...props}
    />
  )
}

/**
 * 카드 제목 컴포넌트.
 *
 * @param props - div 요소의 표준 props.
 * @returns 카드 제목 요소.
 */
function CardTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-title"
      className={cn(
        "font-heading text-base leading-snug font-medium group-data-[size=sm]/card:text-sm",
        className
      )}
      {...props}
    />
  )
}

/**
 * 카드 설명 텍스트 컴포넌트.
 *
 * @param props - div 요소의 표준 props.
 * @returns 카드 설명 요소.
 */
function CardDescription({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-description"
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  )
}

/**
 * 카드 액션 영역 컴포넌트 (헤더 우측 상단에 배치).
 *
 * @param props - div 요소의 표준 props.
 * @returns 카드 액션 요소.
 */
function CardAction({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-action"
      className={cn(
        "col-start-2 row-span-2 row-start-1 self-start justify-self-end",
        className
      )}
      {...props}
    />
  )
}

/**
 * 카드 본문 콘텐츠 영역 컴포넌트.
 *
 * @param props - div 요소의 표준 props.
 * @returns 카드 콘텐츠 요소.
 */
function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-content"
      className={cn("px-4 group-data-[size=sm]/card:px-3", className)}
      {...props}
    />
  )
}

/**
 * 카드 하단 푸터 영역 컴포넌트.
 *
 * @param props - div 요소의 표준 props.
 * @returns 카드 푸터 요소.
 */
function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-footer"
      className={cn(
        "flex items-center rounded-b-xl border-t bg-muted/50 p-4 group-data-[size=sm]/card:p-3",
        className
      )}
      {...props}
    />
  )
}

export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardAction,
  CardDescription,
  CardContent,
}
