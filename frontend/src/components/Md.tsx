import { Fragment, type ReactNode } from "react";

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : <Fragment key={i}>{part}</Fragment>,
  );
}

/** Minimal markdown for model-written briefings: headings, bullets, bold, paragraphs. */
export function Md({ text }: { text: string }) {
  const out: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) {
      out.push(
        <ul key={`u${out.length}`}>
          {list.map((l, i) => (
            <li key={i}>{inline(l)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    if (/^\s*[-*•]\s+/.test(line)) {
      list.push(line.replace(/^\s*[-*•]\s+/, ""));
      continue;
    }
    flush();
    if (!line.trim()) continue;
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) out.push(h[1].length <= 2 ? <h2 key={out.length}>{inline(h[2])}</h2> : <h3 key={out.length}>{inline(h[2])}</h3>);
    else out.push(<p key={out.length}>{inline(line)}</p>);
  }
  flush();
  return <div className="md">{out}</div>;
}
