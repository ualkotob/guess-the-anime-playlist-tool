"""file_metadata dict type with mutation invalidation hook."""


class FileMetadataDict(dict):
    """Dict subclass that calls an optional callback after mutations."""

    def __init__(self, *args, on_change=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._on_change = on_change

    def _changed(self):
        if self._on_change:
            self._on_change()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._changed()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._changed()

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self._changed()

    def pop(self, *args):
        result = super().pop(*args)
        self._changed()
        return result

    def clear(self):
        super().clear()
        self._changed()
