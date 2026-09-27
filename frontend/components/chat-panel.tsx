"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import {
  Sparkles,
  Send,
  AlertCircle,
  RefreshCw,
  FileCode2,
  ArrowRight,
  User,
  Bot,
  Layers,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { repositoriesApi } from "@/lib/api/repositories";
import { ApiClientError } from "@/lib/api/client";
import type { Citation, IngestionStatus } from "@/lib/api/types";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Citation[];
  isGenerating?: boolean;
  isError?: boolean;
}

interface ChatPanelProps {
  repositoryId: string;
  repositoryStatus: IngestionStatus;
  onSelectFile: (path: string, line?: number) => void;
  className?: string;
}

export function ChatPanel({
  repositoryId,
  repositoryStatus,
  onSelectFile,
  className = "",
}: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [lastFailedQuery, setLastFailedQuery] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const isIndexed = repositoryStatus === "completed";

  // Auto-scroll to bottom of messages
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isGenerating]);

  const handleSend = useCallback(
    async (queryText: string) => {
      const trimmed = queryText.trim();
      if (!trimmed || !isIndexed || isGenerating) return;

      const userMsgId = `user-${Date.now()}`;
      const assistantMsgId = `asst-${Date.now()}`;

      const userMessage: ChatMessage = {
        id: userMsgId,
        role: "user",
        content: trimmed,
      };

      const pendingAssistantMessage: ChatMessage = {
        id: assistantMsgId,
        role: "assistant",
        content: "",
        isGenerating: true,
      };

      setMessages((prev) => [...prev, userMessage, pendingAssistantMessage]);
      setInput("");
      setIsGenerating(true);
      setLastFailedQuery(null);

      try {
        const response = await repositoriesApi.chat(repositoryId, {
          question: trimmed,
        });

        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMsgId
              ? {
                  ...msg,
                  content: response.answer,
                  sources: response.sources,
                  isGenerating: false,
                }
              : msg
          )
        );
      } catch (err) {
        const errorMessage =
          err instanceof ApiClientError
            ? err.detail || `Server error (${err.status})`
            : "An unexpected error occurred while communicating with the assistant.";

        setLastFailedQuery(trimmed);

        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMsgId
              ? {
                  ...msg,
                  content: errorMessage,
                  isGenerating: false,
                  isError: true,
                }
              : msg
          )
        );
      } finally {
        setIsGenerating(false);
      }
    },
    [repositoryId, isIndexed, isGenerating]
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    handleSend(input);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend(input);
    }
  };

  const handleRetry = () => {
    if (lastFailedQuery) {
      handleSend(lastFailedQuery);
    }
  };

  return (
    <div
      className={`flex flex-col h-full overflow-hidden bg-sidebar/30 ${className}`}
      data-testid="chat-panel"
    >
      {/* Header */}
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-border px-4 bg-muted/10">
        <div className="flex items-center gap-2 min-w-0">
          <Bot className="size-4 shrink-0 text-primary" />
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground truncate">
            Repository Assistant
          </span>
        </div>
        <Badge
          variant="outline"
          className="text-[10px] font-mono px-1.5 py-0 h-5 text-muted-foreground border-border/80"
        >
          RAG
        </Badge>
      </div>

      {/* Main Conversation Area */}
      <div className="flex-1 overflow-y-auto min-h-0 p-3 space-y-4" data-testid="chat-messages">
        {!isIndexed ? (
          /* State 1: Unindexed repository */
          <div
            className="flex flex-col items-center justify-center p-6 text-center h-full"
            data-testid="chat-not-indexed"
          >
            <div className="flex size-10 items-center justify-center rounded-xl border border-border bg-muted/30 mb-3 text-muted-foreground">
              <Layers className="size-5" />
            </div>
            <h4 className="text-xs font-semibold text-foreground mb-1">
              Indexing required
            </h4>
            <p className="text-xs text-muted-foreground max-w-xs leading-relaxed">
              This repository has not been indexed yet. Complete indexing to enable grounded RAG question-answering.
            </p>
          </div>
        ) : messages.length === 0 ? (
          /* State 2: Welcome / Initial State */
          <div className="flex flex-col items-center justify-center p-6 text-center h-full">
            <div className="flex size-10 items-center justify-center rounded-xl border border-border bg-muted/30 mb-3 text-primary">
              <Sparkles className="size-5" />
            </div>
            <h4 className="text-xs font-semibold text-foreground mb-1">
              Ask about this repository
            </h4>
            <p className="text-xs text-muted-foreground max-w-xs leading-relaxed mb-4">
              Ask questions about implementation, configuration, or architecture. Answers are grounded in indexed code with exact line citations.
            </p>
            <div className="space-y-1.5 w-full max-w-xs text-left">
              <span className="text-[10px] uppercase font-semibold tracking-wider text-muted-foreground/70">
                Suggested questions:
              </span>
              <button
                type="button"
                onClick={() => handleSend("Where is the projects section handled?")}
                className="w-full text-left px-2.5 py-1.5 rounded border border-border/60 bg-muted/20 hover:bg-muted/40 text-[11px] text-muted-foreground hover:text-foreground transition-colors truncate"
              >
                Where is the projects section handled?
              </button>
              <button
                type="button"
                onClick={() => handleSend("Where is PostgreSQL or database configured?")}
                className="w-full text-left px-2.5 py-1.5 rounded border border-border/60 bg-muted/20 hover:bg-muted/40 text-[11px] text-muted-foreground hover:text-foreground transition-colors truncate"
              >
                Where is PostgreSQL or database configured?
              </button>
            </div>
          </div>
        ) : (
          /* State 3: Active messages list */
          messages.map((message) => {
            const isUser = message.role === "user";

            if (isUser) {
              return (
                <div
                  key={message.id}
                  className="flex items-start justify-end gap-2"
                  data-testid="chat-user-message"
                >
                  <div className="max-w-[85%] rounded-lg border border-primary/30 bg-primary/10 px-3 py-2 text-xs text-foreground leading-relaxed shadow-xs">
                    {message.content}
                  </div>
                  <div className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/20 text-primary mt-0.5">
                    <User className="size-3.5" />
                  </div>
                </div>
              );
            }

            // Assistant message
            return (
              <div
                key={message.id}
                className="flex items-start gap-2"
                data-testid="chat-assistant-message"
              >
                <div className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted border border-border text-foreground mt-0.5">
                  <Bot className="size-3.5 text-primary" />
                </div>

                <div className="flex-1 space-y-2 max-w-[90%]">
                  {message.isGenerating ? (
                    /* Loading skeleton */
                    <div
                      className="rounded-lg border border-border/80 bg-card/60 p-3 space-y-2"
                      data-testid="chat-loading"
                    >
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <RefreshCw className="size-3 animate-spin text-primary" />
                        <span>Generating grounded answer...</span>
                      </div>
                      <Skeleton className="h-3.5 w-full" />
                      <Skeleton className="h-3.5 w-4/5" />
                      <Skeleton className="h-3.5 w-3/5" />
                    </div>
                  ) : message.isError ? (
                    /* Error card */
                    <div
                      className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 space-y-2 text-xs"
                      data-testid="chat-error"
                    >
                      <div className="flex items-center gap-1.5 text-destructive font-medium">
                        <AlertCircle className="size-3.5" />
                        <span>Generation failed</span>
                      </div>
                      <p className="text-muted-foreground">{message.content}</p>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleRetry}
                        className="h-6 text-[11px] gap-1 text-foreground"
                        data-testid="chat-retry-button"
                      >
                        <RefreshCw className="size-3" />
                        Try again
                      </Button>
                    </div>
                  ) : (
                    /* Normal assistant answer */
                    <div className="rounded-lg border border-border/80 bg-card p-3 space-y-3 shadow-xs">
                      <div className="text-xs text-foreground leading-relaxed whitespace-pre-wrap">
                        {message.content}
                      </div>

                      {/* Sources / Citations */}
                      {message.sources && message.sources.length > 0 && (
                        <div
                          className="pt-2 border-t border-border/60 space-y-1.5"
                          data-testid="chat-sources"
                        >
                          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                            Sources ({message.sources.length})
                          </div>

                          <div className="space-y-1.5">
                            {message.sources.map((source, sIdx) => {
                              const filePath = source.file_path || source.path;
                              return (
                                <div
                                  key={`${filePath}-${source.start_line}-${sIdx}`}
                                  className="group flex items-center justify-between gap-2 rounded border border-border/60 bg-muted/20 hover:border-primary/40 px-2 py-1.5 transition-colors"
                                  data-testid={`source-card-${sIdx}`}
                                  data-source-card
                                >
                                  <div className="min-w-0 flex-1 flex items-center gap-1.5 font-mono text-[11px]">
                                    <FileCode2 className="size-3 shrink-0 text-muted-foreground" />
                                    <span className="truncate text-foreground font-medium" title={filePath}>
                                      {filePath}
                                    </span>
                                    <span className="text-muted-foreground shrink-0">
                                      L{source.start_line}–{source.end_line}
                                    </span>
                                  </div>

                                  <button
                                    type="button"
                                    onClick={() => onSelectFile(filePath, source.start_line)}
                                    className="shrink-0 flex items-center gap-1 text-[10px] font-medium text-muted-foreground hover:text-primary transition-colors cursor-pointer"
                                    title={`Open ${filePath} at line ${source.start_line}`}
                                    data-testid={`open-source-button-${sIdx}`}
                                  >
                                    <span>Open</span>
                                    <ArrowRight className="size-3" />
                                  </button>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="p-3 border-t border-border bg-card/20 shrink-0">
        <form onSubmit={handleSubmit} className="space-y-2">
          <div className="relative rounded-lg border border-input bg-background/90 focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/40 transition-all">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={!isIndexed || isGenerating}
              placeholder={
                isIndexed
                  ? "Ask about this repository... (Enter to send, Shift+Enter for newline)"
                  : "Indexing required to chat"
              }
              rows={2}
              className="w-full resize-none bg-transparent px-3 py-2 text-xs text-foreground placeholder:text-muted-foreground/60 outline-none disabled:cursor-not-allowed disabled:opacity-50"
              data-testid="chat-input"
            />
            <div className="flex items-center justify-between px-2.5 pb-2">
              <span className="text-[10px] text-muted-foreground/70 hidden sm:inline">
                Shift + Enter for new line
              </span>
              <Button
                type="submit"
                size="sm"
                disabled={!isIndexed || isGenerating || !input.trim()}
                className="h-6 px-2 text-[11px] gap-1 ml-auto font-medium"
                data-testid="chat-send-button"
              >
                {isGenerating ? (
                  <>
                    <RefreshCw className="size-3 animate-spin" />
                    <span>Thinking...</span>
                  </>
                ) : (
                  <>
                    <Send className="size-3" />
                    <span>Ask</span>
                  </>
                )}
              </Button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
