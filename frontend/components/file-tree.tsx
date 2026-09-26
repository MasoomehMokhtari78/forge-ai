"use client";

import React, { useState, useMemo, useCallback } from "react";
import {
  Folder,
  FolderOpen,
  ChevronRight,
  ChevronDown,
  FileCode2,
  FileJson,
  FileText,
  File,
  Search,
  X,
  Files,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  buildFileTree,
  filterFileTree,
  formatBytes,
  type FileTreeNode,
} from "@/lib/file-tree";
import type { FileMetadata } from "@/lib/api/types";

interface FileTreeProps {
  files: FileMetadata[];
  selectedFilePath: string | null;
  onSelectFile: (path: string) => void;
  isLoading?: boolean;
}

function FileIcon({ extension, isSelected }: { extension: string; isSelected: boolean }) {
  const ext = extension.toLowerCase().replace(/^\./, "");
  const className = `size-3.5 shrink-0 ${
    isSelected ? "text-primary" : "text-muted-foreground/70 group-hover:text-foreground"
  }`;

  switch (ext) {
    case "ts":
    case "tsx":
    case "js":
    case "jsx":
    case "py":
    case "rs":
    case "go":
    case "sql":
    case "sh":
    case "bash":
      return <FileCode2 className={className} />;
    case "json":
    case "yaml":
    case "yml":
    case "toml":
      return <FileJson className={className} />;
    case "md":
    case "txt":
      return <FileText className={className} />;
    default:
      return <File className={className} />;
  }
}

interface TreeNodeItemProps {
  node: FileTreeNode;
  depth: number;
  expandedFolders: Set<string>;
  onToggleFolder: (path: string) => void;
  selectedFilePath: string | null;
  onSelectFile: (path: string) => void;
  isSearching: boolean;
}

function TreeNodeItem({
  node,
  depth,
  expandedFolders,
  onToggleFolder,
  selectedFilePath,
  onSelectFile,
  isSearching,
}: TreeNodeItemProps) {
  if (node.type === "folder") {
    // When searching, all matched folders are automatically expanded
    const isExpanded = isSearching ? true : expandedFolders.has(node.path);

    return (
      <div className="select-none">
        <button
          type="button"
          onClick={() => onToggleFolder(node.path)}
          className="flex w-full items-center gap-1.5 py-1 px-2 text-xs text-muted-foreground hover:bg-muted/40 hover:text-foreground rounded transition-colors text-left group"
          style={{ paddingLeft: `${depth * 14 + 8}px` }}
          data-testid={`folder-${node.name}`}
          aria-expanded={isExpanded}
        >
          {isExpanded ? (
            <ChevronDown className="size-3.5 shrink-0 text-muted-foreground/60 group-hover:text-foreground" />
          ) : (
            <ChevronRight className="size-3.5 shrink-0 text-muted-foreground/60 group-hover:text-foreground" />
          )}
          {isExpanded ? (
            <FolderOpen className="size-3.5 shrink-0 text-primary/80" />
          ) : (
            <Folder className="size-3.5 shrink-0 text-muted-foreground/80 group-hover:text-foreground" />
          )}
          <span className="truncate font-medium text-foreground/90">{node.name}</span>
        </button>

        {isExpanded && (
          <div>
            {node.children.map((child) => (
              <TreeNodeItem
                key={child.id}
                node={child}
                depth={depth + 1}
                expandedFolders={expandedFolders}
                onToggleFolder={onToggleFolder}
                selectedFilePath={selectedFilePath}
                onSelectFile={onSelectFile}
                isSearching={isSearching}
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  // File node
  const isSelected = selectedFilePath === node.path;

  return (
    <div className="select-none">
      <button
        type="button"
        onClick={() => onSelectFile(node.path)}
        className={`flex w-full items-center justify-between py-1 px-2 text-xs rounded transition-colors text-left group ${
          isSelected
            ? "bg-accent text-accent-foreground font-medium"
            : "text-muted-foreground hover:bg-muted/40 hover:text-foreground"
        }`}
        style={{ paddingLeft: `${depth * 14 + 22}px` }}
        data-testid={`file-${node.name}`}
        data-selected={isSelected}
      >
        <div className="flex items-center gap-1.5 min-w-0 truncate">
          <FileIcon extension={node.extension} isSelected={isSelected} />
          <span className="truncate">{node.name}</span>
        </div>
        <span className="text-[10px] tabular-nums text-muted-foreground/50 shrink-0 ml-2 hidden group-hover:inline">
          {formatBytes(node.size_bytes)}
        </span>
      </button>
    </div>
  );
}

function getInitialFolders(selectedPath: string | null): Set<string> {
  const folders = new Set<string>();
  if (!selectedPath) return folders;
  const parts = selectedPath.split("/").filter(Boolean);
  let cur = "";
  for (let i = 0; i < parts.length - 1; i++) {
    cur = cur ? `${cur}/${parts[i]}` : parts[i];
    folders.add(cur);
  }
  return folders;
}

export function FileTree({
  files,
  selectedFilePath,
  onSelectFile,
  isLoading = false,
}: FileTreeProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(() =>
    getInitialFolders(selectedFilePath)
  );

  // 1. Build tree structure from flat files
  const rootNodes = useMemo(() => buildFileTree(files), [files]);

  // 2. Filter tree when search query is entered
  const filteredNodes = useMemo(() => {
    return filterFileTree(rootNodes, searchQuery);
  }, [rootNodes, searchQuery]);

  const isSearching = searchQuery.trim().length > 0;

  const handleToggleFolder = useCallback((folderPath: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(folderPath)) {
        next.delete(folderPath);
      } else {
        next.add(folderPath);
      }
      return next;
    });
  }, []);

  const handleSelect = useCallback(
    (path: string) => {
      // Auto-expand any ancestors of the selected file
      const parts = path.split("/").filter(Boolean);
      let cur = "";
      setExpandedFolders((prev) => {
        const next = new Set(prev);
        for (let i = 0; i < parts.length - 1; i++) {
          cur = cur ? `${cur}/${parts[i]}` : parts[i];
          next.add(cur);
        }
        return next;
      });
      onSelectFile(path);
    },
    [onSelectFile]
  );

  return (
    <div className="flex flex-col h-full overflow-hidden" data-testid="file-tree">
      {/* Explorer Top Header */}
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-border px-3 bg-muted/10">
        <div className="flex items-center gap-1.5">
          <Files className="size-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Files
          </span>
        </div>
        <Badge variant="secondary" className="text-[10px] font-mono px-1.5 py-0 h-5">
          {files.length}
        </Badge>
      </div>

      {/* Filter / Search Bar */}
      <div className="p-2 border-b border-border/50">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3 text-muted-foreground pointer-events-none" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search files..."
            className="h-7 text-xs pl-7 pr-7 bg-muted/20 border-border/60 focus-visible:ring-1"
            data-testid="file-search-input"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground p-0.5"
              title="Clear search"
            >
              <X className="size-3" />
            </button>
          )}
        </div>
      </div>

      {/* Tree Content Area */}
      <div className="flex-1 overflow-y-auto p-1.5 space-y-0.5" data-testid="file-tree-content">
        {isLoading ? (
          <div className="p-4 space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className="h-4 bg-muted/30 rounded animate-pulse"
                style={{ width: `${60 + (i % 3) * 15}%`, marginLeft: `${(i % 3) * 12}px` }}
              />
            ))}
          </div>
        ) : filteredNodes.length === 0 ? (
          <div className="p-6 text-center text-xs text-muted-foreground">
            {searchQuery ? "No matching files found." : "No files available."}
          </div>
        ) : (
          filteredNodes.map((node) => (
            <TreeNodeItem
              key={node.id}
              node={node}
              depth={0}
              expandedFolders={expandedFolders}
              onToggleFolder={handleToggleFolder}
              selectedFilePath={selectedFilePath}
              onSelectFile={handleSelect}
              isSearching={isSearching}
            />
          ))
        )}
      </div>
    </div>
  );
}
