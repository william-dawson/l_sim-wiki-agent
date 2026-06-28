---
name: wiki
description: Search the lab wiki for prior knowledge, and record new findings. Use when stuck on a problem, or when you learn something non-obvious worth preserving.
---

# Lab Wiki

The wiki is the lab's shared memory. It is written by both humans and agents.

## When you are stuck

Call `search_wiki` with your question before asking the user. If you find a
relevant page, read it in full with `read_page`. If the page looks wrong or
outdated, call `get_page_history` to understand why it was written that way,
then correct it with `write_page`.

## When you learn something

After solving a non-trivial problem, call `find_or_create` with a short topic
description. Then:

- If `action` is `"update"`: read the existing page, integrate your finding,
  and call `write_page` with the updated content.
- If `action` is `"create"`: call `list_sections` to see the current wiki
  structure, pick the most appropriate section, and write a new page there.

## Commit message format (required for write_page)

```
<one-line summary of what was learned>

task: <what you were doing when you learned this>
agent_id: <your model name>
confidence: <empirical | inferred | uncertain>
```
