"""
Wiki MCP server.

On first run, clones the wiki repo into ~/.cache/wiki-mcp/repo.
On every run, pulls latest (includes fresh embeddings.db from CI).
No API key required — embeddings are pre-computed by CI using fastembed.
"""

import json
import os
import sqlite3
import subprocess
from pathlib import Path

import sqlite_vec
import yaml
from fastembed import TextEmbedding
from mcp.server.fastmcp import FastMCP

GITLAB_TOKEN = os.environ["GITLAB_TOKEN"]
GITLAB_PROJECT = os.environ.get("GITLAB_PROJECT", "wddawson/l_sim-agent-wiki")
CACHE_DIR = Path(os.environ.get("WIKI_CACHE_DIR", Path.home() / ".cache" / "wiki-mcp"))
REPO_DIR = CACHE_DIR / "repo"
DB_PATH = REPO_DIR / "embeddings.db"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
SIMILARITY_THRESHOLD = 0.82

mcp = FastMCP("wiki")
_embedder: TextEmbedding | None = None


def _sync_repo() -> None:
    remote = f"https://ci-token:{GITLAB_TOKEN}@gitlab.com/{GITLAB_PROJECT}.git"
    if not REPO_DIR.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth=1", remote, str(REPO_DIR)], check=True)
    else:
        subprocess.run(["git", "pull", "--ff-only"], cwd=REPO_DIR, check=True)


def _embedder_instance() -> TextEmbedding:
    global _embedder
    if _embedder is None:
        _embedder = TextEmbedding(EMBED_MODEL)
    return _embedder


def _embed(texts: list[str]) -> list[list[float]]:
    return [v.tolist() for v in _embedder_instance().embed(texts)]


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

@mcp.tool()
def list_sections() -> str:
    """Return the current wiki section structure from mkdocs.yml."""
    nav_file = REPO_DIR / "mkdocs.yml"
    config = yaml.safe_load(nav_file.read_text())
    return json.dumps(config.get("nav", []), indent=2)


@mcp.tool()
def search_wiki(query: str, n_results: int = 5) -> str:
    """Semantic search over wiki sections. Returns ranked matches with snippets."""
    vec = _embed([query])[0]
    conn = _db()
    rows = conn.execute(
        """
        SELECT path, heading, snippet,
               1 - vec_distance_cosine(embedding, ?) AS score
        FROM sections
        ORDER BY score DESC
        LIMIT ?
        """,
        [json.dumps(vec), n_results],
    ).fetchall()
    conn.close()
    hits = [{"path": r[0], "heading": r[1], "snippet": r[2], "score": round(r[3], 3)}
            for r in rows]
    return json.dumps(hits, indent=2)


@mcp.tool()
def read_page(path: str) -> str:
    """Read a wiki page. path is relative to docs/, e.g. 'hpc/index.md'."""
    full = REPO_DIR / "docs" / path
    if not full.exists():
        return f"Page not found: {path}"
    return full.read_text()


@mcp.tool()
def get_page_history(path: str, n: int = 10) -> str:
    """Git log for a page — shows who changed it and why."""
    result = subprocess.run(
        ["git", "log", f"-{n}", "--pretty=format:%h %ai %s", "--", f"docs/{path}"],
        cwd=REPO_DIR, capture_output=True, text=True,
    )
    return result.stdout or "No history found."


@mcp.tool()
def find_or_create(topic: str) -> str:
    """
    Given a topic, return whether to update an existing page or create a new one.
    Returns JSON: {action, path, score, heading}.
    If action is 'create', call list_sections to find the right place.
    """
    vec = _embed([topic])[0]
    conn = _db()
    row = conn.execute(
        """
        SELECT path, heading,
               1 - vec_distance_cosine(embedding, ?) AS score
        FROM sections
        ORDER BY score DESC
        LIMIT 1
        """,
        [json.dumps(vec)],
    ).fetchone()
    conn.close()
    if not row:
        return json.dumps({"action": "create", "path": None, "score": 0.0})
    path, heading, score = row
    if score >= SIMILARITY_THRESHOLD:
        return json.dumps({"action": "update", "path": path,
                           "heading": heading, "score": round(score, 3)})
    return json.dumps({"action": "create", "path": None,
                       "score": round(score, 3), "closest": path})


@mcp.tool()
def write_page(path: str, content: str, commit_message: str) -> str:
    """
    Write a wiki page and push directly to main.

    path: relative to docs/, e.g. 'hpc/slurm-tips.md'
    commit_message: must include task, agent_id, and confidence fields.
    """
    full = REPO_DIR / "docs" / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)

    subprocess.run(["git", "add", f"docs/{path}"], cwd=REPO_DIR, check=True)
    subprocess.run(["git", "commit", "-m", commit_message], cwd=REPO_DIR, check=True)

    remote = f"https://ci-token:{GITLAB_TOKEN}@gitlab.com/{GITLAB_PROJECT}.git"
    subprocess.run(["git", "push", remote, "main"], cwd=REPO_DIR, check=True)

    return f"Written and pushed: {path} (CI will update embeddings)"


def main() -> None:
    _sync_repo()
    mcp.run()


if __name__ == "__main__":
    main()
