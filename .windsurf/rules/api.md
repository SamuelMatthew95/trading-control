# Windsurf Rules - API Development Standards

## API Development Philosophy
- **RESTful Design**: Follow REST principles for API design.
- **Type Safety**: Use Pydantic models for request/response validation.
- **Error Handling**: Provide consistent error responses with proper HTTP status codes.
- **Documentation**: Auto-generate OpenAPI documentation from code.

## 1. API Structure Standards
- Use FastAPI with proper dependency injection.
- Separate route definitions from business logic.
- Use Pydantic models for all request/response validation.
- Implement proper HTTP status codes.

## 2. Request/Response Models
- All API endpoints must have Pydantic request models.
- All API endpoints must have Pydantic response models.
- Use proper field validation (min_length, max_length, etc.).
- Provide clear field descriptions.

## 3. Error Handling
- Use HTTPException for API errors.
- Provide meaningful error messages.
- Include error codes and details in responses.
- Log all API errors with context.

## 4. Authentication and Security
- Implement proper authentication middleware.
- Use HTTPS in production.
- Validate all inputs.
- Sanitize outputs to prevent XSS.

## 5. Documentation Standards
- Use FastAPI's auto-documentation features.
- Provide example requests and responses.
- Document all query parameters and path parameters.
- Include rate limiting information.

## 6. Performance Standards
- Use async/await for I/O operations.
- Implement proper caching strategies.
- Monitor API response times.
- Use connection pooling for database operations.

## 7. Testing Standards
- Write integration tests for all API endpoints.
- Test error scenarios and edge cases.
- Mock external dependencies.
- Test authentication and authorization.
