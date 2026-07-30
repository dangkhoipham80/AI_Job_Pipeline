"""Phase 0 smoke tests: config.yaml loads and validates."""

from jobpilot.config import get_config


def test_config_loads():
    cfg = get_config()
    assert cfg.crawl.jobs_per_site == 10
    assert cfg.app.edit_max_rounds >= 1


def test_at_least_one_source_defined():
    cfg = get_config()
    assert len(cfg.sources) >= 1
    keys = {s.key for s in cfg.sources}
    assert {"itviec", "topcv", "vietnamworks"} <= keys


def test_enabled_sources_subset():
    cfg = get_config()
    for s in cfg.enabled_sources():
        assert s.enabled is True
