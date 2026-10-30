"""SQLite FTS5 index over the vault. Fully rebuildable from the markdown files."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .vault import Vault, parse_frontmatter

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs(
  path TEXT PRIMARY KEY, mtime REAL, kind TEXT, id TEXT, platform TEXT, title TEXT,
  created TEXT, updated TEXT, summary TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
  path UNINDEXED, title, role UNINDEXED, ts UNINDEXED, text, tokenize='porter unicode61');
"""
CHUNK = 2000


class Index:
    def __init__(self, vault: Vault):
        self.vault = vault
        vault.state.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(vault.state / "index.db")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # ------------------------------------------------------------ build
    def refresh(self, full: bool = False) -> dict:
        if full:
            self.db.executescript("DELETE FROM docs; DELETE FROM chunks;")
        known = dict(self.db.execute("SELECT path, mtime FROM docs"))
        seen, added = set(), 0
        paths = [*self.vault.iter_conversations(), *self.vault.iter_notes()]
        for p in paths:
            rel = p.relative_to(self.vault.root).as_posix()
            seen.add(rel)
            mtime = p.stat().st_mtime
            if known.get(rel) == mtime:
                continue
            self._index_file(p, rel, mtime)
            added += 1
        gone = set(known) - seen
        for rel in gone:
            self._drop(rel)
        self.db.commit()
        return {"indexed": added, "removed": len(gone), "total": len(seen)}

    def _drop(self, rel: str):
        self.db.execute("DELETE FROM docs WHERE path=?", (rel,))
        self.db.execute("DELETE FROM chunks WHERE path=?", (rel,))

    def _index_file(self, p: Path, rel: str, mtime: float):
        self._drop(rel)
        if rel.startswith("Conversations/"):
            fm, msgs = self.vault.read_conversation(p)
            rows = []
            for m in msgs:
                for i in range(0, max(len(m.text), 1), CHUNK):
                    rows.append((rel, fm.get("title", p.stem), m.role, m.ts.isoformat() if m.ts else "",
                                 m.text[i:i + CHUNK]))
            if fm.get("summary"):
                rows.append((rel, fm.get("title", p.stem), "summary", "", str(fm["summary"])))
            kind = "conversation"
        else:
            fm, body = parse_frontmatter(p.read_text(encoding="utf-8"))
            rows = [(rel, fm.get("title", p.stem), "note", "", body[i:i + CHUNK])
                    for i in range(0, max(len(body), 1), CHUNK)]
            kind = fm.get("type", "note")
        self.db.execute("INSERT INTO docs VALUES(?,?,?,?,?,?,?,?,?)",
                        (rel, mtime, kind, fm.get("id"), fm.get("platform"), str(fm.get("title", p.stem)),
                         str(fm.get("created", "")), str(fm.get("updated", "")), str(fm.get("summary", ""))))
        self.db.executemany("INSERT INTO chunks VALUES(?,?,?,?,?)", rows)

    # ------------------------------------------------------------ query
    @staticmethod
    def _fts_query(q: str) -> str:
        """Turn free text into a forgiving FTS5 query (quoted terms, OR'd, prefix on last)."""
        terms = [t for t in "".join(c if c.isalnum() or c in "-_" else " " for c in q).split() if t]
        if not terms:
            return '""'
        quoted = [f'"{t}"' for t in terms]
        return " OR ".join(quoted)

    def search(self, query: str, limit: int = 10, platform: str | None = None,
               kind: str | None = None) -> list[dict]:
        sql = """
          SELECT c.path, d.title, d.platform, d.kind, d.updated, d.summary,
                 snippet(chunks, 4, '**', '**', ' ... ', 18) AS snip, bm25(chunks, 0, 4.0, 0, 0, 1.0) AS score
          FROM chunks c JOIN docs d ON d.path = c.path
          WHERE chunks MATCH ? {where}
          ORDER BY score LIMIT ?"""
        where, args = "", [self._fts_query(query)]
        if platform:
            where += " AND d.platform = ?"
            args.append(platform)
        if kind:
            where += " AND d.kind = ?"
            args.append(kind)
        rows = self.db.execute(sql.format(where=where), [*args, limit * 6]).fetchall()
        best: dict[str, dict] = {}
        for path, title, plat, k, updated, summary, snip, score in rows:
            hit = best.setdefault(path, {"path": path, "title": title, "platform": plat, "kind": k,
                                         "updated": updated, "summary": summary, "snippets": [], "score": score})
            if len(hit["snippets"]) < 2:
                hit["snippets"].append(snip.replace("\n", " "))
            hit["score"] = min(hit["score"], score)
        return sorted(best.values(), key=lambda h: h["score"])[:limit]

    def recent(self, days: int = 7, platform: str | None = None, limit: int = 30) -> list[dict]:
        from datetime import timedelta

        from .vault import iso, now
        cutoff = iso(now() - timedelta(days=days))
        sql = "SELECT path, title, platform, updated, summary FROM docs WHERE kind='conversation' AND updated >= ?"
        args = [cutoff]
        if platform:
            sql += " AND platform = ?"
            args.append(platform)
        sql += " ORDER BY updated DESC LIMIT ?"
        cols = ("path", "title", "platform", "updated", "summary")
        return [dict(zip(cols, r)) for r in self.db.execute(sql, [*args, limit])]

    def stats(self) -> dict:
        rows = self.db.execute("SELECT kind, platform, count(*) FROM docs GROUP BY kind, platform").fetchall()
        return {f"{k}:{p}" if p else k: n for k, p, n in rows}
