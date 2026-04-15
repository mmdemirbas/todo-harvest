# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-04-15

Initial public release.

### Features

- Pull and merge TODO items from five sources into a local state file:
  Vikunja, Jira, Microsoft To Do, Notion, and Plane (self-hosted).
- Push local state back to Vikunja and Plane. Push is not yet implemented
  for Jira or Microsoft To Do (stubs raise `NotImplementedError`). Notion
  is pull-only by design.
- Unified schema with config-driven status, priority, and field mappings
  for Jira, Notion, and Plane.
- Conflict resolution on pull: field-by-field comparison using timestamps.
- Local inspection commands: `inspect projects`, `inspect stats`,
  `inspect fields`.
- Snapshot export to JSON and CSV.
- Secure MSAL token cache (`~/.config/todo-harvest/msal_cache.json`,
  `0o700` directory, `0o600` file, atomic writes).
- Shared HTTP retry layer with exponential backoff on 429/5xx/network
  errors and a 30-second per-request timeout.
- Bootstrap scripts for macOS/Linux (`./todo`) and Windows (`harvest.ps1`).
