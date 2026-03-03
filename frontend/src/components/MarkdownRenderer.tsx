import Markdown from "react-markdown"

export function MarkdownRenderer({ content }: { content: string }) {
  return (
    <div className="prose prose-sm max-w-none">
      <Markdown>{content}</Markdown>
    </div>
  )
}
