import * as React from "react"
import { cn } from "~/lib/utils"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex min-h-[80px] w-full bg-zinc-950 px-4 py-3 text-sm ring-offset-black placeholder:text-zinc-500 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white disabled:cursor-not-allowed disabled:opacity-50 border-l border-white/20 resize-none",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
