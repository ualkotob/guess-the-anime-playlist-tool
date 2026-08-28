"""Regression coverage for Auto Queue and reveal-control behavior."""

import math

import pytest

from core.game_state import state
from _app_scripts.playback import blind_screen
from _app_scripts.queue_round.lightning_rounds import (
    lightning_settings,
    peek_dispatch,
)


def _reset_timer():
    peek_dispatch._timed_reveal.update(
        active=False, start=None, length=0, mode="reveal"
    )


def test_timed_reveal_uses_normalized_lightning_progress(monkeypatch):
    rendered = []
    destroyed = []
    countdowns = []
    monkeypatch.setattr(peek_dispatch, "is_peek_active", lambda: True)
    monkeypatch.setattr(
        peek_dispatch,
        "render_reveal_progress",
        lambda progress: rendered.append(progress),
    )
    monkeypatch.setattr(peek_dispatch, "destroy_peek", lambda: destroyed.append(True))
    monkeypatch.setattr(
        peek_dispatch.osd_text,
        "set_countdown",
        lambda value=None, **kwargs: countdowns.append((value, kwargs)),
    )
    monkeypatch.setattr(state.lightning, "light_mode", None)

    _reset_timer()
    peek_dispatch.start_timed_reveal(10)
    peek_dispatch.update_timed_reveal(3)
    peek_dispatch.update_timed_reveal(8)
    peek_dispatch.update_timed_reveal(13)

    assert rendered == [0.0, 0.0, 0.5, 1.0]
    assert countdowns == [
        (10, {"position": "top right"}),
        (5, {"position": "top right"}),
        (0, {"position": "top right"}),
        (None, {}),
    ]
    assert destroyed == [True]
    assert peek_dispatch._timed_reveal["active"] is False


def test_shared_renderer_uses_lightning_edge_endpoint(monkeypatch):
    block_percents = []
    monkeypatch.setattr(state.playback, "currently_playing", {"data": {"popularity": 240}})
    monkeypatch.setattr(peek_dispatch.peek_overlay, "peek_overlay1", None)
    monkeypatch.setattr(peek_dispatch.edge_overlay, "edge_overlay_box", True)
    monkeypatch.setattr(peek_dispatch.grow_overlay, "grow_overlay_boxes", {})
    monkeypatch.setattr(peek_dispatch.filter_overlay, "filter_vf_active", False)
    monkeypatch.setattr(
        peek_dispatch.edge_overlay,
        "toggle_edge_overlay",
        lambda block_percent: block_percents.append(block_percent),
    )

    peek_dispatch.render_reveal_progress(0.5)

    # Lightning's popularity-scaled edge_max is 240 / 12 = 20; halfway
    # therefore covers 90%, rather than Auto Queue stretching halfway to 50%.
    assert block_percents == [90.0]


def test_shared_renderer_uses_lightning_slice_gap_outside_lightning(monkeypatch):
    draws = []
    monkeypatch.setattr(state.playback, "currently_playing", {"data": {"popularity": 120}})
    monkeypatch.setattr(state.lightning, "light_mode", None)
    monkeypatch.setattr(state.lightning, "light_round_started", False)
    monkeypatch.setattr(peek_dispatch, "peek_light_direction", "right")
    monkeypatch.setattr(peek_dispatch.peek_overlay, "peek_overlay1", True)
    monkeypatch.setattr(peek_dispatch.edge_overlay, "edge_overlay_box", None)
    monkeypatch.setattr(peek_dispatch.grow_overlay, "grow_overlay_boxes", {})
    monkeypatch.setattr(peek_dispatch.filter_overlay, "filter_vf_active", False)
    monkeypatch.setattr(
        peek_dispatch.peek_overlay,
        "toggle_peek_overlay",
        lambda **kwargs: draws.append(kwargs),
    )

    peek_dispatch.render_reveal_progress(0.5)

    assert draws == [{"direction": "right", "progress": 50.0, "gap": 2.2}]


def test_automatic_curve_defaults_preserve_current_behavior():
    assert lightning_settings.lightning_mode_settings_default["reveal"][
        "automatic_curve_strength"
    ] == {
        "blur": 100,
        "pixelize": 100,
        "outline": 100,
        "wave": 100,
        "zoom": 100,
    }


def test_old_reveal_settings_gain_legacy_curve_defaults():
    settings = lightning_settings.update_lightning_mode_settings(
        {"reveal": {"length": 15}}
    )

    assert settings["reveal"]["automatic_curve_strength"]["zoom"] == 100


@pytest.mark.parametrize("variant", ["blur", "pixelize", "outline", "wave", "zoom"])
def test_curve_strength_100_returns_exact_legacy_progress(monkeypatch, variant):
    monkeypatch.setattr(
        state.playback,
        "lightning_mode_settings",
        {"reveal": {"automatic_curve_strength": {variant: 100}}},
    )

    assert (
        peek_dispatch.filter_overlay.get_automatic_filter_progress(variant, 0.37)
        == 0.37
    )


@pytest.mark.parametrize("variant", ["blur", "pixelize", "outline", "zoom"])
def test_curve_strength_zero_frontloads_visually_nonlinear_variants(
    monkeypatch, variant
):
    monkeypatch.setattr(
        state.playback,
        "lightning_mode_settings",
        {"reveal": {"automatic_curve_strength": {variant: 0}}},
    )

    adjusted = peek_dispatch.filter_overlay.get_automatic_filter_progress(
        variant, 0.5
    )

    assert 0.5 < adjusted < 1.0


def test_wave_zero_curve_remains_constant_amplitude(monkeypatch):
    monkeypatch.setattr(
        state.playback,
        "lightning_mode_settings",
        {"reveal": {"automatic_curve_strength": {"wave": 0}}},
    )

    assert (
        peek_dispatch.filter_overlay.get_automatic_filter_progress("wave", 0.5)
        == 0.5
    )


@pytest.mark.parametrize("progress", [0.25, 0.5, 0.75])
def test_zero_blur_curve_changes_displayed_intensity_at_constant_pace(
    monkeypatch, progress
):
    monkeypatch.setattr(
        state.playback,
        "lightning_mode_settings",
        {"reveal": {"automatic_curve_strength": {"blur": 0}}},
    )
    adjusted = peek_dispatch.filter_overlay.get_automatic_filter_progress(
        "blur", progress
    )
    radius = 200 * (1 - adjusted)
    displayed_obscurity = math.log(radius) / math.log(200)

    assert displayed_obscurity == pytest.approx(1 - progress)


@pytest.mark.parametrize("progress", [0.25, 0.5, 0.75])
def test_zero_zoom_curve_reveals_frame_fraction_at_constant_pace(
    monkeypatch, progress
):
    monkeypatch.setattr(
        state.playback,
        "lightning_mode_settings",
        {"reveal": {"automatic_curve_strength": {"zoom": 0}}},
    )
    adjusted = peek_dispatch.filter_overlay.get_automatic_filter_progress(
        "zoom", progress
    )
    zoom = 15 - 14 * adjusted
    visible_fraction = 1 / zoom
    normalized_reveal = (visible_fraction - 1 / 15) / (1 - 1 / 15)

    assert normalized_reveal == pytest.approx(progress)


def test_curve_strength_blends_linearized_and_legacy_progress(monkeypatch):
    settings = {"reveal": {"automatic_curve_strength": {"zoom": 0}}}
    monkeypatch.setattr(state.playback, "lightning_mode_settings", settings)
    linearized = peek_dispatch.filter_overlay.get_automatic_filter_progress(
        "zoom", 0.5
    )
    settings["reveal"]["automatic_curve_strength"]["zoom"] = 50

    blended = peek_dispatch.filter_overlay.get_automatic_filter_progress(
        "zoom", 0.5
    )

    assert blended == pytest.approx((linearized + 0.5) / 2)


def test_shared_renderer_applies_curve_only_to_automatic_filter_reveal(
    monkeypatch,
):
    rendered = []
    labels = []
    monkeypatch.setattr(state.playback, "currently_playing", {"data": {}})
    monkeypatch.setattr(peek_dispatch.peek_overlay, "peek_overlay1", None)
    monkeypatch.setattr(peek_dispatch.edge_overlay, "edge_overlay_box", None)
    monkeypatch.setattr(peek_dispatch.grow_overlay, "grow_overlay_boxes", {})
    monkeypatch.setattr(peek_dispatch.filter_overlay, "filter_vf_active", True)
    monkeypatch.setattr(peek_dispatch.filter_overlay, "_filter_vf_variant", "zoom")
    monkeypatch.setattr(
        peek_dispatch.filter_overlay,
        "get_automatic_filter_progress",
        lambda variant, progress: 0.8,
    )
    monkeypatch.setattr(
        peek_dispatch.filter_overlay,
        "toggle_filter_vf",
        lambda variant, progress: rendered.append((variant, progress)),
    )
    monkeypatch.setattr(
        peek_dispatch.filter_overlay,
        "_update_filter_intensity_bottom_label",
        lambda variant, progress: labels.append((variant, progress)),
    )

    peek_dispatch.render_reveal_progress(0.5)

    assert rendered == [("zoom", 0.8)]
    assert labels == [("zoom", 0.8)]


def test_timed_reveal_exclusively_owns_slice_progress(monkeypatch):
    draws = []
    monkeypatch.setattr(state.lightning, "light_round_started", False)
    monkeypatch.setattr(peek_dispatch.peek_overlay, "peek_overlay1", True)
    monkeypatch.setattr(
        peek_dispatch.peek_overlay,
        "toggle_peek_overlay",
        lambda **kwargs: draws.append(kwargs),
    )

    _reset_timer()
    peek_dispatch._timed_reveal["active"] = True

    assert peek_dispatch.update_manual_slice_reveal(
        6, {"popularity": 120}
    ) is False
    assert draws == []


def test_manual_slice_animation_still_runs_without_timer(monkeypatch):
    draws = []
    monkeypatch.setattr(state.lightning, "light_mode", None)
    monkeypatch.setattr(state.lightning, "light_round_started", False)
    monkeypatch.setattr(peek_dispatch, "peek_modifier", 0)
    monkeypatch.setattr(peek_dispatch.peek_overlay, "peek_overlay1", True)
    monkeypatch.setattr(
        peek_dispatch.peek_overlay,
        "toggle_peek_overlay",
        lambda **kwargs: draws.append(kwargs),
    )

    _reset_timer()

    assert peek_dispatch.update_manual_slice_reveal(
        6, {"popularity": 120}
    ) is True
    assert draws == [{"direction": "down", "progress": 50.0, "gap": 1}]


def test_timed_blind_uncovers_at_deadline(monkeypatch):
    uncovered = []
    progress_destroyed = []
    refreshed = []
    countdowns = []
    monkeypatch.setattr(state.lightning, "light_mode", None)
    monkeypatch.setattr(blind_screen, "black_overlay", True)
    monkeypatch.setattr(
        blind_screen, "set_black_screen", lambda toggle: uncovered.append(toggle)
    )
    monkeypatch.setattr(
        peek_dispatch.progress_overlay,
        "set_progress_overlay",
        lambda **kwargs: progress_destroyed.append(kwargs),
    )
    monkeypatch.setattr(
        peek_dispatch.popout_window,
        "_refresh_popout_toggles",
        lambda: refreshed.append(True),
    )
    monkeypatch.setattr(
        peek_dispatch.osd_text,
        "set_countdown",
        lambda value=None, **kwargs: countdowns.append((value, kwargs)),
    )

    _reset_timer()
    peek_dispatch.start_timed_reveal(10, mode="blind")
    peek_dispatch.update_timed_reveal(4)
    peek_dispatch.update_timed_reveal(9)
    assert uncovered == []

    peek_dispatch.update_timed_reveal(14)
    assert uncovered == [False]
    assert progress_destroyed == [{"destroy": True}]
    assert refreshed == [True]
    assert countdowns == [
        (10, {"position": "top right"}),
        (5, {"position": "top right"}),
        (0, {"position": "top right"}),
        (None, {}),
    ]
    assert peek_dispatch._timed_reveal["active"] is False


@pytest.mark.parametrize(
    ("variant", "expected_progress"),
    [
        ("blur", 0.05),
        ("pixelize", 0.05),
        ("outline", 0.05),
        ("wave", 0.05),
        ("zoom", 0.5 / 14),
    ],
)
def test_manual_filter_reveal_uses_variant_interval(
    monkeypatch, variant, expected_progress
):
    rendered = []
    monkeypatch.setattr(peek_dispatch.edge_overlay, "edge_overlay_box", None)
    monkeypatch.setattr(peek_dispatch.grow_overlay, "grow_overlay_boxes", {})
    monkeypatch.setattr(peek_dispatch.filter_overlay, "filter_vf_active", True)
    monkeypatch.setattr(peek_dispatch.filter_overlay, "_filter_vf_variant", variant)
    monkeypatch.setattr(peek_dispatch.filter_overlay, "_filter_vf_last_progress", [0.0])
    monkeypatch.setattr(
        peek_dispatch.filter_overlay,
        "toggle_filter_vf",
        lambda selected_variant, progress: rendered.append(
            (selected_variant, progress)
        ),
    )
    monkeypatch.setattr(
        peek_dispatch.filter_overlay,
        "_update_filter_intensity_bottom_label",
        lambda *_args: None,
    )

    peek_dispatch.widen_peek()

    assert rendered == [(variant, pytest.approx(expected_progress))]


def test_manual_blur_reveal_less_reverses_same_interval(monkeypatch):
    first_step = 0.05
    rendered = []
    monkeypatch.setattr(peek_dispatch.edge_overlay, "edge_overlay_box", None)
    monkeypatch.setattr(peek_dispatch.grow_overlay, "grow_overlay_boxes", {})
    monkeypatch.setattr(peek_dispatch.filter_overlay, "filter_vf_active", True)
    monkeypatch.setattr(peek_dispatch.filter_overlay, "_filter_vf_variant", "blur")
    monkeypatch.setattr(
        peek_dispatch.filter_overlay, "_filter_vf_last_progress", [first_step]
    )
    monkeypatch.setattr(
        peek_dispatch.filter_overlay,
        "toggle_filter_vf",
        lambda variant, progress: rendered.append((variant, progress)),
    )
    monkeypatch.setattr(
        peek_dispatch.filter_overlay,
        "_update_filter_intensity_bottom_label",
        lambda *_args: None,
    )

    peek_dispatch.narrow_peek()

    assert rendered == [("blur", 0.0)]


def test_existing_edge_and_grow_manual_intervals_are_unchanged(monkeypatch):
    edge_draws = []
    grow_draws = []
    monkeypatch.setattr(peek_dispatch, "gap_modifier", 0)
    monkeypatch.setattr(peek_dispatch.edge_overlay, "edge_overlay_box", True)
    monkeypatch.setattr(peek_dispatch.grow_overlay, "grow_overlay_boxes", {})
    monkeypatch.setattr(
        peek_dispatch.edge_overlay,
        "toggle_edge_overlay",
        lambda block_percent: edge_draws.append(block_percent),
    )

    peek_dispatch.widen_peek()

    monkeypatch.setattr(peek_dispatch.edge_overlay, "edge_overlay_box", None)
    monkeypatch.setattr(peek_dispatch.grow_overlay, "grow_overlay_boxes", {"active": True})
    monkeypatch.setattr(peek_dispatch.grow_overlay, "grow_position", "center")
    monkeypatch.setattr(peek_dispatch, "gap_modifier", 0)
    monkeypatch.setattr(
        peek_dispatch.grow_overlay,
        "toggle_grow_overlay",
        lambda block_percent, position: grow_draws.append((block_percent, position)),
    )

    peek_dispatch.widen_peek()

    assert edge_draws == [98]
    assert grow_draws == [(95, "center")]
