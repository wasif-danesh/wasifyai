import type { Me } from "@wasifyai/contracts";
import { apiGet } from "./api";

/** Who the API thinks the caller is; null when the API cannot be reached or says no. */
export async function getMe(): Promise<Me | null> {
  try {
    return await apiGet<Me>("/me");
  } catch {
    return null;
  }
}
