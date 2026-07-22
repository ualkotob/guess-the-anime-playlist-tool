"""Player buzz-in toast + sound generator for bonus rounds.

Owns the BUZZ_PRESETS table, segment-based WAV synth, on-screen toast stack,
and the `set_buzz_callback`-bound entry point `_play_buzz_sound`. Wired into
`web_server` so any player buzz from the web controller triggers the toast +
beep on the host machine.

Cross-module use: `_app_scripts/file/web_server/web_host_actions.py` reaches
`BUZZ_PRESETS`, `_buzz_preset_index`, and `_play_buzz_sound` through this
module directly.
"""

import os
import threading
import time
import tkinter as tk

from core.app_logging import get_logger
from core.game_state import state
from _app_scripts.file.web_server import web_server
from _app_scripts.ui.scaling import scl
import _app_scripts.bonus.bonus as bonus
import _app_scripts.file.scoreboard_control as scoreboard_control


def _web_buzzer_lock():
    if web_server.is_running():
        web_server.control_buzzer("lock")
    if web_server.buzzer_is_locked():
        # Just locked — clear ? marks but keep buzz_order numbers
        scoreboard_control.send_command("[CLEAR_SERVED]")
    else:
        # Just unlocked — restore ? marks; buzz_order preserved so buzzed players keep their number
        for name in web_server.get_connected_player_names():
            scoreboard_control.send_command(f"[SERVED]{name}")


def _web_buzzer_reset():
    if web_server.is_running():
        web_server.control_buzzer("reset")
    scoreboard_control.send_command("[CLEAR_BUZZ_ORDER]")
    for name in web_server.get_connected_player_names():
        scoreboard_control.send_command(f"[SERVED]{name}")


def _web_buzzer_open():
    if web_server.is_running():
        web_server.control_buzzer("open")


_SQ, _TRI, _SAW, _SIN, _NOI = 'sq', 'tri', 'saw', 'sin', 'noi'

BUZZ_PRESETS = [
    # ── No sound ─────────────────────────────────────────────────────────
    ('No Sound', [], []),

    # ── Chimes & Bells (sine, melodic) ───────────────────────────────────
    ('Double Ding',
        [{'f1':520,'wave':_SIN,'dur':180,'vol':0.68,'gap':55},
         {'f1':780,'wave':_SIN,'dur':250,'vol':0.68}],
        [{'f1':520,'wave':_SIN,'dur':120,'vol':0.55,'gap':45},
         {'f1':780,'wave':_SIN,'dur':160,'vol':0.55}]),
    ('Triple Ding',
        [{'f1':330,'wave':_SIN,'dur':110,'vol':0.62,'gap':30},
         {'f1':440,'wave':_SIN,'dur':110,'vol':0.66,'gap':30},
         {'f1':660,'wave':_SIN,'dur':200,'vol':0.70}],
        [{'f1':440,'wave':_SIN,'dur': 80,'vol':0.55,'gap':25},
         {'f1':660,'wave':_SIN,'dur':150,'vol':0.60}]),
    ('Ding Dong',
        [{'f1':587,'wave':_SIN,'dur':200,'vol':0.66,'gap':60},
         {'f1':440,'wave':_SIN,'dur':320,'vol':0.66,'rel':0.4}],
        [{'f1':587,'wave':_SIN,'dur':140,'vol':0.55,'gap':45},
         {'f1':440,'wave':_SIN,'dur':220,'vol':0.55,'rel':0.4}]),
    ('Jingle Up',
        [{'f1':392,'wave':_SIN,'dur': 90,'vol':0.60,'gap':18},
         {'f1':494,'wave':_SIN,'dur': 90,'vol':0.63,'gap':18},
         {'f1':587,'wave':_SIN,'dur': 90,'vol':0.66,'gap':18},
         {'f1':784,'wave':_SIN,'dur':220,'vol':0.70,'rel':0.35}],
        [{'f1':494,'wave':_SIN,'dur': 75,'vol':0.55,'gap':15},
         {'f1':784,'wave':_SIN,'dur':180,'vol':0.62,'rel':0.35}]),
    ('Ding-Ding Up',
        [{'f1':440,'wave':_SIN,'dur':120,'vol':0.64,'gap':35},
         {'f1':660,'wave':_SIN,'dur':200,'vol':0.70,'rel':0.45,'gap':80},
         {'f1':440,'wave':_SIN,'dur':120,'vol':0.64,'gap':35},
         {'f1':660,'wave':_SIN,'dur':200,'vol':0.70,'rel':0.45}],
        [{'f1':523,'wave':_SIN,'dur': 90,'vol':0.55,'gap':28},
         {'f1':784,'wave':_SIN,'dur':150,'vol':0.62,'rel':0.45}]),
    ('Tah-Dah',
        [{'f1':330,'wave':_SIN,'dur': 80,'vol':0.58,'gap':15},
         {'f1':523,'wave':_SIN,'dur': 80,'vol':0.62,'gap':15},
         {'f1':659,'wave':_SIN,'dur':280,'vol':0.70,'rel':0.35}],
        [{'f1':392,'wave':_SIN,'dur': 70,'vol':0.53,'gap':14},
         {'f1':659,'wave':_SIN,'dur':210,'vol':0.62,'rel':0.35}]),

    # ── Ascending Runs ──────────────────────────────────────────────────
    ('Four Step Up',
        [{'f1':294,'wave':_SIN,'dur': 90,'vol':0.58,'gap':18},
         {'f1':370,'wave':_SIN,'dur': 90,'vol':0.61,'gap':18},
         {'f1':440,'wave':_SIN,'dur': 90,'vol':0.65,'gap':18},
         {'f1':587,'wave':_SIN,'dur':240,'vol':0.70,'rel':0.35}],
        [{'f1':370,'wave':_SIN,'dur': 72,'vol':0.53,'gap':15},
         {'f1':587,'wave':_SIN,'dur':180,'vol':0.62,'rel':0.35}]),
    ('Skip Up',
        [{'f1':330,'wave':_SIN,'dur': 95,'vol':0.60,'gap':22},
         {'f1':523,'wave':_SIN,'dur': 95,'vol':0.64,'gap':22},
         {'f1':784,'wave':_SIN,'dur':250,'vol':0.70,'rel':0.35}],
        [{'f1':392,'wave':_SIN,'dur': 75,'vol':0.54,'gap':18},
         {'f1':784,'wave':_SIN,'dur':190,'vol':0.62,'rel':0.35}]),
    ('Big Skip',
        [{'f1':262,'wave':_SIN,'dur':100,'vol':0.60,'gap':25},
         {'f1':523,'wave':_SIN,'dur':100,'vol':0.65,'gap':25},
         {'f1':1047,'wave':_SIN,'dur':260,'vol':0.70,'rel':0.32}],
        [{'f1':330,'wave':_SIN,'dur': 80,'vol':0.54,'gap':20},
         {'f1':880,'wave':_SIN,'dur':200,'vol':0.62,'rel':0.32}]),

    # ── Morse & Pulse (sine) ─────────────────────────────────────────────
    ('Ding Dit-Dah',
        [{'f1':659,'wave':_SIN,'dur': 90,'vol':0.64,'gap':55},
         {'f1':659,'wave':_SIN,'dur':260,'vol':0.70,'rel':0.4}],
        [{'f1':784,'wave':_SIN,'dur': 72,'vol':0.55,'gap':44},
         {'f1':784,'wave':_SIN,'dur':195,'vol':0.62,'rel':0.4}]),
    ('Morse Up',
        [{'f1':523,'wave':_SIN,'dur': 85,'vol':0.62,'gap':52},
         {'f1':659,'wave':_SIN,'dur':240,'vol':0.70,'rel':0.4}],
        [{'f1':587,'wave':_SIN,'dur': 68,'vol':0.54,'gap':42},
         {'f1':784,'wave':_SIN,'dur':185,'vol':0.62,'rel':0.4}]),
    ('Dit-Dit-Dah',
        [{'f1':587,'wave':_SIN,'dur': 80,'vol':0.62,'gap':45},
         {'f1':587,'wave':_SIN,'dur': 80,'vol':0.63,'gap':45},
         {'f1':784,'wave':_SIN,'dur':260,'vol':0.70,'rel':0.38}],
        [{'f1':659,'wave':_SIN,'dur': 65,'vol':0.54,'gap':36},
         {'f1':880,'wave':_SIN,'dur':195,'vol':0.62,'rel':0.38}]),

    # ── Classic Buzz (detuned square) ────────────────────────────────────
    ('Buzz Step Up',
        [{'f1':160,'f2':168,'wave':_SQ,'dur':120,'vol':0.72,'gap':25},
         {'f1':200,'f2':210,'wave':_SQ,'dur':120,'vol':0.74,'gap':25},
         {'f1':260,'f2':272,'wave':_SQ,'dur':260,'vol':0.76}],
        [{'f1':200,'f2':210,'wave':_SQ,'dur': 90,'vol':0.60,'gap':20},
         {'f1':280,'f2':294,'wave':_SQ,'dur':180,'vol':0.63}]),
    ('Blip Blip Blap',
        [{'f1':240,'f2':252,'wave':_SQ,'dur': 90,'vol':0.70,'gap':35},
         {'f1':240,'f2':252,'wave':_SQ,'dur': 90,'vol':0.70,'gap':35},
         {'f1':160,'f2':168,'wave':_SQ,'dur':320,'vol':0.76}],
        [{'f1':280,'f2':294,'wave':_SQ,'dur': 70,'vol':0.58,'gap':28},
         {'f1':190,'f2':200,'wave':_SQ,'dur':220,'vol':0.62}]),
    ('Power Chord Hit',
        [{'f1':196,'f2':294,'wave':_SQ,'dur':120,'vol':0.70,'gap':30},
         {'f1':196,'f2':294,'wave':_SQ,'dur':120,'vol':0.72,'gap':30},
         {'f1':196,'f2':294,'wave':_SQ,'dur':320,'vol':0.76,'rel':0.4}],
        [{'f1':220,'f2':330,'wave':_SQ,'dur': 90,'vol':0.58,'gap':24},
         {'f1':220,'f2':330,'wave':_SQ,'dur':220,'vol':0.63,'rel':0.4}]),
    ('Buzz & Ping',
        [{'f1':155,'f2':163,'wave':_SQ,'dur':280,'vol':0.74,'gap':40},
         {'f1':660,'wave':_SQ,'dur':180,'vol':0.66,'rel':0.35}],
        [{'f1':185,'f2':195,'wave':_SQ,'dur':190,'vol':0.60,'gap':32},
         {'f1':784,'wave':_SQ,'dur':130,'vol':0.55,'rel':0.35}]),
    ('Double Zap',
        [{'f1':200,'f2':212,'wave':_SQ,'dur':150,'vol':0.72,'gap':50},
         {'f1':260,'f2':274,'wave':_SQ,'dur':260,'vol':0.76}],
        [{'f1':240,'f2':254,'wave':_SQ,'dur':110,'vol':0.60,'gap':40},
         {'f1':320,'f2':338,'wave':_SQ,'dur':180,'vol':0.64}]),
    ('Tick-Tock Buzz',
        [{'f1':320,'f2':336,'wave':_SQ,'dur': 80,'vol':0.68,'gap':40},
         {'f1':200,'f2':210,'wave':_SQ,'dur': 80,'vol':0.66,'gap':40},
         {'f1':320,'f2':336,'wave':_SQ,'dur': 80,'vol':0.68,'gap':40},
         {'f1':155,'f2':163,'wave':_SQ,'dur':280,'vol':0.76}],
        [{'f1':260,'f2':274,'wave':_SQ,'dur': 65,'vol':0.56,'gap':32},
         {'f1':185,'f2':195,'wave':_SQ,'dur':200,'vol':0.62}]),
    ('Square Fanfare',
        [{'f1':262,'wave':_SQ,'dur': 80,'vol':0.62,'gap':18},
         {'f1':330,'wave':_SQ,'dur': 80,'vol':0.64,'gap':18},
         {'f1':392,'wave':_SQ,'dur': 80,'vol':0.66,'gap':18},
         {'f1':523,'wave':_SQ,'dur':240,'vol':0.70,'rel':0.38}],
        [{'f1':330,'wave':_SQ,'dur': 65,'vol':0.55,'gap':15},
         {'f1':523,'wave':_SQ,'dur':185,'vol':0.62,'rel':0.38}]),
    # ── Square Punchy ────────────────────────────────────────────────────
    ('Double Buzz',
        [{'f1':165,'f2':172,'wave':_SQ,'dur':220,'vol':0.75,'gap':80},
         {'f1':165,'f2':172,'wave':_SQ,'dur':220,'vol':0.75}],
        [{'f1':200,'f2':210,'wave':_SQ,'dur':150,'vol':0.60,'gap':60},
         {'f1':200,'f2':210,'wave':_SQ,'dur':150,'vol':0.60}]),
    ('Stutter Buzz',
        [{'f1':162,'f2':170,'wave':_SQ,'dur':100,'vol':0.72,'gap':35},
         {'f1':162,'f2':170,'wave':_SQ,'dur':100,'vol':0.72,'gap':35},
         {'f1':162,'f2':170,'wave':_SQ,'dur':320,'vol':0.76}],
        [{'f1':195,'f2':205,'wave':_SQ,'dur': 75,'vol':0.60,'gap':28},
         {'f1':195,'f2':205,'wave':_SQ,'dur':220,'vol':0.63}]),
    ('Morse Dit-Dah',
        [{'f1':700,'wave':_SQ,'dur': 80,'vol':0.66,'gap':60},
         {'f1':700,'wave':_SQ,'dur':230,'vol':0.70}],
        [{'f1':800,'wave':_SQ,'dur': 65,'vol':0.56,'gap':48},
         {'f1':800,'wave':_SQ,'dur':170,'vol':0.60}]),
    ('Buzz Morse Up',
        [{'f1':180,'f2':189,'wave':_SQ,'dur': 80,'vol':0.68,'gap':55},
         {'f1':240,'f2':252,'wave':_SQ,'dur':260,'vol':0.74}],
        [{'f1':210,'f2':220,'wave':_SQ,'dur': 65,'vol':0.56,'gap':44},
         {'f1':280,'f2':294,'wave':_SQ,'dur':185,'vol':0.61}]),
    ('Hard Three',
        [{'f1':196,'f2':206,'wave':_SQ,'dur':100,'vol':0.70,'gap':30},
         {'f1':247,'f2':259,'wave':_SQ,'dur':100,'vol':0.72,'gap':30},
         {'f1':294,'f2':308,'wave':_SQ,'dur':260,'vol':0.76}],
        [{'f1':247,'f2':259,'wave':_SQ,'dur': 80,'vol':0.58,'gap':24},
         {'f1':330,'f2':346,'wave':_SQ,'dur':190,'vol':0.63}]),

    # ── Commented-out originals (kept for reference) ──────────────────────
    # ('Classic Game Show', [{'f1':160,'f2':168,'wave':_SQ,'dur':600,'vol':0.75}], [{'f1':200,'f2':210,'wave':_SQ,'dur':350,'vol':0.60}]),
    # ('Deep & Heavy',      [{'f1':110,'f2':116,'wave':_SQ,'dur':750,'vol':0.80}], [{'f1':140,'f2':148,'wave':_SQ,'dur':400,'vol':0.65}]),
    # ('Sharp Buzz',        [{'f1':220,'f2':232,'wave':_SQ,'dur':500,'vol':0.70}], [{'f1':260,'f2':274,'wave':_SQ,'dur':300,'vol':0.55}]),
    # ('Low Rumble',        [{'f1': 95,'f2':100,'wave':_SQ,'dur':700,'vol':0.82}], [{'f1':120,'f2':126,'wave':_SQ,'dur':380,'vol':0.68}]),
    # ('Fast Beat',         [{'f1':155,'f2':175,'wave':_SQ,'dur':500,'vol':0.72}], [{'f1':190,'f2':212,'wave':_SQ,'dur':300,'vol':0.58}]),
    # ('Long Blast',        [{'f1':140,'f2':155,'wave':_SQ,'dur':900,'vol':0.80}], [{'f1':175,'f2':188,'wave':_SQ,'dur':450,'vol':0.65}]),
    # ('Quick Zap',         [{'f1':200,'f2':214,'wave':_SQ,'dur':260,'vol':0.75}], [{'f1':240,'f2':255,'wave':_SQ,'dur':160,'vol':0.62}]),
    # ('Slow Pulse',        [{'f1':145,'f2':147,'wave':_SQ,'dur':850,'vol':0.78}], [{'f1':175,'f2':177,'wave':_SQ,'dur':440,'vol':0.63}]),
    # ('Mid Growl',         [{'f1':175,'f2':190,'wave':_SQ,'dur':580,'vol':0.74}], [{'f1':210,'f2':228,'wave':_SQ,'dur':310,'vol':0.60}]),
    # ('Sawtooth Grind',    [{'f1':150,'f2':158,'wave':_SAW,'dur':600,'vol':0.72}], [{'f1':185,'f2':194,'wave':_SAW,'dur':320,'vol':0.58}]),
    # ('Angry Saw',         [{'f1':200,'f2':215,'wave':_SAW,'dur':500,'vol':0.75}], [{'f1':240,'f2':257,'wave':_SAW,'dur':280,'vol':0.60}]),
    # ('Saw Sweep Down',    [{'f1':350,'f_end':130,'wave':_SAW,'dur':550,'vol':0.73}], [{'f1':290,'f_end':150,'wave':_SAW,'dur':300,'vol':0.59}]),
    # ('Diesel Horn',       [{'f1':120,'f2':161,'wave':_SAW,'dur':700,'vol':0.78}], [{'f1':150,'f2':200,'wave':_SAW,'dur':380,'vol':0.63}]),
    # ('Soft Triangle',     [{'f1':200,'f2':210,'wave':_TRI,'dur':600,'vol':0.80}], [{'f1':240,'f2':252,'wave':_TRI,'dur':320,'vol':0.65}]),
    # ('Mellow Tri-Buzz',   [{'f1':150,'f2':153,'wave':_TRI,'dur':700,'vol':0.78}], [{'f1':185,'f2':188,'wave':_TRI,'dur':360,'vol':0.63}]),
    # ('Warm Hollow',       [{'f1':130,'f2':134,'wave':_TRI,'dur':680,'vol':0.82,'rel':0.65}], [{'f1':160,'f2':164,'wave':_TRI,'dur':350,'vol':0.66}]),
    # ('Falling Tone',      [{'f1':320,'f_end':140,'wave':_SQ,'dur':500,'vol':0.72}], [{'f1':280,'f_end':160,'wave':_SQ,'dur':300,'vol':0.58}]),
    # ('Rising Chirp',      [{'f1':180,'f_end':480,'wave':_SQ,'dur':350,'vol':0.70}], [{'f1':220,'f_end':380,'wave':_SQ,'dur':200,'vol':0.58}]),
    # ('Dive Bomb',         [{'f1':600,'f_end': 80,'wave':_SAW,'dur':650,'vol':0.75}], [{'f1':500,'f_end':100,'wave':_SAW,'dur':380,'vol':0.60}]),
    # ('Laser Up',          [{'f1': 80,'f_end':800,'wave':_SQ,'dur':400,'vol':0.68}], [{'f1':100,'f_end':600,'wave':_SQ,'dur':250,'vol':0.56}]),
    # ('Boing',             [{'f1':300,'f_end': 90,'wave':_SIN,'dur':500,'vol':0.74,'rel':0.5}], [{'f1':260,'f_end':100,'wave':_SIN,'dur':300,'vol':0.60,'rel':0.5}]),
    # ('Woop Woop',         [{'f1':220,'f_end':350,'wave':_SQ,'dur':180,'vol':0.68,'gap':0},{'f1':350,'f_end':220,'wave':_SQ,'dur':180,'vol':0.68}], [{'f1':260,'f_end':380,'wave':_SQ,'dur':130,'vol':0.58,'gap':0},{'f1':380,'f_end':260,'wave':_SQ,'dur':130,'vol':0.58}]),
    # ('Fanfare Hit',       [{'f1':260,'wave':_SIN,'dur':90,'vol':0.60,'gap':20},{'f1':330,'wave':_SIN,'dur':90,'vol':0.64,'gap':20},{'f1':392,'wave':_SIN,'dur':90,'vol':0.68,'gap':20},{'f1':523,'wave':_SIN,'dur':240,'vol':0.72}], [{'f1':330,'wave':_SIN,'dur':80,'vol':0.55,'gap':18},{'f1':523,'wave':_SIN,'dur':180,'vol':0.62}]),
    # ('Bell Chord',        [{'f1':523,'f2':659,'wave':_SIN,'dur':400,'vol':0.65,'rel':0.4}], [{'f1':523,'f2':659,'wave':_SIN,'dur':250,'vol':0.52,'rel':0.4}]),
    # ('Bright Ping',       [{'f1':880,'wave':_SIN,'dur':280,'vol':0.65,'rel':0.3}], [{'f1':1046,'wave':_SIN,'dur':180,'vol':0.55,'rel':0.3}]),
    # ('Victory Trill',     [{'f1':523,'wave':_SQ,'dur':70,'vol':0.60,'gap':22},{'f1':659,'wave':_SQ,'dur':70,'vol':0.62,'gap':22},{'f1':523,'wave':_SQ,'dur':70,'vol':0.60,'gap':22},{'f1':784,'wave':_SQ,'dur':240,'vol':0.68}], [{'f1':659,'wave':_SQ,'dur':60,'vol':0.55,'gap':18},{'f1':784,'wave':_SQ,'dur':190,'vol':0.60}]),
    # ('Triple Zap',        [{'f1':240,'wave':_SQ,'dur':110,'vol':0.70,'gap':45},{'f1':300,'wave':_SQ,'dur':110,'vol':0.72,'gap':45},{'f1':370,'wave':_SQ,'dur':180,'vol':0.75}], [{'f1':280,'wave':_SQ,'dur':80,'vol':0.60,'gap':35},{'f1':370,'wave':_SQ,'dur':130,'vol':0.62}]),
    # ('Rapid Fire',        [{'f1':180,'f2':188,'wave':_SQ,'dur':75,'vol':0.70,'gap':28},{'f1':180,'f2':188,'wave':_SQ,'dur':75,'vol':0.70,'gap':28},{'f1':180,'f2':188,'wave':_SQ,'dur':75,'vol':0.70,'gap':28},{'f1':180,'f2':188,'wave':_SQ,'dur':210,'vol':0.75}], [{'f1':210,'f2':220,'wave':_SQ,'dur':55,'vol':0.60,'gap':22},{'f1':210,'f2':220,'wave':_SQ,'dur':55,'vol':0.60,'gap':22},{'f1':210,'f2':220,'wave':_SQ,'dur':140,'vol':0.62}]),
    # ('Descending Steps',  [{'f1':400,'wave':_SQ,'dur':130,'vol':0.70,'gap':25},{'f1':320,'wave':_SQ,'dur':130,'vol':0.72,'gap':25},{'f1':240,'wave':_SQ,'dur':130,'vol':0.74,'gap':25},{'f1':160,'wave':_SQ,'dur':250,'vol':0.76}], [{'f1':320,'wave':_SQ,'dur':95,'vol':0.58,'gap':20},{'f1':200,'wave':_SQ,'dur':180,'vol':0.62}]),
    # ('Ascending Steps',   [{'f1':160,'wave':_SQ,'dur':120,'vol':0.68,'gap':22},{'f1':240,'wave':_SQ,'dur':120,'vol':0.70,'gap':22},{'f1':360,'wave':_SQ,'dur':120,'vol':0.72,'gap':22},{'f1':480,'wave':_SQ,'dur':200,'vol':0.75}], [{'f1':200,'wave':_SQ,'dur':90,'vol':0.58,'gap':18},{'f1':400,'wave':_SQ,'dur':160,'vol':0.63}]),
    # ('Noise Blast',       [{'wave':_NOI,'dur':380,'vol':0.65}], [{'wave':_NOI,'dur':210,'vol':0.52}]),
    # ('Noise + Buzz',      [{'wave':_NOI,'dur':120,'vol':0.60,'gap':0},{'f1':160,'f2':168,'wave':_SQ,'dur':480,'vol':0.72}], [{'wave':_NOI,'dur':80,'vol':0.50,'gap':0},{'f1':200,'f2':210,'wave':_SQ,'dur':280,'vol':0.58}]),
    # ('Chirp-Chirp-Win',   [{'f1':500,'f_end':700,'wave':_SQ,'dur':120,'vol':0.62,'gap':35},{'f1':500,'f_end':700,'wave':_SQ,'dur':120,'vol':0.64,'gap':35},{'f1':700,'wave':_SIN,'dur':280,'vol':0.70,'rel':0.38}], [{'f1':600,'f_end':800,'wave':_SQ,'dur':90,'vol':0.55,'gap':28},{'f1':800,'wave':_SIN,'dur':200,'vol':0.62,'rel':0.38}]),
    # ('Bounce x3',         [{'f1':330,'wave':_SIN,'dur':80,'vol':0.56,'gap':28},{'f1':440,'wave':_SIN,'dur':80,'vol':0.60,'gap':28},{'f1':330,'wave':_SIN,'dur':80,'vol':0.56,'gap':28},{'f1':440,'wave':_SIN,'dur':80,'vol':0.60,'gap':28},{'f1':330,'wave':_SIN,'dur':80,'vol':0.56,'gap':28},{'f1':587,'wave':_SIN,'dur':220,'vol':0.70,'rel':0.38}], [{'f1':440,'wave':_SIN,'dur':65,'vol':0.52,'gap':22},{'f1':587,'wave':_SIN,'dur':170,'vol':0.60,'rel':0.38}]),
    # ('Level Up',          [{'f1':262,'wave':_SQ,'dur':80,'vol':0.58,'gap':18},{'f1':330,'wave':_SQ,'dur':80,'vol':0.60,'gap':18},{'f1':392,'wave':_SQ,'dur':80,'vol':0.62,'gap':18},{'f1':523,'wave':_SQ,'dur':80,'vol':0.64,'gap':18},{'f1':659,'wave':_SQ,'dur':80,'vol':0.66,'gap':18},{'f1':784,'wave':_SQ,'dur':220,'vol':0.70,'rel':0.35}], [{'f1':392,'wave':_SQ,'dur':65,'vol':0.55,'gap':15},{'f1':523,'wave':_SQ,'dur':65,'vol':0.58,'gap':15},{'f1':784,'wave':_SQ,'dur':170,'vol':0.64,'rel':0.35}]),
    # ('Stab-Stab-Hold',    [{'f1':587,'wave':_SQ,'dur':100,'vol':0.66,'gap':40},{'f1':587,'wave':_SQ,'dur':100,'vol':0.68,'gap':40},{'f1':784,'wave':_SQ,'dur':300,'vol':0.72,'rel':0.4}], [{'f1':659,'wave':_SQ,'dur':80,'vol':0.58,'gap':32},{'f1':880,'wave':_SQ,'dur':220,'vol':0.64,'rel':0.4}]),
    # ('Bwee-Bwee-Bwoop',  [{'f1':400,'f_end':600,'wave':_TRI,'dur':130,'vol':0.62,'gap':30},{'f1':400,'f_end':600,'wave':_TRI,'dur':130,'vol':0.64,'gap':30},{'f1':600,'f_end':300,'wave':_TRI,'dur':280,'vol':0.70,'rel':0.4}], [{'f1':480,'f_end':680,'wave':_TRI,'dur':100,'vol':0.54,'gap':25},{'f1':680,'f_end':340,'wave':_TRI,'dur':200,'vol':0.62,'rel':0.4}]),
    # ('Tada Chord',        [{'f1':392,'f2':523,'wave':_SIN,'dur':100,'vol':0.62,'gap':25},{'f1':392,'f2':523,'wave':_SIN,'dur':100,'vol':0.64,'gap':25},{'f1':523,'f2':659,'wave':_SIN,'dur':320,'vol':0.72,'rel':0.35}], [{'f1':523,'f2':659,'wave':_SIN,'dur':80,'vol':0.56,'gap':20},{'f1':523,'f2':784,'wave':_SIN,'dur':240,'vol':0.64,'rel':0.35}]),
    # ('Mario Coin',        [{'f1':987,'wave':_SIN,'dur':60,'vol':0.66,'gap':8},{'f1':1318,'wave':_SIN,'dur':180,'vol':0.70,'rel':0.3}], [{'f1':987,'wave':_SIN,'dur':50,'vol':0.56,'gap':7},{'f1':1318,'wave':_SIN,'dur':140,'vol':0.62,'rel':0.3}]),
    # ('Correct! x2',       [{'f1':523,'wave':_SIN,'dur':100,'vol':0.62,'gap':30},{'f1':659,'wave':_SIN,'dur':100,'vol':0.66,'gap':30},{'f1':784,'wave':_SIN,'dur':160,'vol':0.70,'rel':0.4,'gap':65},{'f1':523,'wave':_SIN,'dur':100,'vol':0.62,'gap':30},{'f1':659,'wave':_SIN,'dur':100,'vol':0.66,'gap':30},{'f1':784,'wave':_SIN,'dur':160,'vol':0.70,'rel':0.4}], [{'f1':659,'wave':_SIN,'dur':80,'vol':0.55,'gap':22},{'f1':784,'wave':_SIN,'dur':130,'vol':0.62,'rel':0.4}]),
    # ('Retro Win',         [{'f1':523,'wave':_SQ,'dur':90,'vol':0.60,'gap':20},{'f1':659,'wave':_SQ,'dur':90,'vol':0.63,'gap':20},{'f1':523,'wave':_SQ,'dur':90,'vol':0.60,'gap':20},{'f1':784,'wave':_SQ,'dur':220,'vol':0.68,'rel':0.35,'gap':60},{'f1':523,'wave':_SQ,'dur':90,'vol':0.60,'gap':20},{'f1':659,'wave':_SQ,'dur':90,'vol':0.63,'gap':20},{'f1':523,'wave':_SQ,'dur':90,'vol':0.60,'gap':20},{'f1':784,'wave':_SQ,'dur':220,'vol':0.68,'rel':0.35}], [{'f1':659,'wave':_SQ,'dur':70,'vol':0.55,'gap':16},{'f1':784,'wave':_SQ,'dur':170,'vol':0.62,'rel':0.35}]),
    # ('Jingle Bell Hit',   [{'f1':1047,'wave':_SIN,'dur':70,'vol':0.62,'gap':22},{'f1':784,'wave':_SIN,'dur':70,'vol':0.60,'gap':22},{'f1':1047,'wave':_SIN,'dur':70,'vol':0.64,'gap':22},{'f1':1319,'wave':_SIN,'dur':220,'vol':0.70,'rel':0.35}], [{'f1':784,'wave':_SIN,'dur':55,'vol':0.53,'gap':18},{'f1':1047,'wave':_SIN,'dur':170,'vol':0.60,'rel':0.35}]),
]
_buzz_preset_index = 1  # default: Double Ding


BUZZ_TOAST_MAX_ALPHA = 0.9
_buzz_toast_wins = []   # list of dicts: {win, base_y, cx, h}


def _show_buzz_toast(rank, name):
    """Show a rising, fading toast on-screen when a player buzzes in. Multiple stack upward smoothly."""
    try:
        # Mirror push_player_colors: file is authoritative, in-memory overrides
        merged_colors = {}
        try:
            import json as _json
            _sc_path = os.path.join(web_server._SCOREBOARD_DATA, 'scoreboard_colors.json')
            if os.path.exists(_sc_path):
                with open(_sc_path, 'r', encoding='utf-8') as _f:
                    merged_colors.update(_json.load(_f))
        except Exception:
            pass
        merged_colors.update(web_server._player_colors)
        clr = merged_colors.get(name) or {}
        bg       = clr.get('bg',   state.colors.OVERLAY_BACKGROUND_COLOR)
        fg       = clr.get('text', state.colors.OVERLAY_TEXT_COLOR)
        border_c = fg
    except Exception:
        bg       = state.colors.OVERLAY_BACKGROUND_COLOR
        fg       = state.colors.OVERLAY_TEXT_COLOR
        border_c = fg

    rank_labels = {1: '1st \u2013 BUZZ IN', 2: '2nd \u2013 BUZZ IN', 3: '3rd \u2013 BUZZ IN'}
    rank_str = rank_labels.get(rank, f'#{rank} \u2013 BUZZ IN')

    # Lazy import: buzz (bonus) sits below information_popup, which imports bonus.
    import _app_scripts.information.information_popup as information_popup
    mx, my, mw, mh = information_popup._get_mpv_window_rect()
    _sw = state.widgets.root.winfo_screenwidth()
    _sh = state.widgets.root.winfo_screenheight()
    mpv_frac = max(0.25, min(1.0, min(mw / max(_sw, 1), mh / max(_sh, 1))))

    win = tk.Toplevel(state.widgets.root)
    win.overrideredirect(True)
    win.attributes('-topmost', True)
    win.attributes('-alpha', 0.0)
    win.configure(bg=border_c)

    border_px = max(1, int(scl(3) * mpv_frac))
    outer = tk.Frame(win, bg=border_c, padx=border_px, pady=border_px)
    outer.pack()
    inner = tk.Frame(outer, bg=bg, padx=int(scl(40) * mpv_frac), pady=int(scl(20) * mpv_frac))
    inner.pack()
    tk.Label(inner, text=rank_str,
             font=('Segoe UI', max(9, int(scl(24, 'UI') * mpv_frac)), 'bold'),
             fg=fg, bg=bg).pack()
    tk.Label(inner, text=name,
             font=('Segoe UI', max(14, int(scl(48, 'UI') * mpv_frac)), 'bold'),
             fg=fg, bg=bg).pack()

    win.update_idletasks()
    w  = win.winfo_width()
    h  = win.winfo_height()

    bonus_defaults = bonus.BONUS_SETTINGS_DEFAULT
    _pp = state.playback.bonus_settings.get('buzzer', bonus_defaults['buzzer']).get(
        'player_buzz_popup_properties', bonus_defaults['buzzer']['player_buzz_popup_properties'])
    margin  = int(scl(int(_pp.get('margin',     40))) * mpv_frac)
    gap     = int(scl(int(_pp.get('gap',        10))) * mpv_frac)
    rise_px = int(scl(int(_pp.get('rise_px',    50))) * mpv_frac)
    PUSH_MS    = int(_pp.get('push_ms',    220))
    PUSH_STEPS = int(_pp.get('push_steps', 18))

    cx      = mx + (mw - w) // 2
    base_y  = my + mh - h - margin

    entry = {'win': win, 'base_y': base_y, 'cx': cx, 'h': h}
    _buzz_toast_wins.append(entry)

    # --- push existing toasts up smoothly ---
    push_amount = h + gap
    PUSH_MS = 220
    PUSH_STEPS = 18
    push_step_ms = max(1, PUSH_MS // PUSH_STEPS)

    # snapshot existing toasts (all except the new one)
    existing = [e for e in _buzz_toast_wins if e is not entry]
    for e in existing:
        e['base_y'] -= push_amount   # update their target base_y

    def _push_others(step=0):
        if step > PUSH_STEPS:
            return
        t = step / PUSH_STEPS
        ease = t * (2 - t)  # ease-out
        for e in existing:
            if not e['win'].winfo_exists():
                continue
            cur_y = int((e['base_y'] + push_amount) - push_amount * ease)
            e['win'].geometry(f"+{e['cx']}+{cur_y}")
        if step < PUSH_STEPS:
            state.widgets.root.after(push_step_ms, lambda: _push_others(step + 1))
        else:
            for e in existing:
                if e['win'].winfo_exists():
                    e['win'].geometry(f"+{e['cx']}+{e['base_y']}")

    state.widgets.root.after(10, _push_others)

    # --- new toast: rise + fade in ---
    _pp = state.playback.bonus_settings.get('buzzer', bonus_defaults['buzzer']).get(
        'player_buzz_popup_properties', bonus_defaults['buzzer']['player_buzz_popup_properties'])
    FADE_IN_MS  = int(_pp.get('fade_in_ms',  220))
    HOLD_MS     = int(_pp.get('hold_ms',     2400))
    FADE_OUT_MS = int(_pp.get('fade_out_ms', 350))
    STEPS       = int(_pp.get('steps',       18))
    _max_alpha  = float(_pp.get('max_alpha', BUZZ_TOAST_MAX_ALPHA))
    step_ms     = max(1, FADE_IN_MS // STEPS)
    out_step_ms = max(1, FADE_OUT_MS // STEPS)

    win.geometry(f'+{cx}+{base_y + rise_px}')

    def _fade_in(step=0):
        if not win.winfo_exists():
            return
        try:
            t = step / STEPS
            win.attributes('-alpha', t * _max_alpha)
            win.geometry(f'+{cx}+{int(base_y + rise_px * (1.0 - t))}')
            if step < STEPS:
                state.widgets.root.after(step_ms, lambda: _fade_in(step + 1))
            else:
                win.attributes('-alpha', _max_alpha)
                win.geometry(f'+{cx}+{base_y}')
                state.widgets.root.after(HOLD_MS, _fade_out)
        except Exception:
            pass

    def _fade_out(step=0):
        if not win.winfo_exists():
            return
        try:
            win.attributes('-alpha', _max_alpha * (1.0 - step / STEPS))
            if step < STEPS:
                state.widgets.root.after(out_step_ms, lambda: _fade_out(step + 1))
            else:
                try:
                    _buzz_toast_wins.remove(entry)
                except ValueError:
                    pass
                win.destroy()
        except Exception:
            pass

    state.widgets.root.after(10, _fade_in)


def _play_buzz_sound(rank, name):
    """Play a buzzer sound on the host machine when a player buzzes in."""
    if name != 'Test':
        scoreboard_control.send_command(f"[BUZZ_ORDER]{rank}:{name}")
    bonus_defaults = bonus.BONUS_SETTINGS_DEFAULT
    _buz = state.playback.bonus_settings.get("buzzer", bonus_defaults["buzzer"])
    if name != 'Test':
        if _buz.get("player_buzz_popup", True):
            # Measure how long the toast sat in Tk's queue waiting for the main
            # loop — the host-side portion of perceived buzzer lag (network
            # transit excluded). Logged so laggy sessions are diagnosable.
            _received = time.monotonic()

            def _toast_with_lag_check():
                _waited = time.monotonic() - _received
                if _waited >= 0.15:
                    get_logger().warning(
                        "buzz toast for '%s' waited %.2fs for the main loop", name, _waited)
                _show_buzz_toast(rank, name)

            state.widgets.root.after(0, _toast_with_lag_check)
    def _make_wav_segments(segments):
        import wave, struct, math, io, random
        rate = 44100
        all_frames = bytearray()
        for seg in segments:
            f1   = float(seg.get('f1', 220))
            f2   = float(seg.get('f2', f1))
            f_end = seg.get('f_end', None)
            wv   = seg.get('wave', _SQ)
            duty = float(seg.get('duty', 0.5))
            dur  = int(seg.get('dur', 300))
            vol  = float(seg.get('vol', 0.7))
            gap  = int(seg.get('gap', 0))
            atk  = int(seg.get('atk', 5))
            rel  = float(seg.get('rel', 0.75))
            n         = int(rate * dur / 1000)
            attack_n  = max(1, int(rate * atk / 1000))
            rel_start = int(n * rel)
            phase1 = 0.0
            phase2 = 0.0
            for i in range(n):
                t     = i / max(1, n - 1)
                cur_f1 = f1 + (f_end - f1) * t if f_end is not None else f1
                cur_f2 = f2
                p1 = phase1 % 1.0
                p2 = phase2 % 1.0
                if wv == _SQ:
                    s1 = 1.0 if p1 < duty else -1.0
                    s2 = 1.0 if p2 < duty else -1.0
                elif wv == _TRI:
                    s1 = (4*p1 - 1) if p1 < 0.5 else (3 - 4*p1)
                    s2 = (4*p2 - 1) if p2 < 0.5 else (3 - 4*p2)
                elif wv == _SAW:
                    s1 = p1 * 2.0 - 1.0
                    s2 = p2 * 2.0 - 1.0
                elif wv == _SIN:
                    s1 = math.sin(phase1 * 2 * math.pi)
                    s2 = math.sin(phase2 * 2 * math.pi)
                elif wv == _NOI:
                    s1 = s2 = random.uniform(-1.0, 1.0)
                else:
                    s1 = s2 = 0.0
                sample_f = (s1 + s2) * 0.5
                if i < attack_n:
                    env = i / attack_n
                elif i >= rel_start:
                    env = 1.0 - (i - rel_start) / max(1, n - rel_start)
                else:
                    env = 1.0
                val = int(sample_f * env * vol * 32767)
                all_frames += struct.pack('<h', max(-32768, min(32767, val)))
                phase1 += cur_f1 / rate
                phase2 += cur_f2 / rate
            if gap > 0:
                all_frames += b'\x00\x00' * int(rate * gap / 1000)
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(bytes(all_frames))
        return buf.getvalue()

    def _beep():
        try:
            import winsound
            _buz_cfg = state.playback.bonus_settings.get("buzzer", bonus_defaults["buzzer"])
            if not _buz_cfg.get("sound", True):
                return
            p = BUZZ_PRESETS[_buzz_preset_index]
            if p[0] == 'No Sound':
                return
            segs = p[1] if rank == 1 else p[2]
            if state.controls.volume_level <= 0:
                vol_scale = 0.0
            else:
                BGM_DB_RANGE = 45
                vol_scale = 10 ** ((state.controls.volume_level / 200 - 1) * BGM_DB_RANGE / 20)
            sound_volume = float(_buz_cfg.get("sound_volume", 1.0))
            scaled = [{**s, 'vol': s.get('vol', 0.7) * vol_scale * sound_volume} for s in segs]
            wav = _make_wav_segments(scaled)
            winsound.PlaySound(wav, winsound.SND_MEMORY)
        except Exception:
            pass
    threading.Thread(target=_beep, daemon=True).start()
