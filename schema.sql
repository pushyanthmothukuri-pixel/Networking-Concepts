-- IPAM System Database Schema (PostgreSQL Reference)
-- Supports VRFs, hierarchical Subnets (Prefixes), and IP Address Allocations.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "btree_gist";

-- =========================================================================
-- 1. VRFS TABLE (Virtual Routing and Forwarding)
-- Isolates routing domains, allowing overlapping IP spaces.
-- =========================================================================
CREATE TABLE vrfs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    rd VARCHAR(255), -- Route Distinguisher (e.g., "65001:100")
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Unique index for name per VRF (VRF names should be unique)
CREATE UNIQUE INDEX idx_vrfs_name_unique ON vrfs (name);

-- Unique index for Route Distinguisher if provided
CREATE UNIQUE INDEX idx_vrfs_rd_unique ON vrfs (rd) WHERE rd IS NOT NULL;


-- =========================================================================
-- 2. SUBNETS TABLE (Prefixes)
-- Represents network blocks (e.g., 10.0.0.0/16, 10.0.1.0/24).
-- =========================================================================
CREATE TABLE subnets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vrf_id UUID REFERENCES vrfs(id) ON DELETE CASCADE,
    prefix CIDR NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active' 
        CHECK (status IN ('active', 'reserved', 'deprecated')),
    parent_id UUID REFERENCES subnets(id) ON DELETE SET NULL,
    is_pool BOOLEAN NOT NULL DEFAULT TRUE, -- If TRUE, host IPs can be allocated. If FALSE, only subnetting is allowed.
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    
    -- Ensure we only support IPv4 (for this implementation)
    CONSTRAINT chk_ipv4_only CHECK (family(prefix) = 4)
);

-- Unique index to prevent duplicate subnets within the same VRF (handling NULL VRF as global)
CREATE UNIQUE INDEX idx_subnets_prefix_vrf_unique 
ON subnets (COALESCE(vrf_id, '00000000-0000-0000-0000-000000000000'::uuid), prefix);

-- Index on parent_id to speed up tree traversal
CREATE INDEX idx_subnets_parent_id ON subnets (parent_id);

-- GiST index on the prefix column for rapid subnet containment querying (e.g., finding parents/children)
CREATE INDEX idx_subnets_prefix_gist ON subnets USING gist (prefix);


-- =========================================================================
-- 3. IP ADDRESSES TABLE
-- Represents allocated or reserved individual IPs (e.g., 10.0.1.1).
-- =========================================================================
CREATE TABLE ip_addresses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vrf_id UUID REFERENCES vrfs(id) ON DELETE CASCADE,
    subnet_id UUID REFERENCES subnets(id) ON DELETE SET NULL,
    address INET NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'allocated'
        CHECK (status IN ('allocated', 'reserved', 'dhcp', 'static')),
    dns_name VARCHAR(255),
    description TEXT,
    mac_address VARCHAR(17) 
        CHECK (mac_address IS NULL OR mac_address ~* '^([0-9a-f]{2}[:-]){5}([0-9a-f]{2})$'),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,

    -- Ensure we only support IPv4 (for this implementation)
    CONSTRAINT chk_ip_ipv4_only CHECK (family(address) = 4),
    
    -- Ensure address has a /32 host mask context
    CONSTRAINT chk_host_address CHECK (masklen(address) = 32)
);

-- Unique index to prevent duplicate IP addresses within the same VRF (handling NULL VRF as global)
CREATE UNIQUE INDEX idx_ip_addresses_vrf_unique 
ON ip_addresses (COALESCE(vrf_id, '00000000-0000-0000-0000-000000000000'::uuid), address);

-- Index on subnet_id for fast retrieval of all IPs within a specific subnet
CREATE INDEX idx_ip_addresses_subnet_id ON ip_addresses (subnet_id);

-- Index on raw address
CREATE INDEX idx_ip_addresses_address ON ip_addresses (address);


-- =========================================================================
-- TRIGGER: Automatic updated_at Update
-- =========================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER trigger_vrfs_updated_at BEFORE UPDATE ON vrfs FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER trigger_subnets_updated_at BEFORE UPDATE ON subnets FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER trigger_ip_addresses_updated_at BEFORE UPDATE ON ip_addresses FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
