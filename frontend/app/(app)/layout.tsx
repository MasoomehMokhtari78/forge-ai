import type { Metadata } from "next";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";
import { AppSidebar } from "@/components/app-sidebar";
import { AddRepositoryButton } from "@/components/add-repository-button";
import { repositoriesApi } from "@/lib/api/repositories";
import type { Repository } from "@/lib/api/types";

export const metadata: Metadata = {
  title: "ForgeAI",
};

async function getRepositories(): Promise<Repository[]> {
  try {
    return await repositoriesApi.list();
  } catch {
    // Return empty list if backend is unreachable — sidebar won't crash
    return [];
  }
}

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const repositories = await getRepositories();

  return (
    <SidebarProvider>
      <AppSidebar repositories={repositories} />
      <SidebarInset>
        {/* Topbar */}
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border bg-background/80 backdrop-blur-sm">
          <div className="flex flex-1 items-center gap-2 px-4">
            <SidebarTrigger className="-ml-1" />
            <Separator orientation="vertical" className="mr-1 h-4" />
            {/* Breadcrumb area — populated by individual pages via slots/portals in future */}
            <span className="text-sm text-muted-foreground select-none">
              ForgeAI
            </span>
          </div>
          <div className="flex items-center gap-2 px-4">
            <AddRepositoryButton />
            {/* Ollama status indicator */}
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className="size-1.5 rounded-full bg-status-success" />
              <span className="hidden sm:inline">Local</span>
            </div>
          </div>
        </header>

        {/* Main scrollable content */}
        <main className="flex flex-1 flex-col overflow-auto">
          {children}
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
