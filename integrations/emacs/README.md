# Friction for Emacs

`friction.el` is a self-contained package. It captures the current buffer
context asynchronously through the Friction JSON v1 CLI and never opens SQLite
or writes legacy JSONL.

Install the latest tagged release directly from GitHub with the `use-package`
and `package-vc` support built into Emacs 30:

```elisp
(use-package friction
  :vc (:url "https://github.com/snailUlitka/friction.git"
       :lisp-dir "integrations/emacs")
  :config
  (global-friction-mode 1))
```

For a one-time installation without `use-package` configuration:

```elisp
(package-vc-install
 '(friction :url "https://github.com/snailUlitka/friction.git"
            :lisp-dir "integrations/emacs"))
```

Use `M-x package-upgrade-all` for updates and `M-x package-delete` to remove the
package. For development, load the checkout directly:

```elisp
(add-to-list 'load-path "/absolute/path/to/friction/integrations/emacs")
(require 'friction)
(global-friction-mode 1)
```

The CLI must be installed separately. The default executable resolution checks
`exec-path`, `/opt/homebrew/bin/friction`, and `/usr/local/bin/friction`. Set
`friction-executable` explicitly for another location.

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
