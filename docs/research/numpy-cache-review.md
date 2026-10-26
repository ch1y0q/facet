# NumPy fallback cache review

Follow-up to the performance and multi-user notes on PR #275. The candidate
keeps one matrix for the requested encoder width and effective visible photo set. Random revision stamps advance
transactionally with photo inserts and vector/path changes. Schema changes also
invalidate reuse, and missing revision state or tracking triggers disable caching.
A private read-only snapshot binds revision, vectors and visible paths before
result limits are applied. Existing caller-owned write transactions are uncached.

One build lock remains intentional: concurrent dense matrix construction can
multiply peak memory. Restricted searches read allowed paths first, hash their
effective membership in a worker thread, and load only permitted vector rows.
An empty scope returns before vector reads or matrix allocation. Accounts with
equal effective restricted scopes share the matrix; distinct scopes replace the
one retained entry. Unrestricted searches skip the extra membership query/hash.
There is no per-account LRU or hidden-library vector allocation.
The final candidate cache still uses the broad database change token because
text/tag results and visibility can change independently of vectors.

## Synthetic measurement

A temporary production-schema database with 20,000 photos and 1,152-dimensional
float32 vectors (87.89 MiB of vector payload; 122.79 MiB database), warm OS cache, single-thread BLAS, and no model
inference or HTTP transport. Baseline: master `548f1577`. Each scenario uses one
cold call, three warm calls, three calls following rating commits, and six calls
alternating two account IDs. Timed values below are milliseconds; repeated values
are medians. The build count observes actual dense `numpy.stack` allocations.

| Visibility scenario | Version | Cold | Warm | After rating | Alternating accounts | Matrix builds |
|---|---|---:|---:|---:|---:|---:|
| All photos | baseline | 82.17 | 1.86 | 67.50 | 67.37 | 10 |
| All photos | candidate | 79.55 | 3.14 | 2.70 | 2.61 | 1 |
| Half the library per account | baseline | 44.84 | 0.98 | 38.69 | 37.83 | 10 |
| Half the library per account | candidate | 49.67 | 7.82 | 7.36 | 50.29 | 7 |

Rating edits reuse the matrix in both scopes. Equal unrestricted scopes share
one build instead of ten; alternating disjoint restricted scopes builds seven
instead of ten. Restricted warm searches pay for fresh visibility enumeration
and hashing; disjoint scope switches rebuild their permitted cohort and were
slower than baseline in this run. Keeping one retained cohort deliberately
bounds memory rather than retaining a matrix per account. This is not a claim
that every search is faster. These local synthetic results do not measure a NAS, cold filesystem
cache, GPU encoding, an entire HTTP request, or peak resident memory.

## Correctness evidence

- Rating-only commits reuse vectors; external vector/path changes, replacement,
  in-place restore and schema changes invalidate the appropriate state.
- Matrix and visibility remain coherent when the DB pathname is replaced during
  a search. Current visibility is applied before capped and uncapped results.
- The actual requested encoder width controls the cohort, including a library
  whose sampled model width differs from the whole-library majority.
- A malformed vector does not break valid rows in the same permitted cohort.
  A 257-row production-schema resource probe decodes/stacks one vector for an
  account allowed one photo, and reads no vector BLOBs for an empty scope.
- Existing write transactions, old read-only schemas and missing tracking state
  avoid shared caching without schema writes. Cancelled builds do not overlap
  another allocating build; shutdown cancellation and failed reads do not publish
  empty or partial cache entries.
- Real relink and viewer-export integration preserves vectors and user edits,
  changes derived revisions appropriately, and accepts the table through the
  authoritative schema catalog. Exported revisions carry no edit authority.

All probes use disposable databases and synthetic images. Native sqlite-vec,
Windows and a live photo library are outside these measurements.
