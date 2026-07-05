import type { ReactNode } from "react"

import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export function SectionCard({
  title,
  description,
  action,
  children,
  className,
  flush,
}: {
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
  flush?: boolean
}) {
  return (
    <Card className={cn(flush && "pb-0", className)}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description ? <CardDescription className="text-[13px]">{description}</CardDescription> : null}
        {action ? <CardAction>{action}</CardAction> : null}
      </CardHeader>
      <CardContent className={cn(flush && "px-0")}>{children}</CardContent>
    </Card>
  )
}
