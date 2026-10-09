"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  BookOpen,
  Plus,
  Upload,
  Trash2,
  FileText,
  Loader2,
  RefreshCw,
  Layers,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { AddKnowledgeDialog } from "@/components/add-knowledge-dialog";
import { KnowledgeStatusBadge } from "@/components/knowledge-status-badge";
import { knowledgeApi } from "@/lib/api/knowledge";
import { ApiClientError } from "@/lib/api/client";
import { useToast } from "@/components/ui/toast";
import type { EngineeringKnowledge } from "@/lib/api/types";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function formatDate(isoString: string): string {
  try {
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    }).format(new Date(isoString));
  } catch {
    return isoString;
  }
}

interface KnowledgeManagerProps {
  initialScopes?: EngineeringKnowledge[];
}

export function KnowledgeManager({ initialScopes }: KnowledgeManagerProps) {
  const toast = useToast();
  const [scopes, setScopes] = useState<EngineeringKnowledge[]>(initialScopes ?? []);
  const [isLoading, setIsLoading] = useState<boolean>(!initialScopes);
  const [isCreateOpen, setIsCreateOpen] = useState<boolean>(false);
  const [uploadingScopeId, setUploadingScopeId] = useState<string | null>(null);
  const [deletingScopeId, setDeletingScopeId] = useState<string | null>(null);
  const [deletingDocId, setDeletingDocId] = useState<string | null>(null);
  const [collapsedScopes, setCollapsedScopes] = useState<Record<string, boolean>>({});

  const fileInputRefs = useRef<Record<string, HTMLInputElement | null>>({});

  const fetchScopes = async () => {
    try {
      const data = await knowledgeApi.list();
      setScopes(data);
    } catch (err) {
      const msg =
        err instanceof ApiClientError
          ? err.detail ?? err.message
          : err instanceof Error
          ? err.message
          : "Failed to load engineering knowledge scopes.";
      toast.error(msg, "Error Loading Scopes");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (initialScopes) return;
    let ignore = false;
    knowledgeApi
      .list()
      .then((data) => {
        if (!ignore) {
          setScopes(data);
          setIsLoading(false);
        }
      })
      .catch((err) => {
        if (!ignore) {
          const msg =
            err instanceof ApiClientError
              ? err.detail ?? err.message
              : err instanceof Error
              ? err.message
              : "Failed to load engineering knowledge scopes.";
          toast.error(msg, "Error Loading Scopes");
          setIsLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [initialScopes, toast]);

  const handleToggleExpand = (id: string) => {
    setCollapsedScopes((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  const handleKnowledgeCreated = (created: EngineeringKnowledge) => {
    setScopes((prev) => [created, ...prev]);
    toast.success(`Scope "${created.name}" created successfully.`, "Scope Created");
  };

  const handleDeleteScope = async (scopeId: string) => {
    if (!window.confirm("Are you sure you want to delete this engineering knowledge scope? All uploaded documents will be deleted.")) {
      return;
    }
    setDeletingScopeId(scopeId);
    try {
      await knowledgeApi.delete(scopeId);
      setScopes((prev) => prev.filter((s) => s.id !== scopeId));
      toast.success("Engineering knowledge scope deleted.", "Scope Deleted");
    } catch (err) {
      const msg =
        err instanceof ApiClientError
          ? err.detail ?? err.message
          : err instanceof Error
          ? err.message
          : "Failed to delete knowledge scope.";
      toast.error(msg, "Deletion Failed");
    } finally {
      setDeletingScopeId(null);
    }
  };

  const handleTriggerUpload = (scopeId: string) => {
    fileInputRefs.current[scopeId]?.click();
  };

  const MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024; // 500 MB

  const handleFileChange = async (scopeId: string, e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith(".pdf")) {
      const msg = "Only PDF documents (.pdf) can be uploaded.";
      toast.error(msg, "Invalid File");
      e.target.value = "";
      return;
    }

    if (file.size > MAX_FILE_SIZE_BYTES) {
      const msg = `File "${file.name}" exceeds the maximum allowed size of 500 MB.`;
      toast.error(msg, "File Too Large");
      e.target.value = "";
      return;
    }

    setUploadingScopeId(scopeId);

    try {
      const doc = await knowledgeApi.uploadDocument(scopeId, file);
      // Refresh scope or update locally
      setScopes((prev) =>
        prev.map((s) => {
          if (s.id !== scopeId) return s;
          const docs = s.documents ? [...s.documents, doc] : [doc];
          return {
            ...s,
            status: "completed",
            documents: docs,
          };
        })
      );
      toast.success(`"${file.name}" uploaded and indexed successfully.`, "Upload Complete");
      // Re-fetch to get up-to-date chunk counts and statuses
      await fetchScopes();
    } catch (err) {
      const msg =
        err instanceof ApiClientError
          ? err.detail ?? err.message
          : err instanceof Error
          ? err.message
          : "Failed to upload document.";
      toast.error(msg, "Upload Failed");
    } finally {
      setUploadingScopeId(null);
      if (fileInputRefs.current[scopeId]) {
        fileInputRefs.current[scopeId]!.value = "";
      }
    }
  };

  const handleDeleteDocument = async (scopeId: string, documentId: string) => {
    if (!window.confirm("Are you sure you want to delete this document?")) {
      return;
    }
    setDeletingDocId(documentId);
    try {
      await knowledgeApi.deleteDocument(scopeId, documentId);
      setScopes((prev) =>
        prev.map((s) => {
          if (s.id !== scopeId) return s;
          return {
            ...s,
            documents: s.documents.filter((d) => d.id !== documentId),
          };
        })
      );
      toast.success("Document deleted.", "Document Removed");
    } catch (err) {
      const msg =
        err instanceof ApiClientError
          ? err.detail ?? err.message
          : err instanceof Error
          ? err.message
          : "Failed to delete document.";
      toast.error(msg, "Deletion Failed");
    } finally {
      setDeletingDocId(null);
    }
  };

  return (
    <div className="flex flex-col flex-1 p-6 max-w-5xl mx-auto w-full space-y-6" data-testid="knowledge-manager">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-border">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-foreground flex items-center gap-2">
            <BookOpen className="size-5 text-primary" />
            Engineering Knowledge
          </h1>
          <p className="text-xs text-muted-foreground mt-1">
            Manage user-defined engineering knowledge scopes and reference PDFs (up to 500 MB) for knowledge-guided code analysis.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={fetchScopes}
            disabled={isLoading}
            className="h-8 gap-1.5 text-xs"
            title="Refresh knowledge scopes"
            data-testid="refresh-knowledge-button"
          >
            <RefreshCw className={`size-3.5 ${isLoading ? "animate-spin" : ""}`} />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={() => setIsCreateOpen(true)}
            className="h-8 gap-1.5 text-xs font-medium"
            data-testid="open-create-knowledge-button"
          >
            <Plus className="size-3.5" />
            <span>Create Knowledge</span>
          </Button>
        </div>
      </div>

      {/* Loading State */}
      {isLoading ? (
        <div className="flex flex-col items-center justify-center py-20 text-center gap-3">
          <Loader2 className="size-6 animate-spin text-primary" />
          <p className="text-xs text-muted-foreground">Loading engineering knowledge scopes...</p>
        </div>
      ) : scopes.length === 0 ? (
        /* Empty State */
        <div
          className="flex flex-col items-center justify-center gap-4 py-20 text-center rounded-xl border border-dashed border-border bg-card/40 p-8"
          data-testid="knowledge-empty-state"
        >
          <div className="flex size-12 items-center justify-center rounded-xl border border-border bg-muted/40">
            <BookOpen className="size-6 text-muted-foreground" />
          </div>
          <div className="space-y-1">
            <h2 className="text-sm font-medium text-foreground">No engineering knowledge scopes yet</h2>
            <p className="max-w-sm text-xs text-muted-foreground leading-relaxed">
              Create a knowledge scope such as &ldquo;Design Patterns&rdquo; or &ldquo;SOLID Principles&rdquo; and upload reference PDFs to enable knowledge-guided analysis.
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            onClick={() => setIsCreateOpen(true)}
            className="gap-1.5 text-xs font-medium"
            data-testid="empty-create-knowledge-button"
          >
            <Plus className="size-3.5" />
            <span>Create Knowledge Scope</span>
          </Button>
        </div>
      ) : (
        /* Scopes List */
        <div className="space-y-4" data-testid="knowledge-scopes-list">
          {scopes.map((scope) => {
            const isExpanded = !collapsedScopes[scope.id];
            const isUploading = uploadingScopeId === scope.id;
            const isDeletingScope = deletingScopeId === scope.id;
            const docs = scope.documents || [];

            return (
              <div
                key={scope.id}
                className="rounded-lg border border-border bg-card overflow-hidden shadow-xs"
                data-testid={`knowledge-scope-card-${scope.id}`}
              >
                {/* Scope Header */}
                <div className="flex items-start justify-between gap-3 p-4 bg-muted/20 border-b border-border/80">
                  <div
                    className="flex items-start gap-2.5 min-w-0 cursor-pointer select-none flex-1"
                    onClick={() => handleToggleExpand(scope.id)}
                  >
                    <button
                      type="button"
                      className="mt-0.5 text-muted-foreground hover:text-foreground transition-colors p-0.5"
                    >
                      {isExpanded ? (
                        <ChevronDown className="size-4" />
                      ) : (
                        <ChevronRight className="size-4" />
                      )}
                    </button>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h2 className="text-sm font-semibold text-foreground tracking-tight" data-testid="scope-name">
                          {scope.name}
                        </h2>
                        <KnowledgeStatusBadge status={scope.status} />
                        <span className="text-[11px] text-muted-foreground">
                          {formatDate(scope.created_at)}
                        </span>
                      </div>
                      {scope.description && (
                        <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                          {scope.description}
                        </p>
                      )}
                      {scope.error_message && (
                        <p className="text-xs text-destructive mt-1 font-mono">
                          Error: {scope.error_message}
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Scope Actions */}
                  <div className="flex items-center gap-1.5 shrink-0">
                    {/* Hidden file input */}
                    <input
                      type="file"
                      ref={(el) => {
                        fileInputRefs.current[scope.id] = el;
                      }}
                      accept=".pdf"
                      onChange={(e) => handleFileChange(scope.id, e)}
                      className="hidden"
                      data-testid={`upload-input-${scope.id}`}
                    />

                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => handleTriggerUpload(scope.id)}
                      disabled={isUploading || isDeletingScope}
                      className="h-7 px-2.5 text-xs gap-1.5 font-medium"
                      data-testid={`upload-pdf-button-${scope.id}`}
                    >
                      {isUploading ? (
                        <>
                          <Loader2 className="size-3 animate-spin" />
                          <span>Uploading...</span>
                        </>
                      ) : (
                        <>
                          <Upload className="size-3" />
                          <span>Upload PDF</span>
                        </>
                      )}
                    </Button>

                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => handleDeleteScope(scope.id)}
                      disabled={isDeletingScope || isUploading}
                      className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                      title="Delete knowledge scope"
                      data-testid={`delete-scope-button-${scope.id}`}
                    >
                      {isDeletingScope ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : (
                        <Trash2 className="size-3.5" />
                      )}
                    </Button>
                  </div>
                </div>

                {/* Collapsible Documents Section */}
                {isExpanded && (
                  <div className="p-4 space-y-2.5 bg-card/60">
                    <div className="flex items-center justify-between text-xs text-muted-foreground font-medium uppercase tracking-wider px-1">
                      <span>Documents ({docs.length})</span>
                    </div>

                    {docs.length === 0 ? (
                      <div className="rounded-md border border-dashed border-border/70 p-4 text-center text-xs text-muted-foreground bg-muted/10">
                        No PDF documents uploaded yet. Upload a PDF reference to index knowledge chunks.
                      </div>
                    ) : (
                      <div className="divide-y divide-border/60 rounded-md border border-border/80 bg-background/50">
                        {docs.map((doc) => {
                          const isDeletingThisDoc = deletingDocId === doc.id;
                          return (
                            <div
                              key={doc.id}
                              className="flex items-center justify-between gap-3 p-3 text-xs transition-colors hover:bg-muted/20"
                              data-testid={`document-row-${doc.id}`}
                            >
                              <div className="flex items-center gap-2.5 min-w-0 flex-1">
                                <FileText className="size-4 shrink-0 text-primary/80" />
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center gap-2">
                                    <span className="font-medium text-foreground truncate" title={doc.filename} data-testid="doc-filename">
                                      {doc.filename}
                                    </span>
                                    <KnowledgeStatusBadge status={doc.status} />
                                  </div>
                                  <div className="flex items-center gap-3 text-[11px] text-muted-foreground mt-0.5">
                                    <span>{formatBytes(doc.file_size_bytes)}</span>
                                    {doc.chunks_count > 0 && (
                                      <span className="flex items-center gap-1">
                                        <Layers className="size-3" />
                                        {doc.chunks_count} chunks
                                      </span>
                                    )}
                                    <span>{formatDate(doc.created_at)}</span>
                                  </div>
                                  {doc.error_message && (
                                    <p className="text-[11px] text-destructive mt-1 font-mono">
                                      Error: {doc.error_message}
                                    </p>
                                  )}
                                </div>
                              </div>

                              <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                onClick={() => handleDeleteDocument(scope.id, doc.id)}
                                disabled={isDeletingThisDoc}
                                className="h-7 px-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                                title="Delete document"
                                data-testid={`delete-doc-button-${doc.id}`}
                              >
                                {isDeletingThisDoc ? (
                                  <Loader2 className="size-3.5 animate-spin" />
                                ) : (
                                  <Trash2 className="size-3.5" />
                                )}
                              </Button>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Add Knowledge Modal Dialog */}
      <AddKnowledgeDialog
        open={isCreateOpen}
        onOpenChange={setIsCreateOpen}
        onKnowledgeCreated={handleKnowledgeCreated}
      />
    </div>
  );
}
