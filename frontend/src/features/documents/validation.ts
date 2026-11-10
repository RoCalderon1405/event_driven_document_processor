/**
 * Client-side upload preflight. These limits mirror the backend defaults in
 * `bootstrap/settings.py`; the presigned S3 policy remains the authoritative enforcement.
 */

export const ACCEPTED_CONTENT_TYPES = ['application/pdf', 'image/png', 'image/jpeg'] as const;

/** Mirrors `Settings.upload_max_file_size_bytes` default (10 MiB). */
export const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;

/** Mirrors `CreateDocumentRequest.filename` maximum length. */
export const MAX_FILENAME_LENGTH = 255;

export type FileRejectionCode = 'empty' | 'size' | 'name' | 'type';

export interface FileRejection {
  code: FileRejectionCode;
  message: string;
}

/** Extension fallback for platforms that report an empty MIME type for known files. */
const EXTENSION_CONTENT_TYPES: Record<string, string> = {
  pdf: 'application/pdf',
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
};

/**
 * Resolve the content type to send to the API: trust an explicit browser MIME type,
 * and only consult the extension when the browser reported no type at all.
 */
export function resolveContentType(file: Pick<File, 'name' | 'type'>): string | null {
  if (file.type) {
    return (ACCEPTED_CONTENT_TYPES as readonly string[]).includes(file.type) ? file.type : null;
  }
  const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
  return EXTENSION_CONTENT_TYPES[extension] ?? null;
}

/** Validate a selected file before any network request; returns a reason when rejected. */
export function validateFile(file: Pick<File, 'name' | 'type' | 'size'>): FileRejection | null {
  if (file.size <= 0) {
    return { code: 'empty', message: 'This file is empty.' };
  }
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return {
      code: 'size',
      message: `File is too large. The maximum size is ${formatFileSize(MAX_FILE_SIZE_BYTES)}.`,
    };
  }
  if (file.name.length > MAX_FILENAME_LENGTH) {
    return { code: 'name', message: 'File name is too long. Please rename the file.' };
  }
  if (!resolveContentType(file)) {
    return { code: 'type', message: 'Unsupported file type. Upload a PDF, PNG, or JPEG.' };
  }
  return null;
}

/** Human-readable byte size for progress and result panels. */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kib = bytes / 1024;
  if (kib < 1024) return `${kib.toFixed(kib < 10 ? 1 : 0)} KB`;
  return `${(kib / 1024).toFixed(1)} MB`;
}
