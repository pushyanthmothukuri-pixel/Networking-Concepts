import uuid
import ipaddress
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import os
from sqlalchemy import create_engine, select, event, and_
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session

from models import Base, VRF, Subnet, IPAddress
from schemas import (
    VRFCreate, VRFResponse,
    SubnetCreate, SubnetResponse, SubnetSplitRequest, SubnetSplitResponse, SubnetUtilizationResponse,
    IPAddressCreate, IPAddressResponse, IPAllocateRequest,
    CIDRInfoRequest, CIDRInfoResponse, CIDRSplitRequest, CIDRSupernetRequest, CIDRSupernetResponse,
    CIDRDifferenceRequest, CIDRDifferenceResponse, CollisionCheckItem, CollisionCheckResponse
)
from ipam_logic import (
    IPAMValidationError,
    validate_and_find_relations,
    find_next_available_subnet,
    find_next_available_ip,
    get_subnet_utilization
)
from cidr_logic import (
    get_cidr_details, split_cidr, aggregate_cidrs, subtract_cidrs, detect_cidr_collisions
)

# Initialize database engine and session
# Uses environment variable DATABASE_URL if present, falling back to local SQLite database.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ipam.db")

# SQLAlchemy 1.4+ deprecated 'postgres://' in favor of 'postgresql://'
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# check_same_thread is only required/supported for SQLite
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Enforce foreign key constraints only in SQLite
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="IPAM API",
    description="Enterprise IP Address Management API handling VRFs, hierarchical subnets, and IP allocation.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database Session Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================================================================
# EXCEPTION HANDLER
# =========================================================================
@app.exception_handler(IPAMValidationError)
async def ipam_validation_exception_handler(request, exc: IPAMValidationError):
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)}
    )


# =========================================================================
# WEB UI ROOT ROUTE
# =========================================================================
@app.get("/", response_class=HTMLResponse)
def read_index():
    index_path = os.path.join(os.path.dirname(__file__), "index.html")
    if not os.path.exists(index_path):
        return """
        <html>
            <head><title>IPAM API</title></head>
            <body style="font-family: sans-serif; text-align: center; padding-top: 50px; background-color: #0f172a; color: #f8fafc;">
                <h1>IPAM API Server is Running</h1>
                <p>Dashboard UI template <code>index.html</code> was not found in the workspace.</p>
                <p>Visit <a href="/docs" style="color: #6366f1;">/docs</a> to view the interactive API swagger documentation.</p>
            </body>
        </html>
        """
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()


# =========================================================================
# VRF ROUTING
# =========================================================================
@app.post("/api/v1/vrfs", response_model=VRFResponse, status_code=status.HTTP_201_CREATED)
def create_vrf(vrf_in: VRFCreate, db: Session = Depends(get_db)):
    # Check if duplicate name
    existing = db.scalar(select(VRF).where(VRF.name == vrf_in.name))
    if existing:
        raise HTTPException(status_code=400, detail=f"VRF name '{vrf_in.name}' already exists.")
    
    # Check if duplicate RD
    if vrf_in.rd:
        existing_rd = db.scalar(select(VRF).where(VRF.rd == vrf_in.rd))
        if existing_rd:
            raise HTTPException(status_code=400, detail=f"VRF Route Distinguisher '{vrf_in.rd}' already exists.")
            
    db_vrf = VRF(name=vrf_in.name, rd=vrf_in.rd, description=vrf_in.description)
    db.add(db_vrf)
    db.commit()
    db.refresh(db_vrf)
    return db_vrf

@app.get("/api/v1/vrfs", response_model=List[VRFResponse])
def list_vrfs(db: Session = Depends(get_db)):
    return db.scalars(select(VRF).order_by(VRF.name)).all()

@app.get("/api/v1/vrfs/{id}", response_model=VRFResponse)
def get_vrf(id: uuid.UUID, db: Session = Depends(get_db)):
    db_vrf = db.scalar(select(VRF).where(VRF.id == id))
    if not db_vrf:
        raise HTTPException(status_code=404, detail="VRF not found")
    return db_vrf

@app.delete("/api/v1/vrfs/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vrf(id: uuid.UUID, db: Session = Depends(get_db)):
    db_vrf = db.scalar(select(VRF).where(VRF.id == id))
    if not db_vrf:
        raise HTTPException(status_code=404, detail="VRF not found")
    db.delete(db_vrf)
    db.commit()
    return


# =========================================================================
# SUBNETS ROUTING
# =========================================================================
@app.post("/api/v1/subnets", response_model=SubnetResponse, status_code=status.HTTP_201_CREATED)
def create_subnet(subnet_in: SubnetCreate, db: Session = Depends(get_db)):
    # Validate VRF exists if provided
    if subnet_in.vrf_id:
        vrf = db.scalar(select(VRF).where(VRF.id == subnet_in.vrf_id))
        if not vrf:
            raise HTTPException(status_code=400, detail="VRF not found")

    try:
        # Validate overlap and calculate parent-child relationships
        parent_id, children = validate_and_find_relations(
            session=db,
            new_prefix=subnet_in.prefix,
            vrf_id=subnet_in.vrf_id
        )

        # Enforce that if this is a pool, it cannot contain existing subnets
        if subnet_in.is_pool and len(children) > 0:
            raise IPAMValidationError(
                f"Cannot create pool {subnet_in.prefix} containing existing child subnets."
            )

        db_subnet = Subnet(
            vrf_id=subnet_in.vrf_id,
            prefix=subnet_in.prefix,
            status=subnet_in.status,
            parent_id=parent_id,
            is_pool=subnet_in.is_pool,
            description=subnet_in.description
        )
        db.add(db_subnet)
        db.flush() # Populate ID

        # Update child subnets to point to this new subnet as parent
        for child in children:
            child.parent_id = db_subnet.id
            db.add(child)

        db.commit()
        db.refresh(db_subnet)
        return db_subnet

    except IPAMValidationError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/v1/subnets", response_model=List[SubnetResponse])
def list_subnets(vrf_id: Optional[uuid.UUID] = None, db: Session = Depends(get_db)):
    stmt = select(Subnet)
    if vrf_id:
        stmt = stmt.where(Subnet.vrf_id == vrf_id)
    return db.scalars(stmt.order_by(Subnet.prefix)).all()

@app.get("/api/v1/subnets/{id}", response_model=SubnetResponse)
def get_subnet(id: uuid.UUID, db: Session = Depends(get_db)):
    db_subnet = db.scalar(select(Subnet).where(Subnet.id == id))
    if not db_subnet:
        raise HTTPException(status_code=404, detail="Subnet not found")
    return db_subnet

@app.get("/api/v1/subnets/{id}/utilization", response_model=SubnetUtilizationResponse)
def get_utilization(id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        return get_subnet_utilization(db, id)
    except IPAMValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/v1/subnets/{id}/split", response_model=SubnetSplitResponse)
def split_subnet(id: uuid.UUID, req: SubnetSplitRequest, db: Session = Depends(get_db)):
    parent = db.scalar(select(Subnet).where(Subnet.id == id))
    if not parent:
        raise HTTPException(status_code=404, detail="Parent subnet not found")
    
    if parent.is_pool:
        raise HTTPException(status_code=400, detail="Cannot split an IP allocation pool subnet.")

    if req.new_prefix_len <= parent.prefix.prefixlen:
        raise HTTPException(
            status_code=400, 
            detail=f"New prefix length /{req.new_prefix_len} must be greater than parent /{parent.prefix.prefixlen}"
        )

    try:
        # Generate target CIDR subnets
        new_nets = list(parent.prefix.subnets(new_prefix=req.new_prefix_len))
        
        # Validate that none of them overlap with existing subnets that are not under parent
        created_subnets = []
        for net in new_nets:
            parent_id, children = validate_and_find_relations(db, net, parent.vrf_id)
            
            # Create child subnets
            child_sub = Subnet(
                vrf_id=parent.vrf_id,
                prefix=net,
                status="active",
                parent_id=parent.id,
                is_pool=True, # default children to pools
                description=f"Split child of {parent.prefix}"
            )
            db.add(child_sub)
            created_subnets.append(child_sub)
            
        db.commit()
        return {
            "parent_prefix": parent.prefix,
            "new_prefixes": [sub.prefix for sub in created_subnets]
        }
    except IPAMValidationError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/v1/subnets/{id}/next-available", response_model=SubnetResponse, status_code=status.HTTP_201_CREATED)
def allocate_next_available_subnet(id: uuid.UUID, req: SubnetSplitRequest, db: Session = Depends(get_db)):
    parent = db.scalar(select(Subnet).where(Subnet.id == id))
    if not parent:
        raise HTTPException(status_code=404, detail="Parent subnet not found")
        
    try:
        # Find next free subnet CIDR
        next_cidr = find_next_available_subnet(db, parent.id, req.new_prefix_len)
        
        # Create and persist the subnet
        db_subnet = Subnet(
            vrf_id=parent.vrf_id,
            prefix=next_cidr,
            status="active",
            parent_id=parent.id,
            is_pool=True,
            description=f"Allocated from parent {parent.prefix}"
        )
        db.add(db_subnet)
        db.commit()
        db.refresh(db_subnet)
        return db_subnet
        
    except IPAMValidationError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/v1/subnets/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subnet(id: uuid.UUID, db: Session = Depends(get_db)):
    subnet = db.scalar(select(Subnet).where(Subnet.id == id))
    if not subnet:
        raise HTTPException(status_code=404, detail="Subnet not found")
        
    # Check if this subnet has children
    has_children = db.scalar(select(Subnet).where(Subnet.parent_id == id))
    if has_children:
        raise HTTPException(
            status_code=400, 
            detail="Cannot delete subnet because it has active child subnets. Delete child subnets first."
        )
        
    # Check if this subnet has allocations
    has_allocations = db.scalar(select(IPAddress).where(IPAddress.subnet_id == id))
    if has_allocations:
        raise HTTPException(
            status_code=400, 
            detail="Cannot delete subnet because it contains active IP address allocations."
        )
        
    db.delete(subnet)
    db.commit()
    return


# =========================================================================
# IP ADDRESSES ROUTING
# =========================================================================
@app.post("/api/v1/ip-addresses", response_model=IPAddressResponse, status_code=status.HTTP_201_CREATED)
def allocate_specific_ip(ip_in: IPAddressCreate, db: Session = Depends(get_db)):
    # Validate VRF exists if provided
    if ip_in.vrf_id:
        vrf = db.scalar(select(VRF).where(VRF.id == ip_in.vrf_id))
        if not vrf:
            raise HTTPException(status_code=400, detail="VRF not found")

    # If subnet_id is not provided, we must find the containing subnet pool in the same VRF
    subnet = None
    if ip_in.subnet_id:
        subnet = db.scalar(select(Subnet).where(Subnet.id == ip_in.subnet_id))
        if not subnet:
            raise HTTPException(status_code=400, detail="Specified subnet not found.")
    else:
        # Scan subnets to find containing subnet in the same VRF
        stmt = select(Subnet)
        if ip_in.vrf_id is None:
            stmt = stmt.where(Subnet.vrf_id.is_(None))
        else:
            stmt = stmt.where(Subnet.vrf_id == ip_in.vrf_id)
        subnets = db.scalars(stmt).all()
        for s in subnets:
            if ip_in.address in s.prefix:
                subnet = s
                break
        
        if not subnet:
            raise HTTPException(
                status_code=400, 
                detail="No subnet in the specified VRF covers this IP address."
            )

    # Validate that the subnet is an allocation pool
    if not subnet.is_pool:
        raise HTTPException(
            status_code=400, 
            detail=f"Subnet {subnet.prefix} is a container subnet and cannot hold host IP allocations."
        )

    # Validate that the address falls inside the subnet
    if ip_in.address not in subnet.prefix:
        raise HTTPException(
            status_code=400, 
            detail=f"IP Address {ip_in.address} is not within subnet {subnet.prefix}."
        )

    # Check for duplicate IP allocation within the same VRF
    stmt = select(IPAddress).where(IPAddress.address == ip_in.address)
    if subnet.vrf_id is None:
        stmt = stmt.where(IPAddress.vrf_id.is_(None))
    else:
        stmt = stmt.where(IPAddress.vrf_id == subnet.vrf_id)
    existing_ip = db.scalar(stmt)
    if existing_ip:
        raise HTTPException(status_code=400, detail=f"IP address {ip_in.address} is already allocated in this VRF.")

    db_ip = IPAddress(
        vrf_id=subnet.vrf_id,
        subnet_id=subnet.id,
        address=ip_in.address,
        status=ip_in.status,
        dns_name=ip_in.dns_name,
        description=ip_in.description,
        mac_address=ip_in.mac_address
    )
    db.add(db_ip)
    db.commit()
    db.refresh(db_ip)
    return db_ip

@app.post("/api/v1/subnets/{id}/allocate-ip", response_model=IPAddressResponse, status_code=status.HTTP_201_CREATED)
def allocate_next_ip(id: uuid.UUID, req: IPAllocateRequest, db: Session = Depends(get_db)):
    subnet = db.scalar(select(Subnet).where(Subnet.id == id))
    if not subnet:
        raise HTTPException(status_code=404, detail="Subnet not found")

    try:
        next_ip = find_next_available_ip(db, subnet.id)
        
        db_ip = IPAddress(
            vrf_id=subnet.vrf_id,
            subnet_id=subnet.id,
            address=next_ip,
            status=req.status,
            dns_name=req.dns_name,
            description=req.description,
            mac_address=req.mac_address
        )
        db.add(db_ip)
        db.commit()
        db.refresh(db_ip)
        return db_ip
        
    except IPAMValidationError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/v1/ip-addresses", response_model=List[IPAddressResponse])
def list_ip_addresses(
    vrf_id: Optional[uuid.UUID] = None, 
    subnet_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_db)
):
    stmt = select(IPAddress)
    if vrf_id:
        stmt = stmt.where(IPAddress.vrf_id == vrf_id)
    if subnet_id:
        stmt = stmt.where(IPAddress.subnet_id == subnet_id)
    return db.scalars(stmt.order_by(IPAddress.address)).all()

@app.get("/api/v1/ip-addresses/{id}", response_model=IPAddressResponse)
def get_ip_address(id: uuid.UUID, db: Session = Depends(get_db)):
    ip_addr = db.scalar(select(IPAddress).where(IPAddress.id == id))
    if not ip_addr:
        raise HTTPException(status_code=404, detail="IP Address allocation not found")
    return ip_addr

@app.delete("/api/v1/ip-addresses/{id}", status_code=status.HTTP_204_NO_CONTENT)
def release_ip_address(id: uuid.UUID, db: Session = Depends(get_db)):
    ip_addr = db.scalar(select(IPAddress).where(IPAddress.id == id))
    if not ip_addr:
        raise HTTPException(status_code=404, detail="IP Address allocation not found")
    db.delete(ip_addr)
    db.commit()
    return


# =========================================================================
# STATELESS CIDR UTILITY ROUTES
# =========================================================================
@app.post("/api/v1/cidr/info", response_model=CIDRInfoResponse)
def cidr_info(req: CIDRInfoRequest):
    return get_cidr_details(req.cidr)

@app.post("/api/v1/cidr/split", response_model=List[str])
def cidr_split(req: CIDRSplitRequest):
    try:
        subnets = split_cidr(req.cidr, req.new_prefix_len)
        return [str(net) for net in subnets]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/v1/cidr/supernet", response_model=CIDRSupernetResponse)
def cidr_supernet(req: CIDRSupernetRequest):
    aggregated = aggregate_cidrs(req.prefixes)
    return {"aggregated_prefixes": aggregated}

@app.post("/api/v1/cidr/difference", response_model=CIDRDifferenceResponse)
def cidr_difference(req: CIDRDifferenceRequest):
    # Enforce that all occupied subnets are subnets of the parent
    for occ in req.occupied:
        if not occ.subnet_of(req.parent):
            raise HTTPException(
                status_code=400,
                detail=f"Occupied prefix {occ} is not a valid subnet of parent prefix {req.parent}."
            )
    free_blocks = subtract_cidrs(req.parent, req.occupied)
    return {"free_prefixes": free_blocks}

@app.post("/api/v1/cidr/check-collisions", response_model=CollisionCheckResponse)
def check_collisions(req: List[CollisionCheckItem]):
    # Convert request items to format expected by logic
    items = [{"id": item.id, "cidr": item.cidr} for item in req]
    try:
        collisions, overlap_matrix = detect_cidr_collisions(items)
        return {
            "has_collisions": len(collisions) > 0,
            "collisions": collisions,
            "overlap_matrix": overlap_matrix
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

