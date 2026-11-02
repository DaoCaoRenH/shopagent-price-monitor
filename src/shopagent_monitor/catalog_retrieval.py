"""Deterministic, answer-isolated catalog retrieval implementations."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import time
import unicodedata
from typing import Any, Iterable, Literal, Mapping, Sequence

from .contracts import ProductCandidate


TOKENIZER_VERSION = "unicode-bigram/1"
RETRIEVER_VERSION = "catalog-retriever/1"
INDEX_FIELDS = ("title", "category", "attributes", "options", "description")
DEFAULT_FIELD_WEIGHTS = {
    "title": 3.0,
    "category": 2.5,
    "attributes": 1.8,
    "options": 1.4,
    "description": 0.5,
}
_SEGMENT_RE = re.compile(
    r"[a-z0-9]+(?:[-_.][a-z0-9]+)*|[\u3400-\u4dbf\u4e00-\u9fff]+",
    re.IGNORECASE,
)
_COMPACT_RE = re.compile(r"[^a-z0-9\u3400-\u4dbf\u4e00-\u9fff]+")


def normalize_catalog_text(value: Any) -> str:
    """Normalize public catalog text without translating or semantic rewriting."""

    return unicodedata.normalize("NFKC", str(value or "")).casefold().strip()


def unicode_catalog_terms(value: Any) -> tuple[str, ...]:
    """Tokenize one field value; CJK bigrams never cross source boundaries."""

    terms: list[str] = []
    for match in _SEGMENT_RE.finditer(normalize_catalog_text(value)):
        segment = match.group(0)
        if re.fullmatch(r"[\u3400-\u4dbf\u4e00-\u9fff]+", segment):
            if len(segment) == 1:
                terms.append(segment)
            else:
                terms.extend(segment[index : index + 2] for index in range(len(segment) - 1))
        else:
            terms.append(segment)
    return tuple(terms)


def unicode_query_terms(value: Any) -> tuple[str, ...]:
    """Return deterministic unique query terms while preserving source order."""

    return tuple(dict.fromkeys(unicode_catalog_terms(value)))


def _compact(value: Any) -> str:
    return _COMPACT_RE.sub("", normalize_catalog_text(value))


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


@dataclass(frozen=True)
class CatalogDocument:
    """Public product facts copied into the index; no task/evaluator fields."""

    asin: str
    title: tuple[str, ...]
    category: tuple[str, ...]
    attributes: tuple[str, ...]
    options: tuple[str, ...]
    option_values: tuple[str, ...]
    description: tuple[str, ...]
    public_prices: tuple[float, ...] = ()
    price_coverage_complete: bool = False

    def field_values(self, field: str) -> tuple[str, ...]:
        if field not in INDEX_FIELDS:
            raise ValueError(f"unknown catalog field: {field}")
        return tuple(getattr(self, field))

    def content_hash(self) -> str:
        payload = {
            "asin": self.asin,
            **{field: self.field_values(field) for field in INDEX_FIELDS},
            "public_prices": self.public_prices,
            "price_coverage_complete": self.price_coverage_complete,
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def sanitize_catalog_record(record: Mapping[str, Any]) -> CatalogDocument:
    """Copy only allowlisted public product facts from one raw dataset record."""

    asin = str(record.get("asin", "")).strip()
    title = str(record.get("title", "")).strip()
    subtitle = str(record.get("sub_title", "")).strip()
    category = str(record.get("category", "")).strip()
    attributes = _strings(record.get("attribute"))
    description = str(record.get("full_description", "")).strip()

    option_text: list[str] = []
    option_values: list[str] = []
    option_prices: list[float] = []
    available_option_count = 0
    priced_available_option_count = 0
    raw_options = record.get("customization_options")
    if isinstance(raw_options, Mapping):
        for raw_group, raw_values in raw_options.items():
            group = str(raw_group).strip()
            if group:
                option_text.append(group)
            if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes)):
                continue
            for raw_value in raw_values:
                if not isinstance(raw_value, Mapping):
                    continue
                value = str(raw_value.get("value", "")).strip()
                if value:
                    option_text.append(value)
                    option_values.append(value)
                if raw_value.get("is_available") is False:
                    continue
                available_option_count += 1
                price = _float(raw_value.get("price"))
                if price is not None:
                    option_prices.append(price)
                    priced_available_option_count += 1

    base_prices = tuple(
        price for price in (_float(value) for value in (record.get("pricing") or ())) if price is not None
    )
    public_prices = tuple(sorted(set((*base_prices, *option_prices))))
    price_coverage_complete = bool(public_prices) and (
        available_option_count == 0 or available_option_count == priced_available_option_count
    )
    return CatalogDocument(
        asin=asin,
        title=tuple(value for value in (title, subtitle) if value),
        category=(category,) if category else (),
        attributes=attributes,
        options=tuple(option_text),
        option_values=tuple(option_values),
        description=(description,) if description else (),
        public_prices=public_prices,
        price_coverage_complete=price_coverage_complete,
    )


@dataclass(frozen=True)
class CatalogRetrieverConfig:
    schema: str
    config_id: str
    mode: Literal["r2_fielded_bm25"]
    k1: float = 1.2
    b: float = 0.75
    field_weights: Mapping[str, float] | None = None
    option_phrase_max_df_ratio: float = 0.001

    @classmethod
    def from_file(cls, path: str | Path) -> "CatalogRetrieverConfig":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("schema") != "shopagent.catalog-retriever-config/1":
            raise ValueError("unsupported catalog retriever config schema")
        mode = str(payload.get("mode", ""))
        if mode != "r2_fielded_bm25":
            raise ValueError(f"unsupported catalog retriever mode: {mode}")
        raw_weights = payload.get("field_weights") or DEFAULT_FIELD_WEIGHTS
        weights = {field: float(raw_weights[field]) for field in INDEX_FIELDS}
        if any(value < 0 for value in weights.values()):
            raise ValueError("catalog field weights must be non-negative")
        return cls(
            schema=str(payload["schema"]),
            config_id=str(payload["config_id"]),
            mode=mode,
            k1=float(payload.get("k1", 1.2)),
            b=float(payload.get("b", 0.75)),
            field_weights=weights,
            option_phrase_max_df_ratio=float(payload.get("option_phrase_max_df_ratio", 0.001)),
        )

    def content_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "schema": self.schema,
                    "config_id": self.config_id,
                    "mode": self.mode,
                    "k1": self.k1,
                    "b": self.b,
                    "field_weights": dict(self.field_weights or {}),
                    "option_phrase_max_df_ratio": self.option_phrase_max_df_ratio,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class CatalogSearchResult:
    candidates: tuple[ProductCandidate, ...]
    latency_ms: float


class CatalogRetriever:
    """Fielded Unicode BM25 index over public product fields."""

    def __init__(
        self,
        documents: Sequence[CatalogDocument],
        candidates: Mapping[str, ProductCandidate],
        config: CatalogRetrieverConfig,
    ) -> None:
        self.documents = tuple(documents)
        self.candidates = dict(candidates)
        self.config = config
        if len({document.asin for document in self.documents}) != len(self.documents):
            raise ValueError("catalog documents must have unique ASINs")
        if set(self.candidates) != {document.asin for document in self.documents}:
            raise ValueError("catalog documents and public candidates must have identical ASINs")
        self._asin_by_index = tuple(document.asin for document in self.documents)
        self._document_by_asin = {document.asin: document for document in self.documents}
        self._postings: dict[str, dict[str, tuple[tuple[int, int], ...]]] = {}
        self._lengths: dict[str, tuple[int, ...]] = {}
        self._average_lengths: dict[str, float] = {}
        self._option_phrase_df: Counter[str] = Counter()
        self._build_index()

    def _build_index(self) -> None:
        fields = INDEX_FIELDS
        mutable_postings: dict[str, dict[str, list[tuple[int, int]]]] = {field: defaultdict(list) for field in fields}
        mutable_lengths: dict[str, list[int]] = {field: [] for field in fields}
        for index, document in enumerate(self.documents):
            field_terms: dict[str, tuple[str, ...]] = {}
            for field in INDEX_FIELDS:
                terms = tuple(term for value in document.field_values(field) for term in unicode_catalog_terms(value))
                field_terms[field] = terms
                if field == "options":
                    for value in document.option_values:
                        phrase = _compact(value)
                        if phrase:
                            self._option_phrase_df[phrase] += 1
            for field, terms in field_terms.items():
                frequencies = Counter(terms)
                mutable_lengths[field].append(len(terms))
                for term, frequency in frequencies.items():
                    mutable_postings[field][term].append((index, frequency))
        for field in fields:
            self._postings[field] = {term: tuple(rows) for term, rows in mutable_postings[field].items()}
            lengths = tuple(mutable_lengths[field])
            self._lengths[field] = lengths
            self._average_lengths[field] = sum(lengths) / len(lengths) if lengths else 1.0

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> CatalogSearchResult:
        started = time.perf_counter()
        terms = unicode_query_terms(query)
        if not terms:
            return CatalogSearchResult(candidates=(), latency_ms=(time.perf_counter() - started) * 1000)
        scores: defaultdict[int, float] = defaultdict(float)
        matched_fields: defaultdict[int, set[str]] = defaultdict(set)
        field_names = INDEX_FIELDS
        for field in field_names:
            weight = float((self.config.field_weights or {})[field])
            if weight <= 0:
                continue
            lengths = self._lengths[field]
            average_length = self._average_lengths[field] or 1.0
            postings = self._postings[field]
            for term in terms:
                rows = postings.get(term)
                if not rows:
                    continue
                document_frequency = len(rows)
                idf = math.log(1.0 + (len(self.documents) - document_frequency + 0.5) / (document_frequency + 0.5))
                for index, frequency in rows:
                    length_norm = 1.0 - self.config.b + self.config.b * (lengths[index] / average_length)
                    score = idf * (frequency * (self.config.k1 + 1.0) / (frequency + self.config.k1 * length_norm))
                    scores[index] += weight * score
                    matched_fields[index].add(field)

        ranked: list[tuple[float, str, int]] = []
        query_compact = _compact(query)
        unique_phrase_threshold = max(
            1,
            int(len(self.documents) * self.config.option_phrase_max_df_ratio),
        )
        for index, score in scores.items():
            document = self.documents[index]
            if matched_fields[index] == {"options"}:
                unique_option_match = any(
                    len(phrase) >= 4
                    and phrase in query_compact
                    and self._option_phrase_df[phrase] <= unique_phrase_threshold
                    for phrase in (_compact(value) for value in document.option_values)
                )
                if not unique_option_match:
                    continue
            ranked.append((score, document.asin, index))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        candidates = tuple(
            self.candidates[asin].model_copy(update={"rank": rank})
            for rank, (_, asin, _) in enumerate(ranked[:limit], start=1)
        )
        return CatalogSearchResult(
            candidates=candidates,
            latency_ms=(time.perf_counter() - started) * 1000,
        )


def catalog_documents_from_items(items: Iterable[Any]) -> tuple[CatalogDocument, ...]:
    """Create an answer-free index boundary from already sanitized CatalogItems."""

    documents: list[CatalogDocument] = []
    for item in items:
        option_text: list[str] = []
        option_values: list[str] = []
        for group, values in item.options.items():
            option_text.append(str(group))
            for value in values:
                text = str(value.get("value", "")).strip()
                if text:
                    option_text.append(text)
                    option_values.append(text)
        documents.append(
            CatalogDocument(
                asin=item.candidate.asin,
                title=tuple(value for value in (item.candidate.title, item.subtitle) if value),
                category=(item.candidate.category,) if item.candidate.category else (),
                attributes=tuple(item.attributes),
                options=tuple(option_text),
                option_values=tuple(option_values),
                description=(item.description,) if item.description else (),
                public_prices=tuple(item.public_prices),
                price_coverage_complete=bool(item.price_coverage_complete),
            )
        )
    return tuple(documents)
