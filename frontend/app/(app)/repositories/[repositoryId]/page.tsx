import type { Metadata } from "next";
import { notFound } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  FolderGit2,
  Files,
  ChevronRight,
  Clock,
  Hash,
  FileCode2,
  Layers,
} from "lucide-react";
import { repositoriesApi } from "@/lib/api/repositories";
import { RepositoryStatusBadge } from "@/components/repository-status-badge";
import { ApiClientError } from "@/lib/api/client";
import type { Repository, IndexSummary } from "@/lib/api/types";

interface PageProps {
  params: Promise<{ repositoryId: string }>;
}

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { repositoryId } = await params;
  if (!UUID_REGEX.test(repositoryId)) {
    return { title: "Repository Not Found" };
  }
  try {
    const repo = await repositoriesApi.get(repositoryId);
    return { title: repo.name };
  } catch {
    return { title: "Repository" };
  }
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

export default async function RepositoryWorkspacePage({ params }: PageProps) {
  const { repositoryId } = await params;

  if (!UUID_REGEX.test(repositoryId)) {
    notFound();
  }

  // Fetch repo details
  let repo: Repository;
  try {
    repo = await repositoriesApi.get(repositoryId);
  } catch (err) {
    if (err instanceof ApiClientError && (err.status === 404 || err.status === 422)) {
      notFound();
    }
    throw err;
  }

  // Fetch index summary (only relevant when completed)
  let indexSummary: IndexSummary | null = null;
  if (repo.status === "completed") {
    try {
      indexSummary = await repositoriesApi.getIndexSummary(repositoryId);
    } catch {
      // Non-fatal — workspace can render without index stats
    }
  }

  const [owner, repoName] = repo.name.split("/");
  const host = formatRepoHost(repo.url);

  return (
    <div className="flex flex-col h-full">
      {/* Workspace topbar */}
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border px-4">
        <Link
          href="/repositories"
          className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          Repositories
        </Link>
        <ChevronRight className="size-3.5 text-muted-foreground/50" />
        <div className="flex items-center gap-2">
          <FolderGit2 className="size-3.5 text-muted-foreground" />
          <span className="text-xs text-muted-foreground">{owner}/</span>
          <span className="text-xs font-medium text-foreground">{repoName}</span>
        </div>
        <div className="ml-auto">
          <RepositoryStatusBadge status={repo.status} />
        </div>
      </div>

      {/* Three-panel workspace layout */}
      <div className="flex flex-1 overflow-hidden">
        {/* ── Left panel: File Explorer placeholder ── */}
        <aside className="hidden w-56 shrink-0 flex-col border-r border-border bg-sidebar xl:flex">
          <div className="flex h-10 items-center gap-2 border-b border-border px-4">
            <Files className="size-3.5 text-muted-foreground" />
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Files
            </span>
          </div>
          <div className="flex flex-1 flex-col items-center justify-center gap-2 p-4 text-center">
            <FileCode2 className="size-6 text-muted-foreground/40" />
            <p className="text-xs text-muted-foreground/60 leading-relaxed">
              File browser coming in the next phase.
            </p>
          </div>
        </aside>

        {/* ── Center panel: Repository Overview ── */}
        <div className="flex flex-1 flex-col overflow-auto">
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
                href={repo.url}
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
                      {repo.id}
                    </span>
                  }
                />
                <MetaItem
                  icon={Clock}
                  label="Added"
                  value={formatDate(repo.created_at)}
                />
                {repo.ingested_at && (
                  <MetaItem
                    icon={Clock}
                    label="Indexed at"
                    value={formatDate(repo.ingested_at)}
                  />
                )}
                {repo.status === "failed" && repo.error_message && (
                  <MetaItem
                    icon={Files}
                    label="Error"
                    value={
                      <span className="text-destructive text-xs">
                        {repo.error_message}
                      </span>
                    }
                  />
                )}
              </div>
            </div>

            {/* Index Stats — only when indexed */}
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
          </div>
        </div>

        {/* ── Right panel: AI Assistant placeholder ── */}
        <aside className="hidden w-72 shrink-0 flex-col border-l border-border xl:flex">
          <div className="flex h-10 items-center gap-2 border-b border-border px-4">
            <span className="size-1.5 rounded-full bg-primary" />
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              AI Assistant
            </span>
          </div>
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
            <div className="flex size-10 items-center justify-center rounded-xl border border-border bg-muted/40">
              <span className="text-base">✦</span>
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
