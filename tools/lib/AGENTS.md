# AGENTS.md - tools/lib/

## OVERVIEW
Shared infrastructure library for all Life Index atomic tools.

## WHERE TO LOOK

| Task | File | Notes |
|------|------|-------|
| Add new error code | `errors.py` | Follow E{module}{type} format, add recovery strategy |
| Modify frontmatter format | `frontmatter.py` | SSOT: update FIELD_ORDER and type mappings |
| Change data directory paths | `config.py` | Update USER_DATA_DIR, all other paths derive from it |
| Debug concurrent write issues | `file_lock.py` | Cross-platform advisory locks for serialization |
| Debug L2 search performance | `metadata_cache.py` | Check SQLite WAL mode, mtime/size detection |
| Fix FTS5 search issues | `search_index.py` | Supports auto-rebuild on corruption |
| Add semantic search feature | `semantic_search.py` | Requires sentence-transformers, graceful fallback |
| Vector index corruption | `vector_index_simple.py` | Pickle-based fallback when sqlite-vec unavailable |

## MODULES

- **config.py**: Centralized configuration, paths, templates. All paths use `pathlib.Path` for cross-platform compatibility.
- **errors.py**: Structured error codes (E{module}{type}) with recovery strategies for Agent decision-making.
- **file_lock.py**: Cross-platform file locking for concurrent access control. Uses fcntl (Unix) and msvcrt (Windows).
- **frontmatter.py**: SSOT for YAML frontmatter parsing/formatting. All tools must use this, never duplicate logic.
- **metadata_cache.py**: SQLite-based L2 search cache. 50-100x performance improvement over file scanning.
- **search_index.py**: FTS5 full-text search with BM25 ranking, incremental updates.
- **semantic_search.py**: Vector embedding search using all-MiniLM-L6-v2, optional dependency.
- **timing.py**: Performance timing utility for metrics collection. Used in tool outputs for monitoring.
- **vector_index_simple.py**: Pure Python fallback vector index using numpy/pickle.

## CONVENTIONS

**SSOT Pattern**: `frontmatter.py` is the single source of truth for YAML frontmatter. Any format change must happen here first, then propagate to tools.

**Error Recovery**: All errors include a `recovery_strategy` field (`skip_optional`, `ask_user`, `continue_empty`, `fail`, `retry`). Agent uses this to decide next action.

**File Locking**: All write operations (journal, edit, index) use `FileLock` to prevent concurrent conflicts. Lock timeout defaults to 30s for journals, 60s for index operations.

**Optional Dependencies**: Semantic search gracefully degrades when sentence-transformers unavailable. Never fail the main workflow.

## ANTI-PATTERNS

- **Never** duplicate frontmatter parsing logic in tools. Always import from `lib.frontmatter`.
- **Never** hardcode paths. Use `config.USER_DATA_DIR` and derived constants.
- **Never** raise bare exceptions. Use `LifeIndexError` with structured codes.
- **Never** assume sentence-transformers is installed. Check availability and fallback.
- **Never** write journals/indexes without acquiring the appropriate lock first.

## DEPENDENCIES

**This lib depends on**: Python 3.11+, standard library only (pathlib, sqlite3, typing, etc.)

**Optional**: sentence-transformers (for semantic search)

**Tools depend on this lib**: write_journal, search_journals, edit_journal, generate_abstract, build_index, query_weather, dev/validate_data, dev/rebuild_indices
