/**
 * 개별 채팅 메시지 버블 컴포넌트.
 *
 * 사용자 메시지는 오른쪽 정렬, 어시스턴트 메시지는 왼쪽 정렬로 표시됩니다.
 * 어시스턴트 메시지는 Markdown 렌더링 및 출처 인용을 지원합니다.
 * @module ChatMessage
 */
import { ExternalLink, Sparkles, User2 } from "lucide-react";
import Image from "next/image";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

import type { ChatMessage as ChatMessageType } from "@/lib/chat-types";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** ChatMessage 컴포넌트의 props 인터페이스. */
interface ChatMessageProps {
  /** 렌더링할 채팅 메시지 데이터. */
  message: ChatMessageType;
}

/**
 * 단일 채팅 메시지를 카드 형태로 렌더링하는 컴포넌트.
 *
 * - **사용자 메시지**: 오른쪽 정렬, 첨부 이미지 미리보기 포함.
 * - **어시스턴트 메시지**: 왼쪽 정렬, Markdown 렌더링, 출처 인용 링크 포함.
 *
 * @param props - {@link ChatMessageProps} 참조.
 * @returns 채팅 메시지 카드 요소.
 */
export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === "user"; // 사용자 메시지 여부 확인 (정렬 방향 결정)

  return (
    <div className={cn("flex w-full", isUser ? "justify-end" : "justify-start")}>
      <Card
        className={cn(
          "max-w-3xl shadow-sm",
          isUser
            ? "w-auto bg-primary text-primary-foreground ring-primary/20"
            : "w-full bg-card",
        )}
      >
        <CardContent className="space-y-3 py-4">
          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.2em] opacity-80">
            {isUser ? <User2 className="size-4" /> : <Sparkles className="size-4" />}
            <span>{isUser ? "You" : "Assistant"}</span>
          </div>
          {isUser ? (
            <>
              {message.contentParts?.some((p) => p.type === "input_image") ? (
                <div className="flex flex-wrap gap-2">
                  {message.contentParts
                    .filter((p) => p.type === "input_image")
                    .map((p, i) =>
                      p.type === "input_image" ? (
                        <Image
                          key={i}
                          src={p.image_url}
                          alt={`Attached image ${i + 1}`}
                          width={128}
                          height={128}
                          className="size-32 rounded-lg border border-primary-foreground/20 object-cover"
                          unoptimized
                        />
                      ) : null,
                    )}
                </div>
              ) : null}
              <p className="whitespace-pre-wrap leading-7">{message.content}</p>
            </>
          ) : (
            <div className="chat-markdown">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeRaw, rehypeSanitize, rehypeHighlight]}
                components={{
                  a: ({ ...props }) => (
                    <a
                      {...props}
                      className="font-medium text-primary underline underline-offset-4"
                      rel="noreferrer"
                      target="_blank"
                    />
                  ),
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </CardContent>
        {!isUser && message.sources?.length ? (
          <CardFooter className="flex flex-col items-start gap-1 border-t border-muted/30 pt-3">
            <span className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground/60">
              Sources
            </span>
            {message.sources.map((source, index) =>
              source.url ? (
                <a
                  key={source.url}
                  className="inline-flex items-center gap-1 text-[11px] leading-tight text-muted-foreground transition hover:text-primary"
                  href={source.url}
                  rel="noreferrer"
                  target="_blank"
                >
                  <span className="font-medium text-muted-foreground/70">[{index + 1}]</span>
                  <span className="max-w-xs truncate underline underline-offset-2">
                    {source.title || source.label || "Source"}
                  </span>
                  <ExternalLink className="size-2.5 shrink-0" />
                </a>
              ) : (
                <span
                  key={`source-${index}`}
                  className="inline-flex items-center gap-1 text-[11px] leading-tight text-muted-foreground"
                >
                  <span className="font-medium text-muted-foreground/70">[{index + 1}]</span>
                  <span className="max-w-xs truncate">
                    {source.title || source.label || "Source"}
                  </span>
                </span>
              ),
            )}
          </CardFooter>
        ) : null}
      </Card>
    </div>
  );
}
