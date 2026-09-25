"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AddRepositoryDialog } from "./add-repository-dialog";

export function AddRepositoryButton() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="h-7 gap-1.5 px-2 text-xs text-muted-foreground hover:text-foreground"
        onClick={() => setOpen(true)}
      >
        <Plus className="size-3.5" />
        New
      </Button>
      <AddRepositoryDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
