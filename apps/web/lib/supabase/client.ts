import { createBrowserClient } from "@supabase/ssr";

import { supabaseKey, supabaseUrl } from "@/lib/env";

/** Supabase client for Client Components. */
export function createClient() {
  return createBrowserClient(supabaseUrl(), supabaseKey());
}
