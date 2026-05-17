/**
 * 채팅 패널 컴포넌트.
 *
 * 대화 메시지 목록, 입력 영역, 사용량 메트릭 배지를 포함하는
 * 전체 채팅 인터페이스를 렌더링합니다.
 * @module ChatPanel
 */
"use client";

import { MessagesSquare } from "lucide-react";
import { useEffect, useRef } from "react";
import { toast } from "react-toastify";

import { ChatInput } from "@/components/chat/ChatInput";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import type { ChatMessage as ChatMessageType, UsageMetrics } from "@/lib/chat-types";

/** ChatPanel 컴포넌트의 props 인터페이스. */
interface ChatPanelProps {
  /** 현재 대화 ID (새 대화인 경우 `null`). */
  conversationId: string | null;
  /** 어시스턴트가 현재 응답을 스트리밍 중인지 여부. */
  isStreaming: boolean;
  /** 표시할 채팅 메시지 배열. */
  messages: ChatMessageType[];
  /** 사용자가 메시지를 전송할 때 호출되는 콜백. */
  onSend: (value: string, images?: string[]) => void | Promise<void>;
  /** 토큰 사용량 및 성능 메트릭 (표시할 데이터가 없으면 `null`). */
  usage: UsageMetrics | null;
}

/**
 * 대화 메시지, 입력 영역, 사용량 메트릭을 포함하는 채팅 패널.
 *
 * 스트리밍 중에는 로딩 토스트를 표시하고,
 * 새 메시지가 추가되면 자동으로 하단으로 스크롤합니다.
 *
 * @param props - {@link ChatPanelProps} 참조.
 * @returns 채팅 패널 UI 요소.
 */
export function ChatPanel({
  conversationId,
  isStreaming,
  messages,
  onSend,
  usage,
}: ChatPanelProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null); // 스크롤 하단 위치를 추적하는 참조
  const streamToastRef = useRef<ReturnType<typeof toast> | null>(null); // 스트리밍 중 표시되는 토스트 알림 참조

  // 스트리밍 상태 변화에 따라 로딩 토스트 표시/해제
  useEffect(() => {
    if (isStreaming) {
      streamToastRef.current = toast.info("Assistant is streaming a response…", {
        autoClose: false,
        isLoading: true,
      });
    } else if (streamToastRef.current !== null) {
      toast.dismiss(streamToastRef.current);
      streamToastRef.current = null;
    }
  }, [isStreaming]);

  // 새 메시지가 추가되거나 스트리밍 상태 변경 시 하단으로 자동 스크롤
  useEffect(() => {
  }, [messages, isStreaming]);

  return (
    <div className="flex h-full flex-1 flex-col overflow-hidden rounded-[1.75rem] border bg-muted/20 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 sm:px-6">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium">
            <MessagesSquare className="size-4" />
            Live chat
          </div>
          <p className="text-sm text-muted-foreground">
            Streamed answers with status updates and source citations.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{conversationId ? "Conversation active" : "New conversation"}</Badge>
          {conversationId ? (
            <Badge className="max-w-52 truncate" variant="secondary">
              {conversationId}
            </Badge>
          ) : null}
        </div>
      </div>

      <ScrollArea className="flex-1 px-4 py-4 sm:px-6">
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
          {messages.length === 0 && !isStreaming ? (
            <div className="flex flex-1 items-center justify-center py-16">
              <p className="text-center text-sm text-muted-foreground">
                질문을 입력하여 대화를 시작하세요.
              </p>
            </div>
          ) : null}
          {messages.map((message) => (
            <ChatMessage key={message.id} message={message} />
          ))}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      <div className="border-t bg-background/80 px-4 py-3 backdrop-blur sm:px-6">
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {usage?.totalTokens ? (
              <Badge variant="outline">Total tokens: {usage.totalTokens}</Badge>
            ) : null}
            {usage?.promptTokens ? (
              <Badge variant="outline">Prompt: {usage.promptTokens}</Badge>
            ) : null}
            {usage?.completionTokens ? (
              <Badge variant="outline">Completion: {usage.completionTokens}</Badge>
            ) : null}
            {usage?.responseTimeMs ? (
              <Badge variant="outline">Latency: {usage.responseTimeMs} ms</Badge>
            ) : null}
            {usage?.model ? <Badge variant="outline">Model: {usage.model}</Badge> : null}
          </div>
          <Separator />
          <ChatInput isLoading={isStreaming} onSend={onSend} />
        </div>
      </div>
    </div>
  );
}
