import { Suspense } from "react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { repositoriesApi } from "@/lib/api/repositories";
import { ApiClientError } from "@/lib/api/client";
import { RepositoryWorkspace } from "@/components/repository-workspace";
import type { Repository, IndexSummary, FileMetadata } from "@/lib/api/types";
import { Skeleton } from "@/components/ui/skeleton";

interface PageProps {
  params: Promise<{ repositoryId: string }>;
  searchParams: Promise<{ file?: string }>;
}

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function generateMetadata({
  params,
  searchParams,
}: PageProps): Promise<Metadata> {
  const { repositoryId } = await params;
  const { file } = await searchParams;
  if (!UUID_REGEX.test(repositoryId)) {
    return { title: "Repository Not Found" };
  }
  try {
    const repo = await repositoriesApi.get(repositoryId);
    if (file) {
      const fileName = file.split("/").pop() || file;
      return { title: `${fileName} · ${repo.name}` };
    }
    return { title: repo.name };
  } catch {
    return { title: "Repository" };
  }
}

function WorkspaceFallback() {
  return (
    <div className="flex flex-col h-full bg-background animate-pulse">
      <div className="flex h-11 items-center border-b border-border px-4 gap-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-4 w-32" />
      </div>
      <div className="flex flex-1 overflow-hidden">
        <div className="w-64 border-r border-border p-3 space-y-2">
          <Skeleton className="h-7 w-full" />
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
        </div>
        <div className="flex-1 p-8 space-y-4">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-32 w-full" />
        </div>
      </div>
    </div>
  );
}

export default async function RepositoryWorkspacePage({
  params,
  searchParams,
}: PageProps) {
  const { repositoryId } = await params;
  const { file } = await searchParams;

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

  // Fetch repository code files
  let files: FileMetadata[] = [];
  try {
    const filesResponse = await repositoriesApi.getFiles(repositoryId);
    files = filesResponse.files;
  } catch {
    // Non-fatal — files list can be empty or retry later
    files = [];
  }

  return (
    <Suspense fallback={<WorkspaceFallback />}>
      <RepositoryWorkspace
        repository={repo}
        initialFiles={files}
        initialSelectedFile={file || null}
        indexSummary={indexSummary}
      />
    </Suspense>
  );
}

