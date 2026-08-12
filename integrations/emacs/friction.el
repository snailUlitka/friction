;;; friction.el --- Capture workflow friction -*- lexical-binding: t; -*-

;; Copyright (C) 2026
;; Author: Mikhail Polevoda
;; Version: 0.1.0
;; Package-Requires: ((emacs "30.2"))
;; Keywords: convenience, tools

;;; Commentary:

;; A self-contained local minor mode for asynchronously capturing workflow
;; friction through the versioned Friction JSON CLI.  This library never opens
;; SQLite and never writes the historical JSONL format.

;;; Code:

(require 'json)
(require 'subr-x)

(defgroup friction nil
  "Capture local workflow friction from Emacs."
  :group 'tools
  :prefix "friction-")

(defcustom friction-executable "friction"
  "Friction executable name or absolute path."
  :type 'string
  :group 'friction)

(defcustom friction-database-file nil
  "Optional database passed to the Friction root --db option.
Nil keeps normal CLI database resolution."
  :type '(choice (const :tag "Normal Friction resolution" nil) file)
  :group 'friction)

(defcustom friction-capture-prompt "Friction note: "
  "Minibuffer prompt used by `friction-capture'."
  :type 'string
  :group 'friction)

(defcustom friction-default-tags nil
  "Tags attached to every item captured from Emacs."
  :type '(repeat string)
  :group 'friction)

(defvar friction-mode-map (make-sparse-keymap)
  "Keymap active in `friction-mode'.")

(defun friction--set-capture-key (symbol value)
  "Set SYMBOL to VALUE and update `friction-mode-map'."
  (let ((old-value (and (boundp symbol) (symbol-value symbol))))
    (when old-value
      (define-key friction-mode-map (kbd old-value) nil)))
  (set-default symbol value)
  (when value
    (define-key friction-mode-map (kbd value) #'friction-capture)))

(defcustom friction-capture-key "C-c C-f"
  "Key used for `friction-capture' while `friction-mode' is active.
Set this to nil to leave the mode without a binding."
  :type '(choice (const :tag "No binding" nil) string)
  :set #'friction--set-capture-key
  :group 'friction)

(defvar friction--process-counter 0
  "Counter used to give simultaneous capture processes unique names.")

(defun friction--snapshot ()
  "Snapshot capture context in the current buffer at point."
  (let ((path (and buffer-file-name (expand-file-name buffer-file-name)))
        (cwd (and default-directory
                  (directory-file-name (expand-file-name default-directory)))))
    (list :path path
          :line (line-number-at-pos)
          :column (1+ (current-column))
          :cwd cwd
          :filetype (symbol-name major-mode)
          :buffer-name (buffer-name))))

(defun friction--payload (note snapshot)
  "Build a JSON v1 capture payload for NOTE and SNAPSHOT."
  (let ((data `((note . ,note)
                (source . "emacs")
                (line . ,(plist-get snapshot :line))
                (column . ,(plist-get snapshot :column))
                (filetype . ,(plist-get snapshot :filetype))
                (tags . ,(vconcat friction-default-tags))
                (metadata . (("emacs.buffer_name"
                              . ,(plist-get snapshot :buffer-name)))))))
    (when (plist-get snapshot :path)
      (setq data (append data `((path . ,(plist-get snapshot :path))))))
    (when (plist-get snapshot :cwd)
      (setq data (append data `((cwd . ,(plist-get snapshot :cwd))))))
    `((schema_version . 1) (data . ,data))))

(defun friction--command (executable)
  "Build the capture command beginning with EXECUTABLE."
  (append (list executable)
          (when friction-database-file
            (list "--db" (expand-file-name friction-database-file)))
          (list "add" "--input-json" "-" "--output" "json")))

(defun friction--buffer-string (buffer)
  "Return BUFFER contents without text properties."
  (if (buffer-live-p buffer)
      (with-current-buffer buffer
        (buffer-substring-no-properties (point-min) (point-max)))
    ""))

(defun friction--response-value (key object)
  "Return KEY from parsed JSON alist OBJECT."
  (and (listp object) (alist-get key object)))

(defun friction--parse-response (text)
  "Parse response TEXT as a JSON alist, returning nil on malformed input."
  (condition-case nil
      (json-parse-string text
                         :object-type 'alist
                         :array-type 'list
                         :null-object nil
                         :false-object nil)
    (error nil)))

(defun friction--warning-message (response stderr-text exit-status)
  "Build one warning for RESPONSE, STDERR-TEXT, and EXIT-STATUS."
  (let* ((error-value (friction--response-value 'error response))
         (code (friction--response-value 'code error-value))
         (message-value (friction--response-value 'message error-value)))
    (cond
     ((and code message-value)
      (format "%s: %s" code message-value))
     ((and response
           (not (equal (friction--response-value 'schema_version response) 1)))
      "schema_mismatch: Friction returned an unsupported schema version")
     (t
      (let ((stderr-snippet
             (substring stderr-text 0 (min 2000 (length stderr-text)))))
        (format "capture_failed: Friction exited with status %s%s"
                exit-status
                (if (string-empty-p stderr-snippet)
                    ""
                  (format ": %s" stderr-snippet))))))))

(defun friction--process-sentinel (process _event)
  "Handle completion of capture PROCESS and clean its private buffers."
  (when (memq (process-status process) '(exit signal))
    (let* ((stdout-buffer (process-get process 'friction-stdout-buffer))
           (stderr-buffer (process-get process 'friction-stderr-buffer))
           (stdout-text (friction--buffer-string stdout-buffer))
           (stderr-text (friction--buffer-string stderr-buffer))
           (response (friction--parse-response stdout-text))
           (status (process-exit-status process)))
      (unwind-protect
          (let* ((schema (friction--response-value 'schema_version response))
                 (error-value (friction--response-value 'error response))
                 (data (friction--response-value 'data response))
                 (identifier (friction--response-value 'id data)))
            (if (and (= status 0)
                     (equal schema 1)
                     (null error-value)
                     (stringp identifier))
                (message "Friction captured: %s"
                         (substring identifier 0 (min 8 (length identifier))))
              (display-warning
               'friction
               (friction--warning-message response stderr-text status)
               :warning)))
        (when (buffer-live-p stdout-buffer)
          (kill-buffer stdout-buffer))
        (when (buffer-live-p stderr-buffer)
          (kill-buffer stderr-buffer))))))

(defun friction--start-process (executable payload)
  "Start EXECUTABLE asynchronously and send JSON PAYLOAD through stdin."
  (setq friction--process-counter (1+ friction--process-counter))
  (let* ((suffix (format "%d-%d" (emacs-pid) friction--process-counter))
         (stdout-buffer (generate-new-buffer (format " *friction-out-%s*" suffix)))
         (stderr-buffer (generate-new-buffer (format " *friction-err-%s*" suffix)))
         (process
          (condition-case error-value
              (make-process
               :name (format "friction-capture-%s" suffix)
               :buffer stdout-buffer
               :stderr stderr-buffer
               :command (friction--command executable)
               :connection-type 'pipe
               :coding 'utf-8-unix
               :noquery t
               :sentinel #'friction--process-sentinel)
            (error
             (kill-buffer stdout-buffer)
             (kill-buffer stderr-buffer)
             (signal (car error-value) (cdr error-value))))))
    (process-put process 'friction-stdout-buffer stdout-buffer)
    (process-put process 'friction-stderr-buffer stderr-buffer)
    (condition-case error-value
        (progn
          (process-send-string process
                               (concat (json-encode payload) "\n"))
          (process-send-eof process))
      (error
       (delete-process process)
       (kill-buffer stdout-buffer)
       (kill-buffer stderr-buffer)
       (signal (car error-value) (cdr error-value))))
    process))

;;;###autoload
(defun friction-capture (&optional note)
  "Capture NOTE and the current buffer context asynchronously.
Interactively, prompt using `friction-capture-prompt'.  A Lisp caller may pass
a multiline NOTE directly."
  (interactive)
  (let* ((snapshot (friction--snapshot))
         (executable (executable-find friction-executable)))
    (unless executable
      (user-error "Friction executable is not available: %s"
                  friction-executable))
    (let ((capture-note (or note (read-string friction-capture-prompt))))
      (when (string-empty-p (string-trim capture-note))
        (user-error "Friction note must not be empty"))
      (friction--start-process executable
                               (friction--payload capture-note snapshot)))))

;;;###autoload
(define-minor-mode friction-mode
  "Capture workflow friction from the current buffer."
  :lighter " Friction"
  :keymap friction-mode-map)

(defun friction--enable-in-user-buffer ()
  "Enable `friction-mode' in ordinary non-minibuffer user buffers."
  (unless (or (minibufferp) (string-prefix-p " " (buffer-name)))
    (friction-mode 1)))

;;;###autoload
(define-globalized-minor-mode global-friction-mode
  friction-mode friction--enable-in-user-buffer
  :group 'friction)

(provide 'friction)

;;; friction.el ends here
