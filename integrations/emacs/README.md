# Friction for Emacs

`friction.el` is a self-contained local package. It captures the current buffer
context asynchronously through the Friction JSON v1 CLI and never opens SQLite
or writes legacy JSONL.

Load it directly from this repository:

```elisp
(add-to-list 'load-path "/absolute/path/to/friction/integrations/emacs")
(require 'friction)
(global-friction-mode 1)
```

Use `(friction-mode 1)` instead when capture should be enabled only in selected
buffers. The mode-local default binding is `C-c C-f`; there is no global
binding. All public settings are available through `M-x customize-group RET
friction RET`:

- `friction-executable`;
- `friction-database-file`;
- `friction-capture-key`;
- `friction-capture-prompt`;
- `friction-default-tags`.

Changing `friction-capture-key` updates `friction-mode-map` immediately. Setting
it to nil leaves the mode enabled without a key. The command can always be
called as `M-x friction-capture` or from Lisp as `(friction-capture "note")`.
