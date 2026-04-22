# Template Challenge Pack

Copy this directory to create your own challenge pack:

```bash
python cli.py new-pack my_domain
```

Then edit `packs/my_domain/pack.py`:

1. Rename the class
2. Set `name` and `description`
3. Add your prompts in `get_prompts()` — aim for 3-6 at varying difficulty
4. Define your scoring rubric in `get_rubric()` — weights must sum to 1.0
5. Optionally add a system prompt in `get_system_prompt()`
6. Optionally implement an `AutoScorer` if you can verify outputs programmatically

Run it:
```bash
python cli.py run my_domain --score --judge gemini
```
