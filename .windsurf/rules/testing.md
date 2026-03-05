# Windsurf Rules - Testing Standards

## Testing Philosophy
- **Test First**: Write tests before implementation (TDD).
- **Comprehensive Coverage**: Aim for 90%+ test coverage.
- **Clear Assertions**: Use descriptive assertion messages.
- **Isolated Tests**: Tests should not depend on each other.

## 1. Test Structure Standards
- Use pytest as the testing framework.
- Organize tests in separate files mirroring source structure.
- Use descriptive test names that explain what is being tested.
- Group related tests using pytest markers.

## 2. Test Categories
- **Unit Tests**: Test individual functions and classes.
- **Integration Tests**: Test component interactions.
- **Performance Tests**: Test performance benchmarks.
- **Edge Case Tests**: Test error conditions and boundaries.

## 3. Test Data Standards
- Use fixtures for test data setup.
- Use factories for complex object creation.
- Mock external dependencies.
- Clean up test data after each test.

## 4. Assertion Standards
- Use specific assertions (assert_equal, assert_in, etc.).
- Include descriptive messages in assertions.
- Test both positive and negative cases.
- Test edge cases and boundary conditions.

## 5. Mocking Standards
- Mock external services and databases.
- Use pytest-mock for mocking.
- Verify mock calls and arguments.
- Avoid over-mocking (test real behavior when possible).

## 6. Coverage Standards
- Use pytest-cov for coverage reporting.
- Aim for 90%+ line coverage.
- Review uncovered code and add tests.
- Set coverage thresholds in CI/CD.
