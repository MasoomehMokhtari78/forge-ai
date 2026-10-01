"use client";

import React, { useState, useMemo, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Prism from "prismjs";
import "prismjs/components/prism-python";
import "prismjs/components/prism-javascript";
import "prismjs/components/prism-typescript";
import "prismjs/components/prism-jsx";
import "prismjs/components/prism-tsx";
import "prismjs/components/prism-json";
import "prismjs/components/prism-markdown";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-yaml";
import "prismjs/components/prism-css";
import "prismjs/components/prism-sql";
import "prismjs/components/prism-docker";
import "prismjs/components/prism-toml";
import "prismjs/components/prism-rust";
import "prismjs/components/prism-go";

import { Check, Copy } from "lucide-react";

interface MarkdownRendererProps {
  content: string;
  className?: string;
  onSelectFile?: (path: string, line?: number) => void;
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function highlightCode(code: string, language?: string): string {
  if (!code) return "";
  const lang = (language || "").toLowerCase().trim();
  const aliasMap: Record<string, string> = {
    py: "python",
    js: "javascript",
    ts: "typescript",
    tsx: "tsx",
    jsx: "jsx",
    sh: "bash",
    shell: "bash",
    bash: "bash",
    zsh: "bash",
    yml: "yaml",
    docker: "docker",
    dockerfile: "docker",
    rs: "rust",
    golang: "go",
  };
  const targetLang = aliasMap[lang] || lang;
  const grammar = Prism.languages[targetLang];
  if (grammar) {
    try {
      return Prism.highlight(code, grammar, targetLang);
    } catch {
      return escapeHtml(code);
    }
  }
  return escapeHtml(code);
}

interface CodeBlockProps {
  language?: string;
  code: string;
}

function CodeBlock({ language, code }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const highlighted = useMemo(() => {
    return highlightCode(code, language);
  }, [code, language]);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore clipboard error
    }
  }, [code]);

  const displayLang = language ? language.toLowerCase() : "code";

  return (
    <div className="my-2.5 overflow-hidden rounded-md border border-border/70 bg-muted/30 shadow-xs">
      {/* Code Header Bar */}
      <div className="flex h-7 items-center justify-between border-b border-border/50 bg-muted/60 px-3 text-[10px]">
        <span className="font-mono font-medium uppercase tracking-wider text-muted-foreground">
          {displayLang}
        </span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          title="Copy code"
        >
          {copied ? (
            <>
              <Check className="size-3 text-status-success" />
              <span className="text-[10px] text-status-success font-medium">Copied!</span>
            </>
          ) : (
            <>
              <Copy className="size-3" />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>

      {/* Code Content */}
      <div className="overflow-x-auto p-3 text-xs font-mono leading-relaxed">
        <pre className="!m-0 !p-0 !bg-transparent">
          <code
            className={language ? `language-${language}` : ""}
            dangerouslySetInnerHTML={{ __html: highlighted }}
          />
        </pre>
      </div>
    </div>
  );
}

export function MarkdownRenderer({
  content,
  className = "",
  onSelectFile,
}: MarkdownRendererProps) {
  return (
    <div className={`markdown-content text-xs text-foreground leading-relaxed ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Code handling: distinguish block code from inline code
          pre({ children }) {
            return <div className="not-prose my-1">{children}</div>;
          },
          code({ className: codeClassName, children, ...props }) {
            const match = /language-(\w+)/.exec(codeClassName || "");
            const rawText = String(children).replace(/\n$/, "");
            const isBlock = Boolean(match) || rawText.includes("\n");

            if (isBlock) {
              return (
                <CodeBlock
                  language={match ? match[1] : undefined}
                  code={rawText}
                />
              );
            }

            return (
              <code
                className="rounded bg-muted/80 px-1.5 py-0.5 font-mono text-[11px] text-primary border border-border/50"
                {...props}
              >
                {children}
              </code>
            );
          },
          p({ children }) {
            return <p className="mb-2.5 last:mb-0 leading-relaxed">{children}</p>;
          },
          h1({ children }) {
            return (
              <h1 className="text-sm font-bold text-foreground mt-3 mb-2 pb-1 border-b border-border/40">
                {children}
              </h1>
            );
          },
          h2({ children }) {
            return (
              <h2 className="text-xs font-bold text-foreground mt-3 mb-1.5">
                {children}
              </h2>
            );
          },
          h3({ children }) {
            return (
              <h3 className="text-xs font-semibold text-foreground/90 mt-2.5 mb-1">
                {children}
              </h3>
            );
          },
          h4({ children }) {
            return (
              <h4 className="text-xs font-semibold text-foreground/80 mt-2 mb-1">
                {children}
              </h4>
            );
          },
          ul({ children }) {
            return (
              <ul className="list-disc list-outside pl-4 space-y-1 mb-2.5">
                {children}
              </ul>
            );
          },
          ol({ children }) {
            return (
              <ol className="list-decimal list-outside pl-4 space-y-1 mb-2.5">
                {children}
              </ol>
            );
          },
          li({ children }) {
            return <li className="leading-relaxed">{children}</li>;
          },
          blockquote({ children }) {
            return (
              <blockquote className="border-l-2 border-primary/60 pl-3 my-2 text-xs italic text-muted-foreground bg-muted/20 py-1 rounded-r">
                {children}
              </blockquote>
            );
          },
          table({ children }) {
            return (
              <div className="my-2.5 overflow-x-auto rounded border border-border/70 shadow-xs">
                <table className="w-full border-collapse text-[11px]">{children}</table>
              </div>
            );
          },
          thead({ children }) {
            return (
              <thead className="bg-muted/50 border-b border-border/70 text-foreground font-semibold">
                {children}
              </thead>
            );
          },
          th({ children }) {
            return (
              <th className="px-2.5 py-1.5 text-left border-r border-border/40 last:border-r-0 font-medium">
                {children}
              </th>
            );
          },
          td({ children }) {
            return (
              <td className="px-2.5 py-1.5 border-t border-border/30 border-r border-border/40 last:border-r-0 text-muted-foreground">
                {children}
              </td>
            );
          },
          hr() {
            return <hr className="border-border/60 my-3" />;
          },
          strong({ children }) {
            return <strong className="font-semibold text-foreground">{children}</strong>;
          },
          em({ children }) {
            return <em className="italic">{children}</em>;
          },
          a({ href, children, ...props }) {
            // Check if link is a local file reference like "path/file.py" or file://
            if (href && onSelectFile && !href.startsWith("http://") && !href.startsWith("https://")) {
              const cleanPath = href.replace(/^file:\/\/\/?/, "");
              const [filePath, anchor] = cleanPath.split("#");
              const lineMatch = anchor?.match(/L?(\d+)/i);
              const line = lineMatch ? parseInt(lineMatch[1], 10) : undefined;

              return (
                <button
                  type="button"
                  onClick={() => onSelectFile(filePath, line)}
                  className="inline-flex items-center text-primary underline underline-offset-2 hover:text-primary/80 transition-colors cursor-pointer font-medium"
                  title={`Open ${filePath}`}
                >
                  {children}
                </button>
              );
            }

            return (
              <a
                href={href}
                target={href?.startsWith("http") ? "_blank" : undefined}
                rel={href?.startsWith("http") ? "noopener noreferrer" : undefined}
                className="text-primary underline underline-offset-2 hover:text-primary/80 transition-colors"
                {...props}
              >
                {children}
              </a>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
