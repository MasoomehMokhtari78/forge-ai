import { Skeleton } from "@/components/ui/skeleton";

export default function RepositoriesLoading() {
  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-8">
      {/* Header skeleton */}
      <div className="mb-6 flex items-center justify-between">
        <div className="space-y-1.5">
          <Skeleton className="h-5 w-28" />
          <Skeleton className="h-4 w-20" />
        </div>
        <Skeleton className="h-7 w-16" />
      </div>

      {/* Card skeletons */}
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="flex items-start justify-between gap-4 rounded-lg border border-border bg-card px-5 py-4"
          >
            <div className="flex min-w-0 items-start gap-3">
              <Skeleton className="mt-0.5 size-8 shrink-0 rounded-md" />
              <div className="space-y-2">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-3 w-56" />
                <Skeleton className="h-3 w-32" />
              </div>
            </div>
            <Skeleton className="h-5 w-16 rounded-full" />
          </div>
        ))}
      </div>
    </div>
  );
}
