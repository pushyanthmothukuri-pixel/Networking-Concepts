import ipaddress
from typing import List, Dict, Any, Tuple, Optional

def get_cidr_details(network: ipaddress.IPv4Network) -> Dict[str, Any]:
    """
    Computes all standard network properties from an IPv4Network.
    """
    prefixlen = network.prefixlen
    num_addresses = network.num_addresses

    # First and last usable host IPs
    if prefixlen <= 30:
        first_usable = network.network_address + 1
        last_usable = network.broadcast_address - 1
        usable_ips = num_addresses - 2
    else:
        # For /31 and /32, all addresses are usable (RFC 3021)
        first_usable = network.network_address
        last_usable = network.broadcast_address
        usable_ips = num_addresses

    return {
        "cidr": str(network),
        "network_address": str(network.network_address),
        "netmask": str(network.netmask),
        "broadcast_address": str(network.broadcast_address),
        "wildcard_mask": str(network.hostmask),
        "first_usable_ip": str(first_usable),
        "last_usable_ip": str(last_usable),
        "total_ips": num_addresses,
        "usable_ips": usable_ips,
        "prefix_len": prefixlen,
        "is_private": network.is_private,
        "is_loopback": network.is_loopback,
        "is_multicast": network.is_multicast,
        "is_link_local": network.is_link_local,
        "is_global": network.is_global,
        "is_reserved": network.is_reserved,
    }


def split_cidr(network: ipaddress.IPv4Network, new_prefix_len: int) -> List[ipaddress.IPv4Network]:
    """
    Splits a CIDR block into subnets of new_prefix_len.
    """
    if new_prefix_len < network.prefixlen:
        raise ValueError(f"New prefix length /{new_prefix_len} must be greater than or equal to current /{network.prefixlen}")
    return list(network.subnets(new_prefix=new_prefix_len))


def aggregate_cidrs(prefixes: List[ipaddress.IPv4Network]) -> List[ipaddress.IPv4Network]:
    """
    Consolidates a list of CIDR blocks to the smallest possible set of covering subnets.
    """
    return list(ipaddress.collapse_addresses(prefixes))


def subtract_cidrs(parent: ipaddress.IPv4Network, occupied: List[ipaddress.IPv4Network]) -> List[ipaddress.IPv4Network]:
    """
    Subtracts a list of occupied subnets from a parent subnet, returning the remaining free spaces.
    Uses binary-tree subtraction.
    """
    free_subnets = [parent]

    for occ in occupied:
        next_free = []
        for free in free_subnets:
            if not free.overlaps(occ):
                # No overlap: keep this free block intact
                next_free.append(free)
            elif free.subnet_of(occ):
                # The occupied block completely covers/swallows this free block: drop this free block
                continue
            else:
                # The occupied block is a proper subset of this free block.
                # We need to split the free block down the binary tree to carve out the occupied space.
                temp = free
                while temp != occ:
                    c1, c2 = list(temp.subnets(new_prefix=temp.prefixlen + 1))
                    if occ.subnet_of(c1):
                        next_free.append(c2)
                        temp = c1
                    else:
                        next_free.append(c1)
                        temp = c2
        free_subnets = next_free

    # Sort the resulting free subnets for consistency
    free_subnets.sort(key=lambda n: n.network_address)
    return free_subnets


def detect_cidr_collisions(items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]]]:
    """
    Detects pairwise overlaps (collisions) in a list of items containing a CIDR network and an ID.
    Returns:
      - A list of collision reports showing overlap pairs and overlap ranges.
      - A dictionary mapping each ID to a list of other IDs it overlaps with.
    """
    # Parse prefixes
    parsed_items = []
    for item in items:
        network = ipaddress.IPv4Network(item["cidr"], strict=False)
        parsed_items.append({
            "id": item["id"],
            "network": network,
            "original_cidr": item["cidr"]
        })

    collisions = []
    adjacency: Dict[str, List[str]] = {p["id"]: [] for p in parsed_items}

    n = len(parsed_items)
    for i in range(n):
        for j in range(i + 1, n):
            net1 = parsed_items[i]["network"]
            net2 = parsed_items[j]["network"]
            id1 = parsed_items[i]["id"]
            id2 = parsed_items[j]["id"]

            if net1.overlaps(net2):
                # In CIDR overlap, one is always a subnet of another. Overlap range is the smaller one.
                overlap_cidr = net1 if net1.subnet_of(net2) else net2
                collisions.append({
                    "id1": id1,
                    "cidr1": parsed_items[i]["original_cidr"],
                    "id2": id2,
                    "cidr2": parsed_items[j]["original_cidr"],
                    "overlap_cidr": str(overlap_cidr)
                })
                adjacency[id1].append(id2)
                adjacency[id2].append(id1)

    return collisions, adjacency
