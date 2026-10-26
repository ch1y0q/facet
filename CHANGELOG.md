# Changelog

All notable changes to Facet are documented in this file.

## [Unreleased]

### Fixed


- **Readable sidecar import preview errors.** Missing, unreadable or invalid databases now produce a clear refusal instead of a SQLite traceback, without creating or upgrading the database.
