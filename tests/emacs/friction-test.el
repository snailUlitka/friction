;;; friction-test.el --- ERT tests for friction.el -*- lexical-binding: t; -*-

(require 'ert)
(require 'cl-lib)
(require 'json)
(require 'friction)

(defconst friction-test--root
  (expand-file-name "../.." (file-name-directory load-file-name)))

(defconst friction-test--fake-executable
  (expand-file-name "tests/emacs/fixtures/fake-friction" friction-test--root))

(defun friction-test--wait (process)
  (while (process-live-p process)
    (accept-process-output process 0.1))
  (accept-process-output process 0.05))

(ert-deftest friction-test-command-with-and-without-database ()
  (let ((friction-database-file nil))
    (should (equal (friction--command "/tmp/friction")
                   '("/tmp/friction" "add" "--input-json" "-"
                     "--output" "json"))))
  (let ((friction-database-file "/tmp/local.db"))
    (should (equal (friction--command "/tmp/friction")
                   '("/tmp/friction" "--db" "/tmp/local.db" "add"
                     "--input-json" "-" "--output" "json")))))

(ert-deftest friction-test-resolves-path-and-homebrew-fallback ()
  (let ((friction-executable "custom-friction"))
    (cl-letf (((symbol-function 'executable-find)
               (lambda (name)
                 (and (equal name "custom-friction") "/tmp/custom-friction"))))
      (should (equal (friction--resolve-executable) "/tmp/custom-friction"))))
  (let ((friction-executable "friction"))
    (cl-letf (((symbol-function 'executable-find) (lambda (_name) nil))
              ((symbol-function 'file-executable-p)
               (lambda (path) (equal path "/opt/homebrew/bin/friction"))))
      (should (equal (friction--resolve-executable)
                     "/opt/homebrew/bin/friction"))))
  (let ((friction-executable "custom-friction"))
    (cl-letf (((symbol-function 'executable-find) (lambda (_name) nil))
              ((symbol-function 'file-executable-p) (lambda (_path) t)))
      (should-not (friction--resolve-executable)))))

(ert-deftest friction-test-payload-file-buffer-context-and-default-tags ()
  (with-temp-buffer
    (setq buffer-file-name "/tmp/example.py"
          default-directory "/tmp/"
          major-mode 'python-mode)
    (insert "αβ\nsecond")
    (goto-char (point-max))
    (let* ((friction-default-tags '("Editor" "unicode"))
           (payload (friction--payload "quotes \" slash \\ \nline"
                                       (friction--snapshot)))
           (data (alist-get 'data payload)))
      (should (equal (alist-get 'path data) "/tmp/example.py"))
      (should (= (alist-get 'line data) 2))
      (should (= (alist-get 'column data) 7))
      (should (equal (append (alist-get 'tags data) nil)
                     '("Editor" "unicode")))
      (should (equal (alist-get 'note data) "quotes \" slash \\ \nline")))))

(ert-deftest friction-test-payload-non-file-buffer-omits-path ()
  (with-temp-buffer
    (setq default-directory "/tmp/" major-mode 'text-mode)
    (let ((data (alist-get 'data
                           (friction--payload "note" (friction--snapshot)))))
      (should-not (assq 'path data))
      (should (equal (alist-get 'cwd data) "/tmp"))
      (should (equal (alist-get 'filetype data) "text-mode")))))

(ert-deftest friction-test-rejects-whitespace-and-missing-executable ()
  (let ((friction-executable friction-test--fake-executable))
    (should-error (friction-capture " \n\t ") :type 'user-error))
  (let ((friction-executable "/missing/friction-executable"))
    (should-error (friction-capture "note") :type 'user-error)))

(ert-deftest friction-test-asynchronous-stdin-success-and-cleanup ()
  (let ((friction-executable friction-test--fake-executable)
        (friction-database-file "/tmp/private.db")
        (process-environment (copy-sequence process-environment))
        messages)
    (setenv "FRICTION_EMACS_FAKE_CASE" "success")
    (cl-letf (((symbol-function 'message)
               (lambda (format-string &rest args)
                 (push (apply #'format format-string args) messages))))
      (let* ((process (friction-capture "private multiline\nnote"))
             (command (process-command process))
             (stdout (process-get process 'friction-stdout-buffer))
             (stderr (process-get process 'friction-stderr-buffer)))
        (should (processp process))
        (should-not (member "private multiline\nnote" command))
        (should (equal (seq-take (cdr command) 2)
                       '("--db" "/tmp/private.db")))
        (friction-test--wait process)
        (should (seq-some (lambda (value)
                            (string-match-p "Friction captured: 12345678" value))
                          messages))
        (should-not (buffer-live-p stdout))
        (should-not (buffer-live-p stderr))))))

(ert-deftest friction-test-domain-malformed-and-nonzero-warnings ()
  (dolist (case '("domain" "malformed" "nonzero"))
    (let ((friction-executable friction-test--fake-executable)
          (process-environment (copy-sequence process-environment))
          warnings)
      (setenv "FRICTION_EMACS_FAKE_CASE" case)
      (cl-letf (((symbol-function 'display-warning)
                 (lambda (_type message &optional _level _buffer-name)
                   (push message warnings))))
        (friction-test--wait (friction-capture "note"))
        (should (= (length warnings) 1))
        (pcase case
          ("domain" (should (string-match-p "validation_error: bad capture"
                                             (car warnings))))
          ("malformed" (should (string-match-p "malformed output"
                                                (car warnings))))
          ("nonzero" (should (string-match-p "storage unavailable"
                                              (car warnings)))))))))

(ert-deftest friction-test-simultaneous-processes-have-unique-names ()
  (let ((friction-executable friction-test--fake-executable)
        (process-environment (copy-sequence process-environment)))
    (setenv "FRICTION_EMACS_FAKE_CASE" "success")
    (let ((first (friction-capture "first"))
          (second (friction-capture "second")))
      (should-not (equal (process-name first) (process-name second)))
      (friction-test--wait first)
      (friction-test--wait second))))

(ert-deftest friction-test-real-cli-capture-is-queryable ()
  (let* ((executable (expand-file-name ".venv/bin/friction"
                                        friction-test--root))
         (database (make-temp-name
                    (expand-file-name "friction-emacs-real-"
                                      temporary-file-directory)))
         (friction-executable executable)
         (friction-database-file database)
         (friction-default-tags '("ert")))
    (skip-unless (file-executable-p executable))
    (unwind-protect
        (with-temp-buffer
          (setq default-directory friction-test--root
                major-mode 'emacs-lisp-mode)
          (insert "context")
          (friction-test--wait
           (friction-capture "ERT real capture α\nsecond line"))
          (with-temp-buffer
            (should (= (call-process executable nil t nil
                                     "--db" database "search" "ERT real capture"
                                     "--output" "json")
                       0))
            (let* ((response
                    (json-parse-string (buffer-string)
                                       :object-type 'alist
                                       :array-type 'list
                                       :null-object nil))
                   (items (alist-get 'items (alist-get 'data response)))
                   (item (car items)))
              (should (= (length items) 1))
              (should (equal (alist-get 'source item) "emacs"))
              (should (equal (append (alist-get 'tags item) nil) '("ert")))
              (should (equal (alist-get 'cwd item)
                             (directory-file-name friction-test--root))))))
      (dolist (path (list database
                          (concat database "-shm")
                          (concat database "-wal")))
        (when (file-exists-p path)
          (delete-file path))))))

(ert-deftest friction-test-modes-and-customizable-mode-local-binding ()
  (should (featurep 'friction))
  (let ((original friction-capture-key))
    (unwind-protect
        (progn
          (customize-set-variable 'friction-capture-key "C-c x f")
          (should (eq (lookup-key friction-mode-map (kbd "C-c x f"))
                      #'friction-capture))
          (should-not (lookup-key friction-mode-map (kbd original)))
          (should-not (eq (global-key-binding (kbd "C-c x f"))
                          #'friction-capture)))
      (customize-set-variable 'friction-capture-key original)))
  (with-temp-buffer
    (friction-mode 1)
    (should friction-mode)
    (friction-mode -1)
    (should-not friction-mode))
  (with-temp-buffer
    (rename-buffer " *friction-internal-test*" t)
    (friction--enable-in-user-buffer)
    (should-not friction-mode))
  (let ((user-buffer (generate-new-buffer "friction-user-test")))
    (unwind-protect
        (progn
          (global-friction-mode 1)
          (with-current-buffer user-buffer
            (normal-mode)
            (should friction-mode)))
      (global-friction-mode -1)
      (kill-buffer user-buffer))))

(provide 'friction-test)

;;; friction-test.el ends here
