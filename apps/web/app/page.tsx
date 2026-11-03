import { redirect } from "next/navigation";

// The middleware sends signed-in users from /login to /dashboard.
export default function Home() {
  redirect("/login");
}
