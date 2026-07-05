"use client"

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T
  onChange: (value: T) => void
  options: readonly { value: T; label: string }[]
  label: string
}) {
  return (
    <Tabs
      value={value}
      onValueChange={(next) => {
        const option = options.find((o) => o.value === next)
        if (option) onChange(option.value)
      }}
    >
      <TabsList aria-label={label} className="h-8 rounded-lg bg-secondary p-0.5 dark:bg-muted">
        {options.map((option) => (
          <TabsTrigger
            key={option.value}
            value={option.value}
            className="rounded-md px-3 text-[13px] data-active:shadow-sm"
          >
            {option.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  )
}
