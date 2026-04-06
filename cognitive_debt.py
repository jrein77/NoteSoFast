"""
Cognitive debt tracking for bulk imports and unengaged content.

Tracks per-node engagement (last_engaged timestamp, engagement_count)
and flags content that hasn't been reviewed as "cognitive debt".

Debt criteria:
  - engagement_count == 0 AND older than debt_threshold_hours since creation
  - Nodes with many child nodes (shared tags) that remain unengaged
"""

from datetime import datetime


class CognitiveDebtTracker:
    """Tracks engagement with knowledge graph nodes to identify cognitive debt."""

    def __init__(self, debt_threshold_hours=24):
        self.debt_threshold_hours = debt_threshold_hours
        # node_id -> { created_at, last_engaged, engagement_count, tags }
        self._nodes = {}

    def register_node(self, node_id, tags=None):
        """Register a new node when a note is created or uploaded."""
        if node_id in self._nodes:
            return
        self._nodes[node_id] = {
            "created_at": datetime.now(),
            "last_engaged": None,
            "engagement_count": 0,
            "tags": tags or [],
        }

    def is_registered(self, node_id):
        """Check if a node is registered."""
        return node_id in self._nodes

    def record_engagement(self, node_id):
        """Record that the user engaged with a topic (answered a question)."""
        if node_id not in self._nodes:
            self.register_node(node_id)
        node = self._nodes[node_id]
        node["last_engaged"] = datetime.now()
        node["engagement_count"] += 1

    def get_node_state(self, node_id):
        """Return engagement state for a node."""
        return self._nodes.get(node_id)

    def is_in_debt(self, node_id):
        """Check if a specific node qualifies as cognitive debt."""
        node = self._nodes.get(node_id)
        if node is None:
            return False
        if node["engagement_count"] > 0:
            return False
        hours_since_creation = (
            (datetime.now() - node["created_at"]).total_seconds() / 3600.0
        )
        return hours_since_creation >= self.debt_threshold_hours

    def get_debt_nodes(self, notes_dict):
        """Return list of nodes that are in cognitive debt.

        Args:
            notes_dict: The global notes dictionary for title/tag lookup

        Returns:
            List of dicts with node metadata
        """
        debt = []
        now = datetime.now()

        for node_id, state in self._nodes.items():
            if state["engagement_count"] > 0:
                continue

            hours_since = (now - state["created_at"]).total_seconds() / 3600.0
            if hours_since < self.debt_threshold_hours:
                continue

            note = notes_dict.get(node_id)
            if note is None:
                continue

            # Count child nodes (nodes sharing tags) that are also unengaged
            child_count = 0
            node_tags = set(state.get("tags", []))
            if node_tags:
                for other_id, other_state in self._nodes.items():
                    if other_id == node_id:
                        continue
                    other_tags = set(other_state.get("tags", []))
                    if node_tags & other_tags and other_state["engagement_count"] == 0:
                        child_count += 1

            debt.append({
                "note_id": node_id,
                "title": note["title"],
                "tags": note.get("tags", []),
                "hours_since_creation": round(hours_since, 1),
                "engagement_count": 0,
                "child_count": child_count,
            })

        return debt

    def get_debt_count(self, notes_dict):
        """Return the number of nodes in cognitive debt."""
        return len(self.get_debt_nodes(notes_dict))

    def remove_node(self, node_id):
        """Remove a node from tracking (e.g., when a note is deleted)."""
        self._nodes.pop(node_id, None)
