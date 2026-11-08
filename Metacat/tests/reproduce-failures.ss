;; Reproduction proofs for the fixes in patches/fixes/ (0001 to 0006), one case per process.
;;
;; THIS IS OUR OWN TEST DRIVER.  It contains no upstream Metacat source.  It runs on the patched Metacat
;; (the reconstruction with all six fixes) and on nothing else: the project never runs a tree without a
;; fix.  A case is the input that once stopped Metacat (see "How to reproduce the problem behind each fix"
;; in KNOWN-FAILURES.md).  On the patched build the same input no longer stops, and this driver shows
;; that the run takes the FIXED PATH at the codelet where the run used to stop.
;;
;; How it shows it, without touching the source tree or the patches: after the engine is loaded, a wrapper
;; is put round one engine procedure in this process only (set! of its top-level name).  The wrapper looks
;; at the arguments, or at the result, calls the original unchanged, and writes an "EVENT" line with
;; *codelet-count* when the situation that used to be fatal arises and the original returns.  Neither the
;; wrapper nor the driver draws a random number, so the run is the same run.
;;
;;   0001  make-group:  a letter-category group whose first object has no letter category; make-group
;;         returns (it used to send get-uppercase-name to #f).
;;         change-descriptions->rule-clause-template:  the first change description has no BondFacet
;;         change but a later one has; the template is made (it used to leave (3rd #f) for
;;         get-change-phrase).
;;   0002  build-bridge:  a horizontal bridge between objects whose platonic lengths differ because one
;;         is #f (a group of six or more); build-bridge returns and the bridge has no Length
;;         concept-mapping (the mapping used to be made with #f).
;;   0003  the input is refused before any run starts: the control panel's command line answers
;;         "Invalid input!" and the (mcat ...) form raises "invalid syntax".
;;   0004  apply-transforms:  a transform list with a group-category transform and no bond-facet
;;         transform; apply-transforms returns (it used to take (cadr #f)).
;;         check-for-conflicts:  a letter that has a group-category transform; it returns 'done
;;         (it used to send get-bond-facet to the letter).
;;   0005  new-start-letter of a group image (message to an image; every image is wrapped, in this process
;;         only): a group image whose start letter is #f is sent a platonic relation (successor,
;;         predecessor or identity) and returns (it used to send get-related-node to #f); the start letter
;;         stays #f.  The directed trial image-trial does the same to a letter image with start letter #f
;;         (the branch at images.ss:274), which now calls its fail procedure, and to a group image.
;;   0006  possible-to-instantiate?:  a rule-clause template whose objects can be described but whose
;;         change template has an empty descriptor list; it returns #f and rule-scout fizzles (it used to
;;         return #t, and the rule's abstractness then sent get-conceptual-depth to #f).
;;
;; The driver exits 0 only when the case does what its record says: every expected EVENT at its codelet,
;; and the expected end of the run.  Anything else, including a crash of the patched build, prints
;; "REPRODUCER FAILED" and exits 1.  Exit 2: an unknown case key.
;;
;; Run from the Metacat folder, with the patched source at /metacat and this folder at /tests (the
;; Docker command in KNOWN-FAILURES.md), or: bash scripts/reproduce-metacat-fixes.sh.

;; (key kind initial modified target seed cap expected-events end-kind end-answer end-codelets)
;; kind run: a run of init-mcat and run-mcat.  expected-events: ((tag . codelet) ...), the codelet
;; (*codelet-count*) at which the tag first occurred.  end-kind: answer, cap or give-up.
(define reproducer-cases
  '(("misc1-20713988" run abc cba mrrjjj 20713988 100000
     ((make-group-without-letter-category . 2835)) answer "rrjjjm" 2835)
    ("misc1-20716342" run abc cba mrrjjj 20716342 100000
     ((make-group-without-letter-category . 1981)) answer "rrjjjm" 1981)
    ("misc3-20226148" run abc aabbcc kkjjii 20226148 100000
     ((template-with-later-bond-facet-change . 2088)) answer "kji" 2152)
    ("fix2-aaa-seed1" run aaa aaaaaa aaa 1 5000
     ((bridge-with-group-of-six-or-more . 608)) answer "aaaaaa" 1614)
    ("fix3-command-line" command-line "abc abd xy\x00e9;")
    ("fix3-mcat-form" mcat-form "xy\x00e9;")
    ("fix4-pqcd-1" run pqcd cbpo tugh 1 6000
     ((group-category-transform-without-bond-facet . 2389)) cap #f 6000)
    ("fix4-pqcd-69" run pqcd cbpo tugh 69 6000
     ((group-category-transform-without-bond-facet . 2914)) cap #f 6000)
    ("fix4-pqcd-238" run pqcd cbpo tugh 238 6000
     ((group-category-transform-without-bond-facet . 4217)) cap #f 6000)
    ("fix4-defpqr-79" run defpqr pondcb hijstu 79 6000
     ((group-category-transform-without-bond-facet . 4961)) cap #f 6000)
    ("fix4-defpqr-102" run defpqr pondcb hijstu 102 6000
     ((group-category-transform-without-bond-facet . 2521)) cap #f 6000)
    ("fix4-defpqr-161" run defpqr pondcb hijstu 161 6000
     ((group-category-transform-without-bond-facet . 3749)) cap #f 6000)
    ("fix4-abcxyz-35" run abcxyz cbazyx ijkpqr 35 6000
     ((group-category-transform-without-bond-facet . 4544)) cap #f 6000)
    ("fix4-abcxyz-74" run abcxyz cbazyx ijkpqr 74 6000
     ((group-category-transform-without-bond-facet . 5106)) answer "kjirqp" 5168)
    ("fix4-ijkm-11" run abcxyz cbazyx ijkm 11 6000
     ((group-category-transform-without-bond-facet . 4653)
      (letter-with-group-category-transform . 5901)) answer "kjim" 5901)
    ("fix4-ijkm-126" run abcxyz cbazyx ijkm 126 6000
     ((group-category-transform-without-bond-facet . 3253)
      (letter-with-group-category-transform . 3268)) answer "kjim" 3268)
    ("fix4-ijkm-184" run abcxyz cbazyx ijkm 184 6000
     ((group-category-transform-without-bond-facet . 3824)) cap #f 6000)
    ("fix4-tugx-105" run pqcd cbpo tugx 105 6000
     ((group-category-transform-without-bond-facet . 3792)) cap #f 6000)
    ("fix4-letter-trial" trial bcdep ponmb fghiw 1 1)
    ("fix5-wxyz-27" run wxyz xxyz fgzzz 27 100000
     ((group-image-without-start-letter-relation . 2851)) answer "ggh" 2851)
    ("fix5-ihg-121" run ihg ih xyaaa 121 100000
     ((group-image-without-start-letter-relation . 6615)) answer "yz" 6615)
    ("fix5-bcd-18" run bcd bc xbxmnm 18 100000
     ((group-image-without-start-letter-relation . 10351)) answer "wawlm" 57496)
    ("fix5-image-trial" image-trial)
    ("fix6-abcx-19" run abcx xwva ijkr 19 100000
     ((change-template-without-descriptor-not-describable . 8012)) answer "rqpa" 14991)))

(define reproducer-arguments (cdr (command-line)))
(define reproducer-case
  (and (= (length reproducer-arguments) 1)
       (assoc (car reproducer-arguments) reproducer-cases)))
(unless reproducer-case
  (display "Choose one of:")
  (for-each (lambda (c) (display " ") (display (car c))) reproducer-cases)
  (newline)
  (exit 2))

(define *metacat-directory* "/metacat/")
(load "/metacat/metacat-headless.ss")

;;----------------------------------------------------------------------------------
;; Bookkeeping

(define reproducer-failures '())
(define (check! ok? what)
  (printf "CHECK ~a: ~a\n" (if ok? "ok" "FAIL") what)
  (unless ok? (set! reproducer-failures (cons what reproducer-failures))))

(define (finish!)
  (cond
    ((null? reproducer-failures)
     (printf "REPRODUCER ~a: the fixed path was taken, as its record says\n" (car reproducer-case))
     (exit 0))
    (else
     (printf "REPRODUCER FAILED ~a: ~a check(s) failed\n" (car reproducer-case)
       (length reproducer-failures))
     (exit 1))))

(define (fail-now! what)
  (printf "REPRODUCER FAILED ~a: ~a\n" (car reproducer-case) what)
  (exit 1))

(define (condition->string c)
  (call-with-string-output-port (lambda (port) (display-condition c port))))

;; The first codelet count at which each tag occurred, and how many times.
(define event-first '())
(define event-total '())
(define (note-event! tag . detail)
  (let ((seen (assq tag event-total)))
    (if seen
        (set-cdr! seen (+ 1 (cdr seen)))
        (begin
          (set! event-total (cons (cons tag 1) event-total))
          (set! event-first (cons (cons tag *codelet-count*) event-first))
          (printf "EVENT ~a at codelet ~a ~s\n" tag *codelet-count* detail)))))

(set! report-error-and-halt
  (lambda (message object)
    (fail-now! (format "bad message ~s sent to an object" (cdr message)))))

;;----------------------------------------------------------------------------------
;; The wrappers.  Each calls the original unchanged.

(define (wrap-0001)
  (let ((original-make-group make-group)
        (original-template change-descriptions->rule-clause-template))
    (set! make-group
      (lambda args
        (let ((group (apply original-make-group args)))
          (when (and (eq? (list-ref args 2) plato-letter-category)
                     (not (exists? (tell group 'get-initial-letter-category))))
            (note-event! 'make-group-without-letter-category))
          group)))
    (set! change-descriptions->rule-clause-template
      (lambda (change-descriptions)
        (when (eq? (tell (1st change-descriptions) 'object-type) 'intrinsic-change-description)
          (let ((first-change (tell (1st change-descriptions) 'get-BondFacet-change))
                (any-change (ormap-meth change-descriptions 'get-BondFacet-change)))
            (when (and (not (exists? first-change)) (exists? any-change))
              (note-event! 'template-with-later-bond-facet-change))))
        (original-template change-descriptions)))))

(define (wrap-0002)
  (let ((original-build-bridge build-bridge))
    (set! build-bridge
      (lambda (orientation bridge)
        (let* ((length1 (tell (tell bridge 'get-object1) 'get-platonic-length))
               (length2 (tell (tell bridge 'get-object2) 'get-platonic-length))
               (long-group? (and (eq? orientation 'horizontal)
                                 (not (eq? length1 length2))
                                 (not (and (exists? length1) (exists? length2)))))
               (result (original-build-bridge orientation bridge)))
          (when (and long-group? (not (tell bridge 'CM-type-present? plato-length)))
            (note-event! 'bridge-with-group-of-six-or-more))
          result)))))

(define (wrap-0004)
  (let ((original-apply-transforms apply-transforms)
        (original-check-for-conflicts check-for-conflicts))
    (set! apply-transforms
      (lambda (transforms image fail)
        (let ((bare? (and (assq plato-group-category transforms)
                          (not (assq plato-bond-facet transforms)))))
          (let ((result (original-apply-transforms transforms image fail)))
            (when bare?
              (note-event! 'group-category-transform-without-bond-facet))
            result))))
    (set! check-for-conflicts
      (lambda (object-transform-pairs fail)
        (let ((has-letter? (ormap (lambda (ot)
                                (and (letter? (1st ot))
                                     (eq? (1st (2nd ot)) plato-group-category)))
                              object-transform-pairs))
              (result (original-check-for-conflicts object-transform-pairs fail)))
          (when (and has-letter? (eq? result 'done))
            (note-event! 'letter-with-group-category-transform))
          result)))))

;; 0005: every image is put behind a wrapper that looks at new-start-letter messages.  A group image
;; (it has sub-images) whose start letter is #f and that is sent a platonic relation takes the
;; group branch, images.ss:279-281; the original returns (it used to send get-related-node to #f).
;; The wrapper asks the image only for its start letter and whether it is a letter image: neither
;; draws a random number.  Images are made by make-image, also inside the engine (copy), and every
;; call goes through the top-level name, so the wrapper sees them all.
(define (wrap-0005)
  (let ((original-make-image make-image))
    (set! make-image
      (lambda args
        (let ((inner (apply original-make-image args)))
          (lambda msg
            (let ((result (apply inner msg)))
              (when (and (eq? (cadr msg) 'new-start-letter)
                         (pair? (cddr msg))
                         (platonic-relation? (caddr msg))
                         (not (eq? result 'invalid-message-indicator))
                         (not (tell (car msg) 'letter-image?))
                         (not (exists? (tell (car msg) 'get-letter))))
                (note-event! 'group-image-without-start-letter-relation))
              result)))))))

;; 0006: possible-to-instantiate? is called with the rule-clause templates of rule-scout.  The event is:
;; it returned #f, the objects of every template can be described, and an intrinsic template has a change
;; template whose descriptor list is empty.  Without that last condition it would not have been the
;; fixed path.
(define (wrap-0006)
  (let ((original-possible-to-instantiate? possible-to-instantiate?))
    (set! possible-to-instantiate?
      (lambda (rule-clause-templates)
        (let ((result (original-possible-to-instantiate? rule-clause-templates)))
          (when (and (not result)
                     (andmap (lambda (template)
                               (if (intrinsic-clause? template)
                                   (object-description-possible? (2nd template))
                                   (andmap object-description-possible? (2nd template))))
                             rule-clause-templates)
                     (ormap (lambda (template)
                              (and (intrinsic-clause? template)
                                   (ormap (lambda (change-template) (null? (3rd change-template)))
                                          (3rd template))))
                            rule-clause-templates))
            (note-event! 'change-template-without-descriptor-not-describable))
          result)))))

;;----------------------------------------------------------------------------------
;; A run

(define (check-events! expected)
  (for-each
    (lambda (e)
      (let ((seen (assq (car e) event-first)))
        (check! (and seen (= (cdr seen) (cdr e)))
          (format "event ~a first at codelet ~a (the record says ~a)" (car e)
            (if seen (cdr seen) "never") (cdr e)))))
    expected))

(define (run-with-cap cap)
  (set! *break-time* cap)
  (guard (c (#t (cons 'error c)))
    (call/cc
      (lambda (k)
        (set! suspend (lambda () (k 'suspended)))
        (set! break (lambda () (k 'capped)))
        (run-mcat)))))

(define (run-case)
  (let* ((c reproducer-case)
         (initial (list-ref c 2)) (modified (list-ref c 3)) (target (list-ref c 4))
         (seed (list-ref c 5)) (cap (list-ref c 6))
         (expected-events (list-ref c 7))
         (end-kind (list-ref c 8)) (end-answer (list-ref c 9)) (end-codelets (list-ref c 10)))
    (printf "REPRODUCER ~a: ~a ~a ~a, seed ~a, cap ~a, fresh Episodic Memory, Self-watching on\n"
      (car c) initial modified target seed cap)
    (flush-output-port (current-output-port))
    (wrap-0001) (wrap-0002) (wrap-0004) (wrap-0005) (wrap-0006)
    (tell *memory* 'clear)
    (init-mcat initial modified target #f seed)
    (let* ((outcome (run-with-cap cap))
           (answers (tell *memory* 'get-answers)))
      (when (pair? outcome)
        (fail-now! (format "the run stopped with an exception at ~a codelets: ~a"
                     *codelet-count* (condition->string (cdr outcome)))))
      (check-events! expected-events)
      (let ((kind (cond ((pair? answers) 'answer)
                        ((eq? outcome 'capped) 'cap)
                        (else 'give-up)))
            (answer (and (pair? answers) (tell (car answers) 'get-answer-print-name))))
        (printf "END ~a ~a at ~a codelets\n" kind (or answer "") *codelet-count*)
        (check! (eq? kind end-kind) (format "the run ended with ~a (the record says ~a)" kind end-kind))
        (when (eq? end-kind 'answer)
          (check! (equal? answer end-answer)
            (format "the answer is ~s (the record says ~s)" answer end-answer)))
        (check! (= *codelet-count* end-codelets)
          (format "the run ended at ~a codelets (the record says ~a)" *codelet-count* end-codelets)))
      (finish!))))

;;----------------------------------------------------------------------------------
;; 0004, the directed trial: the clause (subobjects group-category opposite) of the whole string,
;; applied to a string of five letters that has no groups.

(define (trial-case)
  (let* ((c reproducer-case)
         (initial (list-ref c 2)) (modified (list-ref c 3)) (target (list-ref c 4))
         (seed (list-ref c 5)) (cap (list-ref c 6)))
    (printf "REPRODUCER ~a: directed trial on ~a ~a ~a, seed ~a, cap ~a\n"
      (car c) initial modified target seed cap)
    (flush-output-port (current-output-port))
    (wrap-0004)
    (tell *memory* 'clear)
    (init-mcat initial modified target #f seed)
    (let ((outcome (run-with-cap cap)))
      (when (pair? outcome)
        (fail-now! (format "the first codelet stopped: ~a" (condition->string (cdr outcome)))))
      (check! (= *codelet-count* 1) (format "the trial starts after ~a codelet (the record says 1)" *codelet-count*))
      (let* ((clause (list 'intrinsic
                       (list (list 'string plato-string-position-category plato-whole))
                       (list (list 'subobjects plato-group-category plato-opposite))))
             (rule (make-rule 'top (list clause))))
        (printf "rule: ~a\n" (tell rule 'get-english-transcription))
        (printf "groups in the initial string: ~s\n"
          (map (lambda (o) (tell o 'get-pname)) (tell *initial-string* 'get-groups)))
        (check! (null? (tell *initial-string* 'get-groups)) "the initial string has no groups")
        (check! (= 5 (length (tell *initial-string* 'get-constituent-objects)))
          "the initial string has five constituent objects (letters)")
        (let ((result (guard (e (#t (cons 'error e)))
                        (list 'returned (apply-rule rule *initial-string* ignore-snag)))))
          (cond
            ((eq? (car result) 'error)
             (fail-now! (format "apply-rule stopped: ~a" (condition->string (cdr result)))))
            (else
             (printf "apply-rule returned a list of ~a (object, transforms) entries\n" (length (cadr result))))))
        (check-events! '((letter-with-group-category-transform . 1)))
        (finish!)))))

;;----------------------------------------------------------------------------------
;; 0005, the directed trial for images.ss:274 and :281: images made by hand, no run.
;;   1. a letter image whose start letter is #f, sent successor: it calls its fail procedure (:274);
;;   2. a group image of two letter images (a and b) whose start letter is #f, sent successor: it
;;      returns done, the sub-images become b and c, and its start letter is still #f (:281);
;;   3. controls: a letter image with start letter a, sent successor, becomes b; a group image with
;;      start letter a, sent successor, gets start letter b.

(define (image-trial-case)
  (printf "REPRODUCER ~a: directed trial of new-start-letter on images with and without a start letter\n"
    (car reproducer-case))
  (flush-output-port (current-output-port))
  (let* ((failed (lambda (image arg)
                   (call/cc (lambda (k)
                     (tell image 'new-start-letter arg (lambda () (k 'failed)))))))
         (letter-image (lambda (letter) (make-image letter #f #f #f #f '())))
         (group-image (lambda (start sub-letters)
                        (make-image start plato-letter-category plato-successor plato-identity plato-right
                          (map letter-image sub-letters))))
         (names (lambda (image) (map (lambda (l) (if (exists? l) (tell l 'get-lowercase-name) '#f))
                                     (tell-all (tell image 'get-sub-images) 'get-letter)))))
    (let* ((i1 (letter-image #f))
           (r1 (failed i1 plato-successor)))
      (check! (eq? r1 'failed) (format "a letter image with no start letter, sent successor, calls fail (~s)" r1))
      (check! (not (exists? (tell i1 'get-letter))) "its start letter is still none"))
    (let* ((i2 (group-image #f (list plato-a plato-b)))
           (r2 (failed i2 plato-successor)))
      (check! (eq? r2 'done) (format "a group image with no start letter, sent successor, returns (~s)" r2))
      (check! (not (exists? (tell i2 'get-letter))) "its start letter is still none")
      (check! (equal? (names i2) '("b" "c")) (format "its sub-images became ~s (b and c expected)" (names i2))))
    (let* ((i3 (letter-image plato-a)) (r3 (failed i3 plato-successor)))
      (check! (and (eq? r3 'done) (eq? (tell i3 'get-letter) plato-b)) "control: a letter image a, sent successor, becomes b"))
    (let* ((i4 (group-image plato-a (list plato-a plato-b))) (r4 (failed i4 plato-successor)))
      (check! (and (eq? r4 'done) (eq? (tell i4 'get-letter) plato-b) (equal? (names i4) '("b" "c")))
        "control: a group image starting at a, sent successor, starts at b"))
    (finish!)))

;;----------------------------------------------------------------------------------
;; 0003, input refused before any run starts.
;; gui.ss is the GUI and cannot be loaded whole; its parser definitions are read by name from the file.

(define (take-definitions! path names)
  (let ((port (open-input-file path)))
    (let loop ()
      (let ((form (read port)))
        (cond
          ((eof-object? form) (close-port port))
          (else
            (when (and (pair? form) (eq? (car form) 'define) (pair? (cdr form)) (memq (cadr form) names))
              (eval form))
            (loop)))))))

(define panel-log '())
(define panel-command-line "")
(define (install-panel-stub!)
  (set! *control-panel*
  (lambda (self message . rest)
    (case message
      ((get-command-line-string) panel-command-line)
      ((display-error) (set! panel-log (cons (list 'display-error (car rest)) panel-log)) 'ok)
      ((init-new-problem) (set! panel-log (cons (list 'init-new-problem (car rest)) panel-log)) 'ok)
      ((run-new-problem) (set! panel-log (cons (list 'run-new-problem (car rest)) panel-log)) 'ok)
      (else (fail-now! (format "unexpected message ~s to the control panel stub" message)))))))

(define (command-line-case)
  (let ((text (list-ref reproducer-case 2)))
    (printf "REPRODUCER ~a: the control panel's command line, Go button, text of ~a characters ending in U+00E9\n"
      (car reproducer-case) (string-length text))
    (install-panel-stub!)
    (take-definitions! "/metacat/gui.ss" '(tokenize-string char-noise? go-button-action))
    (check! (and (procedure? tokenize-string) (procedure? go-button-action))
      "tokenize-string and go-button-action were read from gui.ss")
    ;; The control: an ordinary line starts a problem.
    (set! panel-command-line "abc abd xyz")
    (set! panel-log '())
    (go-button-action #f)
    (check! (equal? panel-log '((init-new-problem (abc abd xyz))))
      (format "control: the line \"abc abd xyz\" starts a problem (~s)" panel-log))
    ;; The case.
    (set! panel-command-line text)
    (set! panel-log '())
    (let ((tokens (tokenize-string text)))
      (printf "tokenize-string gives ~s; valid-token-list? gives ~s\n" tokens (valid-token-list? tokens)))
    (go-button-action #f)
    (printf "the control panel received ~s\n" (reverse panel-log))
    (check! (equal? panel-log '((display-error "Invalid input!")))
      "the command line is refused with \"Invalid input!\" and no problem is started")
    (finish!)))

(define (mcat-form-case)
  (let ((symbol-text (list-ref reproducer-case 2)))
    (printf "REPRODUCER ~a: the form (mcat abc abd <U+00E9 ending>)\n" (car reproducer-case))
    (install-panel-stub!)
    (set! panel-log '())
    (let* ((form `(mcat abc abd ,(string->symbol symbol-text)))
           (control (guard (e (#t (cons 'error (condition->string e))))
                      (eval '(mcat abc abd xyz)) 'accepted))
           (result (guard (e (#t (cons 'error (condition->string e))))
                     (eval form) 'accepted)))
      (check! (eq? control 'accepted) (format "control: (mcat abc abd xyz) is accepted (~s)" control))
      (printf "the form ~s gives ~s\n" form result)
      (check! (and (pair? result)
                   (string=? (cdr result)
                     (string-append "Exception in mcat: invalid syntax (mcat abc abd " symbol-text ")")))
        "the form is refused: \"Exception in mcat: invalid syntax (mcat abc abd xy<U+00E9>)\"")
      (check! (equal? panel-log '((run-new-problem (abc abd xyz))))
        (format "only the control reached the control panel (~s)" panel-log)))
    (finish!)))

(case (cadr reproducer-case)
  ((run) (run-case))
  ((trial) (trial-case))
  ((image-trial) (image-trial-case))
  ((command-line) (command-line-case))
  ((mcat-form) (mcat-form-case)))
