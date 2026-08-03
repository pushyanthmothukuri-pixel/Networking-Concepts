# Enterprise IPAM & CIDR Utility System
## Complete Technical Specification, Architectural Blueprints, and System Manual

---

### Executive Overview & Document Metadata

* **Document Title:** Enterprise IPAM & CIDR Utility System Technical Reference Manual
* **Version:** 1.0.0 (Production Release)
* **Project Team / Authors:**
  1. M. Pushyanth
  2. B. Narayana
  3. Sharook
  4. M. Balaji
* **Target Audience:** Cloud Engineers, Network Architects, DevOps Engineers, and Software Developers
* **System Scope:** State-managed Multi-tenant IP Address Management (IPAM) & Stateless CIDR Math Engine

---

## 1. System Vision & Architecture Overview

### 1.1 Business Rationale & Problem Statement
Modern cloud infrastructure, hybrid networking environments, and multi-tenant enterprise data centers demand rigorous IP Address Management (IPAM). Unplanned IP address assignments inevitably lead to subnet overlaps, routing table bloat, IP space exhaustion, and catastrophic cross-tenant traffic leaks.

The **Enterprise IPAM & CIDR Utility System** is a production-grade, dual-capability networking platform built with **FastAPI**, **SQLAlchemy 2.0**, **Pydantic v2**, and **PostgreSQL/SQLite**. It solves core enterprise networking challenges by providing:
1. **Stateless CIDR Math Suite:** High-speed calculation of netmasks, host boundaries, binary-tree subnet differences, supernet aggregation, and multi-network collision detection.
2. **Stateful Multi-Tenant IPAM Engine:** Tree-structured subnet containment, Virtual Routing and Forwarding (VRF) isolation, automatic next-available subnet/IP allocation, and live utilization metrics.

---

### 1.2 High-Level Architecture Diagram

```mermaid
graph TD
    User([Network Admin / API Client]) --> UI[HTML5/CSS3 Dark-Mode Dashboard]
    User --> API Gateway[FastAPI REST Engine / Uvicorn API]
    
    subgraph FastAPI Framework Layer
        UI --> Static[Index HTML UI Root /]
        API Gateway --> Exception[IPAMValidationError Handler]
        API Gateway --> CORS[CORS Middleware]
        
        API Gateway --> VRF Router[/api/v1/vrfs]
        API Gateway --> Subnet Router[/api/v1/subnets]
        API Gateway --> IP Router[/api/v1/ip-addresses]
        API Gateway --> CIDR Router[/api/v1/cidr]
    end

    subgraph Core Business Logic Layer
        Subnet Router --> IPAM Logic[ipam_logic.py: Containment & Allocation Engine]
        IP Router --> IPAM Logic
        CIDR Router --> CIDR Logic[cidr_logic.py: Binary Tree Math Suite]
    end

    subgraph Data & Persistence Layer
        IPAM Logic --> ORM[SQLAlchemy Declarative Models: models.py]
        ORM --> DB Decorators[Type Decorators: IPv4NetworkType / IPv4AddressType]
        DB Decorators --> Database[(PostgreSQL / SQLite Database)]
    end
```

---

## 2. Technology Stack & Key Innovations

| Layer | Component | Version / Technology | Key Responsibilities |
| :--- | :--- | :--- | :--- |
| **API Framework** | FastAPI | `0.100.0+` | High-performance async/sync REST API endpoints, OpenAPI/Swagger generation. |
| **Data Validation** | Pydantic | `v2.0+` | Strict schema validation, custom field validators, data serialization. |
| **ORM / Data Access** | SQLAlchemy | `2.0+` | Declarative mapping, session management, relational tree navigation. |
| **Database Engines** | PostgreSQL / SQLite | Postgres 14+ / SQLite3 | Relational database with GiST CIDR spatial index support and WAL mode. |
| **Core Networking** | Python `ipaddress` | Standard Library | Standards-compliant IPv4 netmask, network, broadcast, and host manipulation. |
| **Frontend UI** | HTML5 / CSS3 / Vanilla JS | ES6 Native | Single Page Dark-Mode Dashboard, asynchronous AJAX client. |
| **Testing** | Pytest & FastAPI TestClient | `7.0+` | Automated regression testing, JUnit XML integration for CI/CD pipelines. |

---

## 3. Multi-Tenant VRF Isolation Architecture

### 3.1 Concept of Virtual Routing and Forwarding (VRF)
Virtual Routing and Forwarding (VRF) is a core networking technology that allows multiple instances of a routing table to co-exist within the same router or IPAM database simultaneously. 

Without VRF isolation, two subnets using the private IP range `10.0.0.0/16` would collide in the database. With VRF isolation:
* **Tenant A (e.g., Client Alpha)** uses `10.0.0.0/16` under `VRF-Alpha` (Route Distinguisher `65000:100`).
* **Tenant B (e.g., Client Beta)** uses `10.0.0.0/16` under `VRF-Beta` (Route Distinguisher `65000:200`).
* **Global Table (Null VRF)** holds shared corporate enterprise infrastructure.

```
                   +---------------------------------------+
                   |       Global IPAM Database            |
                   +---------------------------------------+
                                       |
         +-----------------------------+-----------------------------+
         |                                                           |
+-------------------+                                       +-------------------+
|  VRF: Client-A    |                                       |  VRF: Client-B    |
|  RD: 65000:100    |                                       |  RD: 65000:200    |
+-------------------+                                       +-------------------+
| 10.0.0.0/16       | <--- Isolated Overlapping Ranges ---> | 10.0.0.0/16       |
| ├── 10.0.1.0/24   |                                       | ├── 10.0.1.0/24   |
| └── 10.0.2.0/24   |                                       | └── 10.0.2.0/24   |
+-------------------+                                       +-------------------+
```

### 3.2 Database Partial Unique Constraint Enforcement
To guarantee multi-tenant isolation at the database layer while preventing duplicate prefixes within the same tenant, custom partial unique indexes are enforced in PostgreSQL and SQLAlchemy:

$$\text{Unique Key} = (\text{COALESCE}(\text{vrf\_id}, \text{'00000000-0000-0000-0000-000000000000'}), \text{prefix})$$

```sql
CREATE UNIQUE INDEX idx_subnets_prefix_vrf_unique 
ON subnets (COALESCE(vrf_id, '00000000-0000-0000-0000-000000000000'::uuid), prefix);
```

---

## 4. Hierarchical Subnet Containment Engine

### 4.1 Container Subnets vs. Allocation Pools
The IPAM system models subnets in a dynamic tree structure (`parent_id` foreign key referencing `subnets.id`). Subnets are categorized into two explicit functional types:

1. **Containers (`is_pool = False`):**
   * High-level network blocks (e.g., `10.0.0.0/8`, `172.16.0.0/12`) meant exclusively to group and organize child subnets.
   * **Rule:** Host IP addresses (`IPAddress` records) **cannot** be allocated directly from a container subnet.
   * **Utilization Metric:** Calculated based on the percentage of total parent address space covered by nested child subnets.

2. **Allocation Pools (`is_pool = True`):**
   * Leaf node subnets (e.g., `10.0.1.0/24`, `192.168.1.0/28`) dedicated to allocating individual host IP addresses.
   * **Rule:** Child subnets **cannot** be created inside an allocation pool.
   * **Utilization Metric:** Calculated based on the percentage of usable host IPs currently assigned.

```
10.0.0.0/16 [Container, is_pool=False] (Root)
│
├── 10.0.1.0/24 [Pool, is_pool=True] (Allocates host IPs: 10.0.1.1, 10.0.1.2)
└── 10.0.2.0/24 [Container, is_pool=False] (Intermediate)
    │
    ├── 10.0.2.0/25 [Pool, is_pool=True] (Allocates host IPs: 10.0.2.1 ... 10.0.2.126)
    └── 10.0.2.128/25 [Pool, is_pool=True] (Allocates host IPs)
```

---

### 4.2 Containment Validation Algorithm (`validate_and_find_relations`)

When a user submits a request to register a new subnet prefix $P_{\text{new}}$ in VRF $V$, the engine executes the following non-disruptive validation routine:

```python
def validate_and_find_relations(session: Session, new_prefix: IPv4Network, vrf_id: Optional[UUID]):
    # 1. Query all existing subnets within the specified VRF context
    existing_subnets = fetch_vrf_subnets(session, vrf_id)
    
    parent_candidate = None
    children_candidates = []
    
    for existing in existing_subnets:
        # Rule A: Reject exact duplicate prefixes
        if existing.prefix == new_prefix:
            raise IPAMValidationError("Subnet prefix already exists in this VRF.")
            
        # Rule B: Inspect CIDR containment if overlap occurs
        if new_prefix.overlaps(existing.prefix):
            if new_prefix.subnet_of(existing.prefix):
                # Find smallest/tightest parent container
                if not parent_candidate or existing.prefix.subnet_of(parent_candidate.prefix):
                    parent_candidate = existing
            elif existing.prefix.subnet_of(new_prefix):
                # Existing subnet becomes a child of new_prefix
                children_candidates.append(existing)
            else:
                raise IPAMValidationError("Invalid partial overlap detected.")
                
    # Rule C: Enforce pool restriction
    if parent_candidate and parent_candidate.is_pool:
        raise IPAMValidationError("Cannot create subnets inside an allocation pool.")
        
    return parent_candidate, children_candidates
```

---

## 5. Usable IP Calculation & Boundary Mechanics

### 5.1 Standard Networks vs. RFC 3021 Point-to-Point Links

Calculating usable host IP counts requires adherence to RFC standards depending on prefix length:

1. **Standard Networks ($\le /30$):**
   * The first IP address is reserved as the **Network Address** (all host bits `0`).
   * The last IP address is reserved as the **Broadcast Address** (all host bits `1`).
   
   $$\text{Total IPs} = 2^{(32 - \text{prefixlen})}$$
   $$\text{Usable IPs} = 2^{(32 - \text{prefixlen})} - 2$$

2. **Point-to-Point Links & Single Hosts ($/31$ and $/32$ per RFC 3021):**
   * $/31$ Subnets (2 addresses): Used for point-to-point router links. Both addresses are fully usable hosts.
   * $/32$ Subnets (1 address): Loopback interfaces or single host routes. The single address is fully usable.
   
   $$\text{Usable IPs} = \text{Total IPs}$$

---

### 5.2 Next Available IP Allocation Routine (`find_next_available_ip`)

The engine automatically computes and allocates the lowest available host IP within an allocation pool:

```python
def find_next_available_ip(session: Session, subnet_id: UUID) -> IPv4Address:
    subnet = session.get(Subnet, subnet_id)
    if not subnet.is_pool:
        raise IPAMValidationError("Cannot allocate IPs from a container subnet.")
        
    allocated_ips = set(session.scalars(
        select(IPAddress.address).where(IPAddress.subnet_id == subnet_id)
    ).all())
    
    # Determine IP generator based on prefix length
    ip_generator = subnet.prefix.hosts() if subnet.prefix.prefixlen <= 30 else list(subnet.prefix)
    
    for candidate_ip in ip_generator:
        if candidate_ip not in allocated_ips:
            return candidate_ip
            
    raise IPAMValidationError("Subnet IP space exhausted.")
```

---

## 6. Stateless CIDR Utility Suite & Algorithms

The system includes a stateless math engine for network planning without requiring database persistence.

### 6.1 CIDR Inspection (`get_cidr_details`)
Extracted properties from any valid CIDR string (e.g., `192.168.1.0/24`):
* **Network Address:** `192.168.1.0`
* **Netmask:** `255.255.255.0`
* **Broadcast Address:** `192.168.1.255`
* **Wildcard Mask:** `0.0.0.255`
* **First Usable IP:** `192.168.1.1`
* **Last Usable IP:** `192.168.1.254`
* **Flags:** `is_private`, `is_loopback`, `is_multicast`, `is_link_local`, `is_global`, `is_reserved`.

---

### 6.2 Binary-Tree CIDR Difference (`subtract_cidrs`)
Carves occupied sub-blocks out of a parent subnet block, returning the remaining available CIDR blocks.

**Algorithm Mechanism:**
1. Start with the set of free blocks containing only the parent: $\mathcal{F} = \{P\}$.
2. For each occupied block $O$:
   - For each block $F \in \mathcal{F}$:
     - If $F \cap O = \emptyset$, retain $F$.
     - If $F \subseteq O$, drop $F$.
     - If $O \subset F$, split $F$ recursively into binary halves ($C_1, C_2$) until the exact occupied block is isolated and removed.

```
Parent: 10.0.0.0/24 (256 IPs)
Occupied: [10.0.0.0/26, 10.0.0.128/25]

Step 1: Split 10.0.0.0/24 into 10.0.0.0/25 and 10.0.0.128/25.
        Drop 10.0.0.128/25 (Occupied).
Step 2: Split 10.0.0.0/25 into 10.0.0.0/26 and 10.0.0.64/26.
        Drop 10.0.0.0/26 (Occupied).

Resulting Free Subnets: [10.0.0.64/26]
```

---

### 6.3 CIDR Collision Detector (`detect_cidr_collisions`)
Performs pairwise $O(N^2)$ inspection across arbitrary lists of networks to identify overlapping scopes (e.g., checking for collisions between cloud VPCs, branch subnets, or client IP requests).

**Output Structure:**
* `has_collisions`: Boolean flag.
* `collisions`: List of overlap pairs showing target identifiers and the specific overlapping CIDR block.
* `overlap_matrix`: Adjacency matrix dictionary mapping each network ID to all colliding network IDs.

---

## 7. Database Architecture & Schema Specification

### 7.1 Entity-Relationship Diagram (ERD)

```mermaid
erdiagram
    VRF ||--o{ SUBNET : "contains"
    VRF ||--o{ IP_ADDRESS : "isolates"
    SUBNET ||--o{ SUBNET : "parent of"
    SUBNET ||--o{ IP_ADDRESS : "holds allocations"

    VRF {
        uuid id PK
        string name UK
        string rd UK
        text description
        timestamp created_at
        timestamp updated_at
    }

    SUBNET {
        uuid id PK
        uuid vrf_id FK
        cidr prefix
        string status
        uuid parent_id FK
        boolean is_pool
        text description
        timestamp created_at
        timestamp updated_at
    }

    IP_ADDRESS {
        uuid id PK
        uuid vrf_id FK
        uuid subnet_id FK
        inet address
        string status
        string dns_name
        string mac_address
        text description
        timestamp created_at
        timestamp updated_at
    }
```

---

### 7.2 Core SQL Schema Definitions (`schema.sql`)

```sql
-- PostgreSQL Extension Enablement
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "btree_gist";

-- 1. VRF Table
CREATE TABLE vrfs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL UNIQUE,
    rd VARCHAR(255) UNIQUE,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2. Subnets Table
CREATE TABLE subnets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vrf_id UUID REFERENCES vrfs(id) ON DELETE CASCADE,
    prefix CIDR NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'reserved', 'deprecated')),
    parent_id UUID REFERENCES subnets(id) ON DELETE SET NULL,
    is_pool BOOLEAN NOT NULL DEFAULT TRUE,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT chk_ipv4_only CHECK (family(prefix) = 4)
);

CREATE INDEX idx_subnets_parent_id ON subnets (parent_id);
CREATE INDEX idx_subnets_prefix_gist ON subnets USING gist (prefix);

-- 3. IP Addresses Table
CREATE TABLE ip_addresses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vrf_id UUID REFERENCES vrfs(id) ON DELETE CASCADE,
    subnet_id UUID REFERENCES subnets(id) ON DELETE SET NULL,
    address INET NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'allocated' CHECK (status IN ('allocated', 'reserved', 'dhcp', 'static')),
    dns_name VARCHAR(255),
    description TEXT,
    mac_address VARCHAR(17) CHECK (mac_address IS NULL OR mac_address ~* '^([0-9a-f]{2}[:-]){5}([0-9a-f]{2})$'),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT chk_ip_ipv4_only CHECK (family(address) = 4),
    CONSTRAINT chk_host_address CHECK (masklen(address) = 32)
);

CREATE INDEX idx_ip_addresses_subnet_id ON ip_addresses (subnet_id);
CREATE INDEX idx_ip_addresses_address ON ip_addresses (address);
```

---

### 7.3 Custom SQLAlchemy Type Decorators (`models.py`)

Python's native `ipaddress` objects do not automatically serialize to standard string columns in SQLite or PostgreSQL without custom type conversion. The system utilizes custom SQLAlchemy `TypeDecorator` instances:

```python
class IPv4NetworkType(TypeDecorator):
    impl = String(49)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(value) if isinstance(value, ipaddress.IPv4Network) else str(ipaddress.IPv4Network(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return ipaddress.IPv4Network(value)
```

---

## 8. RESTful API Endpoints Reference

### 8.1 VRF Management Endpoints

#### `POST /api/v1/vrfs`
Creates a new Virtual Routing and Forwarding (VRF) domain.
* **Request Body:**
  ```json
  {
    "name": "Production-Cloud",
    "rd": "65000:100",
    "description": "Primary AWS VPC routing domain"
  }
  ```
* **Response (`201 Created`):**
  ```json
  {
    "id": "e4b3c2a1-8901-4bcd-ef01-23456789abcd",
    "name": "Production-Cloud",
    "rd": "65000:100",
    "description": "Primary AWS VPC routing domain",
    "created_at": "2026-08-03T14:20:00Z",
    "updated_at": "2026-08-03T14:20:00Z"
  }
  ```

#### `GET /api/v1/vrfs`
Lists all configured VRF domains.

#### `DELETE /api/v1/vrfs/{id}`
Deletes a VRF and cascades deletion to all associated subnets and IP allocations (`204 No Content`).

---

### 8.2 Subnet Management Endpoints

#### `POST /api/v1/subnets`
Registers a new subnet prefix with dynamic parent-child tree linking and collision validation.
* **Request Body:**
  ```json
  {
    "prefix": "10.0.0.0/16",
    "vrf_id": "e4b3c2a1-8901-4bcd-ef01-23456789abcd",
    "status": "active",
    "is_pool": false,
    "description": "Corporate Root Block"
  }
  ```
* **Response (`201 Created`):**
  ```json
  {
    "id": "11223344-5566-7788-9900-aabbccddeeff",
    "vrf_id": "e4b3c2a1-8901-4bcd-ef01-23456789abcd",
    "prefix": "10.0.0.0/16",
    "status": "active",
    "parent_id": null,
    "is_pool": false,
    "description": "Corporate Root Block",
    "created_at": "2026-08-03T14:21:00Z",
    "updated_at": "2026-08-03T14:21:00Z"
  }
  ```

#### `GET /api/v1/subnets/{id}/utilization`
Returns real-time capacity and utilization metrics.
* **Response (`200 OK` for Pool Subnet):**
  ```json
  {
    "subnet_id": "11223344-5566-7788-9900-aabbccddeeff",
    "prefix": "10.0.1.0/24",
    "is_pool": true,
    "total_ips": 256,
    "usable_ips": 254,
    "allocated_ips": 127,
    "free_ips": 127,
    "utilization_percentage": 50.0
  }
  ```

#### `POST /api/v1/subnets/{id}/next-available`
Finds and registers the next available sub-block inside a container parent subnet.
* **Request Body:**
  ```json
  { "new_prefix_len": 24 }
  ```
* **Response (`201 Created`):** Returns the newly allocated `SubnetResponse`.

---

### 8.3 IP Address Management Endpoints

#### `POST /api/v1/subnets/{id}/allocate-ip`
Allocates the next lowest available host IP address from an allocation pool subnet.
* **Request Body:**
  ```json
  {
    "status": "allocated",
    "dns_name": "web-server-01.internal",
    "description": "Primary Nginx Node",
    "mac_address": "00:1B:44:11:3A:B7"
  }
  ```
* **Response (`201 Created`):**
  ```json
  {
    "id": "77889900-aabb-ccdd-eeff-001122334455",
    "vrf_id": "e4b3c2a1-8901-4bcd-ef01-23456789abcd",
    "subnet_id": "11223344-5566-7788-9900-aabbccddeeff",
    "address": "10.0.1.1",
    "status": "allocated",
    "dns_name": "web-server-01.internal",
    "description": "Primary Nginx Node",
    "mac_address": "00:1B:44:11:3A:B7",
    "created_at": "2026-08-03T14:22:00Z",
    "updated_at": "2026-08-03T14:22:00Z"
  }
  ```

#### `DELETE /api/v1/ip-addresses/{id}`
Deallocates an IP address, freeing it back to the subnet pool (`204 No Content`).

---

### 8.4 Stateless CIDR Utility Endpoints

| Method | Route | Description | Input Payload | Output Payload |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/cidr/info` | Inspect Network Details | `{"cidr": "192.168.1.0/24"}` | Network mask, broadcast, usable IPs, flags |
| `POST` | `/api/v1/cidr/split` | Split CIDR into sub-blocks | `{"cidr": "10.0.0.0/24", "new_prefix_len": 26}` | Array of 4 subnets (`/26`) |
| `POST` | `/api/v1/cidr/supernet` | Collapse contiguous routes | `{"prefixes": ["10.0.0.0/24", "10.0.1.0/24"]}` | Collapsed supernet (`10.0.0.0/23`) |
| `POST` | `/api/v1/cidr/difference` | Binary-tree free space subtract | `{"parent": "10.0.0.0/24", "occupied": [...]}` | Remaining unallocated free CIDR blocks |
| `POST` | `/api/v1/cidr/check-collisions` | Pairwise overlap detection | `[{"id": "VPC-A", "cidr": "10.0.0.0/16"}, ...]` | Overlap pairs & adjacency matrix |

---

## 9. Dashboard UI Architecture (`index.html`)

The system includes a single-page dark-mode administrative dashboard served directly from the FastAPI root `/`.

### 9.1 Visual Theme & CSS Token Architecture
* **Dark Mode Palette:** Built using Tailwind-inspired HSL color tokens (`#0f172a` primary background, `#1e293b` card container background, `#6366f1` indigo primary accent).
* **Typography:** Inter / System UI sans-serif fonts with monospace rendering for IP/CIDR addresses.
* **Component System:** Responsive tabs (IPAM Management vs. Stateless CIDR Tools), modal windows, progress bars for subnet utilization, and dynamic badges for subnet/IP status.

```
+-----------------------------------------------------------------------------------+
|  🌐 Enterprise IPAM & CIDR Utility Dashboard                                     |
+-----------------------------------------------------------------------------------+
|  [VRF Selector: Default Global]  [+ New VRF]  [+ New Subnet]  [+ Allocate IP]    |
+-----------------------------------------------------------------------------------+
|  Tab 1: Stateful IPAM Explorer          | Tab 2: Stateless CIDR Calculator Suite |
|  -------------------------------------  | -------------------------------------- |
|  Subnet Tree View                       | [CIDR Inspector]   [Subnet Splitter]   |
|  ├── 10.0.0.0/16 (Container)            | [Supernet Aggregator]                  |
|  │   └── 10.0.1.0/24 (Pool - 50% Util)  | [CIDR Difference]                      |
|  │       ├── 10.0.1.1 (web-server-01)   | [Collision Detector]                   |
|  │       └── 10.0.1.2 (db-primary)     |                                        |
+-----------------------------------------------------------------------------------+
```

---

## 10. Automated Testing & Quality Assurance Suite

### 10.1 Test Architecture (`test_ipam.py`)
The system includes an automated unit testing suite utilizing `pytest` and FastAPI's `TestClient`.

* **Database Isolation:** Tests run against an isolated SQLite file (`test_ipam.db`) with `PRAGMA foreign_keys=ON`.
* **Clean State Guarantee:** Pytest fixtures enforce table re-creation (`drop_all` and `create_all`) before every individual test function runs.

```
test_ipam.py
├── test_create_and_list_vrfs
├── test_create_subnets_hierarchy
├── test_subnet_utilization
├── test_ip_allocation_flow
├── test_subnet_split_and_next_subnet
├── test_cidr_info
├── test_cidr_split
├── test_cidr_supernet
├── test_cidr_difference
└── test_cidr_collisions
```

---

### 10.2 Test Execution Scripts

Cross-platform test runners are provided in the repository root:
* **PowerShell (`run_tests.ps1`):** `pytest test_ipam.py -v --junitxml=test-results.xml`
* **Python CLI (`run_tests.py`):** Multi-platform test runner supporting `--report` flags.
* **Shell Script (`run_tests.sh`):** Bash execution script for Linux/macOS environments.

---

## 11. Local Installation & Deployment Guide

### 11.1 Local Development Environment Setup

1. **Clone Repository & Set Up Virtual Environment:**
   ```bash
   git clone https://github.com/pushyanthmothukuri-pixel/Networking-Concepts.git
   cd Networking-Concepts
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run Automated Test Suite:**
   ```bash
   python run_tests.py
   ```

4. **Launch Local Server:**
   ```bash
   uvicorn main:app --reload --host 127.0.0.1 --port 8000
   ```
   * **Dashboard URL:** `http://127.0.0.1:8000/`
   * **Swagger API Docs:** `http://127.0.0.1:8000/docs`

---

### 11.2 Production Cloud Deployment (Render.com)

1. Log into **Render.com** and create a **PostgreSQL Database**.
2. Create a new **Web Service** pointing to your repository.
3. Configure settings:
   * **Runtime:** `Python 3`
   * **Build Command:** `pip install -r requirements.txt`
   * **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add Environment Variable:
   * **Key:** `DATABASE_URL`
   * **Value:** `<Render Internal Database URL>`
5. Deploy. The application automatically handles SQLAlchemy `postgres://` to `postgresql://` string normalization and creates all database tables on startup.

---

## 12. Troubleshooting & Error Diagnostics Guide

| HTTP Code | Error Message Detail | Root Cause | Solution |
| :--- | :--- | :--- | :--- |
| `400 Bad Request` | `Subnet prefix X already exists in this VRF.` | Duplicate CIDR entry within the same VRF tenant. | Use a distinct CIDR or select the appropriate VRF context. |
| `400 Bad Request` | `Cannot create subnet inside X because it is configured as an IP allocation pool.` | Attempted to create a child subnet inside a subnet marked `is_pool=True`. | Change parent `is_pool` flag to `False` or create subnet inside a container. |
| `400 Bad Request` | `Cannot allocate host IPs from a container subnet.` | Attempted to allocate an IP address inside a subnet marked `is_pool=False`. | Set `is_pool=True` on the target subnet before allocating host IPs. |
| `400 Bad Request` | `IP Address X is not within subnet Y.` | Specified IP host falls outside the network prefix range. | Ensure the IP falls strictly between the network and broadcast address. |
| `400 Bad Request` | `No free IP addresses available in subnet X.` | Allocation pool capacity exhausted. | Expand subnet prefix length or deallocate unused IP addresses. |

---

## 13. System Summary & Future Roadmap

The **Enterprise IPAM & CIDR Utility System** delivers an enterprise-ready foundation for IP address planning and network management. 

### Roadmap Enhancements:
1. **IPv6 Support:** Extending custom type decorators and math utilities to support dual-stack IPv6 prefixes (`/64`, `/48`, `/128`).
2. **RBAC & Authentication:** Integrating OAuth2 / JWT authentication with Role-Based Access Control (Admin, Operator, Read-Only).
3. **External Sync Adapters:** Direct synchronization plugins for Cloud Providers (AWS VPCs, Azure VNets, GCP Cloud Routers) and NetBox APIs.

---
*End of Technical Specification Document.*
