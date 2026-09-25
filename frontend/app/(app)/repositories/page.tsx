import type { Metadata } from "next";
import Link from "next/link";
import {
  FolderGit2,
  ArrowRight,
  AlertCircle,
  GitBranch,
} from "lucide-react";
import { repositoriesApi } from "@/lib/api/repositories";
import { RepositoryStatusBadge } from "@/components/repository-status-badge";
import { AddRepositoryButton } from "@/components/add-repository-button";
import type { Repository } from "@/lib/api/types";

export const metadata: Metadata = {
  title: "Repositories",
};

// Extract readable host from a GitHub URL (e.g. "github.com/owner/repo")
function formatRepoHost(url: string): string {
  try {
    const u = new URL(url);
    return u.hostname + u.pathname;
  } catch {
    return url;
  }
}

function formatDate(isoString: string | null): string {
  if (!isoString) return "—";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(isoString));
}

// Server component — fetches data, no "use client"
async function getRepositories(): Promise<{
  repos: Repository[] | null;
  error: string | null;
}> {
  try {
    const repos = await repositoriesApi.list();
    return { repos, error: null };
  } catch (err) {
    const msg =
      err instanceof Error ? err.message : "Failed to load repositories";
    return { repos: null, error: msg };
  }
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
      <div className="flex size-12 items-center justify-center rounded-xl border border-border bg-muted/40">
        <GitBranch className="size-5 text-muted-foreground" />
      </div>
      <div className="space-y-1">
        <h2 className="text-sm font-medium text-foreground">
          No repositories yet
        </h2>
        <p className="max-w-xs text-xs text-muted-foreground leading-relaxed">
          Connect a public GitHub repository to start understanding your
          codebase with ForgeAI.
        </p>
      </div>
      <AddRepositoryButton />
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
      <div className="flex size-12 items-center justify-center rounded-xl border border-destructive/30 bg-destructive/10">
        <AlertCircle className="size-5 text-destructive" />
      </div>
      <div className="space-y-1">
        <h2 className="text-sm font-medium text-foreground">
          Failed to load repositories
        </h2>
        <p className="max-w-xs text-xs text-muted-foreground">{message}</p>
      </div>
    </div>
  );
}

function RepositoryCard({ repo }: { repo: Repository }) {
  const host = formatRepoHost(repo.url);
  const addedAt = formatDate(repo.created_at);
  const ingestedAt = formatDate(repo.ingested_at);
  const [owner, repoName] = repo.name.split("/");

  return (
    <Link
      href={`/repositories/${repo.id}`}
      className="group flex items-start justify-between gap-4 rounded-lg border border-border bg-card px-5 py-4 transition-all duration-150 hover:border-border/80 hover:bg-card/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex min-w-0 items-start gap-3">
        <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-muted/40">
          <FolderGit2 className="size-4 text-muted-foreground" />
        </div>
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground truncate">
              {owner}/
            </span>
            <span className="text-sm font-medium text-foreground truncate">
              {repoName}
            </span>
          </div>
          <p className="truncate text-xs text-muted-foreground">{host}</p>
          <div className="flex flex-wrap items-center gap-3 pt-0.5">
            <span className="text-xs text-muted-foreground">
              Added {addedAt}
            </span>
            {repo.status === "completed" && repo.ingested_at && (
              <span className="text-xs text-muted-foreground">
                Indexed {ingestedAt}
              </span>
            )}
            {repo.status === "failed" && repo.error_message && (
              <span
                className="max-w-xs truncate text-xs text-destructive"
                title={repo.error_message}
              >
                {repo.error_message}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-3">
        <RepositoryStatusBadge status={repo.status} />
        <ArrowRight className="size-4 text-muted-foreground transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-foreground" />
      </div>
    </Link>
  );
}

interface PageProps {
  searchParams?: Promise<{ state?: string }>;
}

export default async function RepositoriesPage({ searchParams }: PageProps) {
  const params = searchParams ? await searchParams : {};
  let { repos, error } = await getRepositories();

  if (process.env.NODE_ENV === "development") {
    if (params?.state === "empty") {
      repos = [];
      error = null;
    } else if (params?.state === "error") {
      repos = null;
      error = "Could not connect to ForgeAI backend. Please check that the server is running.";
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-8">
      {/* Page header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-foreground">
            Repositories
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {repos
              ? `${repos.length} ${repos.length === 1 ? "repository" : "repositories"}`
              : "Your indexed codebases"}
          </p>
        </div>
        <AddRepositoryButton />
      </div>

      {/* Content */}
      {error ? (
        <ErrorState message={error} />
      ) : repos && repos.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="space-y-2">
          {repos?.map((repo) => (
            <RepositoryCard key={repo.id} repo={repo} />
          ))}
        </div>
      )}
    </div>
  );
}
