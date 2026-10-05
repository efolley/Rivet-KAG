import type { Citation } from "../types";

export default function Citations({ items }: { items: Citation[] }) {
  if (!items.length) return null;
  return (
    <div className="context-items">
      {items.map((c, i) => (
        <div key={c.id} className="context-item">
          <p className="context-content">{c.snippet}</p>
          <p className="context-meta">
            [{i + 1}] <span className={`badge ${c.source_type}`}>{c.source_type === "vector" ? "Vector" : "Graph"}</span>
            {c.title}
            {c.score != null && <> · score {c.score.toFixed(2)}</>}
            {" · "}
            {c.id}
          </p>
        </div>
      ))}
    </div>
  );
}
