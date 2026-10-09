import type { Metadata } from "next";
import { KnowledgeManager } from "@/components/knowledge-manager";
import { knowledgeApi } from "@/lib/api/knowledge";
import type { EngineeringKnowledge } from "@/lib/api/types";

export const metadata: Metadata = {
  title: "Engineering Knowledge",
};

async function getInitialKnowledge(): Promise<EngineeringKnowledge[] | undefined> {
  try {
    return await knowledgeApi.list();
  } catch {
    return undefined;
  }
}

export default async function KnowledgePage() {
  const initialScopes = await getInitialKnowledge();

  return (
    <div className="flex-1 overflow-auto bg-background/50">
      <KnowledgeManager initialScopes={initialScopes} />
    </div>
  );
}
