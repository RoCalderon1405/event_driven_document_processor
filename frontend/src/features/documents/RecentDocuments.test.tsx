import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { RecentDocuments } from './RecentDocuments';
import type { TrackedEntry } from './useDocumentTracker';
import type { DocumentJob, DocumentStatus } from './types';

const JOB_ID = '6f1d8c2e-0a4b-4c5d-9e8f-0a1b2c3d4e5f';

interface EntryOptions {
  status?: DocumentStatus | null;
  jobId?: string;
  filename?: string;
  missing?: boolean;
  paused?: boolean;
  message?: string | null;
}

function makeEntry(options: EntryOptions = {}): TrackedEntry {
  const {
    status = 'PENDING',
    jobId = JOB_ID,
    filename = 'report.pdf',
    missing = false,
    paused = false,
    message = null,
  } = options;
  const lastJob: DocumentJob | null =
    status === null
      ? null
      : {
          job_id: jobId,
          filename,
          content_type: 'application/pdf',
          description: null,
          status,
          created_at: '2026-11-09T12:00:00Z',
        };
  return {
    tracked: { job_id: jobId, filename, added_at: Date.UTC(2026, 10, 9, 12, 0) },
    runtime: { lastJob, failures: 0, paused, missing, message },
  };
}

function renderRecent(entries: TrackedEntry[], announcement: string | null = null) {
  const onRetry = vi.fn();
  const onRemove = vi.fn();
  render(
    <RecentDocuments
      entries={entries}
      announcement={announcement}
      onRetry={onRetry}
      onRemove={onRemove}
    />,
  );
  return { onRetry, onRemove };
}

describe('RecentDocuments', () => {
  it('renders an empty state before anything is tracked', () => {
    renderRecent([]);
    expect(screen.getByText(/No documents tracked yet/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /remove/i })).not.toBeInTheDocument();
  });

  it('shows a distinct badge for every backend status', () => {
    const statuses: DocumentStatus[] = [
      'PENDING',
      'PROCESSING',
      'COMPLETED',
      'FAILED',
      'DUPLICATE',
    ];
    renderRecent(
      statuses.map((status, index) =>
        makeEntry({ status, jobId: `job-${index}`, filename: `file-${index}.pdf` }),
      ),
    );

    for (const label of ['Pending', 'Processing', 'Completed', 'Failed', 'Duplicate']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getAllByRole('listitem')).toHaveLength(statuses.length);
  });

  it('shows a connecting state until the first response arrives', () => {
    renderRecent([makeEntry({ status: null })]);
    expect(screen.getByText('Connecting…')).toBeInTheDocument();
  });

  it('explains a paused job and retries through the callback', () => {
    const { onRetry } = renderRecent([
      makeEntry({
        status: 'PENDING',
        paused: true,
        message: 'Status checks paused after 5 connection errors. Retry to resume.',
      }),
    ]);

    expect(screen.getByText(/Status checks paused after 5 connection errors/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledWith(JOB_ID);
  });

  it('marks jobs the backend no longer knows as not found', () => {
    renderRecent([
      makeEntry({
        missing: true,
        message: 'This job no longer exists in backend storage. Remove it or retry later.',
      }),
    ]);

    expect(screen.getByText('Not found')).toBeInTheDocument();
    expect(screen.getByText(/no longer exists in backend storage/)).toBeInTheDocument();
  });

  it('removes entries through an accessible control naming the file', () => {
    const { onRemove } = renderRecent([makeEntry({ filename: 'invoice.pdf' })]);

    fireEvent.click(screen.getByRole('button', { name: 'Remove invoice.pdf from tracking' }));
    expect(onRemove).toHaveBeenCalledWith(JOB_ID);
  });

  it('publishes transition messages through a polite status region', () => {
    renderRecent([makeEntry()], 'report.pdf is now Completed.');

    const liveRegion = screen.getByRole('status');
    expect(liveRegion).toHaveAttribute('aria-live', 'polite');
    expect(liveRegion).toHaveTextContent('report.pdf is now Completed.');
  });
});
