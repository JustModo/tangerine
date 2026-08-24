import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "~/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center justify-center border px-2.5 py-1 text-[10px] font-black uppercase tracking-widest w-fit whitespace-nowrap shrink-0 transition-colors",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-white text-black",
        secondary:
          "border-zinc-800 bg-transparent text-white",
        destructive:
          "border-transparent bg-red-600 text-white",
        outline:
          "border-white/20 text-white",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant,
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "span"

  return (
    <Comp
      data-slot="badge"
      className={cn(badgeVariants({ variant }), "rounded-none", className)}
      {...props}
    />
  )
}

export { Badge }
