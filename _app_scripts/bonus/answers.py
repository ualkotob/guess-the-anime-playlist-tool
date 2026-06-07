"""Bonus-round web-answer scoring + polling.

Owns the scorer for every bonus-question type (numeric proximity, multiple
choice, tags, characters, fixed_mc, yt_bonus, studio/artist/song), the
reveal/score-hint submission path called from `bonus.reset_bonus()`, the
right-column bonus-answers list, and the 1-second poll loop that drains
`web_server.get_answers()` / `get_served()` / `get_removals()` / `get_emojis()`
and watches `scoreboard_data/*.json` mtimes for color/score/team updates.

The scoreboard senders are thin pass-throughs to `scoreboard_control`;
`selected_rules_file` lives in `state.config`.
"""

import os
import json
from datetime import datetime
from tkinter import messagebox

from core.game_state import state
import _app_scripts.bonus.bonus as bonus
import _app_scripts.file.web_server.web_server as web_server
import _app_scripts.file.session_stats as session_stats
import _app_scripts.file.scoreboard_control as scoreboard_control
import _app_scripts.file.session_end as session_end
import _app_scripts.search.search as search_ops
import _app_scripts.playback.blind_screen as blind_screen
import _app_scripts.toggles.censors as censors
import _app_scripts.ui.lists as lists
import _app_scripts.ui.windowing as windowing
import _app_scripts.queue_round.fixed_lightning_actions as fixed_lightning_actions
from _app_scripts.queue_round.lightning_rounds import (
    peek_dispatch, peek_overlay, edge_overlay, grow_overlay, filter_overlay,
)


_scoreboard_colors_mtime = 0.0
_scoreboard_scores_mtime = 0.0
_scoreboard_teams_mtime = 0.0
_last_pushed_scores_snapshot: dict = {}


def _score_bonus_answers(answers, q_type, correct):
    """Compute scores for all answers. Returns {name: pts} (float) in submission order,
    first answer per player wins. Returns empty dict if scoring is not possible."""
    result = {}
    if correct is None or not answers:
        return result

    if q_type in ("year", "members", "popularity", "score"):
        _s = state.playback.bonus_settings.get(q_type, {})
        _def = bonus.BONUS_SETTINGS_DEFAULT[q_type]
        if state.lightning.light_round_started:
            _pt_close = float(_s.get("lightning_points_close", _s.get("points_close", _def["points_close"])))
            _pt_exact = float(_s.get("lightning_points_exact", _s.get("points_exact", _def["points_exact"])))
        else:
            _pt_close = float(_s.get("points_close", _def["points_close"]))
            _pt_exact = float(_s.get("points_exact", _def["points_exact"]))
        try:
            correct_val = float(correct)
        except (TypeError, ValueError):
            return result
        seen = {}
        for entry in answers:
            name = entry["name"].strip()
            if name and name not in seen:
                try:
                    seen[name] = float(entry["answer"].replace(",", ""))
                except ValueError:
                    pass
        if not seen:
            return result
        closest_delta = min(abs(v - correct_val) for v in seen.values())
        # Threshold for "exact" on percentage-scaled types: configurable per type.
        _members_pct = float(state.playback.bonus_settings.get("members", {}).get("exact_pct", 0.10))
        _popularity_pct = float(state.playback.bonus_settings.get("popularity", {}).get("exact_pct", 0.10))
        for name, guess in seen.items():
            if abs(guess - correct_val) <= closest_delta:
                if q_type == "members":
                    exact = correct_val == 0 or (abs(guess - correct_val) / abs(correct_val)) <= _members_pct
                elif q_type == "popularity":
                    exact = correct_val == 0 or (abs(guess - correct_val) / abs(correct_val)) <= _popularity_pct
                elif q_type == "score":
                    exact = round(guess, 1) == round(correct_val, 1)
                else:
                    exact = guess == correct_val
                result[name] = _pt_exact if exact else _pt_close
            else:
                result[name] = 0.0

    elif q_type == "multiple":
        _s = state.playback.bonus_settings.get("multiple", {})
        _def_multiple = bonus.BONUS_SETTINGS_DEFAULT["multiple"]
        _pts = float(_s.get("lightning_points" if state.lightning.light_round_started else "points",
                             _def_multiple["lightning_points"] if state.lightning.light_round_started else _def_multiple["points"]))
        seen = set()
        for entry in answers:
            name = entry["name"].strip()
            if name and name not in seen:
                seen.add(name)
                result[name] = _pts if entry["answer"].strip().lower() == str(correct).strip().lower() else 0.0

    elif q_type in ("studio", "artist", "song"):
        seen = set()
        for entry in answers:
            name = entry["name"].strip()
            if name and name not in seen:
                seen.add(name)
                _s = state.playback.bonus_settings.get(q_type, {})
                _def_choice = bonus.BONUS_SETTINGS_DEFAULT[q_type]
                _pts = float(_s.get("lightning_points" if state.lightning.light_round_started else "points", _def_choice["lightning_points"] if state.lightning.light_round_started else _def_choice["points"]))
                result[name] = _pts if entry["answer"].strip().lower() == str(correct).strip().lower() else 0.0

    elif q_type == "fixed_mc":
        _pts = float((state.lightning.fixed_current_round or {}).get("mc_points", 1))
        seen = set()
        for entry in answers:
            name = entry["name"].strip()
            if name and name not in seen:
                seen.add(name)
                result[name] = _pts if entry["answer"].strip().lower() == str(correct).strip().lower() else 0.0

    elif q_type == "yt_bonus":
        _pts = float(bonus._yt_bonus_pts)
        seen = set()
        for entry in answers:
            name = entry["name"].strip()
            if name and name not in seen:
                seen.add(name)
                result[name] = _pts if entry["answer"].strip().lower() == str(correct).strip().lower() else 0.0

    elif q_type == "tags":
        _s = state.playback.bonus_settings.get("tags", {})
        _def_tags = bonus.BONUS_SETTINGS_DEFAULT["tags"]
        if state.lightning.light_round_started:
            _pt_tag = float(_s.get("lightning_points_per_tag", _s.get("points_per_tag", _def_tags["points_per_tag"])))
        else:
            _pt_tag = float(_s.get("points_per_tag", _def_tags["points_per_tag"]))
        correct_tags = {t.strip().lower() for t in correct} if isinstance(correct, (list, set)) else set()
        seen = set()
        for entry in answers:
            name = entry["name"].strip()
            if name and name not in seen:
                seen.add(name)
                picked = [t.strip().lower() for t in entry["answer"].split(",") if t.strip()]
                if picked:
                    right = sum(1 for t in picked if t in correct_tags)
                    wrong = len(picked) - right
                    result[name] = max(0.0, _pt_tag * right - _pt_tag * wrong)

    elif q_type == "characters":
        _s = state.playback.bonus_settings.get("characters", {})
        _def_chars = bonus.BONUS_SETTINGS_DEFAULT["characters"]
        if state.lightning.light_round_started:
            _pt_char = float(_s.get("lightning_points_per_correct", _def_chars["lightning_points_per_correct"]))
        else:
            _pt_char = float(_s.get("points_per_correct", _def_chars["points_per_correct"]))
        correct_labels = {l.strip().upper() for l in correct} if isinstance(correct, (list, set)) else set()
        seen = set()
        for entry in answers:
            name = entry["name"].strip()
            if name and name not in seen:
                seen.add(name)
                picked = [l.strip().upper() for l in entry["answer"].split(",") if l.strip()]
                right = sum(1 for l in picked if l in correct_labels)
                result[name] = _pt_char * right

    return result


def _evaluate_and_submit_bonus_answers():
    """Called from reset_bonus() to score collected answers and push deltas to the sheet."""
    answers  = bonus._pending_bonus_answers[:]
    correct  = bonus._bonus_correct_answer
    q_type   = bonus.guessing_extra          # still set at this point (cleared after we return)

    scores = _score_bonus_answers(answers, q_type, correct) if (answers and correct is not None) else {}

    score_hints: dict = {}
    if q_type in ("year", "score", "members", "popularity") and scores:
        _s   = state.playback.bonus_settings.get(q_type, {})
        _def = bonus.BONUS_SETTINGS_DEFAULT[q_type]
        _is_light = state.lightning.light_round_started
        _pts_exact = float(_s.get("lightning_points_exact" if _is_light else "points_exact",
                                  _def["lightning_points_exact" if _is_light else "points_exact"]))
        for name, pts in scores.items():
            if pts == 0.0:
                score_hints[name] = "none"
            elif pts >= _pts_exact:
                score_hints[name] = "exact"
            else:
                score_hints[name] = "close"

    if correct is not None and q_type:
        if isinstance(correct, list):
            correct_display = ", ".join(str(t) for t in correct)
        else:
            correct_display = str(correct)
        web_server.reveal_answer(
            correct_display,
            q_type=q_type,
            correct_tags=list(correct) if isinstance(correct, (list, set)) else None,
            score_hints=score_hints or None,
            player_scores=scores or None,
        )
    bonus._pending_bonus_answers.clear()
    bonus._bonus_correct_answer = None

    if answers and q_type:
        seen_names = set()
        log_entries = []
        for e in answers:
            name = e["name"].strip()
            if name and name not in seen_names:
                seen_names.add(name)
                log_entries.append({"name": name, "answer": e["answer"], "pts": scores.get(name, 0)})
        session_stats.add_entry({
            "type": "bonus_question",
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "q_type": q_type,
            "correct": correct,
            "answers": log_entries,
        })
        session_stats.save_session_history(create_text_file=False)

    if not (answers and correct is not None and web_server.is_running()):
        return

    for name, pts in scores.items():
        if pts > 0:
            scoreboard_control.send_score(name, pts)
        answer = next((e["answer"] for e in answers if e["name"].strip() == name), "?")
        print(f"[BONUS] {name}: {answer!r} → +{pts}")


def _preview_bonus_points(answers, q_type, correct):
    """Return {name: display_str} using the shared scorer. Empty string = submitted but not scoring."""
    scores = _score_bonus_answers(answers, q_type, correct)
    result = {}
    for name, pts in scores.items():
        if pts > 0:
            n = int(pts) if pts == int(pts) else pts
            result[name] = f"[+{n}]"
        else:
            result[name] = ""
    return result


def _refresh_bonus_answer_list():
    """Show or update the bonus-answers list in the right column.
    Only acts if no other list is open, or if the bonus-answers list is already open."""
    if state.lists.list_loaded is not None and state.lists.list_loaded != "bonus_answers":
        return
    if not bonus._pending_bonus_answers:
        return  # Leave list as-is (shows last content after round ends; closed via K)

    preview = _preview_bonus_points(bonus._pending_bonus_answers, bonus.guessing_extra, bonus._bonus_correct_answer)

    seen_names = {}
    for entry in bonus._pending_bonus_answers:
        name = entry["name"].strip()
        if name and name not in seen_names:
            pts_str = preview.get(name, "")
            seen_names[name] = {"answer": entry["answer"], "pts": pts_str}

    content = {str(i): v for i, v in enumerate(seen_names.items())}

    def _name_func(key, value):
        name, info = value
        pts = info["pts"]
        answer = info["answer"]
        if bonus.guessing_extra == "freeform":
            pts_col = ""
        elif pts:
            pts_col = f"{pts:<5} "
        else:
            pts_col = "      "
        budget = 47 - len(pts_col) - 2
        name_min = budget // 4
        name_used = max(name_min, min(len(name), budget - len(answer)))
        answer_used = budget - name_used
        if len(name) > name_used:
            name = name[:name_used - 1] + "…"
        if len(answer) > answer_used:
            answer = answer[:answer_used - 1] + "…"
        return f"{pts_col}{name}: {answer}"

    def _do_remove_bonus_answer(idx):
        items = list(seen_names.keys())
        if idx < 0 or idx >= len(items):
            return
        name = items[idx]
        if not state.lists._list_action_from_keyboard:
            if not messagebox.askyesno("Remove Submission", f"Remove {name}'s submission?"):
                return
        bonus._pending_bonus_answers[:] = [e for e in bonus._pending_bonus_answers if e["name"].strip() != name]
        web_server.remove_answer_by_name(name)
        if bonus._pending_bonus_answers:
            _refresh_bonus_answer_list()
        else:
            lists._close_list(state.widgets.right_column)

    lists.show_list("bonus_answers", state.widgets.right_column, content, _name_func,
              _do_remove_bonus_answer, -1, update=True, title="BONUS QUESTION ANSWERS", show_numbers=False)


def _push_web_teams():
    """Read team names from shared file and push to web clients."""
    try:
        path = os.path.join('scoreboard_data', 'scoreboard_teams.json')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                names = json.load(f)
            web_server.push_teams(names)
    except Exception as e:
        print(f"Error pushing teams: {e}")


def _push_web_scores():
    """Read current scores from shared file and push to web host clients."""
    global _last_pushed_scores_snapshot
    try:
        path = os.path.join('scoreboard_data', 'scoreboard_scores.json')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                scores_data = json.load(f)
            try:
                prev = dict(_last_pushed_scores_snapshot or {})
                cur_players = [(str(p.get('name', '') or ''), float(p.get('score', 0.0) or 0.0), str(p.get('team','') or '')) for p in scores_data.get('players', [])]
                cur = {n: (s, t) for (n, s, t) in cur_players}
                prev_names = set(prev.keys())
                cur_names = set(cur.keys())
                removed = prev_names - cur_names
                added = cur_names - prev_names
                if removed and added:
                    pairs = []
                    for old in list(removed):
                        old_score, old_team = prev.get(old, (None, None))
                        candidates = [n for n in added if cur.get(n) == (old_score, old_team)]
                        if len(candidates) == 1:
                            new = candidates[0]
                            pairs.append((old, new))
                            added.remove(new)
                    if pairs:
                        for old_name, new_name in pairs:
                            changed = False
                            renamed_sids = []
                            for sid, pname in list(web_server._connected_players.items()):
                                if sid in web_server._host_sids:
                                    continue
                                if pname == old_name:
                                    web_server._connected_players[sid] = new_name
                                    changed = True
                                    renamed_sids.append(sid)
                            if old_name in web_server._shadow_kicked_players and new_name not in web_server._shadow_kicked_players:
                                web_server._shadow_kicked_players[new_name] = web_server._shadow_kicked_players.pop(old_name)
                            if old_name in web_server._pending_selections:
                                old_pending = web_server._pending_selections.pop(old_name)
                                if new_name not in web_server._pending_selections:
                                    web_server._pending_selections[new_name] = old_pending
                            for a in web_server._submitted_answers:
                                if a.get('name') == old_name:
                                    a['name'] = new_name
                            if old_name in web_server._player_colors and new_name not in web_server._player_colors:
                                web_server._player_colors[new_name] = web_server._player_colors.pop(old_name)
                                try:
                                    clr = web_server._player_colors.get(new_name) or {}
                                    web_server._write_color_command(new_name, str(clr.get('bg', '') or ''), str(clr.get('text', '') or ''))
                                except Exception:
                                    pass
                            if changed:
                                web_server._broadcast_players_update()
                                web_server._emit_peer_answers_update()
                                for sid in renamed_sids:
                                    try:
                                        web_server._socketio.emit('name_forced', {'name': new_name}, to=sid)
                                    except Exception:
                                        pass
                                for sid in list(web_server._host_sids):
                                    try:
                                        web_server._socketio.emit('answer_update', {'answers': list(web_server._submitted_answers)}, to=sid)
                                    except Exception:
                                        pass
            except Exception:
                pass
            try:
                _last_pushed_scores_snapshot = { str(p.get('name','') or ''): (float(p.get('score',0.0) or 0.0), str(p.get('team','') or '')) for p in scores_data.get('players', []) }
            except Exception:
                pass
            cfg_path = os.path.join('scoreboard_data', 'scoreboard_config.json')
            if os.path.exists(cfg_path):
                try:
                    with open(cfg_path, 'r', encoding='utf-8') as cf:
                        sb_cfg = json.load(cf)
                    style = sb_cfg.get('style', {})
                    scores_data['auto_send']      = bool(style.get('delta_auto_send',     {}).get('selected', True))
                    scores_data['delay_together'] = bool(style.get('delta_delay_together', {}).get('selected', False))
                    scores_data['commit_delay']   = int(style.get('delta_commit_delay',   {}).get('selected', 1500))
                    scores_data['score_font']     = str(style.get('score_font', {}).get('selected', 'Consolas'))
                    scores_data['name_font']      = str(style.get('score_font', {}).get('selected', 'Consolas'))
                except Exception:
                    pass
            web_server.push_scores(scores_data)
    except Exception as e:
        print(f"Error pushing scores: {e}")


def _push_web_toggles():
    """Push current toggle states to all web host clients."""
    if not web_server.is_running():
        return
    if not state.playback.fl_rounds_list:
        fixed_lightning_actions.load_fixed_lightning_rounds(filter_missing_themes=True)
    fn = state.playback.currently_playing.get("filename", "")
    _all_censors = censors.get_file_censors(fn) or [] if fn else []
    censor_count      = sum(1 for c in _all_censors if not c.get('nsfw'))
    censor_nsfw_count = sum(1 for c in _all_censors if c.get('nsfw'))
    mute_state = state.controls.light_muted if (state.lightning.light_mode or state.lightning.light_round_started) else state.controls.disable_video_audio
    scoreboard_open = bool(scoreboard_control.is_running())
    scoreboard_visible = bool(scoreboard_open and (scoreboard_control.visible_hint is not False))
    web_server.push_toggles({
        "blind":        blind_screen.black_overlay is not None,
        "reveal":         bool(peek_dispatch.is_peek_active()),
        "mute":         bool(mute_state),
        "censors":      censors.censors_enabled,
        "censors_nsfw": censors.censors_nsfw_enabled,
        "shortcuts":    not state.controls.disable_shortcuts,
        "dock":         bool(windowing.is_docked()),
        "info_start":   bool(state.controls.auto_info_start),
        "info_end":     bool(state.controls.auto_info_end),
        "info_popup":   bool(state.info_display._title_popup_intent and not state.info_display.title_info_only),
        "title_popup":  bool(state.info_display._title_popup_intent and state.info_display.title_info_only),
        "artist_popup": bool(state.info_display._title_popup_intent and state.info_display.artist_info_display),
        "studio_popup": bool(state.info_display._title_popup_intent and state.info_display.studio_info_display),
        "season_popup": bool(state.info_display._title_popup_intent and state.info_display.season_info_display),
        "year_popup":   bool(state.info_display._title_popup_intent and state.info_display.year_info_display),
        "censor_count": censor_count,
        "censor_nsfw_count": censor_nsfw_count,
        "queue_blind":   bool(blind_screen.blind_round_toggle),
        "queue_reveal":    bool(peek_dispatch.peek_round_toggle),
        "queue_mute_reveal": bool(peek_dispatch.mute_peek_round_toggle),
        "queued_peek_variant": peek_dispatch._queued_peek_variant[0] or "",
        "live_peek_variant": (
            "slice" if peek_overlay.peek_overlay1
            else "edge" if edge_overlay.edge_overlay_box
            else "grow" if grow_overlay.grow_overlay_boxes
            else (filter_overlay._filter_vf_variant or "") if filter_overlay.filter_vf_active
            else ""
        ),
        "light_mode":    state.lightning.light_mode or "",
        "has_fixed_lightning": bool(state.playback.fl_rounds_list),
        "has_youtube":   bool(state.metadata.youtube_metadata.get("videos")),
        "yt_queued":     bool(state.playback.youtube_queue),
        "fl_queued":     bool(state.lightning.fixed_lightning_queue),
        "fl_active":     bool(state.lightning.fixed_lightning_round_playlist_data),
        "search_queued": bool(search_ops.search_queue),
        "difficulty":    state.metadata.playlist.get("difficulty", 2),
        "auto_bonus_start": state.controls.auto_bonus_start,
        "active_bonus": bonus.guessing_extra,
        "end_session_popup": bool(session_end.end_message_window),
        "scoreboard_open": scoreboard_open,
        "scoreboard_visible": scoreboard_visible,
        "session_history_count": session_stats.get_themes_played_count(),
        "selected_rules_file": state.config.selected_rules_file,
        "selected_light_mode_settings": state.settings_presets.selected_light_mode_settings,
        "autoplay_fullscreen": bool(state.controls.autoplay_fullscreen),
        "always_on_top": bool(state.controls.mpv_always_on_top),
        "bonus_menu_visibility": {
            t: state.playback.bonus_settings.get(t, {}).get("show_in_menu", True)
            for t in ("freeform", "buzzer", "multiple", "year", "score", "members",
                      "popularity", "tags", "studio", "artist", "song", "characters")
        },
        "reveal_variant_menu_visibility": dict(
            state.playback.lightning_mode_settings.get("reveal", {}).get("show_in_menu", {})
        ),
    })


def _poll_web_answers():
    """Accumulate web answers while a bonus question is active; print all submissions."""
    global _scoreboard_colors_mtime, _scoreboard_scores_mtime, _scoreboard_teams_mtime
    new_answers = False
    for entry in web_server.get_answers():
        print(f"[WEB ANSWER] {entry['name']}: {entry['answer']}")
        if bonus.guessing_extra:
            bonus._pending_bonus_answers.append(entry)
            new_answers = True
            scoreboard_control.send_command(f"[SUBMITTED]{entry['name']}")
    for served_name in web_server.get_served():
        scoreboard_control.send_command(f"[SERVED]{served_name}")
    for removed_name in web_server.get_removals():
        before = len(bonus._pending_bonus_answers)
        bonus._pending_bonus_answers[:] = [e for e in bonus._pending_bonus_answers if e["name"].strip() != removed_name]
        if len(bonus._pending_bonus_answers) != before:
            new_answers = True
    for i, (emoji_name, emoji_char) in enumerate(web_server.get_emojis()):
        delay = i * 600
        state.widgets.root.after(delay, lambda n=emoji_name, e=emoji_char: scoreboard_control.send_command(f"[EMOJI]{n}:{e}"))
    if new_answers or state.lists.list_loaded == "bonus_answers":
        _refresh_bonus_answer_list()
    try:
        _sc_colors_path = os.path.join('scoreboard_data', 'scoreboard_colors.json')
        if os.path.exists(_sc_colors_path):
            mtime = os.path.getmtime(_sc_colors_path)
            if mtime != _scoreboard_colors_mtime:
                _scoreboard_colors_mtime = mtime
                web_server.push_player_colors()
    except Exception:
        pass
    try:
        _sc_scores_path = os.path.join('scoreboard_data', 'scoreboard_scores.json')
        if os.path.exists(_sc_scores_path):
            mtime = os.path.getmtime(_sc_scores_path)
            if mtime != _scoreboard_scores_mtime:
                _scoreboard_scores_mtime = mtime
                _push_web_scores()
    except Exception:
        pass
    try:
        _sc_teams_path = os.path.join('scoreboard_data', 'scoreboard_teams.json')
        if os.path.exists(_sc_teams_path):
            mtime = os.path.getmtime(_sc_teams_path)
            if mtime != _scoreboard_teams_mtime:
                _scoreboard_teams_mtime = mtime
                _push_web_teams()
    except Exception:
        pass
    state.widgets.root.after(1000, _poll_web_answers)


def _start_web_server():
    """Start the web answer server at startup if enabled and a tunnel is available."""
    if not web_server.NGROK_AVAILABLE and not web_server.CLOUDFLARED_AVAILABLE:
        print("[Web Server] No tunnel found (ngrok or cloudflared) — web answer server disabled. "
              "Place ngrok.exe or cloudflared.exe next to this app or install one to PATH.")
        return
    if state.config.WEB_SERVER_ENABLED:
        web_server.start(port=8080, ngrok_domain=state.config.NGROK_DOMAIN or None,
                         cloudflare_token=state.config.CLOUDFLARE_TUNNEL_TOKEN or None,
                         cloudflare_url=state.config.CLOUDFLARE_PUBLIC_URL or None)
        state.widgets.root.after(1000, _poll_web_answers)


def toggle_web_server():
    """Manually start or stop the web answer server from the menu."""
    if web_server.is_running():
        web_server.stop()
        print("[Web Server] Stopped.")
    else:
        web_server.start(port=8080, ngrok_domain=state.config.NGROK_DOMAIN or None,
                         cloudflare_token=state.config.CLOUDFLARE_TUNNEL_TOKEN or None,
                         cloudflare_url=state.config.CLOUDFLARE_PUBLIC_URL or None)
        state.widgets.root.after(1000, _poll_web_answers)
