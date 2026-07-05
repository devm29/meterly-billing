import { AlertTriangle, type LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      <Icon className="size-11 text-muted-foreground/70" strokeWidth={1.25} aria-hidden />
      <h3 className="mt-4 text-[17px] font-semibold">{title}</h3>
      <p className="mt-1 max-w-sm text-[13px] leading-[18px] text-muted-foreground">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  )
}

const DEV_HINT = process.env.NODE_ENV === "production" ? "" : " Check that the API is running on port 8107."

export function ErrorState({ error, retry }: { error: Error; retry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center px-6 py-16 text-center">
      <AlertTriangle className="size-10 text-warning" strokeWidth={1.5} aria-hidden />
      <h3 className="mt-4 text-[17px] font-semibold">We couldn’t load this</h3>
      <p className="mt-1 max-w-sm text-[13px] text-muted-foreground">
        {error.message}.{DEV_HINT}
      </p>
      {retry ? (
        <button
          type="button"
          onClick={retry}
          className="mt-4 text-[14px] font-medium text-primary hover:underline focus-visible:underline focus-visible:outline-none"
        >
          Try again
        </button>
      ) : null}
    </div>
  )
}

export function InlineError({ error, retry }: { error: Error; retry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex min-h-24 flex-col items-center justify-center gap-1 px-5 py-6 text-center text-[13px]"
    >
      <span className="inline-flex items-center gap-1.5 font-medium">
        <AlertTriangle className="size-4 text-warning" strokeWidth={1.75} aria-hidden />
        Couldn’t load this section
      </span>
      <span className="text-muted-foreground">{error.message}</span>
      {retry ? (
        <button
          type="button"
          onClick={retry}
          className="mt-1 font-medium text-primary hover:underline focus-visible:underline focus-visible:outline-none"
        >
          Try again
        </button>
      ) : null}
    </div>
  )
}
