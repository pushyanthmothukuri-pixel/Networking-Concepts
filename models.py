import uuid
import ipaddress
from datetime import datetime
from typing import List, Optional
from sqlalchemy import String, ForeignKey, Boolean, DateTime, func, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

# Custom SQLAlchemy Type Decorators to map network strings to ipaddress objects
class IPv4NetworkType(TypeDecorator):
    """
    Custom type for storing IPv4 CIDR networks in the database as strings,
    but retrieving them as python ipaddress.IPv4Network objects.
    """
    impl = String(49)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, ipaddress.IPv4Network):
            return str(value)
        return str(ipaddress.IPv4Network(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return ipaddress.IPv4Network(value)

class IPv4AddressType(TypeDecorator):
    """
    Custom type for storing IPv4 host addresses in the database as strings,
    but retrieving them as python ipaddress.IPv4Address objects.
    """
    impl = String(45)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, ipaddress.IPv4Address):
            return str(value)
        return str(ipaddress.IPv4Address(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return ipaddress.IPv4Address(value)


class VRF(Base):
    __tablename__ = "vrfs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    rd: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    subnets: Mapped[List["Subnet"]] = relationship("Subnet", back_populates="vrf", cascade="all, delete-orphan")
    ip_addresses: Mapped[List["IPAddress"]] = relationship("IPAddress", back_populates="vrf", cascade="all, delete-orphan")


class Subnet(Base):
    __tablename__ = "subnets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    vrf_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("vrfs.id", ondelete="CASCADE"), nullable=True)
    prefix: Mapped[ipaddress.IPv4Network] = mapped_column(IPv4NetworkType, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False) # active, reserved, deprecated
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("subnets.id", ondelete="SET NULL"), nullable=True)
    is_pool: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    vrf: Mapped[Optional[VRF]] = relationship("VRF", back_populates="subnets")
    parent: Mapped[Optional["Subnet"]] = relationship("Subnet", remote_side=[id], back_populates="children")
    children: Mapped[List["Subnet"]] = relationship("Subnet", back_populates="parent")
    ip_addresses: Mapped[List["IPAddress"]] = relationship("IPAddress", back_populates="subnet")


class IPAddress(Base):
    __tablename__ = "ip_addresses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    vrf_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("vrfs.id", ondelete="CASCADE"), nullable=True)
    subnet_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("subnets.id", ondelete="SET NULL"), nullable=True)
    address: Mapped[ipaddress.IPv4Address] = mapped_column(IPv4AddressType, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="allocated", nullable=False) # allocated, reserved, dhcp, static
    dns_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    mac_address: Mapped[Optional[str]] = mapped_column(String(17), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    vrf: Mapped[Optional[VRF]] = relationship("VRF", back_populates="ip_addresses")
    subnet: Mapped[Optional[Subnet]] = relationship("Subnet", back_populates="ip_addresses")
