/**
 * Lazy-loadable Markdown renderer. Lives in its own chunk so the entry
 * bundle never has to ship react-markdown + remark-gfm + rehype-sanitize
 * for routes that don't render markdown (settings, alerts, etc.).
 *
 * Mobile-safe: tables / fenced code wrap in horizontal-scroll containers,
 * long paragraphs / inline code / URLs break instead of overflowing.
 *
 * Usage:
 *
 *     <Suspense fallback={<Skeleton …/>}>
 *       <MarkdownBody>{md}</MarkdownBody>
 *     </Suspense>
 */
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeSanitize, { defaultSchema } from "rehype-sanitize"
import { cn } from "@/lib/utils"

const MD_SANITIZE_SCHEMA = {
  ...defaultSchema,
  attributes: {
    ...(defaultSchema.attributes ?? {}),
    code: [...(defaultSchema.attributes?.code ?? []), "className"],
    span: [...(defaultSchema.attributes?.span ?? []), "className"],
    div: [...(defaultSchema.attributes?.div ?? []), "className"],
    a: [...(defaultSchema.attributes?.a ?? []), "target", "rel"],
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
    <div className={cn("mdx-body", className)}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeSanitize, MD_SANITIZE_SCHEMA]]}
        components={{
          pre: ({ node: _node, children, ...props }) => (
            <div className="overflow-x-auto rounded border border-border/40 my-3">
              <pre {...props} className="!my-0 !rounded-none">{children}</pre>
            </div>
          ),
          table: ({ node: _node, children, ...props }) => (
            <div className="overflow-x-auto my-3">
              <table {...props}>{children}</table>
            </div>
          ),
          a: ({ node: _node, children, href, ...props }) => (
            <a
              {...props}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="break-all"
            >
              {children}
            </a>
          ),
        }}
      >
        {children}
      </Markdown>
    </div>
  )
}
