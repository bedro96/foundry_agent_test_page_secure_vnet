"use client";

/**
 * 채팅 페이지 — 주요 대화형 UI.
 *
 * SSE를 통해 백엔드에 연결된 스트리밍 채팅 인터페이스를 렌더링합니다.
 * 대화 기록 사이드바, 대화 저장/복원, 대화 상세 모달을 포함합니다.
 * @module chat/page
 */
import { History, MessageSquarePlus, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "react-toastify";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  extractSources,
  extractStatusText,
  extractUsageMetrics,
  mergeSources,
} from "@/lib/chat-helpers";
import type { ApiContentPart, ApiMessage, ChatMessage, UsageMetrics } from "@/lib/chat-types";
import { streamChat } from "@/lib/sse-client";
import { useAuthGuard } from "@/lib/useAuthGuard";

/* ── 대화 기록 관련 타입 ── */

/** 대화 목록 항목 타입. */
interface ConversationSummary {
  id: string;
  title: string | null;
  created_at: string;
  message_count: number;
  azure_conversation_id: string | null;
}

/** 대화 상세 메시지 타입. */
interface ConversationMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

/** 대화 상세 조회 응답 타입. */
interface ConversationDetail {
  id: string;
  title: string | null;
  created_at: string;
  azure_conversation_id: string | null;
  messages: ConversationMessage[];
}

/**
 * `crypto.randomUUID`를 사용하여 고유 ID를 생성하며, 타임스탬프 대체를 지원합니다.
 *
 * @returns 고유 문자열 식별자.
 */
const createId = () =>
  globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;

/** 채팅 페이지가 처음 로드될 때 빈 메시지 배열로 시작합니다. */
const initialMessages: ChatMessage[] = [];

/**
 * 프론트엔드 ChatMessage 배열을 백엔드에서 기대하는 API 메시지 형식으로 변환합니다.
 *
 * 상태/오류 메시지를 필터링하고 콘텐츠 파트가 있을 때 매핑합니다.
 *
 * @param messages - React 상태의 전체 채팅 메시지 히스토리.
 * @returns 백엔드에 전송할 준비가 된 {@link ApiMessage} 객체 배열.
 */
const toApiMessages = (messages: ChatMessage[]): ApiMessage[] =>
  messages
    .filter(
      (message): message is ChatMessage & { role: "user" | "assistant" } =>
        (message.role === "user" || message.role === "assistant") &&
        message.content.length > 0,
    )
    .map((message) => ({
      role: message.role,
      content: message.contentParts ?? message.content,
    }));

/**
 * 날짜 문자열을 MM/DD 형식으로 변환합니다.
 *
 * @param dateStr - ISO 8601 형식의 날짜 문자열.
 * @returns "MM/DD" 형식의 문자열.
 */
function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${mm}/${dd}`;
}

/**
 * 채팅 페이지 루트 컴포넌트.
 *
 * 대화 상태를 관리하고, SSE를 통해 어시스턴트 응답을 스트리밍하며,
 * 대화 기록 사이드바와 함께 채팅 패널을 렌더링합니다.
 */
export default function HomePage() {
  // 인증 가드: 미인증 사용자는 로그인 페이지('/')로 리다이렉트
  const { loading: authLoading } = useAuthGuard();

  // 대화 메시지 목록 상태
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  // Azure AI 에이전트 대화 ID (서버 측 세션 식별용)
  const [conversationId, setConversationId] = useState<string | null>(null);
  // SSE 스트리밍 진행 중 여부
  const [isStreaming, setIsStreaming] = useState(false);
  // 토큰 사용량 메트릭 (입력/출력 토큰 수)
  const [usage, setUsage] = useState<UsageMetrics | null>(null);
  // SSE 스트림 중단을 위한 AbortController 참조
  const abortControllerRef = useRef<AbortController | null>(null);
  // 스트리밍 상태를 콜백 내에서 동기적으로 확인하기 위한 참조
  const isStreamingRef = useRef(false);

  /** 대화 기록 목록 상태. */
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  /** 대화 상세 모달에 표시할 대화 데이터. */
  const [selectedConversation, setSelectedConversation] = useState<ConversationDetail | null>(null);
  /** 대화 저장 완료 여부 (중복 저장 방지). */
  const savedConversationIdRef = useRef<string | null>(null);
  /** 현재 페이지 번호 (1부터 시작). */
  const [currentPage, setCurrentPage] = useState(1);
  /** 전체 대화 수 (페이징 계산용). */
  const [totalConversations, setTotalConversations] = useState(0);
  /** 날짜 필터: 시작일 (YYYY-MM-DD). */
  const [filterFrom, setFilterFrom] = useState("");
  /** 날짜 필터: 종료일 (YYYY-MM-DD). */
  const [filterTo, setFilterTo] = useState("");

  /**
   * 백엔드에서 대화 기록 목록을 페이지네이션과 날짜 필터를 적용하여 불러옵니다.
   *
   * @param page - 조회할 페이지 번호 (기본값: currentPage).
   */
  const fetchConversations = useCallback(async (page?: number) => {
    try {
      const p = page ?? currentPage;
      const params = new URLSearchParams({ page: String(p), page_size: "10" });
      if (filterFrom) params.set("from_date", filterFrom);
      if (filterTo) params.set("to_date", filterTo);

      const res = await fetch(`/api/conversations?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        if (data && Array.isArray(data.items)) {
          setConversations(data.items);
          setTotalConversations(data.total ?? 0);
          setCurrentPage(data.page ?? p);
        } else if (Array.isArray(data)) {
          /* 이전 응답 형식 호환 */
          setConversations(data);
          setTotalConversations(data.length);
        }
      } else {
        console.error("[chat] 대화 기록 조회 실패: status=", res.status);
      }
    } catch (err) {
      console.error("[chat] 대화 기록 조회 실패:", err);
    }
  }, [currentPage, filterFrom, filterTo]);

  /**
   * 특정 대화의 상세 내용을 불러와 모달에 표시합니다.
   *
   * @param id - 조회할 대화 ID.
   */
  const openConversationDetail = async (id: string) => {
    try {
      const res = await fetch(`/api/conversations/${id}/messages`);
      if (res.ok) {
        const data: ConversationDetail = await res.json();
        setSelectedConversation(data);
      }
    } catch (err) {
      console.error("[chat] 대화 상세 조회 실패:", err);
    }
  };

  /**
   * 대화를 숨김 처리(아카이브)합니다.
   *
   * @param id - 숨길 대화 ID.
   */
  const hideConversation = async (id: string) => {
    try {
      const res = await fetch(`/api/conversations/${id}/hide`, { method: "PATCH" });
      if (res.ok) {
        setConversations((prev) => prev.filter((c) => c.id !== id));
        setTotalConversations((prev) => Math.max(0, prev - 1));
      } else {
        toast.error("대화 숨기기에 실패했습니다.");
      }
    } catch (err) {
      console.error("[chat] 대화 숨기기 실패:", err);
      toast.error("대화 숨기기에 실패했습니다.");
    }
  };

  /**
   * 선택한 대화를 이어서 계속합니다.
   * 대화 메시지를 채팅 상태로 로드하고 대화 ID를 설정합니다.
   */
  const continueConversation = () => {
    if (!selectedConversation) return;
    const loaded: ChatMessage[] = selectedConversation.messages.map((msg) => ({
      id: createId(),
      role: msg.role as "user" | "assistant",
      content: msg.content,
    }));
    setMessages(loaded);
    setConversationId(selectedConversation.azure_conversation_id ?? null);
    savedConversationIdRef.current = null;
    setSelectedConversation(null);
  };

  /**
   * 현재 대화를 백엔드에 저장합니다.
   *
   * @param allMessages - 저장할 전체 메시지 배열.
   * @param convId - 기존 대화 ID (있으면 업데이트).
   */
  const saveConversation = async (allMessages: ChatMessage[], convId: string | null) => {
    /** user/assistant 메시지만 필터링 */
    const saveable = allMessages.filter(
      (m) => (m.role === "user" || m.role === "assistant") && m.content.trim(),
    );
    if (saveable.length === 0) return;

    /** 첫 번째 사용자 메시지에서 제목 생성 */
    const firstUserMsg = saveable.find((m) => m.role === "user")?.content || "";
    const title = firstUserMsg.length > 30 ? firstUserMsg.slice(0, 30) + "..." : firstUserMsg;

    try {
      await fetch("/api/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          conversation_id: convId,
          messages: saveable.map((m) => ({ role: m.role, content: m.content })),
        }),
      });
      console.info("[chat] 대화 저장 완료");
      fetchConversations();
    } catch (err) {
      console.error("[chat] 대화 저장 실패:", err);
    }
  };

  /**
   * 새 대화를 시작합니다 (메시지 초기화, 대화 ID 리셋).
   */
  const startNewConversation = () => {
    setMessages(initialMessages);
    setConversationId(null);
    setUsage(null);
    savedConversationIdRef.current = null;
  };

  /** 상태/오류 메시지를 토스트 알림으로 표시합니다. */
  const showToast = (type: "status" | "error", content: string) => {
    if (!content.trim()) return;
    if (type === "error") {
      toast.error(content);
    } else {
      toast.info(content);
    }
  };

  useEffect(() => {
    /** 페이지 로드 시 또는 필터/페이지 변경 시 대화 기록을 불러옵니다. */
    fetchConversations();
    return () => {
      abortControllerRef.current?.abort();
    };
  }, [fetchConversations]);

  /**
   * 사용자 메시지 전송 핸들러.
   *
   * 사용자 메시지와 선택적 이미지를 받아 SSE 스트림을 시작하고,
   * 어시스턴트 응답을 실시간으로 화면에 렌더링합니다.
   *
   * @param content - 사용자가 입력한 텍스트 메시지.
   * @param images - 첨부된 이미지 URL 배열 (선택).
   */
  const handleSend = async (content: string, images?: string[]) => {
    if (isStreamingRef.current) {
      return;
    }

    console.log(`[chat] User sent message: length=${content.length} images=${images?.length ?? 0}`);
    // 이미지가 있으면 멀티파트 콘텐츠 파트로 구성
    let contentParts: ApiContentPart[] | undefined;
    if (images && images.length > 0) {
      contentParts = [
        { type: "input_text", text: content },
        ...images.map((url) => ({ type: "input_image" as const, image_url: url })),
      ];
    }

    // 사용자 메시지 객체 생성
    const userMessage: ChatMessage = {
      id: createId(),
      role: "user",
      content,
      ...(contentParts ? { contentParts } : {}),
    };
    // 빈 어시스턴트 메시지 플레이스홀더 생성
    const assistantMessageId = createId();
    // 사용자 + 어시스턴트 플레이스홀더를 포함한 다음 메시지 배열
    const nextMessages = [
      ...messages,
      userMessage,
      { id: assistantMessageId, role: "assistant", content: "", sources: [] },
    ] as ChatMessage[];

    setMessages(nextMessages);
    setIsStreaming(true);
    isStreamingRef.current = true;
    setUsage(null);
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      console.log("[chat] Starting SSE stream");
      await streamChat(
        toApiMessages(nextMessages),
        conversationId,
        (event) => {
          if (event.conversation_id) {
            setConversationId(event.conversation_id);
          }

        const statusText = extractStatusText(event.data);
        const sources = extractSources(event.data);
        const metrics = extractUsageMetrics(event.data);

        if (metrics) {
          setUsage((current) => ({ ...(current ?? {}), ...metrics }));
          if (metrics.promptTokens || metrics.completionTokens) {
            toast(`토큰: 입력 ${metrics.promptTokens ?? 0} / 출력 ${metrics.completionTokens ?? 0}`, { autoClose: 5000 });
          }
        }

        if (sources.length) {
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantMessageId
                ? { ...message, sources: mergeSources(message.sources, sources) }
                : message,
            ),
          );
        }

        if (event.event === "message") {
          const delta = typeof event.data === "string" ? event.data : statusText || "";
          if (!delta) {
            return;
          }

          setMessages((current) =>
            current.map((message) =>
              message.id === assistantMessageId
                ? { ...message, content: `${message.content}${delta}` }
                : message,
            ),
          );
          return;
        }

        if (event.event === "status") {
          if (statusText) {
            const sourceMatch = statusText.match(
              /^Source:\s*(.+?)\s*-\s*(https?:\/\/\S+)$/,
            );
            if (sourceMatch) {
              const parsed = [
                {
                  title: sourceMatch[1].trim(),
                  url: sourceMatch[2].trim(),
                },
              ];
              setMessages((current) =>
                current.map((message) =>
                  message.id === assistantMessageId
                    ? {
                        ...message,
                        sources: mergeSources(message.sources, parsed),
                      }
                    : message,
                ),
              );
            } else {
              showToast("status", statusText);
            }
          }
          return;
        }

        if (event.event === "error") {
          showToast(
            "error",
            statusText || "어시스턴트가 요청 처리 중 오류를 반환했습니다.",
          );
          return;
        }

        if (event.event === "done" && statusText === "failed") {
          toast.error("응답이 실패 상태로 종료되었습니다.");
        }
        },
        controller.signal,
      );
    } catch (error) {
      console.log(`[chat] Stream error: ${error instanceof Error ? error.message : "unknown"}`);
      const errorMessage =
        error instanceof Error ? error.message : "백엔드 연결 오류";
      toast.error(errorMessage);
      setMessages((current) => current.filter((message) => message.id !== assistantMessageId));
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
      }
      setIsStreaming(false);
      isStreamingRef.current = false;
      console.log("[chat] Stream completed");
      setMessages((current) => {
        /** 빈 어시스턴트 메시지 제거 후 대화 저장 */
        const cleaned = current.filter(
          (message) =>
            message.id !== assistantMessageId ||
            Boolean(message.content.trim()) ||
            Boolean(message.sources?.length),
        );

        /** 스트림 완료 후 대화 자동 저장 (중복 저장 방지) */
        const hasAssistant = cleaned.some(
          (m) => m.role === "assistant" && m.content.trim(),
        );
        if (hasAssistant) {
          /* 최신 conversationId를 클로저 밖에서 가져오기 위해 setTimeout 사용 */
          setTimeout(() => {
            saveConversation(cleaned, conversationId);
          }, 100);
        }

        return cleaned;
      });
    }
  };

  // 인증 확인 중이면 로딩 표시
  if (authLoading) {
    return (
      <main className="flex flex-1 items-center justify-center">
        <div className="text-muted-foreground text-sm">인증 확인 중...</div>
      </main>
    );
  }

  return (
    <main className="flex flex-1 overflow-hidden px-4 py-4 sm:px-6 sm:py-6">
      <div className="mx-auto grid w-full max-w-7xl flex-1 gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        {/* ── 대화 기록 사이드바 ── */}
        <aside className="hidden lg:flex lg:flex-col lg:gap-4">
          <Card>
            <CardContent className="space-y-3 py-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <History className="size-4 text-primary" />
                  대화 기록
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={startNewConversation}
                  className="h-7 gap-1 text-xs"
                >
                  <MessageSquarePlus className="size-3.5" />
                  새 대화
                </Button>
              </div>

              {/* ── 날짜 필터 ── */}
              <div className="flex items-end gap-2">
                <div className="flex flex-col">
                  <label className="mb-0.5 text-[10px] text-muted-foreground">시작</label>
                  <input
                    type="date"
                    value={filterFrom}
                    onChange={(e) => { setFilterFrom(e.target.value); setCurrentPage(1); }}
                    className="rounded border bg-background px-1.5 py-0.5 text-xs"
                  />
                </div>
                <div className="flex flex-col">
                  <label className="mb-0.5 text-[10px] text-muted-foreground">종료</label>
                  <input
                    type="date"
                    value={filterTo}
                    onChange={(e) => { setFilterTo(e.target.value); setCurrentPage(1); }}
                    className="rounded border bg-background px-1.5 py-0.5 text-xs"
                  />
                </div>
              </div>

              <ScrollArea className="h-[calc(100vh-300px)]">
                <div className="space-y-1 pr-2">
                  {conversations.length === 0 ? (
                    <p className="py-8 text-center text-xs text-muted-foreground">
                      대화 기록이 없습니다
                    </p>
                  ) : (
                    conversations.map((conv) => {
                      /** 제목이 없으면 "새 대화"를 표시 */
                      const displayTitle =
                        conv.title && conv.title.trim()
                          ? conv.title.length > 20
                            ? conv.title.slice(0, 20) + "…"
                            : conv.title
                          : "새 대화";
                      const dateLabel = formatDate(conv.created_at);
                      return (
                        <button
                          key={conv.id}
                          onClick={() => openConversationDetail(conv.id)}
                          className="group flex w-full items-center justify-between rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent"
                        >
                          <span className="truncate text-foreground">
                            {displayTitle}
                          </span>
                          <span className="ml-2 flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
                            [{dateLabel}]
                            <span
                              role="button"
                              tabIndex={0}
                              onClick={(e) => { e.stopPropagation(); hideConversation(conv.id); }}
                              onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); hideConversation(conv.id); } }}
                              className="ml-0.5 hidden cursor-pointer rounded p-0.5 text-muted-foreground hover:bg-destructive/20 hover:text-destructive group-hover:inline-flex"
                              title="숨기기"
                            >
                              <X className="size-3" />
                            </span>
                          </span>
                        </button>
                      );
                    })
                  )}
                </div>
              </ScrollArea>

              {/* ── 페이지네이션 ── */}
              {totalConversations > 15 && (
                <div className="flex items-center justify-between border-t pt-2 text-xs">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={currentPage <= 1}
                    onClick={() => { const p = currentPage - 1; setCurrentPage(p); fetchConversations(p); }}
                    className="h-6 px-2 text-xs"
                  >
                    이전
                  </Button>
                  <span className="text-muted-foreground">
                    {currentPage} / {Math.ceil(totalConversations / 15)}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={currentPage >= Math.ceil(totalConversations / 15)}
                    onClick={() => { const p = currentPage + 1; setCurrentPage(p); fetchConversations(p); }}
                    className="h-6 px-2 text-xs"
                  >
                    다음
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </aside>

        <ChatPanel
          conversationId={conversationId}
          isStreaming={isStreaming}
          messages={messages}
          onSend={handleSend}
          usage={usage}
        />
      </div>

      {/* ── 대화 상세 모달 ── */}
      {selectedConversation && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={() => setSelectedConversation(null)}
        >
          <div
            className="relative mx-4 flex max-h-[80vh] w-full max-w-2xl flex-col rounded-lg border bg-background shadow-lg"
            onClick={(e) => e.stopPropagation()}
          >
            {/* 모달 헤더 */}
            <div className="flex items-center justify-between border-b px-5 py-4">
              <h2 className="text-lg font-semibold">
                {selectedConversation.title || "새 대화"}
              </h2>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSelectedConversation(null)}
                className="size-8 p-0"
              >
                <X className="size-4" />
              </Button>
            </div>

            {/* 모달 본문: 메시지 목록 */}
            <ScrollArea className="flex-1 overflow-y-auto">
              <div className="space-y-4 p-5">
                {selectedConversation.messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`rounded-lg p-3 text-sm ${
                      msg.role === "user"
                        ? "ml-8 bg-primary/10"
                        : "mr-8 bg-muted"
                    }`}
                  >
                    <div className="mb-1 text-xs font-medium text-muted-foreground">
                      {msg.role === "user" ? "사용자" : "어시스턴트"}
                    </div>
                    <div className="whitespace-pre-wrap leading-relaxed">
                      {msg.content}
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>

            {/* 모달 하단: 대화 계속하기 버튼 */}
            <div className="flex justify-end border-t px-5 py-3">
              <Button size="sm" onClick={continueConversation}>
                계속하기
              </Button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
