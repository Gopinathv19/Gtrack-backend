-- =====================================================
-- Supabase Row-Level Security policies for Gtrack
-- =====================================================
-- Apply this after `alembic upgrade head` (or after
-- creating tables) to enable multi-tenant isolation
-- using the JWT `org_id` custom claim.
--
-- All requests must carry a JWT whose payload contains:
--   { "org_id": "<organization_uuid>" }
-- which is then accessible from PostgreSQL via:
--   current_setting('request.jwt.claims', true)::json ->> 'org_id'
-- =====================================================

-- helper to read org_id claim
CREATE OR REPLACE FUNCTION public.current_org_id()
RETURNS uuid LANGUAGE sql STABLE AS $$
  SELECT COALESCE(
    NULLIF(current_setting('request.jwt.claims', true)::json ->> 'org_id', ''),
    NULLIF(current_setting('jwt.claims.org_id', true), '')
  )::uuid
$$;

-- ---------- organizations ----------
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON organizations;
CREATE POLICY tenant_isolation ON organizations
  USING (id = public.current_org_id())
  WITH CHECK (id = public.current_org_id());

-- ---------- instances ----------
ALTER TABLE instances ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON instances;
CREATE POLICY tenant_isolation ON instances
  USING (organization_id = public.current_org_id())
  WITH CHECK (organization_id = public.current_org_id());

-- ---------- groups ----------
ALTER TABLE groups ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON groups;
CREATE POLICY tenant_isolation ON groups
  USING (
    EXISTS (
      SELECT 1 FROM instances i
      WHERE i.id = groups.instance_id
        AND i.organization_id = public.current_org_id()
    )
  );

-- ---------- users ----------
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON users;
CREATE POLICY tenant_isolation ON users
  USING (organization_id = public.current_org_id())
  WITH CHECK (organization_id = public.current_org_id());

-- ---------- user_roles ----------
ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON user_roles;
CREATE POLICY tenant_isolation ON user_roles
  USING (
    EXISTS (
      SELECT 1 FROM users u
      WHERE u.id = user_roles.user_id
        AND u.organization_id = public.current_org_id()
    )
  );

-- ---------- invites ----------
ALTER TABLE invites ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON invites;
CREATE POLICY tenant_isolation ON invites
  USING (organization_id = public.current_org_id())
  WITH CHECK (organization_id = public.current_org_id());

-- ---------- locations ----------
ALTER TABLE locations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON locations;
CREATE POLICY tenant_isolation ON locations
  USING (
    EXISTS (
      SELECT 1 FROM groups g
      JOIN instances i ON i.id = g.instance_id
      WHERE g.id = locations.group_id
        AND i.organization_id = public.current_org_id()
    )
  );

-- ---------- assets ----------
ALTER TABLE assets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON assets;
CREATE POLICY tenant_isolation ON assets
  USING (organization_id = public.current_org_id())
  WITH CHECK (organization_id = public.current_org_id());

-- ---------- sacks ----------
ALTER TABLE sacks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON sacks;
CREATE POLICY tenant_isolation ON sacks
  USING (organization_id = public.current_org_id())
  WITH CHECK (organization_id = public.current_org_id());

-- ---------- asset_movements, sack_movements ----------
ALTER TABLE asset_movements ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON asset_movements;
CREATE POLICY tenant_isolation ON asset_movements
  USING (
    EXISTS (
      SELECT 1 FROM assets a
      WHERE a.id = asset_movements.asset_id
        AND a.organization_id = public.current_org_id()
    )
  );

ALTER TABLE sack_movements ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON sack_movements;
CREATE POLICY tenant_isolation ON sack_movements
  USING (
    EXISTS (
      SELECT 1 FROM sacks s
      WHERE s.id = sack_movements.sack_id
        AND s.organization_id = public.current_org_id()
    )
  );
