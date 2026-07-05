"use client"

import { Moon, Sun } from "lucide-react"
import { useTheme } from "next-themes"

import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

export function ThemeToggle() {
  // The resolved theme is unknown during SSR, so nothing rendered may depend on it.
  const { resolvedTheme, setTheme } = useTheme()
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            aria-label="Toggle light and dark appearance"
            onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
          />
        }
      >
        <Sun className="size-[18px] dark:hidden" strokeWidth={1.75} aria-hidden />
        <Moon className="hidden size-[18px] dark:block" strokeWidth={1.75} aria-hidden />
      </TooltipTrigger>
      <TooltipContent>Appearance</TooltipContent>
    </Tooltip>
  )
}
