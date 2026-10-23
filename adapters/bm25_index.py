import re
from pathlib import Path

from rank_bm25 import BM25Okapi

from core.interfaces import KnowledgeHit

TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def _tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


class BM25Index:
    """One document per markdown file; the title is the first `# ` heading."""

    def __init__(self, docs_dir: Path) -> None:
        self._docs: list[tuple[str, str, str]] = []  # (doc_id, title, text)
        for path in sorted(docs_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            title = text.splitlines()[0].lstrip("# ").strip() if text else path.stem
            self._docs.append((path.stem, title, text))
        self._bm25 = BM25Okapi([_tokenize(f"{title} {text}") for _, title, text in self._docs])

    async def search(self, query: str, k: int = 3) -> list[KnowledgeHit]:
        scores = self._bm25.get_scores(_tokenize(query))
        ranked = sorted(zip(scores, self._docs, strict=True), key=lambda p: p[0], reverse=True)
        return [
            KnowledgeHit(doc_id=doc_id, title=title, text=text, score=float(score))
            for score, (doc_id, title, text) in ranked[:k]
            if score > 0
        ]
