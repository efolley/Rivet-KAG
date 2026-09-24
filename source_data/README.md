# source_data

Sample data for Rivet KAG: a synthetic company, "Northwind Analytics". Nothing here is real.

| Folder | Goes to | Contents |
|---|---|---|
| `vector_data/` | Milvus (vector search) | 6 Markdown documents (onboarding, VPN and access, expenses, incident response, data platform, ML release) and `support_faq.csv` (10 rows). Split into chunks: one per `##` section, one per CSV row. |
| `graph_data/` | Neo4j (graph) | CSVs for employees, teams, projects, tools and documents, plus `relationships.csv`. `load.cypher` is an alternative loader for `cypher-shell`. |

The two sets are linked: every vector file is also a `Document` node in the graph, owned by a team and connected to the projects and tools it describes. That allows questions that need both stores, such as "What does the VPN policy say, and who owns it?"

## Load it

```bash
make ingest    # or: uv run python -m utils.upload all
```

## Explore it

Open `index.html` in a browser for an overview, the chunked documents and an interactive graph. It is generated from the files above; after editing any data, rebuild it with:

```bash
uv run python source_data/build_viewer.py
```

To see what is actually stored in the databases, use the Data Management tab in the app.
