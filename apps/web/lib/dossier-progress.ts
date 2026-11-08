/** How many of the four steps (draft, manager, treasurer, sealed) are finished for a status. */
export function stepsDone(status: string): number {
  return { draft: 0, submitted: 2, approved: 3, sealed: 4, revoked: 4 }[status] ?? 0;
}
