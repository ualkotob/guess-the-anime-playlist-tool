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

# Timed auto-reveal driver — when an auto-queued reveal round wants to fade its
# overlay fully off over N seconds (the "Reveal after X seconds" option). Ticked
# from the seek-bar loop via update_timed_reveal(); progress is derived from the
# player position (like a lightning round) so it pauses/seeks with playback.
_timed_reveal = {"active": False, "start": None, "length": 0}

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


def should_hide_scoreboard(peek_mode):
    """Whether activating ``peek_mode`` should hide the scoreboard. Per-variant,
    configured under reveal → ``hide_scoreboard`` (default: only 'edge' hides,
    since its side blocks would otherwise cover the scoreboard column)."""
    hide = state.playback.lightning_mode_settings.get("reveal", {}).get("hide_scoreboard", {})
    return bool(hide.get(peek_mode, peek_mode == "edge"))


def _activate_peek_variant(peek_mode):
    """Activate a specific peek variant by name."""
    global peek_modifier, gap_modifier
    _had_existing = bool(peek_overlay.peek_overlay1 or edge_overlay.edge_overlay_box
                         or grow_overlay.grow_overlay_boxes or filter_overlay.filter_vf_active)
    gap_modifier = 0
    # Hiding is per-variant; send "show" for non-hiding variants so switching
    # from a hiding variant (e.g. edge) restores the scoreboard mid-round.
    scoreboard_control.send_command("hide" if should_hide_scoreboard(peek_mode) else "show")
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


def render_reveal_progress(progress, full_reveal=False):
    """Re-render whichever reveal overlay is currently active at ``progress``
    (0.0 = fully obscured → 1.0 = clear). Shared by the lightning ticker
    (:func:`lightning_manager.update_light_round`) and the timed auto-reveal
    driver below.

    Lightning rounds pass ``full_reveal=False`` so edge/grow keep their
    popularity-scaled cap (the answer phase does the final reveal). The timed
    auto-reveal passes ``full_reveal=True`` so every variant animates all the
    way to clear over the selected number of seconds.
    """
    progress = min(max(progress, 0.0), 1.0)
    data = state.playback.currently_playing.get("data") or {}
    if peek_overlay.peek_overlay1:
        peek_overlay.toggle_peek_overlay(direction=peek_light_direction,
                                         progress=progress * 100, gap=get_peek_gap(data))
    elif edge_overlay.edge_overlay_box:
        edge_max = 100 if full_reveal else max(15, min(70, (data.get('popularity') or 3000) / 12))
        edge_overlay.toggle_edge_overlay(block_percent=100 - (edge_max * progress))
    elif grow_overlay.grow_overlay_boxes:
        grow_max = 100 if full_reveal else max(20, min(60, (data.get('popularity') or 3000) / 10))
        grow_overlay.toggle_grow_overlay(block_percent=100 - (grow_max * progress),
                                         position=grow_overlay.grow_position)
    elif filter_overlay.filter_vf_active:
        filter_overlay.toggle_filter_vf(filter_overlay._filter_vf_variant, progress)
        filter_overlay._update_filter_intensity_bottom_label(filter_overlay._filter_vf_variant, progress)


def set_auto_reveal(mode, variant=None, toggle=True):
    """Select the auto-queued reveal round armed at the start of every theme.

    ``mode``: None | 'reveal' | 'mute' | 'blind' | 'auto'; ``variant``: None
    (random) or a peek variant key. With ``toggle=True`` (the desktop menu
    default) re-selecting the currently active choice turns it off; with
    ``toggle=False`` (e.g. the web host UI) the given value is set directly."""
    if toggle and state.controls.auto_reveal_start == mode and state.controls.auto_reveal_variant == variant:
        state.controls.auto_reveal_start = None
        state.controls.auto_reveal_variant = None
    else:
        state.controls.auto_reveal_start = mode
        state.controls.auto_reveal_variant = None if (not mode or mode in ("blind", "auto")) else variant


def set_auto_reveal_seconds(seconds, toggle=True):
    """Set the 'Reveal after X seconds' fade duration (0 = off/static). With
    ``toggle=True`` (menu) re-selecting the active value turns it off; with
    ``toggle=False`` (web) the value is set directly."""
    state.controls.auto_reveal_seconds = 0 if (toggle and state.controls.auto_reveal_seconds == seconds) else seconds


# Fallback popularity bands for 'auto' mode when no infinite difficulty_groups
# are available. Popularity is a rank — lower = more popular = easier anime — so
# easy themes get the toughest obfuscation and obscure ones the mildest,
# balancing overall round difficulty. These match the app's default easy/medium
# boundaries (INFINITE_SETTINGS_DEFAULT["difficulty_groups"] in infinite.py).
AUTO_EASY_MAX_DEFAULT = 250       # <= this = easy (popular)        → Mute Reveal
AUTO_MEDIUM_MAX_DEFAULT = 1000    # <= this = medium                → Blind
                                  # above          = hard (obscure) → Reveal


def _auto_reveal_bands():
    """(easy_max, medium_max) popularity boundaries for 'auto' mode. Read from
    the active playlist's infinite ``difficulty_groups`` so a customized infinite
    playlist's bands are respected (``get_infinite_settings`` returns the
    playlist's own settings or the global template); fall back to the defaults."""
    try:
        from _app_scripts.playlists import infinite
        groups = infinite.get_infinite_settings().get("difficulty_groups", {})
        easy_max = groups["easy"]["range"][1]
        medium_max = groups["medium"]["range"][1]
        if isinstance(easy_max, (int, float)) and isinstance(medium_max, (int, float)):
            return easy_max, medium_max
    except Exception:
        pass
    return AUTO_EASY_MAX_DEFAULT, AUTO_MEDIUM_MAX_DEFAULT


def resolve_auto_reveal_mode(data):
    """Map a theme's popularity to a round type for 'auto' mode: easy/popular →
    'mute', medium → 'blind', hard/obscure (or unknown) → 'reveal'. Band
    boundaries come from the active infinite playlist's difficulty_groups when
    available (see :func:`_auto_reveal_bands`), else the app defaults."""
    popularity = (data or {}).get("popularity")
    if not isinstance(popularity, (int, float)):
        popularity = 3000  # unknown popularity → treat as obscure/hard
    easy_max, medium_max = _auto_reveal_bands()
    if popularity <= easy_max:
        return "mute"
    if popularity <= medium_max:
        return "blind"
    return "reveal"


def start_timed_reveal(seconds):
    """Arm the timed fade for the reveal overlay just activated this round. The
    fade origin is captured on the first tick so it tracks the new theme's
    playback position rather than any stale reading from the previous round."""
    _timed_reveal.update(active=bool(seconds), start=None, length=max(1, int(seconds)))


def stop_timed_reveal():
    """Disarm the timed fade. Called at every round start so a fade never leaks
    into a later manual/instant reveal that didn't arm one."""
    _timed_reveal["active"] = False


def update_timed_reveal(time):
    """Ticked ~20 Hz from the seek-bar loop. Fades the active reveal overlay off
    over ``length`` seconds of playback, then tears the visuals down. No-op
    unless a timed auto-reveal is armed and we're not inside a lightning round
    (which drives its own reveal transition)."""
    if not _timed_reveal["active"] or state.lightning.light_mode or not is_peek_active():
        return
    if _timed_reveal["start"] is None or time < _timed_reveal["start"]:
        # Adopt the earliest observed position as the origin — robust to a stale
        # first reading and to the user seeking backwards (which re-obscures).
        _timed_reveal["start"] = time
    progress = min(1.0, max(0.0, (time - _timed_reveal["start"]) / _timed_reveal["length"]))
    render_reveal_progress(progress, full_reveal=True)
    if progress >= 1.0:
        _timed_reveal["active"] = False
        destroy_peek()  # fully revealed — tear down the overlay and unmute (Mute Reveal rounds too)
