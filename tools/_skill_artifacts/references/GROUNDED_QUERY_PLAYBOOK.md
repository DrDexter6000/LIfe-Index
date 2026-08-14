# Grounded Query Playbook

Use this playbook for time-scoped evidence, facet/count/enumeration answers,
cross-facet questions, magazine-style analysis, or an explicit `GROUNDED` /
`PARTIAL` / `UNGROUNDED` status request.

1. Treat planning, multi-hop reasoning, interpretation, and synthesis as host
   agent work. Life Index tools provide deterministic search, navigation, read,
   and validation surfaces.
2. Classify the query shape yourself, then use deterministic tools as
   executors. The tools must not infer which facets to search from natural
   language. For time-scoped, facet, count, enumerate, or cross-facet questions,
   first ensure Index B navigation and inspect the available value menu:
   `life-index index-tree ensure --from YYYY-MM --to YYYY-MM --json`.
   `life-index index-tree discover --from YYYY-MM --to YYYY-MM --facet tag --facet topic --facet project --facet location --json`.
   For concept-style questions, inspect the actual facet value menu first and
   choose matching values from the data. Do not preload a fixed vocabulary for
   any specific topic. Project, people, location, and tag menus may show
   canonical values derived from explicit `entity_graph.yaml` aliases; use
   `raw_values` only to understand which written labels were grouped. Do not
   invent alias mappings that are not present in the graph. If the frontmatter
   facet menu does not expose useful values, request observed journal-body terms
   explicitly with
   `life-index index-tree discover --from YYYY-MM --to YYYY-MM --facet content_term --json`.
   Treat `content_term` values as exact corpus terms, not synonyms. If the menu
   still does not expose useful values, fall back to keyword/entity-weighted
   discovery.
3. Pick relevant facet values yourself from the discover menu, then use
   structured Index B navigation before journal reads:
   `life-index index-tree navigate --from YYYY-MM --to YYYY-MM --filter facet=value --json`.
   Read the reported root/year/month navigation docs and use the returned
   `entry_pointers` as the bounded candidate set. Repeated `--filter` arguments
   are intersections; `value1||value2` is a deterministic OR inside one facet.
   Use discovered canonical values where available; explicit graph aliases are
   also accepted by the navigation tool and resolve deterministically.
   For relationship-shaped questions, choose the relevant entity and optional
   relation type yourself, then call
   `life-index index-tree navigate --entity-neighbors "Entity Name" --entity-relation relation --json`.
   This operation only traverses explicit `entity_graph.yaml` edges and returns
   neighboring entities plus any edge-level supporting journal ids already
   present in the graph; it does not infer relationships or journal evidence.
   If the response source is `journals`, use the returned fallback entry
   pointers directly.
   For clean facet count or enumeration questions, use `navigate`'s exhaustive
   `count`, `entries`, and `entry_pointers` as the candidate/count source. Read
   only the bounded journal entries needed to support the answer, such as
   boundary dates, representative rows, or entries that disambiguate a date
   gap. Do not restart with broad search after a successful exhaustive
   navigation unless the user asks for semantic facts beyond the selected
   facets.
   Do not use `index-tree nodes`, `index-tree lens`, or `index-tree shadow`
   for normal host-agent retrieval/navigation. They are debug-only legacy
   diagnostics retained for compatibility; the agent-facing navigation path is
   `ensure` -> `discover` -> `navigate`.
4. Read only bounded candidates through stable domain tools:
   `life-index journal batch-get --path Journals/YYYY/MM/name.md --path Journals/YYYY/MM/other.md`.
   Do NOT call journal get repeatedly for multiple candidates; if there are
   two or more paths, use one `journal batch-get`.
   Use `life-index journal get --path Journals/YYYY/MM/name.md` for a single
   candidate. Use
   `life-index smart-search` or `life-index search` for keyword/entity-weighted
   discovery paths, then feed discovered exact paths back into `journal batch-get`
   or `journal get`.
   Do not use `life-index recall` in new playbooks; it is a deprecated
   compatibility wrapper over `search`.
   Do not use ad hoc `grep` or broad full-directory reads.
5. Ordinary count, facet, enumeration, cross-facet, and time-scoped answers use
   bounded evidence and honest uncertainty without requiring `answer.insights[]` or a
   `GROUNDED` / `PARTIAL` / `UNGROUNDED` status.
6. Only for magazine-style analysis or an explicit grounded-status request,
   return the magazine answer shape:
   `answer.insights[]` where each item has `quote`, `interpretation`, and
   `evidence_refs`, plus `answer.summary` as connective prose. Every factual
   date, count, location, event, or conclusion must be covered by cited
   insights. If the answer includes an aggregate count, include a dedicated
   insight whose `interpretation` repeats the exact count and whose
   `evidence_refs` cover the counted journal entries.
7. When returning an explicit grounding status, never mark an answer `GROUNDED`
   with zero citations, missing journal IDs, or facts that only come from hidden
   session memory. If evidence is insufficient or validation fails, return
   `PARTIAL` or `UNGROUNDED` with a concrete gap.

## Search And Smart-Search Consumption

For ordinary discovery, map the user's intent to deterministic parameters:

| User intent | Recommended parameters |
|---|---|
| Work journals | `--topic work` |
| Last year's entries | `--date-from 2025-01-01 --date-to 2025-12-31` |
| Entries about a person | `--people NAME` |
| Entries containing a term | `--query "TERM"` |
| Entries with a mood | `--mood MOOD` |
| Entries for a project | `--project PROJECT` |
| Strict keyword match | `--query "TERM" --no-semantic` |

`search` and `smart-search` execute retrieval; they do not decide the user's
conclusion. `smart-search --include-evidence` returns a deterministic scaffold
and reuses its extracted keywords as bounded subqueries.
Inspect `query_plan.sub_queries`, `query_plan.strategy`, `agent_instructions`,
`answer_scaffold`, `filtered_results`, and `evidence_pack`, then perform query
rewrite, multi-hop calls, interpretation, and synthesis in the host agent.
Never invent evidence or treat `entity_expansion` as a filter or adjudicator;
use it only to explain alias or relationship attribution.

Retrieval threshold and completeness: `life-index search` runs with
`min_relevance=0` by default. `min_relevance=0` is the intentional Phase 1 recall-first default: search passes an explicit zero token-match threshold and thereby bypasses the legacy high-frequency dynamic threshold; this is by design, not an omission.
Whether a search has seen the whole admitted set is governed by the returned
`retrieval_coverage` object (`retrieval_coverage.v1`), not by the legacy
`total_*` fields alone: `status: "complete"` is the only proof of completeness,
`next_offset` only says the same deterministic query can mechanically continue
(page forward by exactly that value; level 1/2 windows paginate
`l1_results`/`l2_results`), and any `partial_reasons` entry names the honest
gap.

Consume `evidence_pack.diagnostics.retrieval_outcome` as follows:

| Outcome | Host-agent action |
|---|---|
| `ok` | Consume the bounded results normally. |
| `weak_results` | State low confidence and use `suggestions` to refine the query. |
| `no_confident_match` | State that no confident match was found; suggest another term or filter. |
| `zero_results` | Report an empty result and use `suggestions` to broaden the query. |

These diagnostics are deterministic and advisory. If the request is too vague
to form a meaningful query or filter, clarify first. Never disguise tool failure
as an empty result, and never claim a raw result list is the final user answer.
If the user next asks to edit, summarize, or compare, switch workflows
explicitly instead of mixing the operations implicitly.

## Aggregation And Heuristic Evidence

Use this procedure for count, compare, trend, or summary questions that cannot
be answered directly by a structured `aggregate` or `trajectory` result:

1. Extract the time window and structured filters first.
2. Prefer hard evidence: explicit frontmatter, direct journal statements, and
   deterministic index, timeline, or metadata values.
3. If more candidates are needed, use the bounded navigation/search procedure
   above and expand the query only around the same user question.
4. Classify every candidate as `MATCH`, `NO_MATCH`, or `UNCERTAIN`.
5. Return the count, comparison, trend, or summary while separating confirmed
   conclusions from heuristic inference.

Do not use `search_journals.total_found` as the answer unless the user asks only
how many search hits were returned. Hard evidence is a structured field or
explicit statement. Soft evidence is an indirect proxy such as a late writing
time or wording like “熬夜/很困/准备睡”. Uncertain evidence cannot support a
claim by itself. Soft evidence may support only downgraded language such as
“high probability”, “possible”, or “cannot confirm”; never encode the heuristic
as a CLI rule or invent a one-off product workflow for it. The CLI supplies
evidence; the host agent owns classification, aggregation, explanation, and an
honest account of limitations.
