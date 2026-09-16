"""Layer assignment and ordering for the layout engine.

Assigns each node to a layer (depth from root) and orders nodes within
each layer to minimize edge crossings using a barycenter heuristic.
"""
from __future__ import annotations

from collections import deque

from ..graph.model import ArrowType, Edge, EdgeStyle, Graph, Subgraph


def expand_subgraph_edges(graph: Graph) -> list[Edge]:
    """Create virtual node-to-node edges for edges with subgraph endpoints.

    An edge like ``A --> B`` where A and B are subgraphs constrains every
    node of B to a layer below every node of A. Layer assignment only
    understands node-to-node edges, so expand each subgraph endpoint into
    its member nodes (recursively) and emit one virtual edge per pair.
    The virtual edges are used for layer assignment only and never drawn.
    """
    def _members(sg: Subgraph, result: set[str]) -> None:
        result.update(sg.node_ids)
        for child in sg.children:
            _members(child, result)

    virtual: list[Edge] = []
    for e in graph.edges:
        if not (e.source_is_subgraph or e.target_is_subgraph):
            continue
        sources: set[str] = set()
        targets: set[str] = set()
        for endpoint, is_sg, bucket in (
            (e.source, e.source_is_subgraph, sources),
            (e.target, e.target_is_subgraph, targets),
        ):
            if is_sg:
                sg = graph.find_subgraph_by_id(endpoint)
                if sg:
                    _members(sg, bucket)
            else:
                bucket.add(endpoint)
        if not sources or not targets or sources & targets:
            # Empty subgraph, self-edge, or nested endpoints: the
            # constraint is unsatisfiable, so skip it.
            continue
        for s in sources:
            for t in targets:
                virtual.append(Edge(source=s, target=t, min_length=e.min_length))
    return virtual


def _acyclic_layer_constraints(graph: Graph) -> set[tuple[str, str]] | None:
    """Keep every dependency in a DAG, including shortcuts from its roots.

    Bidirectional arrows use their declared source/target for ranking; the
    reverse arrowhead does not introduce a second layout dependency.
    Cyclic graphs retain the existing discovery-tree feedback policy.
    """
    # Compound graphs have their own membership and orthogonal-rank rules.
    # Keep their existing constraints until the compound pass resolves them.
    if graph.subgraphs:
        return None
    successors: dict[str, set[str]] = {node_id: set() for node_id in graph.node_order}
    incoming_count = {node_id: 0 for node_id in graph.node_order}
    constraints: set[tuple[str, str]] = set()
    for edge in graph.edges:
        if edge.source not in successors or edge.target not in successors:
            continue
        if edge.target not in successors[edge.source]:
            successors[edge.source].add(edge.target)
            incoming_count[edge.target] += 1
            constraints.add((edge.source, edge.target))
    ready = deque(node_id for node_id in graph.node_order if incoming_count[node_id] == 0)
    visited_count = 0
    while ready:
        source_id = ready.popleft()
        visited_count += 1
        for target_id in successors[source_id]:
            incoming_count[target_id] -= 1
            if incoming_count[target_id] == 0:
                ready.append(target_id)
    return constraints if visited_count == len(graph.node_order) else None


def _discovery_tree_constraints(graph: Graph) -> set[tuple[str, str]]:
    """Stable feedback policy for cyclic and compound graphs."""
    roots = graph.get_roots()
    visited = set(roots)
    queue = deque(roots)
    constraints: set[tuple[str, str]] = set()
    for component_root in [*roots, *graph.node_order]:
        if component_root not in visited:
            visited.add(component_root)
            queue.append(component_root)
        while queue:
            source_id = queue.popleft()
            for target_id in graph.get_children(source_id):
                if target_id not in visited:
                    visited.add(target_id)
                    constraints.add((source_id, target_id))
                    queue.append(target_id)
    return constraints


def assign_layers(graph: Graph) -> dict[str, int]:
    """Respect DAG dependencies; use bounded feedback ranks for other graphs.

    A root shortcut cannot pull a downstream DAG node above its other
    predecessors. Compound graphs keep their membership/orthogonal policy.
    """
    roots = graph.get_roots()
    layers = {root: 0 for root in roots}
    acyclic_constraints = _acyclic_layer_constraints(graph)
    layer_edges = (_discovery_tree_constraints(graph) if acyclic_constraints is None
                   else acyclic_constraints)

    # Build edge min_length lookup
    edge_min_lengths: dict[tuple[str, str], int] = {}
    for e in graph.edges:
        key = (e.source, e.target)
        edge_min_lengths[key] = max(edge_min_lengths.get(key, 1), e.min_length)

    # Assign layers using forward constraints (no back-edges).
    changed = True
    max_iter = len(graph.node_order) * 2
    iteration = 0
    while changed and iteration < max_iter:
        changed = False
        iteration += 1
        for src, tgt in layer_edges:
            if src in layers:
                ml = edge_min_lengths.get((src, tgt), 1)
                new_layer = layers[src] + ml
                if tgt not in layers or layers[tgt] < new_layer:
                    layers[tgt] = new_layer
                    changed = True

    # Assign unplaced nodes to layer 0
    for nid in graph.node_order:
        if nid not in layers:
            layers[nid] = 0

    # Collapse orthogonal subgraph nodes to the same layer
    ortho_sets = _get_orthogonal_sg_nodes(graph)
    if ortho_sets:
        for sg_nodes in ortho_sets:
            present = [nid for nid in sg_nodes if nid in layers]
            if not present:
                continue
            min_layer = min(layers[nid] for nid in present)
            for nid in present:
                layers[nid] = min_layer

        # Recompute layers for non-ortho nodes from scratch so downstream
        # nodes (like F) get pulled up to the correct layer after collapse.
        all_ortho = set()
        for s in ortho_sets:
            all_ortho.update(s)

        # Remove non-ortho nodes and recompute from roots
        for nid in graph.node_order:
            if nid not in all_ortho:
                layers.pop(nid, None)
        for root in graph.get_roots():
            if root not in layers:
                layers[root] = 0

        changed = True
        max_iter = len(graph.node_order) * 2
        iteration = 0
        while changed and iteration < max_iter:
            changed = False
            iteration += 1
            for src, tgt in layer_edges:
                if src in layers:
                    ml = edge_min_lengths.get((src, tgt), 1)
                    new_layer = layers[src] + ml
                    if tgt in all_ortho:
                        continue
                    if tgt not in layers or layers[tgt] < new_layer:
                        layers[tgt] = new_layer
                        changed = True

        for nid in graph.node_order:
            if nid not in layers:
                layers[nid] = 0

    return layers


def _assign_internal_layers(
    graph: Graph, members: set[str], edges: list[Edge],
) -> dict[str, int]:
    """Longest-path layers, with deterministic feedback edges for cycles.

    Process every node once. If only cycles remain, choose the first declared
    remaining node and treat subsequent incoming edges as return routes.
    Acyclic edges still retain their full longest-path and min-length constraints.
    """
    node_order = [node_id for node_id in graph.node_order if node_id in members]
    successors: dict[str, list[Edge]] = {node_id: [] for node_id in node_order}
    incoming_count = {node_id: 0 for node_id in node_order}
    for edge in edges:
        successors[edge.source].append(edge)
        incoming_count[edge.target] += 1
    ready = deque(node_id for node_id in node_order if incoming_count[node_id] == 0)
    remaining = set(node_order)
    internal_layers = {node_id: 0 for node_id in node_order}
    while remaining:
        if not ready:
            ready.append(next(node_id for node_id in node_order if node_id in remaining))
        source_id = ready.popleft()
        remaining.remove(source_id)
        for edge in successors[source_id]:
            if edge.target not in remaining:
                continue
            internal_layers[edge.target] = max(
                internal_layers[edge.target], internal_layers[source_id] + edge.min_length,
            )
            incoming_count[edge.target] -= 1
            if incoming_count[edge.target] == 0:
                ready.append(edge.target)
    return internal_layers


def separate_subgraph_layers(graph: Graph, layers: dict[str, int]) -> dict[str, int]:
    """Fix overlapping subgraph layer ranges.

    When cross-boundary edges cause nodes from different subgraphs to land
    on the same layer, the subgraph boxes overlap visually. This function
    detects the overlap and reassigns layers so each subgraph occupies a
    contiguous, non-overlapping range.

    Internal edges within each subgraph determine relative node positions.
    Cross-boundary edges determine the ordering between subgraphs.
    """
    if not graph.subgraphs:
        return layers

    # Build node -> innermost subgraph mapping
    node_sg: dict[str, str] = {}

    def _map_sg(subs: list[Subgraph]) -> None:
        for sg in subs:
            _map_sg(sg.children)
            for nid in sg.node_ids:
                node_sg[nid] = sg.id

    _map_sg(graph.subgraphs)

    # Compute layer range per subgraph
    sg_ranges: dict[str, tuple[int, int]] = {}
    for nid, layer in layers.items():
        sg_id = node_sg.get(nid)
        if sg_id is None:
            continue
        if sg_id not in sg_ranges:
            sg_ranges[sg_id] = (layer, layer)
        else:
            lo, hi = sg_ranges[sg_id]
            sg_ranges[sg_id] = (min(lo, layer), max(hi, layer))

    if len(sg_ranges) < 2:
        return layers

    # Check for overlapping ranges between different subgraphs
    sg_ids = list(sg_ranges.keys())
    has_overlap = False
    for i in range(len(sg_ids)):
        for j in range(i + 1, len(sg_ids)):
            r1 = sg_ranges[sg_ids[i]]
            r2 = sg_ranges[sg_ids[j]]
            if r1[0] <= r2[1] and r2[0] <= r1[1]:
                has_overlap = True
                break
        if has_overlap:
            break

    if not has_overlap:
        return layers

    # Build subgraph DAG from cross-boundary edges
    sg_succs: dict[str, set[str]] = {sid: set() for sid in sg_ids}
    sg_in_deg: dict[str, int] = {sid: 0 for sid in sg_ids}
    for e in graph.edges:
        s_sg = node_sg.get(e.source)
        t_sg = node_sg.get(e.target)
        if s_sg and t_sg and s_sg != t_sg and s_sg in sg_succs:
            if t_sg not in sg_succs[s_sg]:
                sg_succs[s_sg].add(t_sg)
                sg_in_deg[t_sg] += 1

    # Topological sort (Kahn's)
    queue_list = [sid for sid in sg_ids if sg_in_deg[sid] == 0]
    topo: list[str] = []
    while queue_list:
        node = queue_list.pop(0)
        topo.append(node)
        for succ in sg_succs[node]:
            sg_in_deg[succ] -= 1
            if sg_in_deg[succ] == 0:
                queue_list.append(succ)

    if len(topo) != len(sg_ids):
        return layers  # cycle in subgraph DAG, fall back

    # Compute internal layers per subgraph using only internal edges
    sg_internal: dict[str, dict[str, int]] = {}
    sg_sizes: dict[str, int] = {}
    for sg_id in topo:
        sg_nodes = {nid for nid, sid in node_sg.items() if sid == sg_id}
        int_edges = [e for e in graph.edges
                     if e.source in sg_nodes and e.target in sg_nodes
                     and not e.is_self_reference]

        # Relax each forward edge once; return edges cannot keep pushing
        # both endpoints of a restore/offload cycle into empty layers.
        int_layers = _assign_internal_layers(graph, sg_nodes, int_edges)

        sg_internal[sg_id] = int_layers
        sg_sizes[sg_id] = (max(int_layers.values()) + 1) if int_layers else 0

    # Compute absolute offsets by stacking subgraphs in topo order.
    non_sg_layers = [l for nid, l in layers.items() if nid not in node_sg]
    first_sg_min = sg_ranges[topo[0]][0] if topo else 0
    non_sg_above = [l for l in non_sg_layers if l < first_sg_min]
    offset = (max(non_sg_above) + 1) if non_sg_above else 0

    sg_offsets: dict[str, int] = {}
    for sg_id in topo:
        # Stacking groups must not pull a backend up onto its standalone
        # caller's layer. That would make the group's rectangular frame
        # enclose a node which is not a member of the subgraph.
        predecessor_floor = max((
            layers[edge.source] + edge.min_length
            for edge in graph.edges
            if node_sg.get(edge.target) == sg_id
            and edge.source not in node_sg and edge.source in layers
            and layers[edge.source] < layers[edge.target]
        ), default=0)
        offset = max(offset, predecessor_floor)
        sg_offsets[sg_id] = offset
        offset += sg_sizes[sg_id]

    # Build new layer assignment
    new_layers = dict(layers)
    for sg_id, int_layers in sg_internal.items():
        for nid, rel in int_layers.items():
            new_layers[nid] = sg_offsets[sg_id] + rel

    # Re-assign non-subgraph nodes: use longest-path from their predecessors
    non_sg = [nid for nid in graph.node_order if nid not in node_sg]
    if non_sg:
        for nid in non_sg:
            best = -1
            for e in graph.edges:
                if e.target == nid and e.source in new_layers:
                    best = max(best, new_layers[e.source])
            if best >= 0:
                new_layers[nid] = best + 1

    return new_layers


def _count_crossings(graph: Graph, layer_lists: list[list[str]]) -> int:
    """Count the total number of edge crossings between adjacent layers."""
    total = 0
    for layer_idx in range(1, len(layer_lists)):
        prev_pos = {nid: i for i, nid in enumerate(layer_lists[layer_idx - 1])}
        cur_pos = {nid: i for i, nid in enumerate(layer_lists[layer_idx])}
        # Collect edges between these two layers
        edges_between: list[tuple[int, int]] = []
        for edge in graph.edges:
            if edge.source in prev_pos and edge.target in cur_pos:
                edges_between.append((prev_pos[edge.source], cur_pos[edge.target]))
        # Count crossings: two edges (u1,v1) and (u2,v2) cross iff
        # u1 < u2 and v1 > v2 (or vice versa)
        for i in range(len(edges_between)):
            for j in range(i + 1, len(edges_between)):
                u1, v1 = edges_between[i]
                u2, v2 = edges_between[j]
                if (u1 - u2) * (v1 - v2) < 0:
                    total += 1
    return total


def _greedy_crossing_sweeps(graph: Graph, ordering: list[list[str]]) -> list[list[str]]:
    """Bounded two-sided adjacent swaps after barycenter ordering stalls.

    Like layered layout's greedy-switch phase, accept only strict crossing
    reductions. Preserve group membership and stable order for tied scores.
    """
    candidate_order = [list(layer) for layer in ordering]
    crossing_count = _count_crossings(graph, candidate_order)
    if crossing_count == 0:
        return candidate_order
    groups = {node_id: graph.find_subgraph_for_node(node_id) for layer in ordering for node_id in layer}
    for sweep in range(4):
        improved = False
        for layer in candidate_order[::1 if sweep % 2 == 0 else -1]:
            for position in range(len(layer) - 1):
                first, second = layer[position:position + 2]
                if groups[first] is not groups[second]:
                    continue
                layer[position], layer[position + 1] = second, first
                proposed_count = _count_crossings(graph, candidate_order)
                if proposed_count < crossing_count:
                    crossing_count = proposed_count
                    improved = True
                else:
                    layer[position], layer[position + 1] = first, second
        if not improved or crossing_count == 0:
            break
    return candidate_order


def order_layers(graph: Graph, layers: dict[str, int]) -> list[list[str]]:
    """Order nodes within each layer using barycenter heuristic."""
    # Group nodes by layer
    max_layer = max(layers.values()) if layers else 0
    layer_lists: list[list[str]] = [[] for _ in range(max_layer + 1)]
    for nid in graph.node_order:
        layer_lists[layers.get(nid, 0)].append(nid)

    # Barycenter ordering with improvement tracking
    best_crossings = _count_crossings(graph, layer_lists)
    best_ordering = [layer[:] for layer in layer_lists]
    no_improvement = 0

    for _pass in range(8):  # Max 8 passes
        for layer_idx in range(1, len(layer_lists)):
            prev_positions = {nid: i for i, nid in enumerate(layer_lists[layer_idx - 1])}
            barycenters: dict[str, float] = {}
            for nid in layer_lists[layer_idx]:
                # Find positions of predecessors in previous layer
                pred_positions: list[int] = []
                for edge in graph.edges:
                    if edge.target == nid and edge.source in prev_positions:
                        pred_positions.append(prev_positions[edge.source])
                if pred_positions:
                    barycenters[nid] = sum(pred_positions) / len(pred_positions)
                else:
                    barycenters[nid] = float(layer_lists[layer_idx].index(nid))

            layer_lists[layer_idx].sort(key=lambda n: barycenters.get(n, 0))

        crossings = _count_crossings(graph, layer_lists)
        if crossings < best_crossings:
            best_crossings = crossings
            best_ordering = [layer[:] for layer in layer_lists]
            no_improvement = 0
        else:
            no_improvement += 1

        if no_improvement >= 4 or best_crossings == 0:
            break

    layer_lists = _greedy_crossing_sweeps(graph, best_ordering)

    # Enforce topological order for orthogonal subgraph nodes in the same layer
    ortho_sets = _get_orthogonal_sg_nodes(graph)
    if ortho_sets:
        for layer in layer_lists:
            for sg_nodes in ortho_sets:
                in_layer = [n for n in layer if n in sg_nodes]
                if len(in_layer) <= 1:
                    continue
                # Build topological order from internal edges
                internal = set(in_layer)
                successors: dict[str, list[str]] = {n: [] for n in internal}
                in_degree: dict[str, int] = {n: 0 for n in internal}
                for edge in graph.edges:
                    if edge.source in internal and edge.target in internal:
                        successors[edge.source].append(edge.target)
                        in_degree[edge.target] += 1
                # Kahn's algorithm
                kahn_queue = [n for n in in_layer if in_degree[n] == 0]
                topo: list[str] = []
                while kahn_queue:
                    node = kahn_queue.pop(0)
                    topo.append(node)
                    for succ in successors[node]:
                        in_degree[succ] -= 1
                        if in_degree[succ] == 0:
                            kahn_queue.append(succ)
                # Replace in-layer positions: find positions of sg nodes, fill with topo order.
                # A cycle leaves topo incomplete; rewriting then duplicates
                # some nodes and drops others, so keep the original order.
                positions = [i for i, n in enumerate(layer) if n in internal]
                if len(topo) == len(positions):
                    for idx, pos in enumerate(positions):
                        layer[pos] = topo[idx]

    return layer_lists


def compute_gap_expansions(
    graph: Graph, layer_order: list[list[str]],
) -> dict[int, int]:
    """Compute extra grid cells needed between adjacent layers for crossing edges.

    When edges between two layers connect nodes at different perpendicular
    positions, they need horizontal (TD) or vertical (LR) routing space in
    the gap. If multiple such edges exist, the default single gap cell is
    not enough and they overlap. This function counts how many extra grid
    cells to insert per gap so the pathfinder has room to separate them.

    Returns a dict mapping gap index (between layer i and i+1) to the
    number of extra grid cells to insert.
    """
    # Build node -> (layer, position) lookup
    node_layer: dict[str, int] = {}
    node_pos: dict[str, int] = {}
    for layer_idx, nodes in enumerate(layer_order):
        for pos_idx, nid in enumerate(nodes):
            node_layer[nid] = layer_idx
            node_pos[nid] = pos_idx

    # Count edges that need horizontal routing per gap
    channels_per_gap: dict[int, set[int]] = {}
    bus_owners: dict[tuple[str, int, bool, bool], int] = {}
    bus_counts: dict[int, int] = {}
    endpoint_counts: dict[tuple[str, str], int] = {}
    for edge in graph.edges:
        endpoints = (edge.source, edge.target)
        endpoint_counts[endpoints] = endpoint_counts.get(endpoints, 0) + 1
    for edge_index, edge in enumerate(graph.edges):
        if edge.is_self_reference:
            continue
        src_layer = node_layer.get(edge.source)
        tgt_layer = node_layer.get(edge.target)
        if src_layer is None or tgt_layer is None:
            continue
        src_p = node_pos.get(edge.source, 0)
        tgt_p = node_pos.get(edge.target, 0)
        if src_p == tgt_p:
            continue  # straight edge, no horizontal routing needed

        # Compatible forward siblings turn on a single bus. Reserving one
        # lane per destination makes an ordinary fan-out unnecessarily tall.
        channel_index = edge_index
        if (not graph.subgraphs and tgt_layer == src_layer + 1
                and edge.style == EdgeStyle.SOLID
                and edge.arrow_type_start == edge.arrow_type_end == ArrowType.ARROW
                and endpoint_counts[(edge.source, edge.target)] == 1
                and edge_index not in graph.link_styles and -1 not in graph.link_styles):
            signature = (edge.source, tgt_layer, edge.has_arrow_start, edge.has_arrow_end)
            channel_index = bus_owners.setdefault(signature, edge_index)
            bus_counts[channel_index] = bus_counts.get(channel_index, 0) + 1

        # Count routing channels in every gap crossed by the edge.
        lo, hi = min(src_layer, tgt_layer), max(src_layer, tgt_layer)
        for gap_idx in range(lo, hi):
            channels_per_gap.setdefault(gap_idx, set()).add(channel_index)

    # Extra cells = max(0, n_diagonal - 1): one edge fits in the default
    # gap cell, each additional edge needs one more cell.
    # Even one shared bus needs separate turn and approach cells when a
    # terminal gap is only one character high/wide.
    shared_channels = {channel for channel, count in bus_counts.items() if count > 1}
    return {gap: max(int(bool(channels & shared_channels)), len(channels) - 1)
            for gap, channels in channels_per_gap.items()}


def _get_orthogonal_sg_nodes(graph: Graph) -> list[set[str]]:
    """Find sets of node IDs in subgraphs whose direction is orthogonal to the graph's."""
    graph_vertical = graph.direction.normalized().is_vertical
    result: list[set[str]] = []

    def _walk(subs: list[Subgraph]) -> None:
        for sg in subs:
            if sg.direction is not None:
                sg_vertical = sg.direction.normalized().is_vertical
                if sg_vertical != graph_vertical:
                    result.append(set(sg.node_ids))
            _walk(sg.children)

    _walk(graph.subgraphs)
    return result
