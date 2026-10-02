import sys
import os
import asyncio
import argparse

# Locate the A2A-Swarm dependency by walking up from this file rather than hardcoding one
# developer's absolute path (Category F). A2A-Swarm is a SIBLING of this repo, not a
# child, so search each ancestor's children. NODEOS_SWARM_SRC overrides the search.
def _locate_swarm_src():
    override = os.environ.get('NODEOS_SWARM_SRC')
    if override and os.path.isdir(override):
        return override
    path = os.path.abspath(__file__)
    for _ in range(6):
        path = os.path.dirname(path)
        candidate = os.path.join(path, 'A2A-Swarm', 'src')
        if os.path.isdir(candidate):
            return candidate
    return None

_SWARM_SRC = _locate_swarm_src()
if _SWARM_SRC:
    sys.path.append(_SWARM_SRC)
    try:
        from udp_node import UDPNode
    except ImportError as exc:
        # Present but broken: report loudly instead of failing later at construction.
        sys.stderr.write(
            f"[SwarmEngine] Found A2A-Swarm at {_SWARM_SRC} but could not import "
            f"udp_node: {exc}. UDP swarm features are unavailable.\n")
        UDPNode = None
else:
    sys.stderr.write(
        "[SwarmEngine] A2A-Swarm not found in any ancestor directory; UDP swarm features "
        "are unavailable. Set NODEOS_SWARM_SRC to the src/ directory to enable them.\n")
    UDPNode = None

class SwarmEngine:
    def __init__(self, port=9999):
        if UDPNode is None:
            raise RuntimeError(
                "SwarmEngine unavailable: the A2A-Swarm dependency is not installed.")
        self.node = UDPNode(port=port, role="NodeOS-Agent")
        
    async def run_swarm(self, group, task, payload):
        await self.node.start()
        self.node.join_group(group)
        await asyncio.sleep(1)
        await self.node.broadcast_cfp(group, task, {"payload": payload})
        print(f"Broadcasted task '{task}' to group '{group}'")
        await asyncio.sleep(5) # Wait for responses

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NodeOS Swarm P2P Bridge.")
    parser.add_argument("--group", required=True, help="Swarm group name")
    parser.add_argument("--task", required=True, help="Task name")
    parser.add_argument("--payload", required=True, help="Task payload")
    args = parser.parse_args()
    
    engine = SwarmEngine()
    asyncio.run(engine.run_swarm(args.group, args.task, args.payload))
