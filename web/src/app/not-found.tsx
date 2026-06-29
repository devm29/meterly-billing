import { Compass } from "lucide-react"
import Link from "next/link"

import { EmptyState } from "@/components/common/states"
import { Button } from "@/components/ui/button"

export default function NotFound() {
  return (
    <div className="grid min-h-dvh place-items-center">
      <EmptyState
        icon={Compass}
        title="This page doesn’t exist"
        description="The link may be out of date, or the record was never created."
        action={
          <Button nativeButton={false} render={<Link href="/" />}>
            Back to overview
          </Button>
        }
      />
    </div>
  )
}
