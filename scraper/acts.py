# Backwards-compatibility shim.
# scraper/acts.py has been superseded by scraper/generic.py.
# All symbols are re-exported from there.
from scraper.generic import *  # noqa: F401, F403
from scraper.generic import (  # noqa: F401 — re-export private helpers used by run_demo.py
    GITHUB_API,
    _Cache,
    _get,
    _find_closing_prs,
    _fetch_pr_diff,
    _has_src_changes,
    _paginate,
    _session,
    _split_diff,
    load_repo_config,
    scrape,
)
