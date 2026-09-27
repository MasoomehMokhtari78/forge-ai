import type { FileMetadata } from "./api/types";

export interface FileTreeFileNode {
  type: "file";
  id: string;
  name: string;
  path: string;
  size_bytes: number;
  extension: string;
}

export interface FileTreeFolderNode {
  type: "folder";
  id: string;
  name: string;
  path: string;
  children: FileTreeNode[];
}

export type FileTreeNode = FileTreeFileNode | FileTreeFolderNode;

/**
 * Builds a hierarchical tree from a flat list of FileMetadata.
 * Folders appear first, sorted alphabetically, followed by files sorted alphabetically.
 */
export function buildFileTree(files: FileMetadata[]): FileTreeNode[] {
  const rootNodes: FileTreeNode[] = [];
  const folderMap = new Map<string, FileTreeFolderNode>();

  // Ensure consistent sorting
  const sortedFiles = [...files].sort((a, b) => a.path.localeCompare(b.path));

  for (const file of sortedFiles) {
    const parts = file.path.split("/").filter(Boolean);
    if (parts.length === 0) continue;

    let currentPath = "";
    let parentFolder: FileTreeFolderNode | null = null;

    // Traverse or create folders for each segment except the last one
    for (let i = 0; i < parts.length - 1; i++) {
      const folderName = parts[i];
      currentPath = currentPath ? `${currentPath}/${folderName}` : folderName;

      let folder = folderMap.get(currentPath);
      if (!folder) {
        folder = {
          type: "folder",
          id: currentPath,
          name: folderName,
          path: currentPath,
          children: [],
        };
        folderMap.set(currentPath, folder);

        if (parentFolder) {
          parentFolder.children.push(folder);
        } else {
          rootNodes.push(folder);
        }
      }
      parentFolder = folder;
    }

    // Add the file node
    const fileName = parts[parts.length - 1];
    const fileNode: FileTreeFileNode = {
      type: "file",
      id: file.path,
      name: fileName,
      path: file.path,
      size_bytes: file.size_bytes,
      extension: file.extension,
    };

    if (parentFolder) {
      parentFolder.children.push(fileNode);
    } else {
      rootNodes.push(fileNode);
    }
  }

  // Recursively sort folders first, then files alphabetically
  function sortNodes(nodes: FileTreeNode[]): FileTreeNode[] {
    nodes.sort((a, b) => {
      if (a.type !== b.type) {
        return a.type === "folder" ? -1 : 1;
      }
      return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
    });

    for (const node of nodes) {
      if (node.type === "folder") {
        sortNodes(node.children);
      }
    }

    return nodes;
  }

  return sortNodes(rootNodes);
}

/**
 * Filter tree nodes matching a search query.
 * Retains ancestor folders if any descendant matches.
 */
export function filterFileTree(
  nodes: FileTreeNode[],
  query: string
): FileTreeNode[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return nodes;

  function filterNode(node: FileTreeNode): FileTreeNode | null {
    if (node.type === "file") {
      return node.name.toLowerCase().includes(normalized) ||
        node.path.toLowerCase().includes(normalized)
        ? node
        : null;
    }

    // For folders, check if any child matches
    const filteredChildren = node.children
      .map(filterNode)
      .filter((child): child is FileTreeNode => child !== null);

    if (filteredChildren.length > 0) {
      return {
        ...node,
        children: filteredChildren,
      };
    }

    // If folder itself matches query, include with all original children
    if (
      node.name.toLowerCase().includes(normalized) ||
      node.path.toLowerCase().includes(normalized)
    ) {
      return node;
    }

    return null;
  }

  return nodes
    .map(filterNode)
    .filter((node): node is FileTreeNode => node !== null);
}

/**
 * Format raw byte count into human-readable string.
 */
export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const val = bytes / Math.pow(1024, i);
  return `${val < 10 && i > 0 ? val.toFixed(1) : Math.round(val)} ${units[i]}`;
}
