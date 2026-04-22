import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center justify-center rounded px-2 py-0.5 text-xs font-sans font-semibold",
  {
    variants: {
      variant: {
        default: "bg-indigo-500/15 text-indigo-600 dark:text-indigo-400",
        secondary: "bg-slate-500/15 text-slate-600 dark:text-slate-300",
        destructive: "bg-rose-500/15 text-rose-600 dark:text-rose-400",
        outline:
          "border border-slate-200 text-slate-600 dark:border-slate-700 dark:text-slate-300",
        ghost: "bg-transparent text-slate-600 dark:text-slate-300",
        link: "bg-transparent text-indigo-600 underline-offset-4 hover:underline dark:text-indigo-400",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

function Badge({
  className,
  variant,
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span";

  return (
    <Comp
      data-slot="badge"
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  );
}

export { Badge, badgeVariants };
