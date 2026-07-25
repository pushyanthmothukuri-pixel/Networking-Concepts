import ipaddress
import uuid
from typing import List, Optional, Set, Tuple
from sqlalchemy import select, or_, and_, func
from sqlalchemy.orm import Session
from models import Subnet, IPAddress, VRF

class IPAMValidationError(Exception):
    """Custom exception for IPAM validation and allocation errors."""
    pass


def get_subnet_utilization(session: Session, subnet_id: uuid.UUID) -> dict:
    """
    Calculate utilization metrics for a given subnet.
    If it is a container (is_pool=False), utilization is based on child subnets.
    If it is a pool (is_pool=True), utilization is based on allocated host IPs.
    """
    subnet = session.scalar(select(Subnet).where(Subnet.id == subnet_id))
    if not subnet:
        raise IPAMValidationError("Subnet not found")

    total_ips = subnet.prefix.num_addresses
    
    # Usable IPs for pools: skip network and broadcast for prefixes <= 30
    if subnet.prefix.prefixlen <= 30:
        usable_ips = total_ips - 2
    else:
        usable_ips = total_ips

    if subnet.is_pool:
        # Calculate host IP allocations
        allocated_count = session.scalar(
            select(func.count(IPAddress.id))
            .where(IPAddress.subnet_id == subnet_id)
        ) or 0
        
        utilization_percentage = (allocated_count / usable_ips * 100) if usable_ips > 0 else 0.0
        
        return {
            "subnet_id": str(subnet.id),
            "prefix": str(subnet.prefix),
            "is_pool": True,
            "total_ips": total_ips,
            "usable_ips": usable_ips,
            "allocated_ips": allocated_count,
            "free_ips": max(0, usable_ips - allocated_count),
            "utilization_percentage": round(utilization_percentage, 2)
        }
    else:
        # For containers, sum the IP count covered by child subnets
        child_subnets = session.scalars(
            select(Subnet).where(Subnet.parent_id == subnet_id)
        ).all()
        
        child_ips_covered = sum(child.prefix.num_addresses for child in child_subnets)
        utilization_percentage = (child_ips_covered / total_ips * 100) if total_ips > 0 else 0.0
        
        return {
            "subnet_id": str(subnet.id),
            "prefix": str(subnet.prefix),
            "is_pool": False,
            "total_ips": total_ips,
            "child_subnets_count": len(child_subnets),
            "allocated_subnet_ips": child_ips_covered,
            "free_subnet_ips": max(0, total_ips - child_ips_covered),
            "utilization_percentage": round(utilization_percentage, 2)
        }


def validate_and_find_relations(
    session: Session, 
    new_prefix: ipaddress.IPv4Network, 
    vrf_id: Optional[uuid.UUID],
    exclude_id: Optional[uuid.UUID] = None
) -> Tuple[Optional[uuid.UUID], List[Subnet]]:
    """
    Validate that a new prefix does not cause invalid overlaps in the given VRF.
    If valid, returns a tuple: (parent_id, list_of_child_subnets).
    
    Rules:
    1. A prefix cannot already exist in the same VRF (duplicate prefix).
    2. Overlaps are only allowed if one is a subnet of another (strict parent-child containment).
    3. If there is a parent subnet, it must NOT be a pool (is_pool=False), because host allocation pools cannot have child subnets.
    4. peer subnets (same level/hierarchy) must not overlap.
    """
    # Fetch all subnets in the VRF
    if vrf_id is None:
        stmt = select(Subnet).where(Subnet.vrf_id.is_(None))
    else:
        stmt = select(Subnet).where(Subnet.vrf_id == vrf_id)
    if exclude_id:
        stmt = stmt.where(Subnet.id != exclude_id)
    
    existing_subnets = session.scalars(stmt).all()

    parent_candidate: Optional[Subnet] = None
    children_candidates: List[Subnet] = []

    for existing in existing_subnets:
        existing_net = existing.prefix
        
        # 1. Check for exact duplicate
        if existing_net == new_prefix:
            raise IPAMValidationError(f"Subnet prefix {new_prefix} already exists in this VRF.")

        # Check for overlap
        if new_prefix.overlaps(existing_net):
            # Since they overlap, one must be a subset of the other in CIDR
            if new_prefix.subnet_of(existing_net):
                # existing_net is a parent of new_prefix.
                # We want the smallest/tightest parent.
                if not parent_candidate or existing_net.subnet_of(parent_candidate.prefix):
                    parent_candidate = existing
            elif existing_net.subnet_of(new_prefix):
                # existing_net is a child of new_prefix.
                children_candidates.append(existing)
            else:
                # Should not happen in CIDR, as one is always a subset if they overlap
                raise IPAMValidationError(f"Subnet prefix {new_prefix} overlaps with {existing_net}.")

    # 3. If a parent is found, check if it's an allocation pool
    if parent_candidate and parent_candidate.is_pool:
        raise IPAMValidationError(
            f"Cannot create subnet inside {parent_candidate.prefix} because it is configured as an IP allocation pool."
        )

    # 4. If children are found and the new subnet is to be a pool, check if it's allowed
    # (A pool cannot contain child subnets)
    # We will enforce this validation inside the create route once we know if the new subnet is a pool.

    return parent_candidate.id if parent_candidate else None, children_candidates


def find_next_available_subnet(
    session: Session,
    parent_subnet_id: uuid.UUID,
    new_prefix_len: int
) -> ipaddress.IPv4Network:
    """
    Finds the first available subnetwork of size new_prefix_len inside the parent subnet.
    Ensures it does not overlap with any existing child subnets.
    """
    parent = session.scalar(select(Subnet).where(Subnet.id == parent_subnet_id))
    if not parent:
        raise IPAMValidationError("Parent subnet not found")
        
    if parent.is_pool:
        raise IPAMValidationError("Cannot subnet an IP allocation pool")

    if new_prefix_len <= parent.prefix.prefixlen:
        raise IPAMValidationError(
            f"New prefix length (/{new_prefix_len}) must be larger than parent prefix length (/{parent.prefix.prefixlen})"
        )

    # Get all direct and indirect children of the parent subnet
    # (To be safe, get all subnets in the VRF that are subnets of the parent prefix)
    stmt = select(Subnet)
    if parent.vrf_id is None:
        stmt = stmt.where(Subnet.vrf_id.is_(None))
    else:
        stmt = stmt.where(Subnet.vrf_id == parent.vrf_id)
    stmt = stmt.where(Subnet.id != parent.id)
    existing_children = session.scalars(stmt).all()

    # Filter in-memory to find subnets that are subnets of the parent
    occupied_networks = [
        s.prefix for s in existing_children if s.prefix.subnet_of(parent.prefix)
    ]

    # Generate all candidate subnets of the target prefix length
    candidates = parent.prefix.subnets(new_prefix=new_prefix_len)
    
    for candidate in candidates:
        # Check if candidate overlaps with any occupied network
        has_overlap = False
        for occupied in occupied_networks:
            if candidate.overlaps(occupied):
                has_overlap = True
                break
        
        if not has_overlap:
            return candidate

    raise IPAMValidationError(
        f"No free /{new_prefix_len} subnets available inside parent {parent.prefix}."
    )


def find_next_available_ip(
    session: Session,
    subnet_id: uuid.UUID
) -> ipaddress.IPv4Address:
    """
    Finds the first free host IP address inside the given subnet pool.
    Excludes network and broadcast address for prefixes <= 30.
    Excludes already allocated/reserved IP addresses.
    """
    subnet = session.scalar(select(Subnet).where(Subnet.id == subnet_id))
    if not subnet:
        raise IPAMValidationError("Subnet not found")
        
    if not subnet.is_pool:
        raise IPAMValidationError("Cannot allocate host IPs from a container subnet. Set is_pool=True first.")

    # Get all existing allocated IP addresses in this subnet
    allocated_ips = session.scalars(
        select(IPAddress.address).where(IPAddress.subnet_id == subnet_id)
    ).all()
    
    allocated_set: Set[ipaddress.IPv4Address] = set(allocated_ips)

    # Determine IP generator based on subnet size
    if subnet.prefix.prefixlen <= 30:
        # hosts() automatically excludes network and broadcast addresses
        ip_generator = subnet.prefix.hosts()
    else:
        # For /31 and /32, all addresses are usable hosts (RFC 3021)
        # Using list cast to make it iterable
        ip_generator = list(subnet.prefix)

    for ip in ip_generator:
        if ip not in allocated_set:
            return ip

    raise IPAMValidationError(f"No free IP addresses available in subnet {subnet.prefix}.")
