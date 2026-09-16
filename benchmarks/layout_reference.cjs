// Optional reference geometry, independent of Termaid's runtime dependencies.
// node benchmarks/layout_reference.cjs DAGRE_BUNDLE ELK_BUNDLE graphs.json references.json
const fs = require('node:fs');
const path = require('node:path');
const dagre = require(path.resolve(process.argv[2]));
const ELK = require(path.resolve(process.argv[3]));
const elk = new ELK();
const samples = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));

async function compare() {
  const results = [];
  for (const sample of samples) {
    // Compound layout is not comparable after flattening group membership.
    if (sample.compound) continue;
    const graph = new dagre.graphlib.Graph({ multigraph: true });
    graph.setGraph({ rankdir: 'TB', ranker: 'network-simplex' });
    graph.setDefaultEdgeLabel(() => ({}));
    for (const node of sample.nodes) graph.setNode(node.id, { width: 120, height: 50 });
    for (const [index, edge] of sample.edges.entries()) {
      graph.setEdge(edge.source, edge.target, { minlen: edge.min_length }, String(index));
    }
    dagre.layout(graph);
    const elkGraph = await elk.layout({
      id: 'root', layoutOptions: { 'elk.algorithm': 'layered', 'elk.direction': 'DOWN' },
      children: sample.nodes.map(node => ({ id: node.id, width: 120, height: 50 })),
      edges: sample.edges.map((edge, index) => ({ id: String(index), sources: [edge.source], targets: [edge.target] })),
    });
    results.push({
      sample: sample.name, dagre_version: dagre.version,
      note: 'Uniform abstract boxes; compare topology and alignment, not browser pixels or terminal cell dimensions. ELK uses unit edge lengths.',
      dagre: graph.nodes().map(id => ({ id, x: graph.node(id).x, y: graph.node(id).y })),
      elk: elkGraph.children.map(node => ({ id: node.id, x: node.x + 60, y: node.y + 25 })),
    });
  }
  fs.writeFileSync(process.argv[5], JSON.stringify(results, null, 2) + '\n');
}
compare().catch(error => { console.error(error); process.exitCode = 1; });
