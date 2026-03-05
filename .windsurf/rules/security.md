# Windsurf Rules - Security Standards

## Security Philosophy
- **Defense in Depth**: Multiple layers of security controls.
- **Least Privilege**: Grant minimum necessary permissions.
- **Zero Trust**: Verify everything, trust nothing.
- **Secure by Default**: Security features enabled by default.

## 1. Authentication Standards
- Use strong password policies (minimum 12 characters, complexity requirements).
- Implement multi-factor authentication (MFA).
- Use secure session management with proper timeouts.
- Implement rate limiting for authentication endpoints.

## 2. Authorization Standards
- Use role-based access control (RBAC).
- Implement principle of least privilege.
- Audit all authorization decisions.
- Use secure token-based authentication.

## 3. Data Protection Standards
- Encrypt sensitive data at rest and in transit.
- Use environment variables for secrets and credentials.
- Implement data masking for sensitive information.
- Follow GDPR and data protection regulations.

## 4. Input Validation Standards
- Validate all inputs from external sources.
- Use allow-lists instead of block-lists.
- Sanitize user inputs to prevent XSS and injection attacks.
- Validate file uploads with proper type and size limits.

## 5. API Security Standards
- Use HTTPS for all API communications.
- Implement API rate limiting and throttling.
- Use API keys and tokens for authentication.
- Implement CORS policies properly.

## 6. Logging and Monitoring Standards
- Log all security events and incidents.
- Monitor for suspicious activities and anomalies.
- Implement intrusion detection systems.
- Regular security audits and penetration testing.

## 7. Code Security Standards
- Use static code analysis tools (bandit, semgrep).
- Regular dependency vulnerability scanning.
- Secure coding practices and guidelines.
- Code review processes with security focus.
