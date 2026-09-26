"use client";

import React, { useState, useCallback, useRef, useEffect } from "react";
import {
  Search,
  Sparkles,
  AlertCircle,
  RefreshCw,
  FileCode2,
  X,
  Layers,
  ArrowRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { repositoriesApi } from "@/lib/api/repositories";
import { ApiClientError } from "@/lib/api/client";
import type {
  ChunkRetrievalResult,
  IngestionStatus,
} from "@/lib/api/types";

interface SemanticSearchProps {
  repositoryId: string;
  repositoryStatus: IngestionStatus;
  onSelectFile: (path: string, line?: number) => void;
  className?: string;
}

export function SemanticSearch({
  repositoryId,
  repositoryStatus,
  onSelectFile,
  className = "",
}: SemanticSearchProps) {
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [results, setResults] = useState<ChunkRetrievalResult[] | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);

  const isIndexed = repositoryStatus === "completed";

  // Global shortcut: Cmd+K / Ctrl+K focuses the search input
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        const el = document.querySelector<HTMLInputElement>(
          '[data-testid="semantic-search-input"]'
        );
        el?.focus();
        el?.select();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const handleSearch = useCallback(
    async (searchQuery: string) => {
      const trimmed = searchQuery.trim();
      if (!trimmed) {
        setValidationError("Please enter a search query.");
        return;
      }

      setValidationError(null);
      setError(null);
      setIsLoading(true);
      setSubmittedQuery(trimmed);

      try {
        const response = await repositoriesApi.search(repositoryId, {
          query: trimmed,
          top_k: 8,
        });
        setResults(response.results);
      } catch (err) {
        const message =
          err instanceof ApiClientError
            ? err.detail || `Search failed with status ${err.status}`
            : "An unexpected error occurred during search. Please try again.";
        setError(message);
        setResults(null);
      } finally {
        setIsLoading(false);
      }
    },
    [repositoryId]
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!isIndexed || isLoading) return;
    handleSearch(query);
  };

  const handleClear = () => {
    setQuery("");
    setValidationError(null);
    const el = document.querySelector<HTMLInputElement>(
      '[data-testid="semantic-search-input"]'
    );
    el?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSearch(query);
    } else if (e.key === "Escape") {
      if (validationError) {
        setValidationError(null);
      } else if (query) {
        handleClear();
      }
    }
  };

  return (
    <div
      className={`flex flex-col h-full overflow-hidden bg-sidebar/40 ${className}`}
      data-testid="semantic-search-panel"
    >
      {/* Search Header */}
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-border px-4 bg-muted/10">
        <div className="flex items-center gap-2 min-w-0">
          <Sparkles className="size-4 shrink-0 text-primary" />
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground truncate">
            Semantic Search
          </span>
        </div>
        <Badge
          variant="outline"
          className="text-[10px] font-mono px-1.5 py-0 h-5 text-muted-foreground border-border/80"
        >
          pgvector
        </Badge>
      </div>

      {/* Query Form */}
      <div className="p-3 border-b border-border bg-card/20 space-y-2 shrink-0">
        <form onSubmit={handleSubmit} className="space-y-2">
          <div className="relative flex items-center">
            <Search className="absolute left-2.5 size-3.5 text-muted-foreground pointer-events-none" />
            <Input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                if (validationError) setValidationError(null);
              }}
              onKeyDown={handleKeyDown}
              placeholder={
                isIndexed
                  ? "Ask code question (e.g. auth handling)..."
                  : "Indexing required to search"
              }
              disabled={!isIndexed || isLoading}
              className="h-8 pl-8 pr-16 text-xs bg-background/80 placeholder:text-muted-foreground/60"
              data-testid="semantic-search-input"
            />
            <div className="absolute right-1.5 flex items-center gap-1">
              {query && (
                <button
                  type="button"
                  onClick={handleClear}
                  className="p-1 rounded text-muted-foreground hover:text-foreground transition-colors"
                  title="Clear input (Esc)"
                  data-testid="semantic-search-clear"
                >
                  <X className="size-3" />
                </button>
              )}
              <kbd className="hidden sm:inline-flex select-none items-center rounded border border-border/80 bg-muted/40 px-1 font-mono text-[9px] text-muted-foreground">
                ↵
              </kbd>
            </div>
          </div>

          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] text-muted-foreground">
              Natural language code retrieval
            </span>
            <Button
              type="submit"
              size="sm"
              disabled={!isIndexed || isLoading}
              className="h-7 px-3 text-xs gap-1.5 font-medium"
              data-testid="semantic-search-button"
            >
              {isLoading ? (
                <>
                  <RefreshCw className="size-3 animate-spin" />
                  <span>Searching...</span>
                </>
              ) : (
                <>
                  <Search className="size-3" />
                  <span>Search</span>
                </>
              )}
            </Button>
          </div>
        </form>

        {validationError && (
          <p
            className="text-[11px] text-destructive flex items-center gap-1 mt-1"
            data-testid="search-validation-error"
          >
            <AlertCircle className="size-3 shrink-0" />
            {validationError}
          </p>
        )}
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {/* State 1: Repository not indexed */}
        {!isIndexed ? (
          <div
            className="flex flex-col items-center justify-center p-6 text-center h-full"
            data-testid="search-not-indexed"
          >
            <div className="flex size-10 items-center justify-center rounded-xl border border-border bg-muted/30 mb-3 text-muted-foreground">
              <Layers className="size-5" />
            </div>
            <h4 className="text-xs font-semibold text-foreground mb-1">
              Indexing required
            </h4>
            <p className="text-xs text-muted-foreground max-w-xs leading-relaxed">
              This repository has not been indexed yet. Complete indexing to enable pgvector semantic retrieval.
            </p>
          </div>
        ) : isLoading ? (
          /* State 2: Loading skeletons */
          <div className="p-3 space-y-3" data-testid="search-loading">
            <div className="flex items-center justify-between">
              <Skeleton className="h-3 w-28" />
              <Skeleton className="h-3 w-12" />
            </div>
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="rounded-lg border border-border/80 bg-card/40 p-3 space-y-2.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <Skeleton className="h-3.5 w-3/5" />
                  <Skeleton className="h-4 w-12 rounded" />
                </div>
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-16 w-full rounded" />
              </div>
            ))}
          </div>
        ) : error ? (
          /* State 3: Error state with retry */
          <div
            className="flex flex-col items-center justify-center p-6 text-center h-full"
            data-testid="search-error"
          >
            <div className="flex size-10 items-center justify-center rounded-xl border border-destructive/30 bg-destructive/10 text-destructive mb-3">
              <AlertCircle className="size-5" />
            </div>
            <h4 className="text-xs font-semibold text-foreground mb-1">
              Search failed
            </h4>
            <p className="text-xs text-muted-foreground max-w-xs mb-4 leading-relaxed">
              {error}
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleSearch(submittedQuery || query)}
              className="gap-1.5 text-xs h-7"
              data-testid="search-retry-button"
            >
              <RefreshCw className="size-3" />
              Try again
            </Button>
          </div>
        ) : results !== null && results.length === 0 ? (
          /* State 4: No results found */
          <div
            className="flex flex-col items-center justify-center p-6 text-center h-full"
            data-testid="search-no-results"
          >
            <div className="flex size-10 items-center justify-center rounded-xl border border-border bg-muted/30 mb-3 text-muted-foreground/60">
              <Search className="size-5" />
            </div>
            <h4 className="text-xs font-semibold text-foreground mb-1">
              No results found
            </h4>
            <p className="text-xs text-muted-foreground max-w-xs leading-relaxed">
              No relevant code found in this repository. Try phrasing your query differently.
            </p>
          </div>
        ) : results !== null && results.length > 0 ? (
          /* State 5: Search results list */
          <div className="p-3 space-y-3" data-testid="semantic-search-results">
            <div className="flex items-center justify-between text-xs text-muted-foreground px-0.5">
              <span>
                {results.length} relevant {results.length === 1 ? "chunk" : "chunks"}
              </span>
              <span className="text-[11px] font-mono text-muted-foreground/70">
                Ranked by similarity
              </span>
            </div>

            <div className="space-y-2.5">
              {results.map((result, idx) => {
                const scorePercent = Math.round(result.similarity * 100);

                return (
                  <div
                    key={result.chunk_id || idx}
                    className="group rounded-lg border border-border/70 bg-card hover:border-primary/50 transition-all p-3 space-y-2 shadow-xs"
                    data-testid={`search-result-item-${idx}`}
                    data-search-result-item
                  >
                    {/* Header: File path & Similarity score */}
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div
                          className="flex items-center gap-1.5 font-mono text-xs font-medium text-foreground truncate cursor-pointer hover:text-primary transition-colors"
                          onClick={() => onSelectFile(result.path, result.start_line)}
                          title={result.path}
                        >
                          <FileCode2 className="size-3.5 shrink-0 text-muted-foreground" />
                          <span className="truncate">{result.path}</span>
                        </div>
                        <div className="text-[11px] text-muted-foreground mt-0.5">
                          Lines {result.start_line}–{result.end_line}
                        </div>
                      </div>

                      <Badge
                        variant="secondary"
                        className="shrink-0 text-[10px] font-mono px-1.5 py-0 h-5 tabular-nums bg-primary/10 text-primary border-primary/20"
                        title={`Cosine similarity: ${result.similarity.toFixed(4)}`}
                      >
                        {scorePercent}% match
                      </Badge>
                    </div>

                    {/* Code Snippet */}
                    <div className="rounded border border-border/50 bg-background/80 p-2 font-mono text-[11px] leading-relaxed overflow-x-auto text-foreground/90 max-h-36">
                      <pre className="whitespace-pre overflow-x-auto m-0 p-0 font-mono">
                        <code>{result.content}</code>
                      </pre>
                    </div>

                    {/* Action button */}
                    <div className="flex items-center justify-end pt-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onSelectFile(result.path, result.start_line)}
                        className="h-6 px-2 text-[11px] gap-1 text-muted-foreground hover:text-foreground group-hover:text-primary transition-colors"
                        data-testid={`open-result-button-${idx}`}
                      >
                        <span>Open in viewer</span>
                        <ArrowRight className="size-3" />
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          /* State 0: Initial prompt / instructions */
          <div className="flex flex-1 flex-col items-center justify-center p-6 text-center h-full">
            <div className="flex size-10 items-center justify-center rounded-xl border border-border bg-muted/30 mb-3 text-primary">
              <Sparkles className="size-5" />
            </div>
            <h4 className="text-xs font-semibold text-foreground mb-1">
              Ask about this codebase
            </h4>
            <p className="text-xs text-muted-foreground max-w-xs leading-relaxed mb-4">
              Enter a question or description to semantically retrieve relevant code chunks with line citations.
            </p>
            <div className="space-y-1.5 w-full max-w-xs text-left">
              <span className="text-[10px] uppercase font-semibold tracking-wider text-muted-foreground/70">
                Try searching for:
              </span>
              <button
                type="button"
                onClick={() => {
                  setQuery("Where is authentication handled?");
                  inputRef.current?.focus();
                }}
                className="w-full text-left px-2.5 py-1.5 rounded border border-border/60 bg-muted/20 hover:bg-muted/40 text-[11px] text-muted-foreground hover:text-foreground transition-colors truncate"
              >
                Where is authentication handled?
              </button>
              <button
                type="button"
                onClick={() => {
                  setQuery("Configuration and environment settings");
                  inputRef.current?.focus();
                }}
                className="w-full text-left px-2.5 py-1.5 rounded border border-border/60 bg-muted/20 hover:bg-muted/40 text-[11px] text-muted-foreground hover:text-foreground transition-colors truncate"
              >
                Configuration and environment settings
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
