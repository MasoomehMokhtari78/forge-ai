import { Skeleton } from "@/components/ui/skeleton";

export default function RepositoryWorkspaceLoading() {
  return (
    <div className="flex flex-col h-full">
      {/* Topbar skeleton */}
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border px-4">
        <Skeleton className="h-3 w-28" />
        <Skeleton className="h-3 w-3" />
        <Skeleton className="h-3 w-32" />
        <div className="ml-auto">
          <Skeleton className="h-5 w-16 rounded-full" />
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Left panel */}
        <aside className="hidden w-56 shrink-0 border-r border-border xl:block">
          <div className="h-10 border-b border-border px-4 flex items-center">
            <Skeleton className="h-3 w-16" />
          </div>
        </aside>

        {/* Center panel */}
        <div className="flex-1 overflow-auto">
          <div className="mx-auto w-full max-w-2xl px-8 py-8 space-y-6">
            {/* Header */}
            <div className="flex items-center gap-3">
              <Skeleton className="size-9 rounded-lg" />
              <div className="space-y-1.5">
                <Skeleton className="h-4 w-36" />
                <Skeleton className="h-3 w-20" />
              </div>
            </div>
            <Skeleton className="h-3 w-48" />

            {/* Details card */}
            <div className="rounded-lg border border-border bg-card">
              <div className="px-4 py-3 border-b border-border">
                <Skeleton className="h-3 w-12" />
              </div>
              <div className="divide-y divide-border px-4">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="flex gap-3 py-3">
                    <Skeleton className="mt-0.5 size-4 shrink-0 rounded" />
                    <div className="space-y-1.5 flex-1">
                      <Skeleton className="h-3 w-20" />
                      <Skeleton className="h-4 w-48" />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Index stats card */}
            <div className="rounded-lg border border-border bg-card">
              <div className="px-4 py-3 border-b border-border">
                <Skeleton className="h-3 w-10" />
              </div>
              <div className="grid grid-cols-2 divide-x divide-border">
                {Array.from({ length: 2 }).map((_, i) => (
                  <div key={i} className="flex flex-col items-center gap-2 p-5">
                    <Skeleton className="h-3 w-12" />
                    <Skeleton className="h-7 w-16" />
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Right panel */}
        <aside className="hidden w-72 shrink-0 border-l border-border xl:block">
          <div className="h-10 border-b border-border px-4 flex items-center">
            <Skeleton className="h-3 w-24" />
          </div>
        </aside>
      </div>
    </div>
  );
}
