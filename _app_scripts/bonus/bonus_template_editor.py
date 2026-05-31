# _app_scripts/bonus_template_editor.py
# Bonus template editor window — extracted from guess_the_anime.py (Step 25).
import re
import tkinter as tk
from tkinter import messagebox

from core.game_state import state
import _app_scripts.bonus.bonus as bonus
import _app_scripts.queue_round.youtube.youtube_control as youtube_control

# ---------------------------------------------------------------------------
# Injected context (populated by set_context() at startup)
# ---------------------------------------------------------------------------
_get_window_position_and_setup = None
_seek_to = None
_get_projected_player_time = None
BACKGROUND_COLOR = "gray12"
HIGHLIGHT_COLOR = "gray26"


def set_context(*, get_window_position_and_setup, seek_to, get_projected_player_time,
                background_color, highlight_color):
    global _get_window_position_and_setup, _seek_to, _get_projected_player_time
    global BACKGROUND_COLOR, HIGHLIGHT_COLOR
    _get_window_position_and_setup = get_window_position_and_setup
    _seek_to = seek_to
    _get_projected_player_time = get_projected_player_time
    BACKGROUND_COLOR = background_color
    HIGHLIGHT_COLOR = highlight_color


def open_youtube_bonus_template_editor(video_id):
    """Open the bonus template editor for a YouTube video."""
    top = tk.Toplevel()
    top.title(f"Bonus Template Editor — {video_id}")
    top.configure(bg=BACKGROUND_COLOR)
    _get_window_position_and_setup(top)

    questions = list(youtube_control.load_bonus_template(video_id))
    selected_idx = [0]

    font_big = ("Arial", 14)
    font_sm = ("Arial", 12)
    fg = "white"
    bg = BACKGROUND_COLOR
    entry_bg = "#1a1a1a"

    # --- Left panel: question list ---
    left_frame = tk.Frame(top, bg=bg, width=240)
    left_frame.pack(side="left", fill="y", padx=(8, 4), pady=8)
    left_frame.pack_propagate(False)
    tk.Label(left_frame, text="QUESTIONS", font=("Arial", 14, "bold"), bg=bg, fg=fg).pack(pady=(0, 4))
    q_listbox = tk.Listbox(left_frame, bg="#111", fg=fg, selectbackground=HIGHLIGHT_COLOR,
                            font=font_sm, width=28, activestyle="none", relief="flat",
                            highlightthickness=1, highlightbackground="#444")
    q_listbox.pack(fill="both", expand=True)

    # --- Right panel: edit form ---
    right_frame = tk.Frame(top, bg=bg)
    right_frame.pack(side="left", fill="both", expand=True, padx=(4, 8), pady=8)

    r = 0
    tk.Label(right_frame, text="Header:", font=font_big, bg=bg, fg=fg).grid(row=r, column=0, sticky="w", pady=4)
    h_var = tk.StringVar(value="Bonus Question")
    tk.Entry(right_frame, textvariable=h_var, font=font_big, width=52,
             bg=entry_bg, fg=fg, insertbackground=fg).grid(row=r, column=1, columnspan=3, sticky="ew", pady=4, padx=4)
    r += 1

    tk.Label(right_frame, text="Question:", font=font_big, bg=bg, fg=fg).grid(row=r, column=0, sticky="w", pady=4)
    q_var = tk.StringVar()
    tk.Entry(right_frame, textvariable=q_var, font=font_big, width=52,
             bg=entry_bg, fg=fg, insertbackground=fg).grid(row=r, column=1, columnspan=3, sticky="ew", pady=4, padx=4)
    r += 1

    # --- Choices with checkboxes (checked = answer; single-select for now) ---
    tk.Label(right_frame, text="Choices:", font=font_big, bg=bg, fg=fg).grid(row=r, column=0, sticky="nw", pady=4)
    choices_frame = tk.Frame(right_frame, bg=bg)
    choices_frame.grid(row=r, column=1, columnspan=3, sticky="ew", pady=4, padx=4)

    MAX_CHOICES = 10
    choice_checked = [tk.BooleanVar(value=False) for i in range(MAX_CHOICES)]
    choice_text = [tk.StringVar() for _ in range(MAX_CHOICES)]
    choice_btns = []
    choice_rows = []
    choice_entries = []

    CORRECT_ROW_BG    = "#33aa33"   # bright green frame — visible as outline
    CORRECT_ENTRY_BG  = "#0d2b0d"   # dark green entry
    INCORRECT_ROW_BG  = bg
    INCORRECT_ENTRY_BG = entry_bg

    def _apply_row_style(i, is_correct):
        row_bg   = CORRECT_ROW_BG   if is_correct else INCORRECT_ROW_BG
        e_bg     = CORRECT_ENTRY_BG if is_correct else INCORRECT_ENTRY_BG
        btn_bg   = "#226622"        if is_correct else "#662222"
        btn_text = "CORRECT"        if is_correct else "INCORRECT"
        choice_rows[i].configure(bg=row_bg)
        choice_entries[i].configure(bg=e_bg)
        choice_btns[i].configure(text=btn_text, bg=btn_bg)

    def on_correct_toggle(idx):
        """Toggle clicked choice; clicking CORRECT again deselects it."""
        currently_correct = choice_checked[idx].get()
        for i, cv in enumerate(choice_checked):
            cv.set(False)
            _apply_row_style(i, False)
        if not currently_correct:
            choice_checked[idx].set(True)
            _apply_row_style(idx, True)

    for j in range(MAX_CHOICES):
        row_bg = INCORRECT_ROW_BG
        row_f = tk.Frame(choices_frame, bg=row_bg, padx=1, pady=1)
        row_f.pack(fill="x", pady=1)
        choice_rows.append(row_f)
        e_bg = INCORRECT_ENTRY_BG
        ent = tk.Entry(row_f, textvariable=choice_text[j], font=font_sm, width=46,
                       bg=e_bg, fg=fg, insertbackground=fg)
        ent.pack(side="left", fill="x", expand=True, padx=(0, 4))
        choice_entries.append(ent)
        init_bg_btn = "#662222"
        init_text = "INCORRECT"
        btn = tk.Button(row_f, text=init_text, font=font_sm, bg=init_bg_btn, fg=fg,
                        width=10, command=lambda idx=j: on_correct_toggle(idx))
        btn.pack(side="left")
        choice_btns.append(btn)
    r += 1

    # --- Start + End Time on the same row ---
    tk.Label(right_frame, text="Start / End (s):", font=font_big, bg=bg, fg=fg).grid(row=r, column=0, sticky="w", pady=4)
    times_frame = tk.Frame(right_frame, bg=bg)
    times_frame.grid(row=r, column=1, columnspan=3, sticky="w", pady=4, padx=4)

    st_var = tk.DoubleVar(value=0.0)
    tk.Button(times_frame, text="−", font=font_big, bg="#333", fg=fg, width=2,
              command=lambda: st_var.set(round(st_var.get() - 0.1, 1))).pack(side="left")
    tk.Entry(times_frame, textvariable=st_var, font=font_big, width=7,
             bg=entry_bg, fg=fg, insertbackground=fg, justify="center").pack(side="left", padx=2)
    tk.Button(times_frame, text="+", font=font_big, bg="#333", fg=fg, width=2,
              command=lambda: st_var.set(round(st_var.get() + 0.1, 1))).pack(side="left")
    tk.Button(times_frame, text="NOW", font=font_sm, bg="#333", fg=fg,
              command=lambda: st_var.set(round(_get_projected_player_time() / 1000, 1))).pack(side="left", padx=(4, 2))
    tk.Button(times_frame, text="GO", font=font_sm, bg="#224466", fg=fg,
              command=lambda: _seek_to(int(st_var.get() * 1000))).pack(side="left", padx=(0, 16))

    tk.Label(times_frame, text="→", font=font_big, bg=bg, fg="#aaa").pack(side="left", padx=(0, 8))

    et_var = tk.DoubleVar(value=0.0)
    tk.Button(times_frame, text="−", font=font_big, bg="#333", fg=fg, width=2,
              command=lambda: et_var.set(round(et_var.get() - 0.1, 1))).pack(side="left")
    tk.Entry(times_frame, textvariable=et_var, font=font_big, width=7,
             bg=entry_bg, fg=fg, insertbackground=fg, justify="center").pack(side="left", padx=2)
    tk.Button(times_frame, text="+", font=font_big, bg="#333", fg=fg, width=2,
              command=lambda: et_var.set(round(et_var.get() + 0.1, 1))).pack(side="left")
    tk.Button(times_frame, text="NOW", font=font_sm, bg="#333", fg=fg,
              command=lambda: et_var.set(round(_get_projected_player_time() / 1000, 1))).pack(side="left", padx=(4, 2))
    tk.Button(times_frame, text="GO", font=font_sm, bg="#224466", fg=fg,
              command=lambda: _seek_to(int(et_var.get() * 1000))).pack(side="left", padx=(0, 0))
    r += 1

    tk.Label(right_frame, text="Points:", font=font_big, bg=bg, fg=fg).grid(row=r, column=0, sticky="w", pady=4)
    pts_var = tk.DoubleVar(value=1.0)
    tk.Spinbox(right_frame, textvariable=pts_var, from_=0.5, to=10.0, increment=0.5,
               font=font_big, width=8, bg=entry_bg, fg=fg,
               buttonbackground="#333", relief="flat").grid(row=r, column=1, sticky="w", pady=4, padx=4)
    r += 1

    # --- Footer buttons (own row below Points) ---
    btn_frame = tk.Frame(right_frame, bg=bg)
    btn_frame.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(12, 4))

    def refresh_listbox():
        q_listbox.delete(0, tk.END)
        for i, q in enumerate(questions):
            label = f"{i + 1}. {q.get('question', '(empty)')[:28]}"
            q_listbox.insert(tk.END, label)
        if 0 <= selected_idx[0] < len(questions):
            q_listbox.selection_clear(0, tk.END)
            q_listbox.selection_set(selected_idx[0])
            q_listbox.see(selected_idx[0])

    def load_to_form(idx):
        if 0 <= idx < len(questions):
            q = questions[idx]
            h_var.set(q.get("header", "Bonus Question") or "Bonus Question")
            q_var.set(q.get("question", ""))
            choices = q.get("choices", [])
            answer = q.get("answer", "")
            for i in range(MAX_CHOICES):
                if i < len(choices):
                    choice_text[i].set(choices[i])
                    is_correct = choices[i] == answer
                    choice_checked[i].set(is_correct)
                    if choice_btns:
                        _apply_row_style(i, is_correct)
                else:
                    choice_text[i].set("")
                    choice_checked[i].set(False)
                    if choice_btns:
                        _apply_row_style(i, False)
            # If nothing is checked but choices exist, default to first
            if choices and not any(cv.get() for cv in choice_checked):
                pass  # allow no answer to be selected
            st_var.set(float(q.get("start_time", 0.0)))
            et_var.set(float(q.get("end_time", 0.0)))
            pts_var.set(float(q.get("points", 1.0)))

    def save_form_to_questions():
        if 0 <= selected_idx[0] < len(questions):
            all_choices = [choice_text[i].get().strip() for i in range(MAX_CHOICES) if choice_text[i].get().strip()]
            answer = ""
            for i in range(MAX_CHOICES):
                if choice_checked[i].get() and choice_text[i].get().strip():
                    answer = choice_text[i].get().strip()
                    break
            if not answer and all_choices:
                answer = all_choices[0]
            questions[selected_idx[0]] = {
                "header": h_var.get().strip() or "Bonus Question",
                "question": q_var.get().strip(),
                "answer": answer,
                "choices": all_choices,
                "start_time": round(float(st_var.get()), 1),
                "end_time": round(float(et_var.get()), 1),
                "points": float(pts_var.get()),
            }

    def on_listbox_select(event):
        sel = q_listbox.curselection()
        if sel and sel[0] != selected_idx[0]:
            save_form_to_questions()
            selected_idx[0] = sel[0]
            load_to_form(selected_idx[0])

    q_listbox.bind("<<ListboxSelect>>", on_listbox_select)

    def add_question():
        save_form_to_questions()
        questions.append({
            "question": "",
            "answer": "",
            "choices": [],
            "start_time": round(_get_projected_player_time() / 1000, 1),
            "end_time": 0.0,
            "points": 1.0,
        })
        selected_idx[0] = len(questions) - 1
        refresh_listbox()
        load_to_form(selected_idx[0])

    def delete_question():
        if not questions:
            return
        if not messagebox.askyesno("Delete Question", "Delete this question?", parent=top):
            return
        del questions[selected_idx[0]]
        selected_idx[0] = max(0, selected_idx[0] - 1)
        refresh_listbox()
        load_to_form(selected_idx[0])

    def _increment_hash_number(text):
        """Increment the last #N in text by 1, e.g. '#13' → '#14'."""
        return re.sub(r'#(\d+)(?!.*#\d)', lambda m: f'#{int(m.group(1)) + 1}', text)

    def copy_forward():
        save_form_to_questions()
        try:
            offset = float(copy_forward_var.get())
        except ValueError:
            offset = 0.0
        if 0 <= selected_idx[0] < len(questions):
            src = questions[selected_idx[0]]
            new_q = {
                "header": _increment_hash_number(src.get("header", "Bonus Question")),
                "question": _increment_hash_number(src.get("question", "")),
                "answer": "",
                "choices": list(src.get("choices", [])),
                "start_time": round(src.get("start_time", 0.0) + offset, 1),
                "end_time": round(src.get("end_time", 0.0) + offset, 1),
                "points": src.get("points", 1.0),
            }
        else:
            new_q = {"header": "Bonus Question", "question": "", "answer": "", "choices": [], "start_time": 0.0, "end_time": 0.0, "points": 1.0}
        questions.append(new_q)
        selected_idx[0] = len(questions) - 1
        refresh_listbox()
        load_to_form(selected_idx[0])

    def save_all():
        save_form_to_questions()
        youtube_control.save_bonus_template(video_id, questions)
        if state.playback.currently_playing.get("data", {}).get("url") == video_id:
            bonus.setup_for_youtube(list(questions))
        save_btn.configure(text="SAVED!")
        top.after(600, lambda: save_btn.configure(text="SAVE"))

    def calc_common_gap():
        """Return the most common gap between consecutive question start_times (to 1 decimal)."""
        starts = sorted(q.get("start_time", 0) for q in questions if q.get("start_time", 0) > 0)
        if len(starts) < 2:
            return 30
        gaps = [round(starts[i + 1] - starts[i], 1) for i in range(len(starts) - 1)]
        if not gaps:
            return 30
        return max(set(gaps), key=gaps.count)

    def recalc_gap():
        copy_forward_var.set(str(calc_common_gap()))

    # --- Footer buttons ---
    tk.Button(btn_frame, text="ADD QUESTION", font=font_big, bg="#226622", fg=fg,
              command=add_question).pack(side="left", padx=8)
    tk.Button(btn_frame, text="DELETE", font=font_big, bg="#662222", fg=fg,
              command=delete_question).pack(side="left", padx=8)
    tk.Button(btn_frame, text="COPY FORWARD", font=font_big, bg="#224466", fg=fg,
              command=copy_forward).pack(side="left", padx=(16, 2))
    copy_forward_var = tk.StringVar(value=str(calc_common_gap()) if len(questions) >= 2 else "30")
    tk.Entry(btn_frame, textvariable=copy_forward_var, font=font_big, width=4,
             bg=entry_bg, fg=fg, insertbackground=fg, justify="center").pack(side="left", padx=2)
    tk.Label(btn_frame, text="s", font=font_big, bg=bg, fg=fg).pack(side="left")
    tk.Button(btn_frame, text="⟳", font=font_big, bg="#333", fg=fg,
              command=recalc_gap).pack(side="left", padx=(2, 0))
    save_btn = tk.Button(btn_frame, text="SAVE", font=font_big, bg="#333", fg=fg,
                         command=save_all)
    save_btn.pack(side="right", padx=8)

    if not questions:
        questions.append({
            "question": "",
            "answer": "",
            "choices": [],
            "start_time": round(_get_projected_player_time() / 1000, 1),
            "end_time": 0.0,
            "points": 1.0,
        })
    refresh_listbox()
    load_to_form(0)
