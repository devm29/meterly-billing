import type { ReactNode } from "react"

import { Toolbar } from "@/components/shell/toolbar"

export function Page({
  title,
  subtitle,
  toolbarTitle,
  actions,
  children,
}: {
  title: ReactNode
  subtitle?: ReactNode
  toolbarTitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <>
      <Toolbar title={toolbarTitle ?? title} />
      <div className="mx-auto w-full max-w-[1280px] px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-[34px] leading-[41px] font-bold tracking-tight">{title}</h1>
            {subtitle ? <p className="mt-1 text-[15px] text-muted-foreground">{subtitle}</p> : null}
          </div>
          {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
        </div>
        {children}
      </div>
    </>
  )
}
