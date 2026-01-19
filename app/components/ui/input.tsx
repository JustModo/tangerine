import * as React from "react"
import { cn } from "~/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "flex h-10 w-full bg-zinc-950 px-4 py-2 text-sm ring-offset-black file:border-0 file:bg-transparent file:text-sm file:font-bold file:uppercase placeholder:text-zinc-500 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white disabled:cursor-not-allowed disabled:opacity-50 border-l border-white/20",
        className
      )}
      {...props}
    />
  )
}

export { Input }
