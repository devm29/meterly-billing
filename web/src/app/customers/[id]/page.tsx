import type { Metadata } from "next"

import { CustomerView } from "@/components/customers/customer-view"
import { Toolbar } from "@/components/shell/toolbar"

export const metadata: Metadata = { title: "Customer" }

export default async function CustomerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return (
    <>
      <Toolbar title="Customers" />
      <div className="mx-auto w-full max-w-[1280px] px-4 py-8 sm:px-6 lg:px-8">
        <CustomerView id={decodeURIComponent(id)} />
      </div>
    </>
  )
}
