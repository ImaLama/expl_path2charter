# Feat: Relevance-Based Context Ordering

**Status:** Planned
**Priority:** High — trivial to implement, measurable quality gain
**Depends on:** RAG-augmented generation (feat)

## Problem

LLMs have a well-documented recency bias — they attend more strongly to content
at the end of the context window (closest to the question). If we place the most
relevant chunk first and least relevant last, the model may under-attend to the
best information.

## Solution

Sort retrieved chunks in ascending relevance order so the most relevant chunk
appears last, immediately before the user's question.

## Implementation

Single sort call in context assembly:

```python
chunks.sort(key=lambda c: c["relevance_score"])  # ascending = best last
```

Zero dependencies, zero latency cost.

## Verification

- A/B test: same query, same chunks, ascending vs descending order
- Check if model cites information from the last chunk more accurately
