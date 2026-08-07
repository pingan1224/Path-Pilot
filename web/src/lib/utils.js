import { clsx } from "clsx"
import { twMerge } from "tailwind-merge"

// Written by hand, not by the CLI. `npx shadcn add --yes` in plain-JS mode generates
// components that all import `cn` from here, but scaffolds neither this file nor its three
// dependencies (clsx, tailwind-merge, class-variance-authority). If a future `shadcn add`
// produces components that fail to resolve, this is the first place to look.
export function cn(...inputs) {
  return twMerge(clsx(inputs))
}
