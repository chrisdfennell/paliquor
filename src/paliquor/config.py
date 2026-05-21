"""Central configuration.

Politeness settings live here so there's one obvious place to dial things back.
The User-Agent is built to be *honest*: it names the project and a contact
address so the site operator can reach us. We do not disguise the client.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"

BASE_URL = "https://www.finewineandgoodspirits.com"

# Categories we care about (code -> label), from the published category sitemap.
# Bourbon is the focus; the rest are whiskey siblings kept for context.
WHISKEY_CATEGORIES: dict[str, str] = {
    "152": "Bourbon",
    "156": "Rye Whiskey",
    "157": "American Whiskey",
    "159": "Irish Whiskey",
    "158": "Japanese Whisky",
    "153": "Scotch",
    "160": "Flavored Whiskey",
    "161": "Canadian Whisky",
    "162": "More Imported Whiskey",
}
# Default scrape target. Override on the CLI to include the siblings.
DEFAULT_CATEGORIES = ["152"]


# Curated "allocated" / chase bottles for the radar. Matched as case-insensitive
# substrings of the product name. Kept focused so the radar means something.
ALLOCATED_PATTERNS = [
    "Blanton's", "Weller", "E.H. Taylor", "Colonel E.H. Taylor", "Eagle Rare",
    "George T. Stagg", "Stagg", "Sazerac 18", "William Larue Weller",
    "Thomas H. Handy", "Pappy Van Winkle", "Van Winkle", "Old Rip Van Winkle",
    "Booker's", "Four Roses Limited", "Four Roses Small Batch Select",
    "Michter's 10", "Michter's 20", "Michter's 25", "Michter's Toasted",
    "Old Forester Birthday", "Elijah Craig Barrel Proof", "Elijah Craig 18",
    "Elijah Craig 23", "Henry McKenna 10", "Larceny Barrel Proof",
    "Wild Turkey Rare Breed", "Wild Turkey Master's Keep", "Russell's Reserve 13",
    "1792 Full Proof", "Kentucky Owl", "Garrison Brothers", "Woodinville",
]
_ALLOCATED_LOWER = [p.lower() for p in ALLOCATED_PATTERNS]


def is_allocated(name: str | None) -> bool:
    n = (name or "").lower()
    return any(p in n for p in _ALLOCATED_LOWER)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    contact_email: str = "you@example.com"
    project_url: str = "https://github.com/yourname/paliquor"

    min_request_interval: float = 2.0  # seconds between catalog HTTP requests
    catalog_ttl_hours: int = 168       # how long catalog data stays fresh
    inventory_ttl_hours: int = 6       # how long a store's stock check is cached
    browser_concurrency: int = 1       # headless browser parallelism (keep low)

    request_timeout: float = 30.0
    database_url: str = f"sqlite:///{DATA_DIR / 'paliquor.db'}"

    # Optional SMTP for restock / price-drop alert emails. If unset, alerts are
    # logged instead of sent (so the feature works without credentials).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    # In-process nightly refresh. Off by default; when on, the API process
    # re-scrapes the catalog daily at REFRESH_HOUR (local time) so price history
    # accrues and alerts fire automatically. Empty categories = all whiskey.
    scheduler_enabled: bool = False
    refresh_hour: int = 3
    refresh_categories: str = ""

    @property
    def scheduled_categories(self) -> list[str]:
        if self.refresh_categories.strip():
            return [c.strip() for c in self.refresh_categories.split(",") if c.strip()]
        return list(WHISKEY_CATEGORIES.keys())

    @property
    def user_agent(self) -> str:
        # Honest, identifiable UA with a contact. Looks like a normal browser
        # *and* says who we are — the legitimate way to identify ourselves.
        return (
            "Mozilla/5.0 (compatible; PaLiquorBot/0.1; "
            f"+{self.project_url}; {self.contact_email})"
        )


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(exist_ok=True)
    CACHE_DIR.mkdir(exist_ok=True)
    return Settings()
