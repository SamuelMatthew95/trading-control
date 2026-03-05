# Windsurf Rules - Performance Standards

## Performance Philosophy
- **Measure First**: Profile before optimizing.
- **Premature Optimization**: Avoid optimizing without measurements.
- **Bottleneck Focus**: Optimize actual bottlenecks, not perceived ones.
- **Scalability Design**: Design for scale from the beginning.

## 1. Code Performance Standards
- Use appropriate data structures for the use case.
- Avoid unnecessary computations in loops.
- Use caching for expensive operations.
- Profile code before and after optimizations.

## 2. Database Performance Standards
- Use proper indexing for query optimization.
- Implement connection pooling.
- Use query optimization and EXPLAIN plans.
- Implement read replicas for scaling reads.

## 3. API Performance Standards
- Use async/await for I/O operations.
- Implement proper caching strategies.
- Use pagination for large datasets.
- Monitor API response times and throughput.

## 4. Memory Management Standards
- Avoid memory leaks and circular references.
- Use generators for large datasets.
- Implement proper garbage collection.
- Monitor memory usage patterns.

## 5. Concurrency Standards
- Use proper synchronization mechanisms.
- Avoid race conditions and deadlocks.
- Use thread pools for concurrent operations.
- Implement proper error handling in concurrent code.

## 6. Monitoring Standards
- Monitor application performance metrics.
- Set up alerts for performance degradation.
- Use APM tools for application monitoring.
- Regular performance testing and benchmarking.

## 7. Optimization Standards
- Profile before optimizing (cProfile, py-spy).
- Use performance testing tools (locust, pytest-benchmark).
- Implement performance regression testing.
- Document optimization decisions and results.
