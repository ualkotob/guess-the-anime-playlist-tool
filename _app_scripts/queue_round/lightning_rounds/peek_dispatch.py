"""Peek lightning-round dispatch — variant selection, activation, and the
round toggles. Each variant routes to one of the renderer modules
(`peek_overlay`, `edge_overlay`, `grow_overlay`, `filter_overlay`).

Extracted from `guess_the_anime.py`. This module owns the peek-mode
state (`peek_round_toggle`, `mute_peek_round_toggle`, `_queued_peek_variant`,
`gap_modifier`, `peek_modifier`, `last_peek_mode`, `available_peek_modes`,
`peek_light_direction`) and the `_PEEK_VARIANT_LABELS` table.

Cross-module note: `gap_modifier` was previously read by `peek_overlay`
through the broad main globals dict. After this extraction the dispatch
owns it; `peek_overlay` now imports this module lazily and reads
`peek_dispatch.gap_modifier` directly.

Cross-module calls go directly to the owning sibling modules
(``scoreboard_control``, ``progress_overlay``, ``coming_up_ui``,
``popout_window``, ``audio_toggles`` at module level; ``blind_screen``
lazily, since it imports this module back). Lightning settings/state come
from ``core.game_state.state``. The live blind state is read directly from
``blind_screen.black_overlay`` (lazy sibling import).
"""
from __future__ import annotations

import random

from core.game_state import state
from . import peek_overlay, edge_overlay, grow_overlay, filter_overlay
import _app_scripts.file.scoreboard_control as scoreboard_control
import _app_scripts.playback.progress_overlay as progress_overlay
import _app_scripts.playback.coming_up_ui as coming_up_ui
import _app_scripts.popout.popout_window as popout_window
import _app_scripts.toggles.audio_toggles as audio_toggles


# ---------------------------------------------------------------------------
# Module state — externally readable (main qualifies as `peek_dispatch.<name>`).
# `peek_round_toggle` / `mute_peek_round_toggle` are queried by many call
# sites (popout toggles, lightning ticker, queue helpers); `gap_modifier`
# is read by `peek_overlay` via lazy sibling import.
# ---------------------------------------------------------------------------
available_peek_modes  = []
last_peek_mode        = ""
peek_modifier         = 0
gap_modifier          = 0
peek_round_toggle     = False
mute_peek_round_toggle = False
_queued_peek_variant  = [None]  # [variant_name | None] — forced variant for next reveal round
peek_light_direction  = None

_PEEK_VARIANT_LABELS = {
    "blur":      ("🌫", "Blur",     "Gaussian blur — strong at the start, fades as the round progresses."),
    "edge":      ("◼",  "Edge",     "Blocks the middle of the screen, showing only the edges. Shrinks the blocked area over time."),
    "grow":      ("⬛", "Grow",     "Small window that slowly expands to reveal more of the video."),
    "outline":   ("✏️",  "Outline",  "Only shows black outlines on white background. Line density increases over time."),
    "pixelize":  ("🟦", "Pixelize", "Heavy pixelation — block size shrinks as the round progresses."),
    "slice":     ("◧",  "Slice",    "Two black panels slide apart to reveal a growing strip of video."),
    "wave":      ("🌊", "Wave",     "Sine-wave spatial warp — distortion amplitude decreases over time."),
    "zoom":      ("🔍", "Zoom",     "Extreme zoom-in on a random region, gradually pulls back to full frame."),
}


def get_next_peek_mode():
    global available_peek_modes, last_peek_mode

    lightning_mode_settings = state.playback.lightning_mode_settings
    if not available_peek_modes:
        all_variants = []
        available_variants = []
        for variant, enabled in lightning_mode_settings.get("reveal", {}).get("variants", {}).items():
            all_variants.append(variant)
            if enabled:
                available_variants.append(variant)
        available_variants = available_variants or all_variants
        while not available_peek_modes:
            available_peek_modes = random.sample(available_variants, k=len(available_variants))
            if len(available_peek_modes) > 1 and available_peek_modes[0] == last_peek_mode:
                available_peek_modes = []

    last_peek_mode = available_peek_modes.pop(0)
    if _queued_peek_variant[0] is not None:
        mode = _queued_peek_variant[0]
        _queued_peek_variant[0] = None
        return mode
    return last_peek_mode


def _activate_peek_variant(peek_mode):
    """Activate a specific peek variant by name."""
    global peek_modifier, gap_modifier
    _had_existing = bool(peek_overlay.peek_overlay1 or edge_overlay.edge_overlay_box
                         or grow_overlay.grow_overlay_boxes or filter_overlay.filter_vf_active)
    gap_modifier = 0
    scoreboard_control.send_command("hide")
    # Activate the new variant first to avoid a visible gap
    if peek_mode == 'edge':
        edge_overlay.toggle_edge_overlay(block_percent=99)
    elif peek_mode == 'grow':
        grow_overlay.set_grow_position()
        grow_overlay.toggle_grow_overlay(block_percent=96, position=grow_overlay.grow_position)
    elif peek_mode == 'slice':
        peek_modifier = random.randint(0, 24)
        peek_overlay.toggle_peek_overlay()
    elif peek_mode in ('blur', 'outline', 'pixelize', 'wave', 'zoom'):
        filter_overlay.filter_vf_active = True
        filter_overlay._filter_vf_variant = peek_mode
        if peek_mode == 'zoom':
            filter_overlay._filter_zoom_offset[0] = random.uniform(-0.35, 0.35)
            filter_overlay._filter_zoom_offset[1] = random.uniform(-0.35, 0.35)
        filter_overlay.toggle_filter_vf(peek_mode, 0)
        filter_overlay._update_filter_intensity_bottom_label(peek_mode, 0)
    # Now remove the old variant (new one is already visible)
    if _had_existing:
        if peek_mode != 'slice':
            peek_overlay.toggle_peek_overlay(destroy=True)
        if peek_mode != 'edge':
            edge_overlay.toggle_edge_overlay(destroy=True)
        if peek_mode != 'grow':
            grow_overlay.toggle_grow_overlay(destroy=True)
        if peek_mode not in ('blur', 'outline', 'pixelize', 'wave', 'zoom'):
            filter_overlay.toggle_filter_vf(destroy=True)
    from _app_scripts.playback import blind_screen
    if blind_screen.black_overlay:
        # Mirror blind()'s dismiss cleanup: tearing down the blind must also
        # remove the manual-blind progress overlay (the animated music-note bar),
        # which set_black_screen(False) alone does not destroy.
        def _drop_blind():
            blind_screen.set_black_screen(False)
            progress_overlay.set_progress_overlay(destroy=True)
        state.widgets.root.after(100, _drop_blind)
    popout_window._refresh_popout_toggles()


def is_peek_active():
    return bool(peek_overlay.peek_overlay1 or edge_overlay.edge_overlay_box
                or grow_overlay.grow_overlay_boxes or filter_overlay.filter_vf_active)


def toggle_peek(toggle=None):
    if toggle is None:
        toggle = not is_peek_active()
    destroy_peek()
    if toggle:
        _activate_peek_variant(get_next_peek_mode())


def destroy_peek():
    scoreboard_control.send_command("show")
    peek_overlay.toggle_peek_overlay(destroy=True)
    edge_overlay.toggle_edge_overlay(destroy=True)
    grow_overlay.toggle_grow_overlay(destroy=True)
    filter_overlay.toggle_filter_vf(destroy=True)
    audio_toggles.toggle_mute(False)


def toggle_peek_round():
    global peek_round_toggle
    from _app_scripts.playback import blind_screen
    peek_round_toggle = not peek_round_toggle
    if peek_round_toggle:
        if blind_screen.blind_round_toggle:
            blind_screen.toggle_blind_round()
        if mute_peek_round_toggle:
            toggle_mute_peek_round()
        if state.config.special_round_warning:
            coming_up_ui.toggle_coming_up_popup(True, "Reveal Round", "Guess the anime from a partially obscured visual.\nThe reveal style varies each round.\nNormal rules apply.", queue=True)
    else:
        coming_up_ui.toggle_coming_up_popup(False, "Reveal Round")


def toggle_mute_peek_round():
    global mute_peek_round_toggle
    from _app_scripts.playback import blind_screen
    mute_peek_round_toggle = not mute_peek_round_toggle
    if mute_peek_round_toggle:
        if peek_round_toggle:
            toggle_peek_round()
        if blind_screen.blind_round_toggle:
            blind_screen.toggle_blind_round()
        if state.config.special_round_warning:
            coming_up_ui.toggle_coming_up_popup(True, "Mute Reveal Round", "Guess the anime from a partially obscured visual.\nThe reveal style varies each round.\nAudio will also be muted.\nNormal rules apply.", queue=True)
    else:
        coming_up_ui.toggle_coming_up_popup(False, "Mute Reveal Round")


def _queue_peek_variant(variant, mute=False):
    """Queue a specific reveal variant for the next round and ensure the round toggle is on."""
    _queued_peek_variant[0] = variant
    if mute:
        if not mute_peek_round_toggle:
            toggle_mute_peek_round()
    else:
        if not peek_round_toggle:
            toggle_peek_round()
    # Override the generic popup with a variant-specific title and description
    if state.config.special_round_warning:
        _, label, tooltip = _PEEK_VARIANT_LABELS.get(variant, ('', variant.title(), ''))
        mute_suffix = "\nAudio will also be muted." if mute else ""
        coming_up_ui.toggle_coming_up_popup(
            True,
            f"Reveal Round: {label}",
            f"Guess the anime from a partially obscured visual.\n{tooltip}{mute_suffix}\nNormal rules apply.",
            queue=True
        )


def _queue_peek_random(mute=False):
    """Clear any queued variant (use random selection) and ensure the round toggle is on."""
    _queued_peek_variant[0] = None
    if mute:
        if not mute_peek_round_toggle:
            toggle_mute_peek_round()
        elif state.config.special_round_warning:
            coming_up_ui.toggle_coming_up_popup(True, "Mute Reveal Round", "Guess the anime from a partially obscured visual.\nThe reveal style varies each round.\nAudio will also be muted.\nNormal rules apply.", queue=True)
    else:
        if not peek_round_toggle:
            toggle_peek_round()
        elif state.config.special_round_warning:
            coming_up_ui.toggle_coming_up_popup(True, "Reveal Round", "Guess the anime from a partially obscured visual.\nThe reveal style varies each round.\nNormal rules apply.", queue=True)


def narrow_peek():
    global gap_modifier
    gap_modifier -= 1
    gap_modifier = max(0, gap_modifier)
    if edge_overlay.edge_overlay_box:
        edge_overlay.toggle_edge_overlay(block_percent=99-gap_modifier)
    elif grow_overlay.grow_overlay_boxes:
        grow_overlay.toggle_grow_overlay(block_percent=96-gap_modifier, position=grow_overlay.grow_position)
    elif filter_overlay.filter_vf_active:
        progress = max(0.0, round(filter_overlay._filter_vf_last_progress[0] - 0.05, 3))
        filter_overlay._filter_vf_last_progress[0] = progress
        filter_overlay.toggle_filter_vf(filter_overlay._filter_vf_variant, progress)
        filter_overlay._update_filter_intensity_bottom_label(filter_overlay._filter_vf_variant, progress)


def widen_peek():
    global gap_modifier
    gap_modifier += 1
    if edge_overlay.edge_overlay_box:
        edge_overlay.toggle_edge_overlay(block_percent=99-gap_modifier)
    elif grow_overlay.grow_overlay_boxes:
        grow_overlay.toggle_grow_overlay(block_percent=96-gap_modifier, position=grow_overlay.grow_position)
    elif filter_overlay.filter_vf_active:
        progress = min(1.0, round(filter_overlay._filter_vf_last_progress[0] + 0.05, 3))
        filter_overlay._filter_vf_last_progress[0] = progress
        filter_overlay.toggle_filter_vf(filter_overlay._filter_vf_variant, progress)
        filter_overlay._update_filter_intensity_bottom_label(filter_overlay._filter_vf_variant, progress)


def get_peek_gap(data):
    if state.lightning.light_mode == 'reveal' or state.lightning.light_round_started:
        gap = (1 + min(9, (data.get('popularity') or 3000)/100))
    else:
        gap = 1
    return gap


def choose_peek_direction():
    global peek_light_direction
    new_dir = peek_light_direction
    while new_dir == peek_light_direction:
        new_dir = random.choice(["right", "down"])
    peek_light_direction = new_dir
