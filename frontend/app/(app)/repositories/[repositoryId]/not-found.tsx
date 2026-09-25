import Link from "next/link";
import { AlertCircle, ArrowLeft } from "lucide-react";

export default function RepositoryNotFound() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
      <div className="flex size-12 items-center justify-center rounded-xl border border-destructive/30 bg-destructive/10">
        <AlertCircle className="size-5 text-destructive" />
      </div>
      <div className="space-y-1">
        <h2 className="text-sm font-medium text-foreground">
          Repository not found
        </h2>
        <p className="max-w-xs text-xs text-muted-foreground">
          This repository does not exist or may have been removed.
        </p>
      </div>
      <Link
        href="/repositories"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        Back to Repositories
      </Link>
    </div>
  );
}
