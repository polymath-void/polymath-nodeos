import sys
import os
import asyncio
import argparse

# Add A2A-Swarm to path
sys.path.append('/data/data/com.termux/files/home/Projects/A2A-Swarm/src/')
from udp_node import UDPNode

class SwarmEngine:
    def __init__(self, port=9999):
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
