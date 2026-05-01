/**
 * Lazy-loadable Markdown renderer. Lives in its own chunk so the entry
 * bundle never has to ship react-markdown + remark-gfm + rehype-sanitize
 * for routes that don't render markdown (settings, alerts, etc.).
 *
 * Usage:
 *
 *     <Suspense fallback={<Skeleton …/>}>
 *       <MarkdownBody>{md}</MarkdownBody>
 *     </Suspense>
 *
 * Tables + fenced code are explicitly allowed; raw HTML is stripped.
 */
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeSanitize, { defaultSchema } from "rehype-sanitize"

const MD_SANITIZE_SCHEMA = {
  ...defaultSchema,
  attributes: {
    ...(defaultSchema.attributes ?? {}),
    code: [...(defaultSchema.attributes?.code ?? []), "className"],
    span: [...(defaultSchema.attributes?.span ?? []), "className"],
    div: [...(defaultSchema.attributes?.div ?? []), "className"],
  },
  tagNames: [
    ...(defaultSchema.tagNames ?? []),
    "table", "thead", "tbody", "tr", "th", "td",
    "code", "pre",
  ],
}

interface MarkdownBodyProps {
  children: string
  className?: string
}

export default function MarkdownBody({ children, className }: MarkdownBodyProps) {
  return (
    <div className={className}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeSanitize, MD_SANITIZE_SCHEMA]]}
      >
        {children}
      </Markdown>
    </div>
  )
}
