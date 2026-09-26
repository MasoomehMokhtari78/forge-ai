"use client";

import React, { useState, useMemo, useCallback } from "react";
import Prism from "prismjs";
import "prismjs/components/prism-python";
import "prismjs/components/prism-javascript";
import "prismjs/components/prism-typescript";
import "prismjs/components/prism-jsx";
import "prismjs/components/prism-tsx";
import "prismjs/components/prism-json";
import "prismjs/components/prism-markdown";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-yaml";
import "prismjs/components/prism-css";
import "prismjs/components/prism-sql";
import "prismjs/components/prism-docker";
import "prismjs/components/prism-toml";
import "prismjs/components/prism-rust";
import "prismjs/components/prism-go";

import {
  Copy,
  Check,
  FileCode2,
  AlertCircle,
  RefreshCw,
  FileText,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatBytes } from "@/lib/file-tree";
import type { FileContentResponse } from "@/lib/api/types";

interface CodeViewerProps {
  filePath: string | null;
  fileData: FileContentResponse | null;
  isLoading: boolean;
  error: string | null;
  onRetry?: () => void;
}

interface LanguageInfo {
  prismKey: string;
  label: string;
}

function getLanguageInfo(filePath: string): LanguageInfo {
  const normalized = filePath.toLowerCase();
  const filename = normalized.split("/").pop() || "";
  const ext = filename.includes(".") ? filename.split(".").pop() || "" : "";

  // Exact file name matches
  if (filename === "dockerfile") return { prismKey: "docker", label: "Dockerfile" };
  if (filename === "makefile") return { prismKey: "bash", label: "Makefile" };
  if (filename.startsWith(".env")) return { prismKey: "bash", label: "Env" };
  if (filename === ".gitignore" || filename === ".dockerignore") return { prismKey: "bash", label: "Ignore" };

  switch (ext) {
    case "py":
    case "pyw":
      return { prismKey: "python", label: "Python" };
    case "ts":
    case "mts":
    case "cts":
      return { prismKey: "typescript", label: "TypeScript" };
    case "tsx":
      return { prismKey: "tsx", label: "TSX" };
    case "js":
    case "mjs":
    case "cjs":
      return { prismKey: "javascript", label: "JavaScript" };
    case "jsx":
      return { prismKey: "jsx", label: "JSX" };
    case "json":
      return { prismKey: "json", label: "JSON" };
    case "md":
    case "markdown":
      return { prismKey: "markdown", label: "Markdown" };
    case "sh":
    case "bash":
    case "zsh":
      return { prismKey: "bash", label: "Shell" };
    case "css":
    case "scss":
    case "less":
      return { prismKey: "css", label: "CSS" };
    case "yaml":
    case "yml":
      return { prismKey: "yaml", label: "YAML" };
    case "sql":
      return { prismKey: "sql", label: "SQL" };
    case "toml":
      return { prismKey: "toml", label: "TOML" };
    case "rs":
      return { prismKey: "rust", label: "Rust" };
    case "go":
      return { prismKey: "go", label: "Go" };
    case "html":
    case "htm":
      return { prismKey: "markup", label: "HTML" };
    default:
      return { prismKey: "text", label: ext ? ext.toUpperCase() : "Plain Text" };
  }
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

export function CodeViewer({
  filePath,
  fileData,
  isLoading,
  error,
  onRetry,
}: CodeViewerProps) {
  const [copied, setCopied] = useState(false);

  const langInfo = useMemo(() => {
    return filePath ? getLanguageInfo(filePath) : { prismKey: "text", label: "Text" };
  }, [filePath]);

  const rawContent = fileData?.content ?? "";

  const highlightedHtml = useMemo(() => {
    if (!rawContent) return "";
    try {
      const grammar = Prism.languages[langInfo.prismKey] || Prism.languages.text;
      if (grammar) {
        return Prism.highlight(rawContent, grammar, langInfo.prismKey);
      }
      return escapeHtml(rawContent);
    } catch {
      return escapeHtml(rawContent);
    }
  }, [rawContent, langInfo.prismKey]);

  const lineCount = useMemo(() => {
    if (!rawContent) return 0;
    return rawContent.split("\n").length;
  }, [rawContent]);

  const handleCopy = useCallback(async () => {
    if (!rawContent) return;
    try {
      await navigator.clipboard.writeText(rawContent);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore clipboard error
    }
  }, [rawContent]);

  // 1. Empty state: no file selected
  if (!filePath) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center p-8 text-center" data-testid="code-viewer-empty">
        <div className="flex size-12 items-center justify-center rounded-xl border border-border bg-muted/30 mb-3">
          <FileCode2 className="size-6 text-muted-foreground/60" />
        </div>
        <h3 className="text-sm font-medium text-foreground mb-1">
          No file selected
        </h3>
        <p className="text-xs text-muted-foreground max-w-xs leading-relaxed">
          Select a file from the repository tree to inspect its source code, line numbers, and metadata.
        </p>
      </div>
    );
  }

  // 2. Loading state: file selected, fetching content
  if (isLoading) {
    return (
      <div className="flex flex-1 flex-col h-full overflow-hidden" data-testid="code-viewer-loading">
        <div className="flex h-11 shrink-0 items-center justify-between border-b border-border px-4 bg-muted/10">
          <div className="flex items-center gap-2">
            <Skeleton className="h-4 w-4 rounded" />
            <Skeleton className="h-4 w-40" />
          </div>
          <div className="flex items-center gap-2">
            <Skeleton className="h-6 w-16 rounded" />
            <Skeleton className="h-6 w-20 rounded" />
          </div>
        </div>
        <div className="flex-1 p-4 space-y-3 overflow-hidden">
          {Array.from({ length: 16 }).map((_, i) => (
            <div key={i} className="flex gap-4 items-center">
              <Skeleton className="h-3 w-8 shrink-0" />
              <Skeleton
                className="h-3 rounded"
                style={{ width: `${Math.max(25, (i * 37) % 85 + 15)}%` }}
              />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // 3. Error state: file failed to load
  if (error || !fileData) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center p-8 text-center" data-testid="code-viewer-error">
        <div className="flex size-12 items-center justify-center rounded-xl border border-destructive/30 bg-destructive/10 text-destructive mb-3">
          <AlertCircle className="size-6" />
        </div>
        <h3 className="text-sm font-medium text-foreground mb-1">
          Unable to load file
        </h3>
        <p className="text-xs text-muted-foreground max-w-sm mb-4 leading-relaxed">
          {error || "An unexpected error occurred while reading the file content from the server."}
        </p>
        {onRetry && (
          <Button
            variant="outline"
            size="sm"
            onClick={onRetry}
            className="gap-2 text-xs"
            data-testid="code-viewer-retry-button"
          >
            <RefreshCw className="size-3.5" />
            Try again
          </Button>
        )}
      </div>
    );
  }

  // 4. Source code viewer with breadcrumbs, line numbers, and Prism syntax highlighting
  const pathParts = filePath.split("/").filter(Boolean);

  return (
    <div className="flex flex-1 flex-col h-full overflow-hidden bg-background" data-testid="code-viewer">
      {/* File Header Bar */}
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-border px-4 bg-card/40 backdrop-blur-xs select-none">
        {/* Breadcrumb path */}
        <div className="flex items-center gap-1.5 min-w-0 text-xs overflow-hidden">
          <FileText className="size-3.5 shrink-0 text-muted-foreground" />
          <div className="flex items-center gap-1 truncate font-mono">
            {pathParts.map((segment, index) => {
              const isLast = index === pathParts.length - 1;
              return (
                <React.Fragment key={index}>
                  {index > 0 && (
                    <span className="text-muted-foreground/40">/</span>
                  )}
                  <span
                    className={
                      isLast
                        ? "font-semibold text-foreground truncate"
                        : "text-muted-foreground truncate hover:text-foreground transition-colors"
                    }
                  >
                    {segment}
                  </span>
                </React.Fragment>
              );
            })}
          </div>
        </div>

        {/* Metadata Badges & Copy Action */}
        <div className="flex items-center gap-2 shrink-0 ml-3">
          <Badge variant="outline" className="text-[11px] font-mono px-2 py-0 h-6">
            {langInfo.label}
          </Badge>
          <Badge variant="secondary" className="text-[11px] font-mono px-2 py-0 h-6 tabular-nums">
            {lineCount} {lineCount === 1 ? "line" : "lines"}
          </Badge>
          <Badge variant="secondary" className="text-[11px] font-mono px-2 py-0 h-6 tabular-nums hidden sm:inline-flex">
            {formatBytes(fileData.size_bytes)}
          </Badge>

          <Button
            variant="ghost"
            size="sm"
            onClick={handleCopy}
            className="h-7 px-2 text-xs gap-1.5 text-muted-foreground hover:text-foreground"
            title="Copy file contents"
            data-testid="copy-code-button"
          >
            {copied ? (
              <>
                <Check className="size-3.5 text-status-success" />
                <span className="text-[11px] text-status-success font-medium">Copied</span>
              </>
            ) : (
              <>
                <Copy className="size-3.5" />
                <span className="text-[11px] hidden sm:inline">Copy</span>
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Code body with independent scrolling */}
      <div className="flex-1 overflow-auto bg-background" data-testid="code-container">
        <div className="flex min-w-full font-mono text-[13px] leading-6">
          {/* Gutter: Line numbers */}
          <div
            className="sticky left-0 z-10 shrink-0 select-none py-3 pl-3 pr-3 text-right font-mono text-xs text-muted-foreground/40 border-r border-border/50 bg-background/95 backdrop-blur-xs"
            aria-hidden="true"
            data-testid="line-numbers-gutter"
          >
            {Array.from({ length: lineCount }, (_, i) => (
              <div key={i} className="h-6 leading-6 tabular-nums">
                {i + 1}
              </div>
            ))}
          </div>

          {/* Source Code Content */}
          <div className="flex-1 min-w-0 py-3 pl-4 pr-6 overflow-x-auto">
            <pre className="font-mono text-[13px] leading-6 tab-size-2 m-0 p-0 bg-transparent overflow-visible">
              <code
                className={`language-${langInfo.prismKey}`}
                dangerouslySetInnerHTML={{ __html: highlightedHtml }}
              />
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
}
