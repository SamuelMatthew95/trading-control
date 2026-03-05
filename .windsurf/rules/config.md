# Windsurf Rules - Configuration Management Standards

## Configuration Philosophy
- **Environment Separation**: Different configs for different environments.
- **Secrets Management**: Never commit secrets to version control.
- **Type Safety**: Use typed configuration models.
- **Validation**: Validate all configuration values.

## 1. Configuration Structure Standards
- Use environment variables for configuration.
- Separate configuration by environment (dev, staging, prod).
- Use configuration classes with type hints.
- Provide default values where appropriate.

## 2. Environment Variables Standards
- Use descriptive variable names with clear prefixes.
- Document all environment variables.
- Use .env files for local development.
- Never commit sensitive environment variables.

## 3. Configuration Validation Standards
- Validate all configuration values at startup.
- Use Pydantic models for configuration validation.
- Provide clear error messages for invalid configurations.
- Fail fast on configuration errors.

## 4. Secrets Management Standards
- Use environment variables for secrets.
- Use secret management services in production.
- Rotate secrets regularly.
- Audit secret access and usage.

## 5. Configuration Documentation Standards
- Document all configuration options.
- Provide examples for common configurations.
- Include environment-specific configuration guides.
- Document security implications of configuration options.

## 6. Testing Configuration Standards
- Test configuration validation.
- Test with different environment configurations.
- Mock external configuration sources in tests.
- Test configuration loading and error handling.
