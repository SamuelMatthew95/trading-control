# Windsurf Rules - Database Development Standards

## Database Philosophy
- **Data Integrity**: Use proper constraints and validations.
- **Type Safety**: Use typed database models and migrations.
- **Performance**: Optimize queries and use proper indexing.
- **Security**: Prevent SQL injection and protect sensitive data.

## 1. Database Structure Standards
- Use SQLAlchemy ORM with proper model definitions.
- Define all tables with proper primary keys and constraints.
- Use foreign keys for relationships with proper cascading.
- Include created_at and updated_at timestamps.

## 2. Model Definitions
- All models must inherit from a base model class.
- Use proper column types with length limits.
- Define relationships with proper back_populates.
- Include table names explicitly.

## 3. Migration Standards
- Use Alembic for database migrations.
- Write descriptive migration messages.
- Test migrations in development before production.
- Include rollback strategies.

## 4. Query Standards
- Use ORM queries instead of raw SQL when possible.
- Use proper filtering and pagination.
- Optimize queries with proper indexes.
- Use connection pooling for performance.

## 5. Testing Standards
- Use test databases for integration testing.
- Mock database for unit tests.
- Test all CRUD operations.
- Test query performance.

## 6. Security Standards
- Use parameterized queries to prevent SQL injection.
- Hash sensitive data (passwords, tokens).
- Use environment variables for database credentials.
- Implement proper access controls.
