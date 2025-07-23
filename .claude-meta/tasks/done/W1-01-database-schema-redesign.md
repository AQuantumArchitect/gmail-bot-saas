# Task: Database Schema Redesign

**Type**: rebuild  
**Component**: database  
**Priority**: critical  
**Week**: 1  
**Days**: 1-2  
**Dependencies**: None (foundational task)

## Goal
Analyze schema-code mismatches and design optimal database schema that matches business requirements and supports modern architecture patterns.

## Current State
- Database schema in `database_schema.txt` doesn't match `database.py` implementation
- OAuth token structure is inconsistent between schema and code
- Missing proper foreign key relationships
- No proper indexes for performance
- Schema causes runtime errors due to mismatches

## Target State
- Consistent schema that matches business requirements
- Proper foreign key relationships between tables
- Optimized indexes for performance
- OAuth token structure that matches implementation
- Migration-friendly schema design

## Approach
1. **Analyze Current Mismatches**
   - Compare `database_schema.txt` with `database.py` implementation
   - Document all schema-code inconsistencies
   - Identify root causes of runtime errors

2. **Design New Schema**
   - Create user_profiles table that matches business needs
   - Design proper OAuth token storage structure
   - Add processing_jobs table with proper relationships
   - Create usage_logs table for analytics
   - Design system_config table for application settings

3. **Optimize for Performance**
   - Add proper indexes for frequently queried columns
   - Design efficient foreign key relationships
   - Optimize data types for storage and query performance

4. **Create Migration Strategy**
   - Design migration-friendly schema structure
   - Plan for future schema changes
   - Create rollback capabilities

## Technical Requirements
- PostgreSQL 15+ compatible
- Supabase RLS (Row Level Security) integration
- Encrypted storage for sensitive data (OAuth tokens)
- UUID primary keys for scalability
- JSONB fields for flexible configuration

## Done When
- [ ] New schema design document created
- [ ] All schema-code mismatches identified and resolved
- [ ] OAuth token structure properly designed
- [ ] Foreign key relationships properly defined
- [ ] Indexes designed for optimal performance
- [ ] Migration strategy documented
- [ ] Schema validated against business requirements

## Tests Required
- [ ] Schema validation tests
- [ ] Foreign key constraint tests
- [ ] Index performance tests
- [ ] Migration rollback tests

## Files Created/Modified
- `database/new_schema.sql` - New schema design
- `database/migration_plan.md` - Migration strategy
- `.claude-meta/analysis/schema_analysis.md` - Schema comparison analysis

## Validation
- Schema matches all business requirements
- No runtime errors from schema-code mismatches
- Performance benchmarks meet targets
- Migration strategy tested and validated