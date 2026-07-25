import pytest
import os
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import event
from sqlalchemy.engine import Engine

from main import app, get_db
from models import Base

# Setup test database
TEST_DATABASE_URL = "sqlite:///./test_ipam.db"

engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Enforce foreign key constraints in SQLite for tests
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

@pytest.fixture(scope="session", autouse=True)
def setup_database():
    # Make sure we start clean
    if os.path.exists("./test_ipam.db"):
        os.remove("./test_ipam.db")
    Base.metadata.create_all(bind=engine)
    yield
    # Clean up test database file
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("./test_ipam.db"):
        try:
            os.remove("./test_ipam.db")
        except PermissionError:
            pass

@pytest.fixture
def db():
    # Recreate tables to ensure a completely clean state for each test function
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()

@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    del app.dependency_overrides[get_db]


# =========================================================================
# VRF TESTS
# =========================================================================
def test_create_and_list_vrfs(client):
    # Create VRF
    response = client.post("/api/v1/vrfs", json={"name": "Prod-East", "rd": "65000:10"})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Prod-East"
    assert data["rd"] == "65000:10"
    assert "id" in data

    # Create Duplicate Name VRF - should fail
    response_dup = client.post("/api/v1/vrfs", json={"name": "Prod-East"})
    assert response_dup.status_code == 400

    # List VRFs
    response_list = client.get("/api/v1/vrfs")
    assert response_list.status_code == 200
    vrfs = response_list.json()
    assert len(vrfs) >= 1
    assert any(v["name"] == "Prod-East" for v in vrfs)


# =========================================================================
# SUBNET TESTS
# =========================================================================
def test_create_subnets_hierarchy(client):
    # 1. Create a root container subnet (is_pool=False)
    root_resp = client.post(
        "/api/v1/subnets",
        json={"prefix": "10.0.0.0/16", "is_pool": False, "description": "Root Class A"}
    )
    assert root_resp.status_code == 201
    root_data = root_resp.json()
    root_id = root_data["id"]
    assert root_data["parent_id"] is None
    assert root_data["is_pool"] is False

    # 2. Create a child allocation pool subnet (is_pool=True) inside the root
    child_resp = client.post(
        "/api/v1/subnets",
        json={"prefix": "10.0.1.0/24", "is_pool": True, "description": "Subnet 1 Pool"}
    )
    assert child_resp.status_code == 201
    child_data = child_resp.json()
    child_id = child_data["id"]
    assert child_data["parent_id"] == root_id
    assert child_data["is_pool"] is True

    # 3. Attempt to create a nested subnet inside the pool (should fail, as pools cannot have child subnets)
    nested_resp = client.post(
        "/api/v1/subnets",
        json={"prefix": "10.0.1.0/25", "is_pool": True}
    )
    assert nested_resp.status_code == 400
    assert "configured as an IP allocation pool" in nested_resp.json()["detail"]

    # 4. Attempt to create an overlapping peer subnet that is not a clean subset (should fail)
    # Note: 10.0.1.128/25 overlaps with child 10.0.1.0/24
    overlap_resp = client.post(
        "/api/v1/subnets",
        json={"prefix": "10.0.1.128/25", "is_pool": True}
    )
    assert overlap_resp.status_code == 400


def test_subnet_utilization(client):
    # Create subnet pool /30 (4 total IPs, 2 usable: .1 and .2)
    sub_resp = client.post(
        "/api/v1/subnets",
        json={"prefix": "192.168.1.0/30", "is_pool": True}
    )
    assert sub_resp.status_code == 201
    sub_id = sub_resp.json()["id"]

    # Utilization should be 0% initially
    util_resp = client.get(f"/api/v1/subnets/{sub_id}/utilization")
    assert util_resp.status_code == 200
    util_data = util_resp.json()
    assert util_data["total_ips"] == 4
    assert util_data["usable_ips"] == 2
    assert util_data["allocated_ips"] == 0
    assert util_data["utilization_percentage"] == 0.0

    # Allocate one IP
    alloc_resp = client.post(f"/api/v1/subnets/{sub_id}/allocate-ip", json={})
    assert alloc_resp.status_code == 201
    assert alloc_resp.json()["address"] == "192.168.1.1"

    # Utilization should be 50%
    util_resp = client.get(f"/api/v1/subnets/{sub_id}/utilization")
    assert util_resp.status_code == 200
    assert util_resp.json()["allocated_ips"] == 1
    assert util_resp.json()["utilization_percentage"] == 50.0


# =========================================================================
# IP ALLOCATION TESTS
# =========================================================================
def test_ip_allocation_flow(client):
    # Create subnet
    sub_resp = client.post(
        "/api/v1/subnets",
        json={"prefix": "10.10.10.0/24", "is_pool": True}
    )
    sub_id = sub_resp.json()["id"]

    # 1. Allocate next available IP (should be 10.10.10.1)
    ip1_resp = client.post(f"/api/v1/subnets/{sub_id}/allocate-ip", json={"dns_name": "host-1"})
    assert ip1_resp.status_code == 201
    assert ip1_resp.json()["address"] == "10.10.10.1"
    assert ip1_resp.json()["dns_name"] == "host-1"

    # 2. Allocate another IP (should be 10.10.10.2)
    ip2_resp = client.post(f"/api/v1/subnets/{sub_id}/allocate-ip", json={})
    assert ip2_resp.status_code == 201
    assert ip2_resp.json()["address"] == "10.10.10.2"

    # 3. Manually allocate specific IP (10.10.10.50)
    spec_resp = client.post(
        "/api/v1/ip-addresses",
        json={"address": "10.10.10.50", "subnet_id": sub_id}
    )
    assert spec_resp.status_code == 201
    assert spec_resp.json()["address"] == "10.10.10.50"

    # 4. Attempt to allocate duplicate IP (should fail)
    dup_resp = client.post(
        "/api/v1/ip-addresses",
        json={"address": "10.10.10.50", "subnet_id": sub_id}
    )
    assert dup_resp.status_code == 400

    # 5. Attempt to allocate IP outside subnet boundaries (should fail)
    outside_resp = client.post(
        "/api/v1/ip-addresses",
        json={"address": "10.10.20.1", "subnet_id": sub_id}
    )
    assert outside_resp.status_code == 400


# =========================================================================
# SUBNET SPLIT & NEXT AVAILABLE SUBNET TESTS
# =========================================================================
def test_subnet_split_and_next_subnet(client):
    # Create parent container subnet (is_pool=False)
    parent_resp = client.post(
        "/api/v1/subnets",
        json={"prefix": "172.16.0.0/16", "is_pool": False}
    )
    parent_id = parent_resp.json()["id"]

    # Allocate next available /24 subnet (should be 172.16.0.0/24)
    next_sub1 = client.post(f"/api/v1/subnets/{parent_id}/next-available", json={"new_prefix_len": 24})
    assert next_sub1.status_code == 201
    assert next_sub1.json()["prefix"] == "172.16.0.0/24"
    assert next_sub1.json()["parent_id"] == parent_id

    # Allocate next available /24 subnet (should be 172.16.1.0/24)
    next_sub2 = client.post(f"/api/v1/subnets/{parent_id}/next-available", json={"new_prefix_len": 24})
    assert next_sub2.status_code == 201
    assert next_sub2.json()["prefix"] == "172.16.1.0/24"


# =========================================================================
# STATELESS CIDR UTILITY ROUTES TESTS
# =========================================================================
def test_cidr_info(client):
    resp = client.post("/api/v1/cidr/info", json={"cidr": "192.168.1.0/24"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["network_address"] == "192.168.1.0"
    assert data["netmask"] == "255.255.255.0"
    assert data["broadcast_address"] == "192.168.1.255"
    assert data["wildcard_mask"] == "0.0.0.255"
    assert data["first_usable_ip"] == "192.168.1.1"
    assert data["last_usable_ip"] == "192.168.1.254"
    assert data["total_ips"] == 256
    assert data["usable_ips"] == 254
    assert data["is_private"] is True

def test_cidr_split(client):
    resp = client.post("/api/v1/cidr/split", json={"cidr": "10.0.0.0/24", "new_prefix_len": 26})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 4
    assert "10.0.0.0/26" in data
    assert "10.0.0.64/26" in data
    assert "10.0.0.128/26" in data
    assert "10.0.0.192/26" in data

def test_cidr_supernet(client):
    resp = client.post("/api/v1/cidr/supernet", json={"prefixes": ["10.0.0.0/24", "10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["aggregated_prefixes"] == ["10.0.0.0/22"]

def test_cidr_difference(client):
    resp = client.post("/api/v1/cidr/difference", json={
        "parent": "10.0.0.0/24",
        "occupied": ["10.0.0.0/26", "10.0.0.128/25"]
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["free_prefixes"] == ["10.0.0.64/26"]

def test_cidr_collisions(client):
    # Overlapping items: VPC-A overlaps Subnet-B. VPC-C is clean.
    resp = client.post("/api/v1/cidr/check-collisions", json=[
        {"id": "VPC-A", "cidr": "10.0.0.0/24"},
        {"id": "Subnet-B", "cidr": "10.0.0.128/25"},
        {"id": "VPC-C", "cidr": "192.168.1.0/24"}
    ])
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_collisions"] is True
    assert len(data["collisions"]) == 1
    col = data["collisions"][0]
    assert col["id1"] == "VPC-A"
    assert col["id2"] == "Subnet-B"
    assert col["overlap_cidr"] == "10.0.0.128/25"
    assert "Subnet-B" in data["overlap_matrix"]["VPC-A"]
    assert "VPC-A" in data["overlap_matrix"]["Subnet-B"]
    assert len(data["overlap_matrix"]["VPC-C"]) == 0

