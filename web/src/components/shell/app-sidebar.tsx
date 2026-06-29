"use client"

import { Calculator, FileText, Gauge, LayoutGrid, Layers, Users } from "lucide-react"
import Link from "next/link"
import { usePathname } from "next/navigation"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"

const sections = [
  {
    label: "Revenue",
    items: [
      { href: "/", label: "Overview", icon: LayoutGrid },
      { href: "/invoices", label: "Invoices", icon: FileText },
    ],
  },
  {
    label: "Customers",
    items: [
      { href: "/customers", label: "Customers", icon: Users },
      { href: "/usage", label: "Usage", icon: Gauge },
    ],
  },
  {
    label: "Pricing",
    items: [
      { href: "/plans", label: "Plans", icon: Layers },
      { href: "/simulator", label: "Simulator", icon: Calculator },
    ],
  },
] as const

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href)
}

export function AppSidebar() {
  const pathname = usePathname()
  return (
    <Sidebar className="material border-r border-border/60 bg-sidebar/80 backdrop-blur-2xl backdrop-saturate-150">
      <SidebarHeader className="px-4 pt-5 pb-3">
        <Link
          href="/"
          className="flex items-center gap-2.5 rounded-md outline-none focus-visible:ring-4 focus-visible:ring-ring"
        >
          <span className="grid size-7 place-items-center rounded-lg bg-primary text-primary-foreground shadow-sm">
            <Gauge className="size-4" strokeWidth={2} aria-hidden />
          </span>
          <span className="text-[15px] font-semibold tracking-tight">Meterly</span>
        </Link>
      </SidebarHeader>
      <SidebarContent className="px-1">
        {sections.map((section) => (
          <SidebarGroup key={section.label}>
            <SidebarGroupLabel className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
              {section.label}
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {section.items.map((item) => (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton
                      isActive={isActive(pathname, item.href)}
                      tooltip={item.label}
                      className="h-8 rounded-md px-2 text-[13px] data-active:bg-sidebar-accent data-active:font-medium"
                      render={<Link href={item.href} />}
                    >
                      <item.icon className="size-4" strokeWidth={1.75} aria-hidden />
                      <span>{item.label}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter className="px-4 pb-4 text-xs text-muted-foreground">Meterly Cloud</SidebarFooter>
    </Sidebar>
  )
}
