"use client";

import { useState, useTransition } from "react";
import { BookOpen, Loader2 } from "lucide-react";

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
import { knowledgeApi } from "@/lib/api/knowledge";
import { ApiClientError } from "@/lib/api/client";
import { useToast } from "@/components/ui/toast";
import type { EngineeringKnowledge } from "@/lib/api/types";

interface AddKnowledgeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onKnowledgeCreated?: (knowledge: EngineeringKnowledge) => void;
}

export function AddKnowledgeDialog({
  open,
  onOpenChange,
  onKnowledgeCreated,
}: AddKnowledgeDialogProps) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isPending, startTransition] = useTransition();

  function handleClose(nextOpen: boolean) {
    if (!isPending) {
      onOpenChange(nextOpen);
      if (!nextOpen) {
        setName("");
        setDescription("");
      }
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) return;

    startTransition(async () => {
      try {
        const created = await knowledgeApi.create({
          name: trimmedName,
          description: description.trim() || undefined,
        });
        onOpenChange(false);
        setName("");
        setDescription("");
        if (onKnowledgeCreated) {
          onKnowledgeCreated(created);
        }
      } catch (err) {
        const msg =
          err instanceof ApiClientError
            ? err.detail ?? err.message
            : err instanceof Error
            ? err.message
            : "An unexpected error occurred. Please try again.";
        toast.error(msg, "Creation Failed");
      }
    });
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base font-semibold">
            <BookOpen className="size-4 text-primary" />
            Create Engineering Knowledge Scope
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            Define a domain knowledge scope (e.g. &ldquo;Design Patterns&rdquo;, &ldquo;SOLID Principles&rdquo;)
            to guide code analysis.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} id="add-knowledge-form" className="space-y-4">
          <div className="space-y-1.5">
            <label
              htmlFor="knowledge-name"
              className="text-xs font-medium text-muted-foreground uppercase tracking-wider"
            >
              Scope Name
            </label>
            <Input
              id="knowledge-name"
              placeholder="e.g. Design Pattern Guidance"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isPending}
              autoFocus
              data-testid="knowledge-name-input"
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="knowledge-desc"
              className="text-xs font-medium text-muted-foreground uppercase tracking-wider"
            >
              Description (Optional)
            </label>
            <Input
              id="knowledge-desc"
              placeholder="e.g. Gang of Four patterns and architectural rules"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={isPending}
              data-testid="knowledge-desc-input"
            />
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => handleClose(false)}
              disabled={isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={isPending || !name.trim()}
              data-testid="create-knowledge-submit"
            >
              {isPending ? (
                <>
                  <Loader2 className="size-3 animate-spin" />
                  <span>Creating...</span>
                </>
              ) : (
                <span>Create Scope</span>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
