import type { GraphEdge, GraphNode } from './types'

type Snapshot = { nodes: GraphNode[]; edges: GraphEdge[] }

/** The latest server graph, retained even while its renderer is unmounted. */
export class MemoryState {
  private nodes = new Map<string, GraphNode>()
  private edges = new Map<string, GraphEdge>()

  replace(snapshot: Snapshot): void {
    this.nodes.clear()
    this.edges.clear()
    this.merge(snapshot)
  }

  merge(batch: Snapshot): void {
    for (const node of batch.nodes) this.nodes.set(node.id, { ...node })
    for (const edge of batch.edges) {
      if (this.nodes.has(edge.source) && this.nodes.has(edge.target)) {
        this.edges.set(edge.id, { ...edge })
      }
    }
  }

  get count(): number {
    return this.nodes.size
  }

  snapshot(): Snapshot {
    return {
      nodes: [...this.nodes.values()].map((node) => ({ ...node })),
      edges: [...this.edges.values()].map((edge) => ({ ...edge })),
    }
  }
}
