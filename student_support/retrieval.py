"""Local ranked retrieval over one small policy document; no embedding API needed."""
import math
import re
from collections import Counter
from pathlib import Path

STOP = set("a an the my i is are can do does what how for of on in to and it me you please about if when this that have has with may would could should tell policy handbook information".split())
ALIASES = {"fees": "fee", "payments": "payment", "pay": "payment", "paying": "payment",
           "failed": "failure", "fails": "failure", "scholarships": "scholarship",
           "courses": "course", "program": "programme", "programs": "programme"}


def words(text):
    return [ALIASES.get(w, w) for w in re.findall(r"[a-z]+", text.lower()) if w not in STOP]


class Handbook:
    def __init__(self, path=None):
        path = path or Path(__file__).resolve().parent.parent / "data/student_handbook.md"
        self.chunks = []
        for section in Path(path).read_text(encoding="utf-8").split("\n## ")[1:]:
            heading, body = section.split("\n", 1)
            chunk_id, title = heading.split(" | ", 1)
            self.chunks.append({"id": chunk_id, "title": title, "text": body.strip(),
                                "source": "Fictional student handbook"})
        self.tokens = [Counter(words(c["title"] + " " + c["text"])) for c in self.chunks]

    def search(self, query, limit=2):
        terms = set(words(query))
        scored = []
        for chunk, counts in zip(self.chunks, self.tokens):
            overlap = terms & counts.keys()
            score = sum((1 + math.log(counts[t])) * math.log(1 + len(self.chunks) /
                        (1 + sum(t in c for c in self.tokens))) for t in overlap)
            # Generic incidental matches are not evidence for an unsupported policy question.
            if score >= 1.0 and overlap:
                scored.append({**chunk, "score": round(score, 3)})
        return sorted(scored, key=lambda x: x["score"], reverse=True)[:limit]
