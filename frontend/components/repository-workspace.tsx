"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import {
  ArrowLeft,
  FolderGit2,
  ChevronRight,
  Clock,
  Hash,
  FileCode2,
  Layers,
  Files,
  X,
  Sparkles,
} from "lucide-react";
import { RepositoryStatusBadge } from "@/components/repository-status-badge";
import { FileTree } from "@/components/file-tree";
import { CodeViewer } from "@/components/code-viewer";
import { repositoriesApi } from "@/lib/api/repositories";
import { ApiClientError } from "@/lib/api/client";
import type {
  Repository,
  IndexSummary,
  FileMetadata,
  FileContentResponse,
} from "@/lib/api/types";

interface RepositoryWorkspaceProps {
  repository: Repository;
  initialFiles: FileMetadata[];
  initialSelectedFile?: string | null;
  indexSummary: IndexSummary | null;
}

function formatDate(isoString: string | null): string {
  if (!isoString) return "—";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(isoString));
}

function formatRepoHost(url: string): string {
  try {
    const u = new URL(url);
    return u.hostname + u.pathname;
  } catch {
    return url;
  }
}

interface MetaItemProps {
  icon: React.ElementType;
  label: string;
  value: React.ReactNode;
}

function MetaItem({ icon: Icon, label, value }: MetaItemProps) {
  return (
    <div className="flex items-start gap-3 py-3">
      <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <p className="text-xs text-muted-foreground">{label}</p>
        <div className="mt-0.5 text-sm text-foreground">{value}</div>
      </div>
    </div>
  );
}

export function RepositoryWorkspace({
  repository,
  initialFiles,
  initialSelectedFile = null,
  indexSummary,
}: RepositoryWorkspaceProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Directly derive active file path from URL query param ?file=...
  const selectedFilePath = searchParams.get("file") || initialSelectedFile || null;

  const [fileContent, setFileContent] = useState<FileContentResponse | null>(null);
  const [isLoadingContent, setIsLoadingContent] = useState<boolean>(false);
  const [contentError, setContentError] = useState<string | null>(null);

  // In-memory cache of loaded file contents
  const fileCacheRef = useRef<Map<string, FileContentResponse>>(new Map());

  const [owner, repoName] = repository.name.split("/");
  const host = formatRepoHost(repository.url);

  // Fetch file content when selectedFilePath changes
  useEffect(() => {
    if (!selectedFilePath) {
      return;
    }

    let ignore = false;
    const cached = fileCacheRef.current.get(selectedFilePath);
    if (cached) {
      setFileContent(cached);
      setContentError(null);
      setIsLoadingContent(false);
      return;
    }

    setIsLoadingContent(true);
    setContentError(null);

    repositoriesApi
      .getFileContent(repository.id, selectedFilePath)
      .then((data) => {
        if (ignore) return;
        fileCacheRef.current.set(selectedFilePath, data);
        setFileContent(data);
        setIsLoadingContent(false);
      })
      .catch((err) => {
        if (ignore) return;
        const message =
          err instanceof ApiClientError && err.status === 404
            ? `File "${selectedFilePath}" not found in this repository.`
            : err?.detail || "An error occurred while loading file content.";
        setContentError(message);
        setFileContent(null);
        setIsLoadingContent(false);
      });

    return () => {
      ignore = true;
    };
  }, [selectedFilePath, repository.id]);

  const handleSelectFile = useCallback(
    (path: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("file", path);
      router.push(`${pathname}?${params.toString()}`);
    },
    [router, pathname, searchParams]
  );

  const handleCloseFile = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("file");
    router.push(`${pathname}?${params.toString()}`);
  }, [router, pathname, searchParams]);

  const handleRetry = useCallback(() => {
    if (!selectedFilePath) return;
    fileCacheRef.current.delete(selectedFilePath);
    setIsLoadingContent(true);
    setContentError(null);

    repositoriesApi
      .getFileContent(repository.id, selectedFilePath)
      .then((data) => {
        fileCacheRef.current.set(selectedFilePath, data);
        setFileContent(data);
        setIsLoadingContent(false);
      })
      .catch((err) => {
        const message =
          err instanceof ApiClientError && err.status === 404
            ? `File "${selectedFilePath}" not found in this repository.`
            : err?.detail || "An error occurred while loading file content.";
        setContentError(message);
        setFileContent(null);
        setIsLoadingContent(false);
      });
  }, [selectedFilePath, repository.id]);

  // If selectedFilePath was cleared, do not show stale fileContent
  const activeFileContent = selectedFilePath ? fileContent : null;

  return (
    <div className="flex flex-col h-full overflow-hidden" data-testid="repository-workspace">
      {/* Workspace Topbar */}
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border px-4 bg-card/20 backdrop-blur-xs z-10">
        <Link
          href="/repositories"
          className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          Repositories
        </Link>
        <ChevronRight className="size-3.5 text-muted-foreground/50" />
        <div className="flex items-center gap-2 min-w-0">
          <FolderGit2 className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="text-xs text-muted-foreground truncate">{owner}/</span>
          <span className="text-xs font-medium text-foreground truncate">{repoName}</span>
        </div>

        {selectedFilePath && (
          <>
            <ChevronRight className="size-3.5 text-muted-foreground/50 shrink-0" />
            <div className="flex items-center gap-1.5 min-w-0 overflow-hidden">
              <span className="font-mono text-xs text-foreground/90 truncate">
                {selectedFilePath}
              </span>
              <button
                type="button"
                onClick={handleCloseFile}
                className="p-0.5 rounded text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                title="Close file and view repository overview"
                data-testid="close-file-button"
              >
                <X className="size-3" />
              </button>
            </div>
          </>
        )}

        <div className="ml-auto shrink-0">
          <RepositoryStatusBadge status={repository.status} />
        </div>
      </div>

      {/* Three-panel workspace layout */}
      <div className="flex flex-1 overflow-hidden">
        {/* ── Left panel: Real File Explorer ── */}
        <aside
          className="w-64 shrink-0 flex flex-col border-r border-border bg-sidebar"
          data-testid="workspace-file-sidebar"
        >
          <FileTree
            files={initialFiles}
            selectedFilePath={selectedFilePath}
            onSelectFile={handleSelectFile}
          />
        </aside>

        {/* ── Center panel: Code Viewer or Repository Overview ── */}
        <div className="flex flex-1 flex-col overflow-hidden bg-background">
          {selectedFilePath ? (
            <CodeViewer
              filePath={selectedFilePath}
              fileData={activeFileContent}
              isLoading={isLoadingContent}
              error={contentError}
              onRetry={handleRetry}
            />
          ) : (
            <div className="flex flex-1 flex-col overflow-auto" data-testid="workspace-overview">
              <div className="mx-auto w-full max-w-2xl px-8 py-8">
                {/* Repository header */}
                <div className="mb-8">
                  <div className="flex items-center gap-3 mb-1">
                    <div className="flex size-9 items-center justify-center rounded-lg border border-border bg-muted/40">
                      <FolderGit2 className="size-4 text-muted-foreground" />
                    </div>
                    <div>
                      <h1 className="text-base font-semibold text-foreground">
                        {repoName}
                      </h1>
                      <p className="text-xs text-muted-foreground">{owner}</p>
                    </div>
                  </div>
                  <a
                    href={repository.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-2 inline-flex text-xs text-primary hover:underline"
                  >
                    {host}
                  </a>
                </div>

                {/* Repository metadata */}
                <div className="rounded-lg border border-border bg-card">
                  <div className="px-4 py-3 border-b border-border">
                    <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                      Details
                    </span>
                  </div>
                  <div className="divide-y divide-border px-4">
                    <MetaItem
                      icon={Hash}
                      label="Repository ID"
                      value={
                        <span className="font-mono text-xs break-all text-muted-foreground">
                          {repository.id}
                        </span>
                      }
                    />
                    <MetaItem
                      icon={Clock}
                      label="Added"
                      value={formatDate(repository.created_at)}
                    />
                    {repository.ingested_at && (
                      <MetaItem
                        icon={Clock}
                        label="Indexed at"
                        value={formatDate(repository.ingested_at)}
                      />
                    )}
                    {repository.status === "failed" && repository.error_message && (
                      <MetaItem
                        icon={Files}
                        label="Error"
                        value={
                          <span className="text-destructive text-xs">
                            {repository.error_message}
                          </span>
                        }
                      />
                    )}
                  </div>
                </div>

                {/* Index Stats */}
                {indexSummary && (
                  <div className="mt-4 rounded-lg border border-border bg-card">
                    <div className="px-4 py-3 border-b border-border">
                      <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                        Index
                      </span>
                    </div>
                    <div className="grid grid-cols-2 divide-x divide-border">
                      <div className="flex flex-col items-center gap-1 p-5">
                        <div className="flex items-center gap-1.5 text-muted-foreground">
                          <FileCode2 className="size-4" />
                          <span className="text-xs">Files</span>
                        </div>
                        <span className="text-2xl font-semibold tabular-nums text-foreground">
                          {indexSummary.files_indexed.toLocaleString("en-US")}
                        </span>
                      </div>
                      <div className="flex flex-col items-center gap-1 p-5">
                        <div className="flex items-center gap-1.5 text-muted-foreground">
                          <Layers className="size-4" />
                          <span className="text-xs">Chunks</span>
                        </div>
                        <span className="text-2xl font-semibold tabular-nums text-foreground">
                          {indexSummary.chunks_created.toLocaleString("en-US")}
                        </span>
                      </div>
                    </div>
                  </div>
                )}

                {/* Explorer Callout */}
                <div className="mt-6 rounded-lg border border-dashed border-border/80 bg-muted/10 p-5 text-center">
                  <FileCode2 className="size-5 mx-auto text-muted-foreground/60 mb-2" />
                  <p className="text-xs font-medium text-foreground mb-0.5">
                    Explore Codebase Files
                  </p>
                  <p className="text-xs text-muted-foreground max-w-sm mx-auto">
                    Select any file in the sidebar to inspect syntax-highlighted source code, copy lines, and view metadata.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ── Right panel: AI Assistant placeholder ── */}
        <aside className="hidden w-72 shrink-0 flex-col border-l border-border xl:flex">
          <div className="flex h-11 items-center gap-2 border-b border-border px-4 bg-muted/10">
            <span className="size-1.5 rounded-full bg-primary" />
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              AI Assistant
            </span>
          </div>
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
            <div className="flex size-10 items-center justify-center rounded-xl border border-border bg-muted/40 text-primary">
              <Sparkles className="size-5" />
            </div>
            <div className="space-y-1">
              <p className="text-xs font-medium text-foreground">
                Coming next
              </p>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Chat with your codebase using RAG and the ForgeAI agent.
              </p>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
