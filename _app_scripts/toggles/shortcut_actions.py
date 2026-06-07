"""Runtime shortcut/menu cycle actions."""

from core.game_state import state
import _app_scripts.playback.blind_screen as blind_screen
import _app_scripts.queue_round.lightning_rounds.peek_dispatch as peek_dispatch
import _app_scripts.queue_round.lightning_rounds.lightning_settings as lightning_settings
import _app_scripts.queue_round.lightning_rounds.lightning_manager as lightning_manager
import _app_scripts.bonus.bonus as bonus


def cycle_light_mode():
    """Cycle through all lightning round modes in defined order."""
    light_mode_keys = list(lightning_settings.light_modes.keys())
    try:
        light_cycle_index = light_mode_keys.index(state.lightning.light_mode)
        next_index = (light_cycle_index + 1) % len(light_mode_keys)
    except ValueError:
        next_index = 0

    mode = light_mode_keys[next_index]
    if mode == "variety":
        lightning_manager.toggle_light_mode()
    else:
        lightning_manager.toggle_light_mode(mode)


def cycle_blind_peek():
    """Cycle: off -> blind round -> reveal round -> mute reveal round."""
    blind_round_toggle = blind_screen.blind_round_toggle
    if not (
        peek_dispatch.mute_peek_round_toggle
        or peek_dispatch.peek_round_toggle
        or blind_round_toggle
    ):
        blind_screen.toggle_blind_round()
    elif not (peek_dispatch.peek_round_toggle or peek_dispatch.mute_peek_round_toggle):
        peek_dispatch.toggle_peek_round()
    else:
        peek_dispatch.toggle_mute_peek_round()


def cycle_guess_stats():
    """Cycle bonus stat questions: year -> score -> popularity -> members."""
    guessing_extra = bonus.guessing_extra
    if guessing_extra not in ["year", "score", "popularity", "members"]:
        bonus.guess_extra("year")
    elif guessing_extra not in ["score", "popularity", "members"]:
        bonus.guess_extra("score")
    elif guessing_extra not in ["popularity", "members"]:
        bonus.guess_extra("popularity")
    else:
        bonus.guess_extra("members")


def cycle_guess_other():
    """Cycle bonus other questions: freeform -> studio -> song -> artist."""
    guessing_extra = bonus.guessing_extra
    if guessing_extra not in ["freeform", "studio", "song", "artist"]:
        bonus.guess_extra("freeform")
    elif guessing_extra not in ["studio", "song", "artist"]:
        bonus.guess_extra("studio")
    elif guessing_extra not in ["song", "artist"]:
        bonus.guess_extra("song")
    else:
        bonus.guess_extra("artist")
