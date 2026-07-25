import uuid
import ipaddress
from datetime import datetime
from typing import Optional, List, Dict
from pydantic import BaseModel, Field, field_validator, ConfigDict


# =========================================================================
# VRF SCHEMAS
# =========================================================================
class VRFCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Unique human-readable name for the VRF")
    rd: Optional[str] = Field(None, max_length=255, description="Route Distinguisher, e.g. '65000:10'")
    description: Optional[str] = Field(None, description="Optional description of the routing domain")

class VRFResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    rd: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# =========================================================================
# SUBNET SCHEMAS
# =========================================================================
class SubnetCreate(BaseModel):
    prefix: ipaddress.IPv4Network = Field(..., description="IPv4 Prefix block in CIDR notation, e.g. 10.0.0.0/24")
    vrf_id: Optional[uuid.UUID] = Field(None, description="Optional associated VRF ID (null implies global table)")
    status: str = Field("active", description="Status of the subnet: active, reserved, or deprecated")
    is_pool: bool = Field(True, description="True if host IPs can be allocated directly, False if for subnet container only")
    description: Optional[str] = Field(None, description="Subnet purpose/description")

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        allowed = {"active", "reserved", "deprecated"}
        if value.lower() not in allowed:
            raise ValueError(f"Status must be one of {allowed}")
        return value.lower()

class SubnetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vrf_id: Optional[uuid.UUID] = None
    prefix: ipaddress.IPv4Network
    status: str
    parent_id: Optional[uuid.UUID] = None
    is_pool: bool
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # Custom serializer to convert IPv4Network to string in JSON output
    @field_validator("prefix", mode="before")
    @classmethod
    def serialize_prefix(cls, value):
        if isinstance(value, str):
            return ipaddress.IPv4Network(value)
        return value

class SubnetSplitRequest(BaseModel):
    new_prefix_len: int = Field(..., ge=1, le=32, description="Target CIDR mask length to split the subnet into")

class SubnetSplitResponse(BaseModel):
    parent_prefix: ipaddress.IPv4Network
    new_prefixes: List[ipaddress.IPv4Network]

class SubnetUtilizationResponse(BaseModel):
    subnet_id: str
    prefix: str
    is_pool: bool
    total_ips: int
    usable_ips: Optional[int] = None
    allocated_ips: Optional[int] = None
    free_ips: Optional[int] = None
    child_subnets_count: Optional[int] = None
    allocated_subnet_ips: Optional[int] = None
    free_subnet_ips: Optional[int] = None
    utilization_percentage: float


# =========================================================================
# IP ADDRESS SCHEMAS
# =========================================================================
class IPAddressCreate(BaseModel):
    address: ipaddress.IPv4Address = Field(..., description="Specific host IP address, e.g. 10.0.0.1")
    vrf_id: Optional[uuid.UUID] = Field(None, description="Associated VRF ID")
    subnet_id: Optional[uuid.UUID] = Field(None, description="Parent Subnet ID")
    status: str = Field("allocated", description="Status: allocated, reserved, dhcp, or static")
    dns_name: Optional[str] = Field(None, max_length=255, description="DNS host name record")
    description: Optional[str] = Field(None, description="IP address description")
    mac_address: Optional[str] = Field(None, pattern=r"^([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})$", description="MAC Address")

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        allowed = {"allocated", "reserved", "dhcp", "static"}
        if value.lower() not in allowed:
            raise ValueError(f"Status must be one of {allowed}")
        return value.lower()

class IPAddressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vrf_id: Optional[uuid.UUID] = None
    subnet_id: Optional[uuid.UUID] = None
    address: ipaddress.IPv4Address
    status: str
    dns_name: Optional[str] = None
    description: Optional[str] = None
    mac_address: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("address", mode="before")
    @classmethod
    def serialize_address(cls, value):
        if isinstance(value, str):
            return ipaddress.IPv4Address(value)
        return value

class IPAllocateRequest(BaseModel):
    status: str = Field("allocated", description="Status of the IP allocation")
    dns_name: Optional[str] = Field(None, max_length=255, description="DNS Name")
    description: Optional[str] = Field(None, description="Purpose or description")
    mac_address: Optional[str] = Field(None, pattern=r"^([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})$", description="MAC Address")


# =========================================================================
# STATELESS CIDR UTILITY SCHEMAS
# =========================================================================
class CIDRInfoRequest(BaseModel):
    cidr: ipaddress.IPv4Network = Field(..., description="CIDR block to analyze, e.g. 192.168.1.0/24")

    # Custom serializer to convert string CIDR to IPv4Network if needed
    @field_validator("cidr", mode="before")
    @classmethod
    def parse_cidr(cls, value):
        if isinstance(value, str):
            return ipaddress.IPv4Network(value, strict=False)
        return value

class CIDRInfoResponse(BaseModel):
    cidr: str
    network_address: str
    netmask: str
    broadcast_address: str
    wildcard_mask: str
    first_usable_ip: str
    last_usable_ip: str
    total_ips: int
    usable_ips: int
    prefix_len: int
    is_private: bool
    is_loopback: bool
    is_multicast: bool
    is_link_local: bool
    is_global: bool
    is_reserved: bool

class CIDRSplitRequest(BaseModel):
    cidr: ipaddress.IPv4Network = Field(..., description="CIDR block to split")
    new_prefix_len: int = Field(..., ge=1, le=32, description="Target CIDR prefix length to split into")

    @field_validator("cidr", mode="before")
    @classmethod
    def parse_cidr(cls, value):
        if isinstance(value, str):
            return ipaddress.IPv4Network(value, strict=False)
        return value

class CIDRSupernetRequest(BaseModel):
    prefixes: List[ipaddress.IPv4Network] = Field(..., description="List of CIDRs or IP addresses to aggregate")

    @field_validator("prefixes", mode="before")
    @classmethod
    def parse_prefixes(cls, value):
        if isinstance(value, list):
            return [ipaddress.IPv4Network(item, strict=False) if isinstance(item, str) else item for item in value]
        return value

class CIDRSupernetResponse(BaseModel):
    aggregated_prefixes: List[ipaddress.IPv4Network]

class CIDRDifferenceRequest(BaseModel):
    parent: ipaddress.IPv4Network = Field(..., description="Parent CIDR block")
    occupied: List[ipaddress.IPv4Network] = Field(..., description="Sub-blocks to subtract from parent")

    @field_validator("parent", mode="before")
    @classmethod
    def parse_parent(cls, value):
        if isinstance(value, str):
            return ipaddress.IPv4Network(value, strict=False)
        return value

    @field_validator("occupied", mode="before")
    @classmethod
    def parse_occupied(cls, value):
        if isinstance(value, list):
            return [ipaddress.IPv4Network(item, strict=False) if isinstance(item, str) else item for item in value]
        return value

class CIDRDifferenceResponse(BaseModel):
    free_prefixes: List[ipaddress.IPv4Network]

class CollisionCheckItem(BaseModel):
    id: str = Field(..., description="Label or Identifier for the scope (e.g. VPC-A, Subnet-1)")
    cidr: str = Field(..., description="CIDR block range to inspect")

class CollisionReportPair(BaseModel):
    id1: str
    cidr1: str
    id2: str
    cidr2: str
    overlap_cidr: str

class CollisionCheckResponse(BaseModel):
    has_collisions: bool
    collisions: List[CollisionReportPair]
    overlap_matrix: Dict[str, List[str]]

