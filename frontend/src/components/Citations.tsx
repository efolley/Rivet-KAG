import type { Citation } from "../types";

export default function Citations({ items }: { items: Citation[] }) {
  if (!items.length) return null;
  return (
    <div className="citations">
      {items.map((c, i) => (
        <details key={c.id}>
          <summary>
            <span className={`badge ${c.source_type}`}>{c.source_type === "vector" ? "Vector" : "Graph"}</span>
            [{i + 1}] {c.title}
            {c.score != null && <em> · {c.score.toFixed(2)}</em>}
          </summary>
          <p>{c.snippet}</p>
        </details>
      ))}
    </div>
  );
}
