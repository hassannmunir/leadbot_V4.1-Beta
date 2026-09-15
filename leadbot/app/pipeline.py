"""
Lead collection orchestration — Performance + Accuracy + Safety balanced.

PERFORMANCE DESIGN:
  Website verification is the bottleneck (3-15s per business, network-bound).
  We parallelize ONLY this step with a thread pool. OSM tile queries stay
  sequential to respect public Overpass server ToS and avoid IP bans.

  Per-host pacing is enforced across ALL worker threads via Guard.wait(),
  which uses a host-level lock — so even with 8 workers, any single website
  never receives concurrent requests. This is the key invariant that makes
  parallelism safe.

ACCURACY DESIGN:
  - Schema.org JSON-LD parsed before regex (structured > unstructured)
  - Contact page fetched when homepage yields no phone/email
  - Website cache prevents re-fetching the same URL within the TTL window
  - OSM data is never overwritten — only gaps are filled
  - Wikidata as final fallback with strict name-similarity validation

SAFETY DESIGN:
  - Guard enforces minimum delay between requests to same host
  - SlidingWindowRateLimiter prevents bursting across all workers
  - robots.txt checked and cached per host (24h TTL)
  - Quota tracker enforces daily API limits across runs
  - Batch flush on crash/Ctrl+C — at most BATCH_SIZE-1 leads ever at risk
  - No proxy rotation, no CAPTCHA bypass, no ToS violations
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from ..discovery.geocode import geocode_region, split_bbox
from ..core.models import Lead
from ..discovery.sources import OpenStreetMapSource, tags_for_niche
from ..core.scoring import LeadScorer
from ..core.utils import quality_score
from ..enrichment.verify import verify_website
from ..enrichment.website_cache import WebsiteCache

# Default batch size for crash-safe flushing to storage
BATCH_SIZE = 20

# Hard ceiling on concurrent workers regardless of config
# Above 12, you hit diminishing returns and risk triggering
# rate-limit blocks on shared infrastructure (Overpass, Wikidata)
MAX_SAFE_WORKERS = 12


class HostPacingRegistry:
    """
    Cross-thread registry that tracks the last request time per host.
    Guard.wait() already does per-host pacing but uses a delay measured
    from the LAST request. When multiple workers fetch different URLs on
    the same host simultaneously, they can all pass the guard check at
    once. This registry serializes concurrent access to the same host
    so only one thread proceeds at a time, while threads for different
    hosts run freely in parallel.

    This is the safety mechanism that makes parallelism respectful:
    - 8 workers fetching 8 different domains -> all run at once (fast)
    - 8 workers all hitting the same domain -> queue up (safe)
    """

    def __init__(self):
        self._host_locks: dict[str, threading.Lock] = {}
        self._registry_lock = threading.Lock()

    def lock_for(self, host: str) -> threading.Lock:
        with self._registry_lock:
            if host not in self._host_locks:
                self._host_locks[host] = threading.Lock()
            return self._host_locks[host]


class RunMetrics:
    """Thread-safe counters for live performance visibility."""

    def __init__(self):
        self._lock = threading.Lock()
        self.start_time = time.monotonic()
        self.verified = 0
        self.cache_hits = 0
        self.contact_found = 0
        self.schema_hits = 0
        self.contact_page_hits = 0
        self.wikidata_hits = 0
        self.website_discoveries = 0
        self.errors = 0

    def record(self, **kwargs):
        with self._lock:
            for key, value in kwargs.items():
                current = getattr(self, key, 0)
                setattr(self, key, current + value)

    def summary(self) -> str:
        elapsed = max(1, time.monotonic() - self.start_time)
        rate = self.verified / elapsed * 3600  # leads per hour
        with self._lock:
            return (
                f"Verified: {self.verified} | "
                f"Rate: {rate:.0f}/hr | "
                f"Contact found: {self.contact_found} "
                f"({self.contact_found/max(1,self.verified)*100:.1f}%) | "
                f"Cache hits: {self.cache_hits} | "
                f"Schema.org: {self.schema_hits} | "
                f"Contact page: {self.contact_page_hits} | "
                f"Wikidata: {self.wikidata_hits} | "
                f"Website discovery: {self.website_discoveries} | "
                f"Errors: {self.errors}"
            )


class LeadPipeline:
    """Coordinate discovery, enrichment, scoring, and append-only storage."""

    def __init__(
        self,
        config: dict,
        guard,
        quota,
        niche_map: dict,
        storage,
        batch_size: Optional[int] = None,
    ):
        self.config = config
        self.guard = guard
        self.quota = quota
        self.niche_map = niche_map
        self.storage = storage

        configured_batch = config.get("storage_batch_size", BATCH_SIZE)
        self.batch_size = max(1, int(batch_size if batch_size is not None else configured_batch))

        self.website_cache = WebsiteCache(
            self.config.get("website_cache_file", "website_cache.sqlite3"),
            self.config.get("website_cache_ttl_seconds", 604800),  # 7 days
        )
        self.scorer = LeadScorer(self.config.get("v4_scoring", {}))
        self._host_pacing = HostPacingRegistry()
        self.metrics = RunMetrics()

    def close(self) -> None:
        """Release persistent resources after a run."""
        self.website_cache.close()

    def _safe_verify(self, lead: Lead, phone_region: str) -> Lead:
        """
        Verify one lead's website with full per-host serialization.

        Called from worker threads. The host-level lock ensures that even
        when multiple workers are running, any given website host is only
        contacted by one thread at a time, regardless of how many workers
        are configured. Different hosts proceed in parallel freely.
        """
        try:
            website_host = ""
            if lead.website:
                from urllib.parse import urlparse
                website_host = urlparse(lead.website).netloc

            # Serialise access to this specific host across all workers
            if website_host:
                host_lock = self._host_pacing.lock_for(website_host)
                with host_lock:
                    verify_website(
                        lead,
                        self.guard,
                        phone_region,
                        self.website_cache,
                        website_discovery_enabled=self.config.get("website_discovery_enabled", True),
                        website_discovery_min_confidence=float(self.config.get("website_discovery_min_confidence", 0.68)),
                        website_discovery_max_results=int(self.config.get("website_discovery_max_results", 6)),
                        website_discovery_search_url=self.config.get(
                            "website_discovery_search_url",
                            "https://html.duckduckgo.com/html/",
                        ),
                        public_contact_search_enabled=bool(self.config.get("public_contact_search_enabled", True)),
                        public_contact_search_min_confidence=float(self.config.get("public_contact_search_min_confidence", 0.72)),
                        public_contact_search_max_results=int(self.config.get("public_contact_search_max_results", 12)),
                    )
            else:
                # No website — Wikidata call is per-business, no host to lock
                verify_website(
                    lead,
                    self.guard,
                    phone_region,
                    self.website_cache,
                    website_discovery_enabled=self.config.get("website_discovery_enabled", True),
                    website_discovery_min_confidence=float(self.config.get("website_discovery_min_confidence", 0.68)),
                    website_discovery_max_results=int(self.config.get("website_discovery_max_results", 6)),
                    website_discovery_search_url=self.config.get(
                        "website_discovery_search_url",
                        "https://html.duckduckgo.com/html/",
                    ),
                    public_contact_search_enabled=bool(self.config.get("public_contact_search_enabled", True)),
                    public_contact_search_min_confidence=float(self.config.get("public_contact_search_min_confidence", 0.72)),
                    public_contact_search_max_results=int(self.config.get("public_contact_search_max_results", 12)),
                )

            # Record metrics
            notes_lower = (lead.notes or "").lower()
            has_contact = bool(lead.email or lead.phone or lead.social_links)
            self.metrics.record(
                verified=1,
                contact_found=1 if has_contact else 0,
                cache_hits=1 if "cached" in notes_lower else 0,
                schema_hits=1 if "schema" in notes_lower else 0,
                contact_page_hits=1 if "contact page" in notes_lower else 0,
                wikidata_hits=1 if "wikidata" in notes_lower else 0,
                website_discoveries=1 if "website_discovery_verified" in (lead.enrichment_stage or "") else 0,
            )

        except Exception as exc:
            self.metrics.record(errors=1, verified=1)
            lead.notes = f"Verification error: {exc}"

        return lead

    def _score(self, lead: Lead) -> Lead:
        """Apply dynamic scoring to a verified lead."""
        scored = self.scorer.score_lead(lead.as_dict())
        for field in (
            "ai_agent_fit_score", "ai_agent_priority", "recommended_offer",
            "contactability_score", "contactability_tier", "is_contactable",
            "contact_channel_count", "lead_quality_score", "lead_quality_tier",
            "sales_priority_score", "sales_priority",
        ):
            setattr(lead, field, scored[field])
        return lead

    def collect_for_query(
        self, query: dict, progress_cb: Callable[[float, str], None]
    ) -> int:
        country = query.get("country", self.config.get("country", ""))
        region = query.get("region", self.config.get("region", ""))
        niche = query.get("niche", "")
        phone_region = self.config.get("phone_region", "US")
        minimum_score = self.config.get("minimum_quality_score", 0)

        # Worker count: configurable, capped at MAX_SAFE_WORKERS
        # Default 6 = good balance of speed vs safety on public APIs
        raw_workers = int(self.config.get("verification_workers", 6))
        workers = max(1, min(raw_workers, MAX_SAFE_WORKERS))
        if workers != raw_workers:
            print(
                f"  [safety] verification_workers capped at {MAX_SAFE_WORKERS} "
                f"(configured: {raw_workers})"
            )

        # ----------------------------------------------------------------
        # Step 1: Niche tag lookup
        # ----------------------------------------------------------------
        tags = tags_for_niche(niche, self.niche_map)
        if not tags:
            print(
                f"Skipping '{niche}': not in niche_map.json. "
                'Add it there as {"category": "...", "value": "..."} '
                "(see OSM wiki for tags)."
            )
            return 0

        # ----------------------------------------------------------------
        # Step 2: Geocode region -> bounding box
        # ----------------------------------------------------------------
        progress_cb(0.02, f"Geocoding '{region}, {country}'...")
        try:
            bbox = geocode_region(
                country,
                region,
                os.getenv("GEOAPIFY_API_KEY", ""),
                self.guard,
                self.quota,
            )
        except RuntimeError as error:
            print(f"Skipping '{region}, {country}': {error}")
            return 0

        # ----------------------------------------------------------------
        # Step 3: Split into tiles, collect from OSM (sequential - ToS safe)
        # ----------------------------------------------------------------
        tiles = split_bbox(
            bbox, max_area_deg2=self.config.get("max_tile_area_deg2", 0.5)
        )
        progress_cb(
            0.08,
            f"'{niche}' in '{region}, {country}' -> {len(tiles)} tile(s) | "
            f"{workers} enrichment worker(s)",
        )

        source = OpenStreetMapSource(
            self.guard,
            endpoints=self.config.get("overpass_endpoints"),
            max_results_per_tile=self.config.get("max_results_per_tile"),
        )
        osm_progress = lambda f, m: progress_cb(0.08 + 0.22 * f, m)
        leads = list(
            source.collect(niche, tags, tiles, country, region, phone_region, osm_progress)
        )
        progress_cb(
            0.30,
            f"{len(leads)} businesses found | "
            f"enriching with {workers} workers...",
        )

        # ----------------------------------------------------------------
        # Step 4: Parallel website enrichment + scoring
        # ----------------------------------------------------------------
        total = len(leads) or 1
        total_added = 0
        buffer: list[Lead] = []
        completed = 0
        buffer_lock = threading.Lock()

        def flush() -> None:
            nonlocal total_added
            if not buffer:
                return
            added = self.storage.append_new_leads(list(buffer))
            total_added += added
            buffer.clear()
            print(
                f"  Flushed batch: {added} new lead(s) saved | "
                f"{self.metrics.summary()}"
            )

        def process_lead(lead: Lead) -> Lead:
            self._safe_verify(lead, phone_region)
            self._score(lead)
            return lead

        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                # Submit ALL leads at once — executor manages the queue
                future_to_lead = {
                    executor.submit(process_lead, lead): lead
                    for lead in leads
                }

                for future in as_completed(future_to_lead):
                    completed += 1
                    lead = future.result()

                    with buffer_lock:
                        if quality_score(lead) >= minimum_score:
                            buffer.append(lead)
                        should_flush = len(buffer) >= self.batch_size

                    progress_cb(
                        0.30 + 0.70 * completed / total,
                        f"Enriched {completed}/{len(leads)} | "
                        f"{self.metrics.contact_found} with contact info",
                    )

                    if should_flush:
                        with buffer_lock:
                            flush()

        except KeyboardInterrupt:
            print("\n  Interrupted — saving what we have...")
        finally:
            with buffer_lock:
                flush()

        # Final metrics summary
        print(f"\n  Run complete: {self.metrics.summary()}")
        return total_added


def collect_for_query(
    query: dict, config: dict, guard, quota, niche_map: dict, progress_cb, storage
) -> int:
    """Compatibility wrapper for callers of the former main.py function."""
    pipeline = LeadPipeline(config, guard, quota, niche_map, storage)
    try:
        return pipeline.collect_for_query(query, progress_cb)
    finally:
        pipeline.close()