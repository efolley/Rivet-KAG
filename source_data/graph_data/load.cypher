// Alternative to `make ingest`: loads the sample graph with cypher-shell.
// Copy the CSVs into Neo4j's import folder first (brew: /opt/homebrew/var/neo4j/import), then run:
//   cypher-shell -u neo4j -p <password> -f load.cypher

CREATE CONSTRAINT employee_id IF NOT EXISTS FOR (n:Employee) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT team_id IF NOT EXISTS FOR (n:Team) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT project_id IF NOT EXISTS FOR (n:Project) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT tool_id IF NOT EXISTS FOR (n:Tool) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT document_id IF NOT EXISTS FOR (n:Document) REQUIRE n.id IS UNIQUE;

LOAD CSV WITH HEADERS FROM 'file:///employees.csv' AS r
MERGE (n:Employee {id: r.id}) SET n.name = r.name, n.title = r.title, n.location = r.location, n.hired = date(r.hired);

LOAD CSV WITH HEADERS FROM 'file:///teams.csv' AS r
MERGE (n:Team {id: r.id}) SET n.name = r.name, n.focus = r.focus;

LOAD CSV WITH HEADERS FROM 'file:///projects.csv' AS r
MERGE (n:Project {id: r.id}) SET n.name = r.name, n.description = r.description, n.status = r.status, n.started = date(r.started);

LOAD CSV WITH HEADERS FROM 'file:///tools.csv' AS r
MERGE (n:Tool {id: r.id}) SET n.name = r.name, n.category = r.category;

LOAD CSV WITH HEADERS FROM 'file:///documents.csv' AS r
MERGE (n:Document {id: r.id}) SET n.filename = r.filename, n.title = r.title;

// Relationship types cannot be parameterised in Cypher, so one statement per type.
LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS r WITH r WHERE r.type = 'MEMBER_OF'
MATCH (a:Employee {id: r.start_id}), (b:Team {id: r.end_id}) MERGE (a)-[:MEMBER_OF]->(b);

LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS r WITH r WHERE r.type = 'LEADS'
MATCH (a:Employee {id: r.start_id}), (b:Team {id: r.end_id}) MERGE (a)-[:LEADS]->(b);

LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS r WITH r WHERE r.type = 'REPORTS_TO'
MATCH (a:Employee {id: r.start_id}), (b:Employee {id: r.end_id}) MERGE (a)-[:REPORTS_TO]->(b);

LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS r WITH r WHERE r.type = 'OWNS'
MATCH (a:Team {id: r.start_id}), (b:Project {id: r.end_id}) MERGE (a)-[:OWNS]->(b);

LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS r WITH r WHERE r.type = 'WORKS_ON'
MATCH (a:Employee {id: r.start_id}), (b:Project {id: r.end_id}) MERGE (a)-[w:WORKS_ON]->(b) SET w.role = r.role;

LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS r WITH r WHERE r.type = 'USES'
MATCH (a:Project {id: r.start_id}), (b:Tool {id: r.end_id}) MERGE (a)-[:USES]->(b);

LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS r WITH r WHERE r.type = 'OWNS_DOC'
MATCH (a:Team {id: r.start_id}), (b:Document {id: r.end_id}) MERGE (a)-[:OWNS_DOC]->(b);

LOAD CSV WITH HEADERS FROM 'file:///relationships.csv' AS r WITH r WHERE r.type = 'DESCRIBES'
MATCH (a:Document {id: r.start_id}), (b {id: r.end_id}) WHERE b:Project OR b:Tool MERGE (a)-[:DESCRIBES]->(b);
