import { redirect } from "next/navigation";

// Root page redirects to the repository dashboard
export default function RootPage() {
  redirect("/repositories");
}
