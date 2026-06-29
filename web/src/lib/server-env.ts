import { z } from "zod"

const DEV_ADMIN_KEY = "mtr_admin_dev_only"

const schema = z
  .object({
    NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
    METERLY_API_URL: z.url().default("http://localhost:8107"),
    METERLY_ADMIN_API_KEY: z.string().min(1).optional(),
  })
  .transform(({ NODE_ENV, METERLY_API_URL, METERLY_ADMIN_API_KEY }) => ({
    apiUrl: METERLY_API_URL,
    // The dev key only matches a backend that also runs with its development defaults.
    adminKey: METERLY_ADMIN_API_KEY ?? (NODE_ENV === "production" ? null : DEV_ADMIN_KEY),
  }))

export type ServerEnv = z.infer<typeof schema>

export function serverEnv(): ServerEnv {
  return schema.parse({
    NODE_ENV: process.env.NODE_ENV,
    METERLY_API_URL: process.env.METERLY_API_URL,
    METERLY_ADMIN_API_KEY: process.env.METERLY_ADMIN_API_KEY,
  })
}
