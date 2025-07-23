# Target Architecture: What We're Building

## Vision: Modern SaaS Email Processing Platform
**Credit-based email processing with Gmail integration, built for scale**

## Core Business Flow
```
User Registration → Gmail OAuth → Credit Purchase → Email Processing → AI Summaries
```

## System Architecture

### High-Level Layers
```
┌─────────────────────────────────────────────────────┐
│                 API LAYER                           │
│  FastAPI Routes + Validation + Authentication       │
└─────────────────────────────────────────────────────┘
                           │
┌─────────────────────────────────────────────────────┐
│               SERVICE LAYER                         │
│  Business Logic + Orchestration                     │
└─────────────────────────────────────────────────────┘
                           │
┌─────────────────────────────────────────────────────┐
│                DATA LAYER                           │
│  Repository Pattern + Database Operations           │
└─────────────────────────────────────────────────────┘
                           │
┌─────────────────────────────────────────────────────┐
│            EXTERNAL SERVICES                        │
│  Gmail + Stripe + Anthropic + Supabase              │
└─────────────────────────────────────────────────────┘
```

## Detailed Architecture

### 1. API Layer (`app/api/`)
**Responsibility**: HTTP request/response handling, validation, authentication

```python
# app/api/routes/
auth.py          # Authentication endpoints
dashboard.py     # User dashboard API
gmail.py         # Gmail integration endpoints
billing.py       # Stripe billing endpoints
admin.py         # Admin functionality
health.py        # Health checks

# app/api/
middleware.py    # Custom middleware
dependencies.py  # FastAPI dependencies
exceptions.py    # HTTP exception handlers
```

**Key Features**:
- Pydantic request/response models
- JWT authentication
- Rate limiting
- Input validation
- Comprehensive error handling

### 2. Service Layer (`app/services/`)
**Responsibility**: Business logic orchestration, external API coordination

```python
auth_service.py       # User authentication business logic
gmail_service.py      # Gmail API integration + OAuth
email_service.py      # Email processing pipeline
billing_service.py    # Credit system + Stripe integration
job_service.py        # Background job management
user_service.py       # User profile management
```

**Key Patterns**:
- Dependency injection
- Repository pattern usage
- External service coordination
- Business rule enforcement
- Error handling and retry logic

### 3. Data Layer (`app/data/`)
**Responsibility**: Database operations, data modeling

```python
# app/data/repositories/
user_repository.py           # User CRUD operations
gmail_repository.py          # Gmail connection data
email_repository.py          # Email processing data
billing_repository.py       # Credit transactions
job_repository.py            # Background job data

# app/data/
database.py                  # Database connection + utilities
models.py                    # Pydantic models for data
migrations.py                # Database schema management
```

**Key Features**:
- Repository pattern
- Type-safe operations
- Transaction support
- Audit logging
- Connection pooling

### 4. External Integrations (`app/external/`)
**Responsibility**: External API clients with proper error handling

```python
gmail_client.py       # Gmail API client
stripe_client.py      # Stripe API client
anthropic_client.py   # Anthropic AI client
supabase_client.py    # Supabase client wrapper
```

**Key Features**:
- Circuit breakers
- Retry mechanisms
- Rate limiting
- Proper error handling
- Mock interfaces for testing

### 5. Core Utilities (`app/core/`)
**Responsibility**: Shared utilities, configuration

```python
config.py         # Application configuration (keep current)
security.py       # Security utilities
exceptions.py     # Custom exceptions
logging.py        # Logging setup
utils.py          # General utilities
```

## Database Schema Design

### Core Tables
```sql
-- User Management
users                 # User profiles and preferences
gmail_connections     # OAuth tokens and connection status
user_sessions        # Active user sessions

-- Email Processing
email_discoveries    # Discovered emails (stage 1)
processing_jobs      # Background processing jobs (stage 2)
email_summaries      # Generated summaries (stage 3)
email_actions        # Actions taken on emails

-- Billing & Usage
credit_transactions  # Credit purchases and usage
stripe_payments      # Payment processing records
usage_analytics      # User behavior tracking
billing_history      # Historical billing data

-- System
background_jobs      # System job queue
system_config        # Application configuration
audit_logs          # Security and compliance logs
```

### Key Features
- **UUID primary keys** for distributed systems
- **Row Level Security** for data isolation
- **Encrypted token storage** for OAuth
- **Audit trail** for all operations
- **Proper indexes** for performance

## Business Logic Flows

### 1. User Registration & OAuth
```python
# POST /api/auth/register
AuthService.register_user()
  └── UserRepository.create_user()
  └── GmailService.initiate_oauth()
      └── GmailClient.get_oauth_url()
```

### 2. Email Processing Pipeline
```python
# Background job triggered
EmailService.process_user_emails()
  └── GmailService.discover_emails()
      └── EmailRepository.create_discoveries()
  └── JobService.create_processing_jobs()
      └── AnthropicClient.generate_summaries()
  └── EmailService.store_summaries()
      └── BillingService.deduct_credits()
```

### 3. Credit Purchase
```python
# POST /api/billing/purchase
BillingService.create_purchase_session()
  └── StripeClient.create_checkout_session()
  └── BillingRepository.create_payment_record()
  
# Stripe webhook
BillingService.handle_payment_success()
  └── BillingRepository.add_credits()
  └── UserRepository.update_credit_balance()
```

## Testing Strategy

### Test Structure
```
tests/
├── unit/                    # Fast, isolated tests
│   ├── services/            # Business logic tests
│   ├── repositories/        # Data layer tests
│   └── utils/               # Utility tests
├── integration/             # Service interaction tests
│   ├── api/                 # API endpoint tests
│   ├── external/            # External service tests
│   └── workflows/           # Multi-service tests
└── e2e/                     # End-to-end user flows
    ├── registration/        # User registration flow
    ├── email_processing/    # Email processing flow
    └── billing/             # Credit purchase flow
```

### Mock Strategy
- **External APIs**: Mock Gmail, Stripe, Anthropic
- **Database**: Mock repository layer
- **Services**: Mock service dependencies
- **Real integrations**: Only in integration tests

## Configuration Management

### Environment-Based Config
```python
# app/core/config.py (keep current Pydantic V2)
class Settings(BaseSettings):
    # Database
    supabase_url: str
    supabase_key: str
    
    # External APIs
    google_client_id: str
    stripe_secret_key: str
    anthropic_api_key: str
    
    # Feature flags
    enable_background_processing: bool = True
    enable_stripe: bool = True
    
    # Security
    jwt_secret: str
    session_secret: str
```

## Security Architecture

### Authentication Flow
```python
# JWT-based authentication
User Login → JWT Token → Request Headers → Validation → User Context
```

### Authorization Levels
- **Public**: Registration, login
- **Authenticated**: Dashboard, email processing
- **Admin**: User management, system config
- **Service**: Background jobs, webhooks

### Data Protection
- **Encryption**: OAuth tokens encrypted at rest
- **RLS**: Row-level security in database
- **Input validation**: All inputs validated
- **Audit logging**: All actions logged

## Performance Targets

### API Performance
- **Response time**: <500ms for 95% of requests
- **Throughput**: 1000+ requests/second
- **Error rate**: <0.1%

### Database Performance
- **Query time**: <100ms for 95% of queries
- **Connection pool**: 10-20 connections
- **Cache hit rate**: >90%

### Background Processing
- **Job processing**: <30 seconds per email
- **Queue depth**: <100 pending jobs
- **Success rate**: >99.5%

## Deployment Architecture

### Services
```
Load Balancer → API Instances → Background Workers → Database
```

### Scaling Strategy
- **Horizontal**: Multiple API instances
- **Vertical**: Scale background workers
- **Database**: Supabase handles scaling
- **Caching**: Redis for session/data caching

## Migration Strategy

### Phase 1: Database & Core Services
1. **New database schema** with proper relationships
2. **Repository layer** with type safety
3. **Core services** with business logic
4. **Comprehensive tests** for all components

### Phase 2: API & External Integrations
1. **API layer** with proper validation
2. **External service clients** with error handling
3. **Authentication** with JWT tokens
4. **Integration tests** for all flows

### Phase 3: Advanced Features
1. **Background processing** with job queue
2. **Monitoring** and observability
3. **Performance optimization**
4. **Security hardening**

## Success Metrics
- ✅ **90%+ test coverage** across all layers
- ✅ **<500ms API response times**
- ✅ **Zero data consistency issues**
- ✅ **Proper error handling** throughout
- ✅ **Clean, maintainable code**

**This is what we're building: a modern, scalable, well-tested SaaS platform.**