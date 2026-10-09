"use client";

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  useEffect,
} from "react";
import { CheckCircle2, AlertCircle, AlertTriangle, Info, X } from "lucide-react";
import { cn } from "cn";

export type ToastType = "default" | "success" | "error" | "warning" | "info";

export interface ToastItem {
  id: string;
  title?: string;
  message: string;
  type?: ToastType;
  duration?: number;
}

interface ToastContextValue {
  toast: (options: Omit<ToastItem, "id">) => void;
  success: (message: string, title?: string) => void;
  error: (message: string, title?: string) => void;
  warning: (message: string, title?: string) => void;
  info: (message: string, title?: string) => void;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const iconMap = {
  default: Info,
  info: Info,
  success: CheckCircle2,
  error: AlertCircle,
  warning: AlertTriangle,
};

const typeStyles: Record<
  ToastType,
  { border: string; iconClass: string; bg: string }
> = {
  default: {
    border: "border-border",
    iconClass: "text-primary",
    bg: "bg-card/95",
  },
  info: {
    border: "border-primary/40",
    iconClass: "text-primary",
    bg: "bg-card/95",
  },
  success: {
    border: "border-status-success/40",
    iconClass: "text-status-success",
    bg: "bg-card/95",
  },
  error: {
    border: "border-destructive/40",
    iconClass: "text-destructive",
    bg: "bg-card/95",
  },
  warning: {
    border: "border-status-warning/40",
    iconClass: "text-status-warning",
    bg: "bg-card/95",
  },
};

function ToastMessageItem({
  item,
  onDismiss,
}: {
  item: ToastItem;
  onDismiss: (id: string) => void;
}) {
  const type = item.type || "default";
  const Icon = iconMap[type] || Info;
  const style = typeStyles[type];

  useEffect(() => {
    const timer = setTimeout(() => {
      onDismiss(item.id);
    }, item.duration ?? 4000);
    return () => clearTimeout(timer);
  }, [item.id, item.duration, onDismiss]);

  return (
    <div
      role="status"
      data-testid="toast-item"
      data-toast-type={type}
      className={cn(
        "pointer-events-auto flex items-start gap-2.5 rounded-lg border p-3 shadow-lg backdrop-blur-md transition-all duration-200 animate-in fade-in-0 slide-in-from-bottom-2 sm:slide-in-from-top-2 w-full max-w-sm text-xs",
        style.bg,
        style.border
      )}
    >
      <Icon className={cn("size-4 shrink-0 mt-0.5", style.iconClass)} />
      <div className="flex-1 min-w-0">
        {item.title && (
          <p className="font-semibold text-foreground text-xs leading-tight mb-0.5">
            {item.title}
          </p>
        )}
        <p className="text-muted-foreground leading-relaxed break-words">
          {item.message}
        </p>
      </div>
      <button
        type="button"
        onClick={() => onDismiss(item.id)}
        className="shrink-0 rounded p-0.5 text-muted-foreground/70 hover:text-foreground hover:bg-muted/50 transition-colors"
        title="Dismiss toast"
      >
        <X className="size-3.5" />
      </button>
    </div>
  );
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback((options: Omit<ToastItem, "id">) => {
    const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    setToasts((prev) => [...prev, { ...options, id }]);
  }, []);

  const success = useCallback(
    (message: string, title?: string) => {
      addToast({ message, title: title || "Success", type: "success" });
    },
    [addToast]
  );

  const error = useCallback(
    (message: string, title?: string) => {
      addToast({ message, title: title || "Error", type: "error" });
    },
    [addToast]
  );

  const warning = useCallback(
    (message: string, title?: string) => {
      addToast({ message, title: title || "Warning", type: "warning" });
    },
    [addToast]
  );

  const info = useCallback(
    (message: string, title?: string) => {
      addToast({ message, title: title || "Notice", type: "info" });
    },
    [addToast]
  );

  const contextValue = useMemo(
    () => ({
      toast: addToast,
      success,
      error,
      warning,
      info,
      dismiss,
    }),
    [addToast, success, error, warning, info, dismiss]
  );

  return (
    <ToastContext.Provider value={contextValue}>
      {children}
      {/* Toast viewport */}
      <div
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full px-4 sm:px-0"
        data-testid="toast-container"
      >
        {toasts.map((item) => (
          <ToastMessageItem key={item.id} item={item} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return context;
}
