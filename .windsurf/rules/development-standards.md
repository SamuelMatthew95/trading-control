---
description: Development standards and project architecture for trading-control
---

# Development Standards

## Project Architecture
- **Backend**: Python FastAPI with async/await patterns
- **Frontend**: React with TypeScript
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Cache**: Redis for real-time state management
- **Testing**: Pytest with async support

## Code Quality Standards

### Python Code Style
- Use `ruff` for linting and formatting
- Follow PEP 8 with modern Python features
- Use type hints consistently
- Prefer async/await for I/O operations

### Error Handling
- Use structured logging with `log_structured()`
- Implement proper exception chaining with `raise ... from None`
- Wrap all external API calls in try/except blocks
- Use exponential backoff for network retries

### Database Patterns
- Always include `schema_version="v3"` in writes
- Use `SafeWriter` for idempotent operations
- Implement proper transaction management
- Use async sessions for database operations

## Frontend Standards

### TypeScript Patterns
- Use strict TypeScript configuration
- Prefer functional components with hooks
- Implement proper error boundaries
- Use environment variables for configuration

### UI/UX Guidelines
- Follow responsive design principles
- Implement proper loading states
- Use consistent color scheme and typography
- Ensure accessibility standards compliance

## Security Requirements

### API Security
- Validate all input parameters
- Use proper authentication middleware
- Implement rate limiting
- Sanitize all user inputs

### Trading Security
- ALWAYS use paper trading in development
- Validate order parameters before execution
- Implement position size limits
- Use unique order IDs for traceability
