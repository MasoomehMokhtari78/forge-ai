"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { FolderGit2, Settings, LayoutDashboard } from "lucide-react";
import { cn } from "cn";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarSeparator,
} from "@/components/ui/sidebar";
import type { Repository } from "@/lib/api/types";

interface AppSidebarProps {
  repositories: Repository[];
}

const mainNav = [
  {
    href: "/repositories",
    label: "Repositories",
    icon: LayoutDashboard,
  },
];

function StatusDot({ status }: { status: Repository["status"] }) {
  return (
    <span
      className={cn("size-1.5 shrink-0 rounded-full", {
        "bg-status-success": status === "completed",
        "bg-status-error": status === "failed",
        "bg-status-warning": status === "pending",
        "bg-status-processing animate-pulse": status === "processing",
      })}
    />
  );
}

export function AppSidebar({ repositories }: AppSidebarProps) {
  const pathname = usePathname();

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-2.5 px-2 py-1.5">
          <div className="flex size-6 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <FolderGit2 className="size-3.5" />
          </div>
          <span className="text-sm font-semibold tracking-tight text-sidebar-foreground group-data-[collapsible=icon]:hidden">
            ForgeAI
          </span>
        </div>
      </SidebarHeader>

      <SidebarSeparator />

      <SidebarContent>
        {/* Main Navigation */}
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {mainNav.map((item) => {
                const isActive = pathname.startsWith(item.href);
                return (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton
                      isActive={isActive}
                      tooltip={item.label}
                      render={<Link href={item.href} />}
                    >
                      <item.icon />
                      <span>{item.label}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarSeparator />

        {/* Repository List */}
        <SidebarGroup>
          <SidebarGroupLabel>Repositories</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {repositories.length === 0 && (
                <p className="px-2 py-1 text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
                  No repositories yet.
                </p>
              )}
              {repositories.map((repo) => {
                const isActive = pathname === `/repositories/${repo.id}`;
                const shortName = repo.name.split("/")[1] ?? repo.name;
                return (
                  <SidebarMenuItem key={repo.id}>
                    <SidebarMenuButton
                      isActive={isActive}
                      tooltip={repo.name}
                      render={<Link href={`/repositories/${repo.id}`} />}
                    >
                      <StatusDot status={repo.status} />
                      <span className="truncate">{shortName}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarSeparator />

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton tooltip="Settings" render={<Link href="/settings" />}>
              <Settings />
              <span>Settings</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
