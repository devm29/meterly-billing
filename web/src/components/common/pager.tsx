import { ChevronLeft, ChevronRight } from "lucide-react"

import { Button } from "@/components/ui/button"

export function Pager({
  offset,
  limit,
  total,
  onChange,
}: {
  offset: number
  limit: number
  total: number
  onChange: (offset: number) => void
}) {
  if (total <= limit) return null
  const end = Math.min(offset + limit, total)
  return (
    <nav
      aria-label="Pagination"
      className="flex items-center justify-between px-5 py-3 text-[13px] text-muted-foreground"
    >
      <span className="tabular-nums">
        {offset + 1}–{end} of {total}
      </span>
      <div className="flex gap-1">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Previous page"
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          <ChevronLeft className="size-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Next page"
          disabled={end >= total}
          onClick={() => onChange(offset + limit)}
        >
          <ChevronRight className="size-4" />
        </Button>
      </div>
    </nav>
  )
}
