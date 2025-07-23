# Task: Rebuild User Authentication

**Type**: rebuild
**Component**: auth
**Priority**: critical

## Goal
Replace broken auth system with secure, testable implementation.

## Current State
- SQL injection vulnerabilities
- No password hashing
- Session management broken
- No tests

## Approach
1. Create new auth module with proper structure
2. Implement secure password hashing
3. Add JWT session management
4. Create comprehensive tests
5. Replace old system

## Done When
- [ ] Secure login/logout functionality
- [ ] Password hashing with salt
- [ ] Session management working
- [ ] Unit tests covering all auth functions
- [ ] Integration tests for auth flow
- [ ] Old auth system removed