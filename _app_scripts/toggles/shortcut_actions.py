"""Runtime shortcut/menu cycle actions."""

_ctx = {}


def set_context(
    *,
    light_modes,
    get_light_mode,
    toggle_light_mode,
    peek_dispatch,
    get_blind_round_toggle,
    toggle_blind_round,
    toggle_peek_round,
    toggle_mute_peek_round,
    bonus,
    guess_extra,
):
    _ctx.clear()
    _ctx.update(locals())


def cycle_light_mode():
    """Cycle through all lightning round modes in defined order."""
    light_mode_keys = list(_ctx["light_modes"].keys())
    try:
        light_cycle_index = light_mode_keys.index(_ctx["get_light_mode"]())
        next_index = (light_cycle_index + 1) % len(light_mode_keys)
    except ValueError:
        next_index = 0

    mode = light_mode_keys[next_index]
    if mode == "variety":
        _ctx["toggle_light_mode"]()
    else:
        _ctx["toggle_light_mode"](mode)


def cycle_blind_peek():
    """Cycle: off -> blind round -> reveal round -> mute reveal round."""
    peek_dispatch = _ctx["peek_dispatch"]
    blind_round_toggle = _ctx["get_blind_round_toggle"]()
    if not (
        peek_dispatch.mute_peek_round_toggle
        or peek_dispatch.peek_round_toggle
        or blind_round_toggle
    ):
        _ctx["toggle_blind_round"]()
    elif not (peek_dispatch.peek_round_toggle or peek_dispatch.mute_peek_round_toggle):
        _ctx["toggle_peek_round"]()
    else:
        _ctx["toggle_mute_peek_round"]()


def cycle_guess_stats():
    """Cycle bonus stat questions: year -> score -> popularity -> members."""
    guessing_extra = _ctx["bonus"].guessing_extra
    if guessing_extra not in ["year", "score", "popularity", "members"]:
        _ctx["guess_extra"]("year")
    elif guessing_extra not in ["score", "popularity", "members"]:
        _ctx["guess_extra"]("score")
    elif guessing_extra not in ["popularity", "members"]:
        _ctx["guess_extra"]("popularity")
    else:
        _ctx["guess_extra"]("members")


def cycle_guess_other():
    """Cycle bonus other questions: freeform -> studio -> song -> artist."""
    guessing_extra = _ctx["bonus"].guessing_extra
    if guessing_extra not in ["freeform", "studio", "song", "artist"]:
        _ctx["guess_extra"]("freeform")
    elif guessing_extra not in ["studio", "song", "artist"]:
        _ctx["guess_extra"]("studio")
    elif guessing_extra not in ["song", "artist"]:
        _ctx["guess_extra"]("song")
    else:
        _ctx["guess_extra"]("artist")
