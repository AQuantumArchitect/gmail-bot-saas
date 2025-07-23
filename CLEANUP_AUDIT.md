# Backend Test Cleanup Audit

## Files That Need Service Role Removal/Cleanup

### 🚨 **IMMEDIATE CLEANUP REQUIRED**

#### `tests/integration/test_supabase_interface.py`
- **Issue**: Uses `SUPABASE_SERVICE_KEY` throughout
- **Line 20-28**: `supabase_client()` fixture uses service key
- **All test classes**: Assume service role bypass of RLS
- **Action**: DELETE or completely rewrite

#### `tests/integration/test_simple_supabase.py`
- **Issue**: Tests both service and anon keys
- **Line 15-23**: Service key fixture
- **Action**: Keep anon key tests, remove service key tests

#### `tests/integration/test_schema_check.py`
- **Issue**: Uses service key exclusively
- **Line 19-22**: Service key fixture
- **Action**: DELETE - this was debugging code

#### `tests/integration/test_auth_schema.py`
- **Issue**: Tests service key permissions
- **Line 15-23**: Service key fixture
- **Action**: DELETE - this was debugging code

#### `tests/integration/test_postgrest_direct.py`
- **Issue**: Direct PostgREST testing with service key
- **Action**: DELETE - this was debugging code

## Backend Code Audit

### 🔍 **NEED TO AUDIT** (Currently Empty Files)

#### `app/data/database.py`
- **Status**: Empty file
- **Concern**: Might be planning service role database operations
- **Action**: Ensure any future code respects RLS

#### `app/data/repositories/*.py`
- **Status**: Empty files
- **Concern**: Repository pattern might assume service role access
- **Action**: When implemented, ensure they use authenticated clients

#### `app/services/*.py`
- **Status**: Empty files
- **Concern**: Services might assume ability to bypass RLS
- **Action**: When implemented, ensure they work with user sessions

#### `app/external/supabase_client.py`
- **Status**: Empty file
- **Concern**: Might configure service role client
- **Action**: Should use anon key + user sessions

## Legitimate Service Role Use Cases

### ✅ **KEEP SERVICE ROLE FOR**

1. **Background Jobs** (if truly needed)
   - Email processing that runs without user context
   - Scheduled tasks that operate on system data
   - **Important**: Minimize this - most jobs should run as the user

2. **System Administration**
   - Database migrations
   - System configuration updates
   - **Important**: Use Supabase Dashboard instead where possible

3. **Cross-User Operations** (rare)
   - Admin functions that need to see all users
   - Aggregations across all users
   - **Important**: Most admin functions should be in Dashboard

## Recommended Cleanup Actions

### 1. **Delete These Files**
```bash
rm tests/integration/test_schema_check.py
rm tests/integration/test_auth_schema.py
rm tests/integration/test_postgrest_direct.py
```

### 2. **Rewrite These Files**
- `tests/integration/test_supabase_interface.py` → Use new `test_rls_compliance.py`
- `tests/integration/test_simple_supabase.py` → Remove service key tests

### 3. **New RLS-Compliant Test**
- ✅ `tests/integration/test_rls_compliance.py` (already created)
- Tests all 9 tables with proper auth.uid() access
- Verifies RLS isolation between users
- No service role assumptions

## Backend Implementation Guidelines

### ✅ **DO THIS**
- Use anon key + user sessions for all user operations
- Respect RLS policies in all application code
- Use Supabase Dashboard for admin operations
- Test with actual authenticated users

### ❌ **DON'T DO THIS**
- Use service key for user operations
- Assume ability to bypass RLS
- Create "admin" endpoints that use service key
- Write tests that mock auth.uid()

## Next Steps

1. **Run new RLS tests**: `pytest tests/integration/test_rls_compliance.py`
2. **Delete debugging files**: Remove the 3 files listed above
3. **Audit empty backend files**: When implementing repositories/services
4. **Update documentation**: Reflect RLS-first approach

## Summary

**Files to delete**: 3 debugging files  
**Files to rewrite**: 2 test files  
**New RLS-compliant test**: ✅ Created  
**Backend files to audit**: All empty files when they get implemented  

The key principle: **Lean on Supabase's built-in tools instead of replicating admin functionality in code.**