import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// React Testing Library needs explicit cleanup when test globals are disabled.
afterEach(() => {
  cleanup();
});
