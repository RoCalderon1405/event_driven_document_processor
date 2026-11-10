import { describe, expect, it } from 'vitest';

import { formatFileSize, resolveContentType, validateFile } from './validation';

function makeFile(name: string, type: string, size?: number): File {
  const file = new File(['content'], name, { type });
  if (size !== undefined) {
    Object.defineProperty(file, 'size', { value: size });
  }
  return file;
}

describe('resolveContentType', () => {
  it('accepts the three supported browser MIME types', () => {
    expect(resolveContentType(makeFile('a.pdf', 'application/pdf'))).toBe('application/pdf');
    expect(resolveContentType(makeFile('b.png', 'image/png'))).toBe('image/png');
    expect(resolveContentType(makeFile('c.jpg', 'image/jpeg'))).toBe('image/jpeg');
  });

  it('falls back to the extension only when the browser reported no type', () => {
    expect(resolveContentType(makeFile('scan.jpeg', ''))).toBe('image/jpeg');
    expect(resolveContentType(makeFile('scan.txt', ''))).toBeNull();
  });

  it('rejects a declared type outside the supported set', () => {
    expect(resolveContentType(makeFile('archive.zip', 'application/zip'))).toBeNull();
  });
});

describe('validateFile', () => {
  it('accepts a valid supported file', () => {
    expect(validateFile(makeFile('report.pdf', 'application/pdf', 2048))).toBeNull();
  });

  it('rejects an empty file', () => {
    expect(validateFile(makeFile('report.pdf', 'application/pdf', 0))?.code).toBe('empty');
  });

  it('rejects a file above the configured size limit', () => {
    const oversized = makeFile('huge.pdf', 'application/pdf', 10 * 1024 * 1024 + 1);
    const rejection = validateFile(oversized);
    expect(rejection?.code).toBe('size');
    expect(rejection?.message).toContain('too large');
  });

  it('rejects an unsupported content type', () => {
    expect(validateFile(makeFile('notes.zip', 'application/zip', 10))?.code).toBe('type');
  });

  it('rejects an overlong file name', () => {
    const longName = `${'a'.repeat(252)}.pdf`; // 256 characters, above the 255 limit
    expect(validateFile(makeFile(longName, 'application/pdf', 10))?.code).toBe('name');
  });
});

describe('formatFileSize', () => {
  it('formats bytes, kibibytes and mebibytes', () => {
    expect(formatFileSize(512)).toBe('512 B');
    expect(formatFileSize(1536)).toBe('1.5 KB');
    expect(formatFileSize(10 * 1024 * 1024)).toBe('10.0 MB');
  });
});
