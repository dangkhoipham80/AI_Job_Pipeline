"""Phase 0 smoke tests: config.yaml loads and validates, plus overlay merging."""

from jobpilot.config import get_config, merge_sources


def test_config_loads():
    cfg = get_config()
    assert cfg.crawl.jobs_per_site == 10
    assert cfg.app.edit_max_rounds >= 1


def test_at_least_one_source_defined():
    cfg = get_config()
    assert len(cfg.sources) >= 1
    keys = {s.key for s in cfg.sources}
    assert {"itviec", "topcv", "vietnamworks"} <= keys


def test_overlay_keeps_sources_it_has_never_heard_of():
    """The Settings page writes the source list as it stood when you saved it.
    Overwriting with that list makes every source added since disappear — not
    default-off but *absent*, so the Settings page cannot even offer it. This is
    what hid the tier-2 feeds on any machine that had opened Settings once."""
    base = [
        {"key": "itviec", "tier": 1, "enabled": True},
        {"key": "weworkremotely", "tier": 2, "enabled": True},
    ]
    overlay = [{"key": "itviec", "tier": 1, "enabled": False}]  # saved before tier 2 existed

    merged = merge_sources(base, overlay)
    assert [s["key"] for s in merged] == ["itviec", "weworkremotely"]
    assert merged[0]["enabled"] is False  # your preference still wins
    assert merged[1]["enabled"] is True  # the new source survives


def test_overlay_may_still_add_a_source_of_its_own():
    merged = merge_sources([{"key": "itviec", "enabled": True}], [{"key": "mine", "enabled": True}])
    assert [s["key"] for s in merged] == ["itviec", "mine"]


def test_merge_sources_ignores_junk_entries():
    merged = merge_sources([{"key": "itviec"}], ["nonsense", {"no_key": 1}])
    assert [s["key"] for s in merged] == ["itviec"]


def test_enabled_sources_subset():
    cfg = get_config()
    for s in cfg.enabled_sources():
        assert s.enabled is True
