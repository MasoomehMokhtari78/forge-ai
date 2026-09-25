"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Plus, GitBranch, Loader2, AlertCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { repositoriesApi } from "@/lib/api/repositories";
import { ApiClientError } from "@/lib/api/client";

interface AddRepositoryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AddRepositoryDialog({
  open,
  onOpenChange,
}: AddRepositoryDialogProps) {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  function handleClose(open: boolean) {
    if (!isPending) {
      onOpenChange(open);
      if (!open) {
        setUrl("");
        setError(null);
      }
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) return;

    setError(null);

    startTransition(async () => {
      try {
        const repo = await repositoriesApi.create({ url: trimmed });
        onOpenChange(false);
        setUrl("");
        router.push(`/repositories/${repo.id}`);
        router.refresh();
      } catch (err) {
        if (err instanceof ApiClientError) {
          setError(err.detail ?? err.message);
        } else {
          setError("An unexpected error occurred. Please try again.");
        }
      }
    });
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base font-semibold">
            <GitBranch className="size-4 text-primary" />
            Add Repository
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            Enter a public GitHub repository URL. ForgeAI will clone and index
            it locally.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} id="add-repo-form" className="space-y-4">
          <div className="space-y-1.5">
            <label
              htmlFor="repo-url"
              className="text-xs font-medium text-muted-foreground uppercase tracking-wider"
            >
              GitHub URL
            </label>
            <Input
              id="repo-url"
              type="url"
              placeholder="https://github.com/owner/repository"
              value={url}
              onChange={(e) => {
                setUrl(e.target.value);
                setError(null);
              }}
              disabled={isPending}
              autoFocus
              className="font-mono text-sm"
            />
          </div>

          {error && (
            <div
              role="alert"
              data-testid="repo-error-alert"
              className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-xs text-destructive"
            >
              <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}
        </form>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            type="button"
            variant="ghost"
            onClick={() => handleClose(false)}
            disabled={isPending}
            className="text-sm"
          >
            Cancel
          </Button>
          <Button
            type="submit"
            form="add-repo-form"
            disabled={isPending || !url.trim()}
            className="gap-2 text-sm"
          >
            {isPending ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Plus className="size-3.5" />
            )}
            {isPending ? "Adding..." : "Add Repository"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
