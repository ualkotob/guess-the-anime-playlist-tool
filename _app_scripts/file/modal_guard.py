"""Modal dialog guard used by global keyboard handlers."""

modal_dialog_open = False


def _wrap_modal_dialog(fn):
    def _wrapped(*args, **kwargs):
        global modal_dialog_open
        modal_dialog_open = True
        try:
            return fn(*args, **kwargs)
        finally:
            modal_dialog_open = False
    return _wrapped


def install_modal_dialog_guard(messagebox_module, simpledialog_module):
    """Patch Tk modal dialogs so shortcuts can ignore them while open."""
    messagebox_module.showinfo = _wrap_modal_dialog(messagebox_module.showinfo)
    messagebox_module.showwarning = _wrap_modal_dialog(messagebox_module.showwarning)
    messagebox_module.showerror = _wrap_modal_dialog(messagebox_module.showerror)
    messagebox_module.askyesno = _wrap_modal_dialog(messagebox_module.askyesno)
    messagebox_module.askokcancel = _wrap_modal_dialog(messagebox_module.askokcancel)
    messagebox_module.askretrycancel = _wrap_modal_dialog(messagebox_module.askretrycancel)
    messagebox_module.askquestion = _wrap_modal_dialog(messagebox_module.askquestion)
    messagebox_module.askyesnocancel = _wrap_modal_dialog(messagebox_module.askyesnocancel)
    simpledialog_module.askstring = _wrap_modal_dialog(simpledialog_module.askstring)
    simpledialog_module.askinteger = _wrap_modal_dialog(simpledialog_module.askinteger)
    simpledialog_module.askfloat = _wrap_modal_dialog(simpledialog_module.askfloat)


def is_modal_dialog_open():
    return modal_dialog_open
