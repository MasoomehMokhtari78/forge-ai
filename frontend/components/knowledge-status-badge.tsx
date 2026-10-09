import { cn } from "cn";
import type { KnowledgeStatus } from "@/lib/api/types";

const statusConfig: Record<
  KnowledgeStatus,
  { label: string; dotClass: string; textClass: string; bgClass: string }
> = {
  completed: {
    label: "Completed",
    dotClass: "bg-status-success",
    textClass: "text-status-success",
    bgClass: "bg-status-success/10",
  },
  failed: {
    label: "Failed",
    dotClass: "bg-status-error",
    textClass: "text-status-error",
    bgClass: "bg-status-error/10",
  },
  pending: {
    label: "Pending",
    dotClass: "bg-status-warning",
    textClass: "text-status-warning",
    bgClass: "bg-status-warning/10",
  },
  processing: {
    label: "Processing",
    dotClass: "bg-status-processing animate-pulse",
    textClass: "text-status-processing",
    bgClass: "bg-status-processing/10",
  },
};

interface KnowledgeStatusBadgeProps {
  status: KnowledgeStatus;
  className?: string;
}

export function KnowledgeStatusBadge({
  status,
  className,
}: KnowledgeStatusBadgeProps) {
  const config = statusConfig[status] ?? statusConfig.pending;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium",
        config.bgClass,
        config.textClass,
        className
      )}
      data-testid="knowledge-status-badge"
    >
      <span
        className={cn("size-1.5 shrink-0 rounded-full", config.dotClass)}
      />
      {config.label}
    </span>
  );
}
