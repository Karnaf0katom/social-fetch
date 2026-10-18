# Changelog

## 0.1.1 — 2026-10-18

- Include the manifest's dotfiles in the source archive and verify the built
  archive in CI, covering the source-distribution development workflow.
- Add a public manifest-refresh command, contribution instructions and a
  reproducible bug-report template.
- Label the release as alpha and clarify the scope of its live verification.
- Acquisition code is unchanged from 0.1.0; its five fresh VM checks still apply.

## 0.1.0 — 2026-10-18

- Standalone JSON CLI and Python client for public social discovery and downloads.
- Public relay adapters for YouTube/Shorts, Instagram and TikTok, plus allowlisted
  yt-dlp extractors for X, Facebook and Reddit.
- Durable jobs, two-worker admission, media receipts and SHA-256 checked MP4 export.
- Per-user data directory, dependency diagnostics and reconnectable CLI waits.
