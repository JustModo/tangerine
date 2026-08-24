import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkBreaks from "remark-breaks";
import rehypeKatex from "rehype-katex";
import { cn } from "~/lib/utils";

// Single place every LLM-authored markdown surface renders through - chat replies, problem
// statements, example explanations and lesson notes - so math and line-break behaviour can
// never drift between them.
//   remark-math + rehype-katex: $inline$ and $$display$$ math (problem statements lean on
//     this heavily for complexity and formulas).
//   remark-breaks: a single newline becomes a line break. LLM prose uses newlines as real
//     breaks, but plain markdown would silently join those lines into one paragraph.
const REMARK_PLUGINS = [remarkGfm, remarkMath, remarkBreaks];
const REHYPE_PLUGINS = [rehypeKatex];

// Wide content scrolls or wraps inside the message, never widening its column. `pre` already
// has overflow-x from typography; katex-display and tables ship none.
const CONTAIN_WIDE_CONTENT =
  "min-w-0 max-w-full break-words " +
  "prose-pre:max-w-full " +
  "[&_.katex-display]:overflow-x-auto [&_.katex-display]:overflow-y-hidden " +
  "prose-table:block prose-table:overflow-x-auto prose-table:max-w-full";

export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("prose dark:prose-invert prose-sm max-w-none", CONTAIN_WIDE_CONTENT, className)}>
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS} rehypePlugins={REHYPE_PLUGINS}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
