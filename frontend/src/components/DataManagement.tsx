import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchChunks, fetchGraph, fetchOverview } from "../api";
import type { DataOverview, GraphData, VectorChunk } from "../types";

const PAGE = 50;

function Status({ ok, error }: { ok: boolean; error: string | null }) {
  return ok ? <span className="status ok">connected</span> : <span className="status bad" title={error ?? ""}>unavailable</span>;
}

function VectorSection({ overview }: { overview: DataOverview["vector"] }) {
  const [source, setSource] = useState<string | null>(null);
  const [items, setItems] = useState<VectorChunk[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (src: string | null, offset: number) => {
    try {
      const page = await fetchChunks(src, PAGE, offset);
      setTotal(page.total);
      setItems((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    if (overview.available) load(source, 0);
  }, [source, overview, load]);

  return (
    <section className="card">
      <h2>
        Vector data · Milvus <Status ok={overview.available} error={overview.error} />
      </h2>
      {!overview.available && <p className="error-text">{overview.error}</p>}
      {overview.available && (
        <>
          <p className="muted">
            Collection <code>{overview.collection}</code> · {overview.total_chunks} chunks · {overview.sources.length} sources
          </p>
          <div className="chips">
            <button className={source === null ? "chip on" : "chip"} onClick={() => setSource(null)}>
              All
            </button>
            {overview.sources.map((s) => (
              <button key={s.source} className={source === s.source ? "chip on" : "chip"} onClick={() => setSource(s.source)}>
                {s.source} <small>{s.chunks}</small>
              </button>
            ))}
          </div>
          {error && <p className="error-text">{error}</p>}
          {overview.total_chunks === 0 && <p className="muted">No chunks yet. Run <code>uv run python -m utils.upload all</code>.</p>}
          <div className="tablewrap">
            <table>
              <thead>
                <tr><th>Source</th><th>#</th><th>Heading</th><th>Text</th></tr>
              </thead>
              <tbody>
                {items.map((c) => (
                  <tr key={c.id}>
                    <td>{c.source}</td>
                    <td>{c.chunk_index}</td>
                    <td>{c.heading}</td>
                    <td className="wrap">{c.text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {items.length < total && (
            <button className="more" onClick={() => load(source, items.length)}>
              Load more ({items.length} of {total})
            </button>
          )}
        </>
      )}
    </section>
  );
}

function GraphSection({ overview }: { overview: DataOverview["graph"] }) {
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [label, setLabel] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!overview.available) return;
    fetchGraph().then((g) => { setGraph(g); setError(null); }).catch((e: Error) => setError(e.message));
  }, [overview]);

  const labels = Object.keys(overview.node_counts);
  const active = label || labels[0] || "";
  const names = useMemo(() => new Map(graph?.nodes.map((n) => [n.id, n.name])), [graph]);
  const nodes = graph?.nodes.filter((n) => n.label === active) ?? [];
  const columns = [...new Set(nodes.flatMap((n) => Object.keys(n.props)))];

  return (
    <section className="card">
      <h2>
        Graph data · Neo4j <Status ok={overview.available} error={overview.error} />
      </h2>
      {!overview.available && <p className="error-text">{overview.error}</p>}
      {overview.available && (
        <>
          <p className="muted">
            {Object.values(overview.node_counts).reduce((a, b) => a + b, 0)} nodes ·{" "}
            {Object.values(overview.relationship_counts).reduce((a, b) => a + b, 0)} relationships
          </p>
          {error && <p className="error-text">{error}</p>}
          <div className="chips">
            {labels.map((l) => (
              <button key={l} className={l === active ? "chip on" : "chip"} onClick={() => setLabel(l)}>
                {l} <small>{overview.node_counts[l]}</small>
              </button>
            ))}
          </div>
          <div className="tablewrap">
            <table>
              <thead>
                <tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr>
              </thead>
              <tbody>
                {nodes.map((n) => (
                  <tr key={n.id}>{columns.map((c) => <td key={c} className="wrap">{String(n.props[c] ?? "")}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3>Relationships</h3>
          <p className="muted">
            {Object.entries(overview.relationship_counts).map(([t, n]) => `${t} ${n}`).join(" · ")}
          </p>
          <div className="tablewrap tall">
            <table>
              <thead>
                <tr><th>From</th><th>Type</th><th>To</th><th>Role</th></tr>
              </thead>
              <tbody>
                {graph?.edges.map((e, i) => (
                  <tr key={i}>
                    <td>{names.get(e.source) ?? e.source}</td>
                    <td><code>{e.type}</code></td>
                    <td>{names.get(e.target) ?? e.target}</td>
                    <td>{e.role}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

export default function DataManagement() {
  const [overview, setOverview] = useState<DataOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setError(null);
    fetchOverview().then(setOverview).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <div className="data">
      <div className="data-head">
        <div>
          <h2 className="page-title">Data Management</h2>
          <p className="muted">Everything currently stored in Milvus and Neo4j.</p>
        </div>
        <button className="more" onClick={refresh}>Refresh</button>
      </div>
      {error && <p className="error-text">Could not reach the API: {error}</p>}
      {!overview && !error && <p className="muted">Loading…</p>}
      {overview && (
        <>
          <VectorSection overview={overview.vector} />
          <GraphSection overview={overview.graph} />
        </>
      )}
    </div>
  );
}
