# Application screenshots

Captured with Playwright MCP from the real React/Vite app at `http://localhost:5173`, using the
documented event stack on ports 8001/4567. No mocked API responses, injected results, UI changes,
retouching or image generation were used.

- `document-upload-desktop.png`: clean browser history, upload dropzone and empty Recent Documents;
  desktop viewport 1440 × 1100 CSS pixels.
- `document-results-desktop.png`: browser-uploaded `demo-report.pdf`, real terminal `COMPLETED`
  status, SHA-256, processed size and validation result; same desktop viewport, full-page capture.
- `document-mobile.png`: same completed job after choosing **Upload another file**, at a
  390 × 844 CSS-pixel viewport; full-page capture. This verifies narrow-width responsiveness,
  not a physical mobile device or touch emulation.

The PDF was generated locally with pikepdf: one page containing a synthetic demonstration heading
and explicit non-sensitive test text (915 bytes). No personal documents or existing browser
history were used. The ignored local fixture is `build/screenshot-fixtures/demo-report.pdf`;
screenshots contain only that test job. Localized timestamps reflect the browser's actual locale.

To recapture, follow `infra/events/README.md` and `frontend/README.md`, confirm the frontend proxy
targets port 8001, use a fresh isolated browser context, generate a test PDF, capture the empty UI,
upload through the visible file picker and wait for **Format validation passed**. Capture desktop
results, choose **Upload another file**, resize to 390 × 844 and capture the mobile page. Use PNG,
CSS-pixel scale and full-page screenshots. Do not manufacture statuses or alter the DOM for images.

The app console recorded only a pre-existing `/favicon.ico` 404. Desktop/mobile image readability
and absence of horizontal page overflow were inspected. README image rendering is checked locally;
GitHub's hosted rendering is not claimed unless separately verified.
