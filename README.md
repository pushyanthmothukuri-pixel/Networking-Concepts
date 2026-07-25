# IPAM & CIDR Utility System

An enterprise-grade **IP Address Management (IPAM)** and **CIDR Calculator Suite** built to automate IP planning, subnet containment validation, IP allocation, and collision mapping.

🚀 **[Live Web Dashboard](https://ipam-dashboard.onrender.com/)**

---

## 🛠️ Key Features

### 1. Multi-Tenant VRF Isolation
Virtual Routing and Forwarding (VRF) support isolates routing domains, allowing overlapping private IP spaces (e.g. multiple clients utilizing `10.0.0.0/16`) in the same database without conflicts.

### 2. Hierarchical Subnetting (Tree Containment)
Strict parent-child network validations prevent overlapping routing paths:
- **Containers (`is_pool = False`)**: Subnets meant only to hold nested child subnets.
- **Pools (`is_pool = True`)**: Subnets configured to allocate host IP addresses. Pools cannot contain subnets.

### 3. Usable host IP Calculation
Automates host boundary checking:
- Respects **RFC 3021** (usable ranges for `/31` and `/32` networks).
- Excludes network and broadcast address boundaries for standard networks ($\le /30$).

### 4. Stateless CIDR Utility Suite
- **CIDR Inspector**: Calculates netmask, host ranges, capacity, and private/public routing status.
- **Subnet Splitter**: Splices ranges into smaller equal-sized sub-blocks.
- **Route Aggregator (Supernet)**: Summarizes contiguous networks to collapse routing tables.
- **CIDR Difference**: Excludes occupied blocks from parent network to find free blocks.
- **Collision Detector**: Identifies overlaps across multiple networks and outputs conflict lists with overlap domains.

---

## 📂 Project Structure

* `main.py`: FastAPI routes, CORS configurations, database initialization, and UI root routing.
* `models.py`: SQLAlchemy database models (VRF, Subnet, IPAddress) with custom TypeDecorators.
* `schemas.py`: Pydantic request and response schemas.
* `ipam_logic.py`: Core IPAM subnet containment, parent-child calculation, and IP lookup.
* `cidr_logic.py`: Core math calculations for CIDR info, supernetting, and collisions.
* `index.html`: Responsive single-page HTML5 dark-mode dashboard UI.
* `schema.sql`: Reference PostgreSQL schema SQL scripts with constraints and indexes.
* `test_ipam.py`: Extensive unit testing suite.
* `run_tests.py`: Python CLI automation script.

---

## 🚀 Local Installation & Setup

### 1. Clone the repository
```bash
git clone https://github.com/pushyanthmothukuri-pixel/Networking-Concepts.git
cd Networking-Concepts
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run Automated Tests
Run all unit tests:
```bash
python run_tests.py
```
To generate a JUnit XML test report (`test-results.xml`) for CI/CD pipelines:
```bash
python run_tests.py --report
```

### 4. Start the Application
Start the uvicorn development server:
```bash
uvicorn main:app --reload
```
Open your browser and navigate to:
- **Web Dashboard UI**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Swagger Documentation**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## ☁️ Deployment on Render

1. Log in to **Render.com** and click **New +** -> **Web Service**.
2. Select this GitHub repository.
3. Configure the following properties:
   - **Language**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add a **PostgreSQL Database** on Render (New -> PostgreSQL).
5. Go to your Web Service **Environment** settings and click **Add Environment Variable**:
   - **Key**: `DATABASE_URL`
   - **Value**: *postgresql://narayana_user:TzASFd0oQxNjQAiRBtQJOqM3DM2XdySj@dpg-d9i8g6b7uimc73b4ljn0-a/narayana*
6. Save Changes. Render will redeploy and configure PostgreSQL automatically.
