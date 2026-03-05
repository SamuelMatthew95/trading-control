# Windsurf Rules - Debugging Standards

## Debugging Philosophy
- **Structured Debugging**: Use systematic debugging approaches.
- **Logging First**: Use structured logging for debugging.
- **Minimal Intervention**: Debug with minimal code changes.
- **Reproducible Issues**: Ensure issues are reproducible.

## 1. Logging Standards
- Use structured logging with context.
- Log at appropriate levels (DEBUG, INFO, WARNING, ERROR).
- Include relevant context in log messages.
- Avoid logging sensitive information.

## 2. Debugging Tools Standards
- Use Python debugger (pdb, ipdb) for step-through debugging.
- Use profiling tools (cProfile, py-spy) for performance debugging.
- Use memory profiling tools (memory_profiler, objgraph).
- Use network debugging tools (wireshark, tcpdump).

## 3. Error Handling Standards
- Use specific exception types.
- Include context in error messages.
- Log errors with full stack traces.
- Implement proper error recovery mechanisms.

## 4. Debugging Code Standards
- Use debug flags and environment variables.
- Implement debug modes with additional logging.
- Use assertions for development-time checks.
- Avoid debug code in production.

## 5. Remote Debugging Standards
- Use remote debugging tools for production issues.
- Implement secure remote debugging access.
- Use logging aggregation for remote debugging.
- Monitor debug access and usage.

## 6. Performance Debugging Standards
- Profile code to identify performance bottlenecks.
- Use performance monitoring tools.
- Debug memory leaks and resource usage.
- Optimize based on profiling results.

## 7. Debugging Documentation Standards
- Document debugging procedures and tools.
- Provide debugging guides for common issues.
- Document debug configuration options.
- Include debugging information in error messages.
