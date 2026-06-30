"""
Entry point for CI: regenerates embeddings for changed markdown files.

Usage:
  wiki-reindex                   # full reindex
  wiki-reindex <before> <after>  # incremental (git diff between two SHAs)
"""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import sqlite_vec
from fastembed import TextEmbedding

WIKI_ROOT = Path(".")
DB_PATH = WIKI_ROOT / "embeddings.db"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
ZERO_SHA = "0" * 40

embedder = TextEmbedding(EMBED_MODEL)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS sections USING vec0(
            embedding float[384],
            +path TEXT,
            +heading TEXT,
            +snippet TEXT
        )
    """)
    conn.commit()
    return conn


def split_sections(rel_path: str, content: str) -> list[dict]:
    sections, current_heading, current_lines = [], "intro", []
    saw_heading = False
    for line in content.splitlines():
        if line.startswith("#"):
            saw_heading = True
            if current_lines:
                text = "\n".join(current_lines).strip()
                if text:
                    sections.append({"heading": current_heading, "text": text})
            current_heading = line.lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            sections.append({"heading": current_heading, "text": text})
    if not sections and saw_heading:
        sections.append({"heading": current_heading, "text": current_heading})
    return sections


def index_file(conn: sqlite3.Connection, rel_path: str) -> None:
    full = WIKI_ROOT / "docs" / rel_path
    if not full.exists():
        conn.execute("DELETE FROM sections WHERE path = ?", [rel_path])
        conn.commit()
        print(f"  removed {rel_path}")
        return

    sections = split_sections(rel_path, full.read_text())
    if not sections:
        return

    vectors = list(embedder.embed([s["text"] for s in sections]))
    conn.execute("DELETE FROM sections WHERE path = ?", [rel_path])
    for s, vec in zip(sections, vectors):
        conn.execute(
            "INSERT INTO sections(embedding, path, heading, snippet) VALUES (?, ?, ?, ?)",
            [json.dumps(vec.tolist()), rel_path, s["heading"], s["text"][:300]],
        )
    conn.commit()
    print(f"  indexed {rel_path} ({len(sections)} sections)")


def changed_files(before_sha: str, after_sha: str) -> list[str]:
    out = subprocess.check_output(
        ["git", "diff", "--name-only", before_sha, after_sha],
    ).decode().splitlines()
    return [p.removeprefix("docs/") for p in out
            if p.startswith("docs/") and p.endswith(".md")]


def main() -> None:
    conn = get_db()
    full_reindex = True

    if len(sys.argv) == 3:
        before_sha, after_sha = sys.argv[1], sys.argv[2]
        if before_sha != ZERO_SHA:
            files = changed_files(before_sha, after_sha)
            print(f"Incremental reindex: {len(files)} file(s) changed")
            full_reindex = False

    if full_reindex:
        files = [str(p.relative_to(WIKI_ROOT / "docs"))
                 for p in (WIKI_ROOT / "docs").rglob("*.md")]
        print(f"Full reindex: {len(files)} file(s)")

    for f in files:
        index_file(conn, f)

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
