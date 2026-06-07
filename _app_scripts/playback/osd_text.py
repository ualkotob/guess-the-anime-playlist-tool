"""mpv OSD text primitives and shared ASS font/color helpers."""

from core.game_state import state

# name -> allocated osd-overlay ID (60-79); permanent for the app lifetime
_floating_text_osd_alloc = {}

# PIL font caches for accurate ASS text-width measurement.
_ass_font_cache = {}
_ass_font_cache_regular = {}
_ass_font_cache_narrow = {}
_ass_font_cache_narrow_bold = {}
_courier_font_cache = {}

floating_windows = {}  # name -> osd_id (int); tracks active floating text OSD slots


def osd_command(*args):
    """Send a raw osd-overlay command to the mpv player (no-op on failure).

    Shared by every OSD overlay module; reads the live player from
    ``state.widgets`` so callers need no injection.
    """
    try:
        state.widgets.player._p.command(*args)
    except Exception:
        pass


def set_countdown(value=None, position="top right", inverse=False):
    """Create, update, or remove the countdown overlay."""
    if state.config.inverted_positions:
        position = "top left"

    # Lazy imports: osd_text is a low-level OSD primitive; bonus and the web
    # server sit above (or alongside) it, so reach them at call time.
    import _app_scripts.file.web_server.web_server as web_server
    import _app_scripts.bonus.bonus as bonus
    if bonus.guessing_extra and value is not None and web_server.is_running():
        try:
            web_server.push_timer(float(value), paused=True)
        except (TypeError, ValueError):
            pass
    set_floating_text("Countdown", value, position=position, inverse=inverse)


def bottom_info(value=None, size=80, width_max=0.7, inverse=False):
    set_floating_text("Bottom Info", value, position="bottom center", size=size, width_max=width_max, inverse=inverse)


def top_info(value=None, size=80, width_max=0.7, inverse=False):
    set_floating_text("Top Info", value, position="top center", size=size, width_max=width_max, inverse=inverse)


def _get_courier_font(px):
    """Return a PIL ImageFont for Courier New Bold at px pixels, cached."""
    if px not in _courier_font_cache:
        from PIL import ImageFont

        font = None
        for path in ["C:/Windows/Fonts/courbd.ttf", "C:/Windows/Fonts/cour.ttf", "C:/Windows/Fonts/lucon.ttf"]:
            try:
                font = ImageFont.truetype(path, px)
                break
            except Exception:
                pass
        _courier_font_cache[px] = font
    return _courier_font_cache[px]


def _get_ass_font(fs, bold=True, narrow=False):
    """Return a PIL ImageFont for Arial at fs pixels, cached across calls."""
    if narrow:
        cache = _ass_font_cache_narrow_bold if bold else _ass_font_cache_narrow
        if fs not in cache:
            from PIL import ImageFont

            font = None
            paths = (
                ["C:/Windows/Fonts/arialnb.ttf", "C:/Windows/Fonts/arialn.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"]
                if bold
                else ["C:/Windows/Fonts/arialn.ttf", "C:/Windows/Fonts/arialnb.ttf", "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"]
            )
            for path in paths:
                try:
                    font = ImageFont.truetype(path, fs)
                    break
                except Exception:
                    pass
            cache[fs] = font
        return cache[fs]

    cache = _ass_font_cache if bold else _ass_font_cache_regular
    if fs not in cache:
        from PIL import ImageFont

        font = None
        paths = ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"] if bold else ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"]
        for path in paths:
            try:
                font = ImageFont.truetype(path, fs)
                break
            except Exception:
                pass
        cache[fs] = font
    return cache[fs]


def _get_floating_osd_id(name):
    """Return a stable osd-overlay ID for this name, allocating one from 60-79 if needed."""
    if name not in _floating_text_osd_alloc:
        next_id = 60 + len(_floating_text_osd_alloc)
        if next_id > 79:
            raise RuntimeError("Too many floating text OSD slots (max 20)")
        _floating_text_osd_alloc[name] = next_id
    return _floating_text_osd_alloc[name]


def _color_str_to_ass_bgr(color_str):
    """Convert a Tkinter color string to an ASS BBGGRR hex string."""
    try:
        r16, g16, b16 = state.widgets.root.winfo_rgb(color_str)
        r, g, b = r16 >> 8, g16 >> 8, b16 >> 8
    except Exception:
        r, g, b = 255, 255, 255
    return f"{b:02X}{g:02X}{r:02X}"


def _ass_wrap_text(text, fs, max_w, bold=True):
    """Word-wrap text into lines that fit within max_w OSD pixels at font size fs."""
    words = text.split()
    if not words:
        return [""]
    fnt = _get_ass_font(fs, bold=bold)
    lines, current_words, current_w = [], [], 0
    try:
        sp_w = round(fnt.getlength(" ")) if fnt else round(fs * 0.25)
    except AttributeError:
        sp_w = fnt.getsize(" ")[0] if fnt else round(fs * 0.25)
    for word in words:
        try:
            word_w = round(fnt.getlength(word)) if fnt else round(len(word) * fs * 0.52)
        except AttributeError:
            word_w = fnt.getsize(word)[0] if fnt else round(len(word) * fs * 0.52)
        gap = sp_w if current_words else 0
        if current_words and current_w + gap + word_w > max_w:
            lines.append(" ".join(current_words))
            current_words = [word]
            current_w = word_w
        else:
            current_words.append(word)
            current_w += gap + word_w
    if current_words:
        lines.append(" ".join(current_words))
    return lines


def set_floating_text(name, value, position="top right", size=80, width_max=0.7, inverse=False, align="center"):
    """Create, update, or remove a floating OSD text overlay via mpv osd-overlay."""
    is_empty = (
        value is None
        or value == ""
        or (isinstance(value, str) and value == "0")
        or (isinstance(value, int) and value < 0)
    )

    if is_empty:
        if name in floating_windows:
            osd_id = floating_windows.pop(name)
            try:
                osd_command("osd-overlay", osd_id, "none", "", 0, 0, 0, "no")
            except Exception:
                pass
        return

    player = state.widgets.player
    try:
        osd_w = int(player._p.osd_width or 0)
        osd_h = int(player._p.osd_height or 0)
    except Exception:
        return
    if not osd_w or not osd_h:
        return

    osd_id = _get_floating_osd_id(name)
    floating_windows[name] = osd_id

    text = str(value)
    lines = text.split("\n")
    ass_text = "\\N".join(lines)
    max_line_len = max(len(line) for line in lines)
    num_lines = len(lines)

    modifier = min(osd_w / 2560, osd_h / 1440)
    fs = max(10, round(size * modifier * 1.6))
    pad = max(6, round(osd_h * 0.01))

    def _metrics(f):
        font = _get_ass_font(f)
        if font is not None:
            try:
                widths = []
                for line in lines:
                    bbox = font.getbbox(line or " ")
                    widths.append(bbox[2] - bbox[0])
                tw = max(widths, default=f)
            except AttributeError:
                tw = max((font.getsize(line or " ")[0] for line in lines), default=f)
        else:
            tw = round(max_line_len * f * 0.52)
        th = round(num_lines * f * 1.0)
        return tw, th, pad

    max_px = osd_w * width_max
    text_w, text_h, pad = _metrics(fs)
    while fs > 10 and text_w + pad * 2 > max_px:
        fs -= 1
        text_w, text_h, pad = _metrics(fs)

    if inverse:
        text_bgr = _color_str_to_ass_bgr(state.colors.INVERSE_OVERLAY_TEXT_COLOR)
        bg_bgr = _color_str_to_ass_bgr(state.colors.INVERSE_OVERLAY_BACKGROUND_COLOR)
    else:
        text_bgr = _color_str_to_ass_bgr(state.colors.OVERLAY_TEXT_COLOR)
        bg_bgr = _color_str_to_ass_bgr(state.colors.OVERLAY_BACKGROUND_COLOR)

    margin = max(4, round(10 * modifier))
    bord_bg = max(pad, round(fs * 0.17))

    if "left" in position:
        tx, col = margin + bord_bg, 0
    elif "right" in position:
        tx, col = osd_w - margin - bord_bg, 2
    else:
        tx, col = osd_w // 2, 1
    v_inset = bord_bg if num_lines > 1 else 0
    if "top" in position:
        ty, row = margin + v_inset, 0
    elif "bottom" in position:
        ty, row = osd_h - margin - v_inset, 2
    else:
        ty, row = osd_h // 2, 1
    text_an = [[7, 8, 9], [4, 5, 6], [1, 2, 3]][row][col]

    bg_alpha = "33"
    ass_payload = (
        f"{{\\an{text_an}\\pos({tx},{ty})"
        f"\\1c&H{bg_bgr}&\\1a&H{bg_alpha}&"
        f"\\3c&H{bg_bgr}&\\3a&H{bg_alpha}&"
        f"\\bord{bord_bg}\\shad0\\fs{fs}\\b1}}{ass_text}\n"
        f"{{\\an{text_an}\\pos({tx},{ty})"
        f"\\1c&H{text_bgr}&\\1a&H00&"
        f"\\bord0\\shad0"
        f"\\fs{fs}\\b1}}{ass_text}"
    )

    try:
        osd_command("osd-overlay", osd_id, "ass-events", ass_payload, osd_w, osd_h, 3, "no")
    except Exception as e:
        print(f"Floating text OSD error ({name}): {e}")
