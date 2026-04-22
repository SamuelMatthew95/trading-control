const nextJest = require("next/jest");

const createJestConfig = nextJest({ dir: "./" });

const customJestConfig = {
  testEnvironment: "node",
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1",
  },
  // All tests use Vitest — exclude them from Jest so `jest --passWithNoTests` exits 0
  testPathIgnorePatterns: [
    "/node_modules/",
    "/.next/",
    "/src/test/",
    "/src/types/__tests__/",
    "/src/utils/__tests__/",
  ],
};

module.exports = createJestConfig(customJestConfig);
