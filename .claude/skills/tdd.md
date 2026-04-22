# Skill: Test-Driven Development
# Invoke: "use the tdd skill"

## Rule
Tests are written before implementation. No exceptions.

## Cycle

### Red — write a failing test
1. Name the behaviour precisely: `test_<subject>_<condition>_<expected>`
2. Write the test against code that does not exist yet.
3. Run it. Confirm it FAILS. A passing test before implementation is testing nothing.
   ```bash
   cd backend && uv run pytest tests/path/to/test_file.py::test_name -v
   ```

### Green — minimal implementation
4. Write the minimum code to pass the test.
5. Run the test. Confirm it PASSES.

### Refactor — clean without breaking
6. Improve structure, naming, duplication — without changing behaviour.
7. Run the full test suite: `uv run pytest`

Repeat for the next behaviour.

## Test structure for this project

```python
# Integration test (API route) — real DB via async client
async def test_create_entry_returns_entry_with_id(client: AsyncClient, db: Session):
    response = await client.post("/api/v1/entries", json={"title": "Test", "entry_type": "note"})
    assert response.status_code == 200
    assert response.json()["id"] is not None

# Unit test (service function) — mocks external HTTP
async def test_extract_from_url_returns_title(respx_mock):
    respx_mock.get("https://example.com").mock(return_value=Response(200, text="<html>..."))
    result = await extract_from_url("https://example.com")
    assert result["title"] is not None
```

## What to test vs. skip
**Always test:** service functions, API routes (happy path + key errors), duplicate detection, feed polling.
**Skip in v1:** frontend components (manual testing), trivial getters with no logic.
