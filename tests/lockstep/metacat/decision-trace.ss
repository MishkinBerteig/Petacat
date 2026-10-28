;;=============================================================================
;; Decision-trace recorder for Metacat (lockstep harness, Metacat side).
;;
;; Load AFTER metacat-headless.ss, from a copy of the Metacat source that has
;; recorder.patch applied (the patch defines the trace-hook-* procedures as
;; no-ops and calls them at the hook points; this file installs the real ones).
;;
;; It only writes records.  It draws no random numbers of its own and changes
;; nothing Metacat computes.  See tests/lockstep/metacat/README.md and
;; meta-peta-trace-idea.md sections 3, 4, 5 and 8.
;;
;; Driver sketch (record.py writes this):
;;   (define *metacat-directory* "/metacat/")
;;   (load "/metacat/metacat-headless.ss")
;;   (load "/recorder/decision-trace.ss")
;;   (trace-open "/out/abc-abd-xyz/1.metacat.jsonl" '(abc abd xyz) 1 100000 "rev")
;;   (tell *memory* 'clear)
;;   (init-mcat 'abc 'abd 'xyz #f 1)
;;   (set! *break-time* 100000)
;;   (trace-run)
;;=============================================================================

;; ---------------------------------------------------------------------------
;; State

(define *tr-audit?* (top-level-bound? '*audit-enabled*))
(define *tr-depth* (if (top-level-bound? '*tr-depth*) (top-level-value '*tr-depth*) 0))
(define *tr-port* #f)
(define *tr-enabled* #f)
(define *tr-snapshots?* #t)
(define *tr-ctx* "init")
(define *tr-who* "init-mcat")
(define *tr-c* 1)
(define *tr-u* #f)
(define *tr-u-counter* 0)
(define *tr-n* 0)
(define *tr-about* #f)
(define *tr-scope* #f)
(define *tr-saved* '())
(define *tr-name-cache* (make-weak-eq-hashtable))

;; ---------------------------------------------------------------------------
;; Output primitives.  Always write to an explicit port: Metacat rebinds
;; `newline` to the port captured when syntactic-sugar.ss was loaded.

(define tr-put (lambda (s) (put-string *tr-port* s)))
(define tr-char (lambda (ch) (put-char *tr-port* ch)))
(define tr-nl (lambda () (put-char *tr-port* #\newline)))

(define tr-hex-digit
  (lambda (d) (string-ref "0123456789abcdef" d)))

(define tr-q
  (lambda (s)
    (tr-char #\")
    (string-for-each
      (lambda (ch)
        (cond
          ((char=? ch #\") (tr-put "\\\""))
          ((char=? ch #\\) (tr-put "\\\\"))
          ((char<? ch #\space)
           (let ((k (char->integer ch)))
             (tr-put "\\u00")
             (tr-char (tr-hex-digit (quotient k 16)))
             (tr-char (tr-hex-digit (remainder k 16)))))
          (else (tr-char ch))))
      s)
    (tr-char #\")))

(define tr-num-string
  (lambda (x)
    (cond
      ((and (exact? x) (integer? x)) (number->string x))
      ((exact? x) (tr-num-string (exact->inexact x)))
      ((or (nan? x) (infinite? x)) "null")
      (else (number->string x)))))

(define tr-num (lambda (x) (tr-put (tr-num-string x))))
(define tr-float (lambda (x) (tr-num (exact->inexact x))))
(define tr-bool (lambda (b) (tr-put (if b "true" "false"))))

;; Write the elements of l with writer, comma separated, inside [ ].
(define tr-array
  (lambda (l writer)
    (tr-char #\[)
    (let loop ((rest l) (first? #t))
      (if (not (null? rest))
          (begin
            (if (not first?) (tr-char #\,))
            (writer (car rest))
            (loop (cdr rest) #f))))
    (tr-char #\])))

(define tr-join
  (lambda (sep strs)
    (cond
      ((null? strs) "")
      ((null? (cdr strs)) (car strs))
      (else (string-append (car strs) sep (tr-join sep (cdr strs)))))))

;; ---------------------------------------------------------------------------
;; Canonical names (spec section 4, Metacat column; DECISIONS.md).

(define tr-number-name
  (lambda (x)
    (cond
      ((and (exact? x) (integer? x)) (number->string x))
      ((exact? x) (tr-number-name (exact->inexact x)))
      ((and (real? x) (not (nan? x)) (not (infinite? x)) (= x (floor x)))
       (number->string (inexact->exact x)))
      (else (number->string x)))))

(define tr-role
  (lambda (string)
    (case (tell string 'get-string-type)
      ((initial) "i")
      ((modified) "m")
      ((target) "t")
      ((answer) "a")
      (else (format "?string-type:~a" (tell string 'get-string-type))))))

(define tr-name
  (lambda (x)
    (cond
      ((symbol? x) (symbol->string x))
      ((boolean? x) (if x "true" "false"))
      ((number? x) (tr-number-name x))
      ((string? x) x)
      ((null? x) "()")
      ((and (pair? x) (list? x))
       (string-append "(" (tr-join "," (map tr-name x)) ")"))
      ((procedure? x) (tr-object-name x))
      (else (format "?scheme:~s" x)))))

(define tr-object-name
  (lambda (x)
    (let ((cached (hashtable-ref *tr-name-cache* x #f)))
      (or cached
          (let ((name (tr-compute-object-name x)))
            (hashtable-set! *tr-name-cache* x name)
            name)))))

(define tr-compute-object-name
  (lambda (x)
    (guard (c (#t (format "?error:~a" (tr-condition-text c))))
      (let ((type (tell x 'object-type)))
        (case type
          ((slipnode) (tell x 'get-lowercase-name))
          ((workspace-string) (format "string(~a)" (tr-role x)))
          ((workspace) "workspace")
          ((letter)
           (format "~a.~a" (tr-role (tell x 'get-string))
                   (tell x 'get-left-string-pos)))
          ((group)
           (format "group(~a.~a-~a,~a,~a,~a)"
                   (tr-role (tell x 'get-string))
                   (tell x 'get-left-string-pos)
                   (tell x 'get-right-string-pos)
                   (tr-name (tell x 'get-group-category))
                   (tr-direction (tell x 'get-direction))
                   (tr-name (tell x 'get-bond-facet))))
          ((bond)
           (let* ((direction (tell x 'get-direction))
                  (from (if direction (tell x 'get-from-object) (tell x 'get-left-object)))
                  (to (if direction (tell x 'get-to-object) (tell x 'get-right-object))))
             (format "bond(~a,~a,~a,~a)"
                     (tr-name from) (tr-name to)
                     (tr-name (tell x 'get-bond-category))
                     (tr-name (tell x 'get-bond-facet)))))
          ((description)
           (format "desc(~a,~a,~a)"
                   (tr-name (tell x 'get-object))
                   (tr-name (tell x 'get-description-type))
                   (tr-name (tell x 'get-descriptor))))
          ((bridge)
           (format "bridge(~a,~a,~a)"
                   (tr-name (tell x 'get-bridge-type))
                   (tr-name (tell x 'get-object1))
                   (tr-name (tell x 'get-object2))))
          ((concept-mapping)
           (format "cm(~a,~a,~a,~a)"
                   (tr-name (tell x 'get-CM-type))
                   (tr-name (tell x 'get-descriptor1))
                   (tr-direction (tell x 'get-label))
                   (tr-name (tell x 'get-descriptor2))))
          ((rule)
           (format "rule(~a,~a)"
                   (tr-name (tell x 'get-rule-type))
                   (tr-clause (tell x 'get-rule-clauses))))
          ((generic-theme bridge-theme)
           (format "theme(~a,~a,~a)"
                   (tr-name (tell x 'get-theme-type))
                   (tr-name (tell x 'get-dimension))
                   (let ((relation (tell x 'get-relation)))
                     (if relation (tr-name relation) "different"))))
          ((theme-cluster)
           (format "cluster(~a,~a)"
                   (tr-name (tell x 'get-theme-type))
                   (tr-name (tell x 'get-dimension))))
          ((codelet-type) (symbol->string (tell x 'get-codelet-type-name)))
          ((codelet)
           (let ((type-name (symbol->string (tell x 'get-codelet-type-name)))
                 (args (tell x 'get-arguments)))
             (if (null? args)
                 type-name
                 (format "~a(~a)" type-name (tr-name (car args))))))
          (else (format "?~a:object" type)))))))

;; "-" stands for "no direction" / "no label".
(define tr-direction
  (lambda (x) (if x (tr-name x) "-")))

;; Rule clauses in Metacat's clause grammar (rules.ss:34-64): lists in
;; parentheses separated by single spaces, symbols as written, nodes by name.
(define tr-clause
  (lambda (x)
    (cond
      ((and (pair? x) (list? x))
       (string-append "(" (tr-join " " (map tr-clause x)) ")"))
      (else (tr-name x)))))

(define tr-condition-text
  (lambda (c)
    (call-with-string-output-port
      (lambda (p)
        (guard (c2 (#t (put-string p "unprintable condition")))
          (display-condition c p))))))

;; ---------------------------------------------------------------------------
;; Unit context

(define tr-set-unit!
  (lambda (ctx who c u)
    (set! *tr-ctx* ctx)
    (set! *tr-who* who)
    (set! *tr-c* c)
    (set! *tr-u* u)
    (set! *tr-n* 0)
    (set! *tr-about* #f)
    (set! *tr-scope* #f)))

(define tr-about-name
  (lambda ()
    (let ((a *tr-about*))
      (cond
        ((not a) #f)
        ((vector? a)
         (let ((type-name (symbol->string (tell (vector-ref a 0) 'get-codelet-type-name)))
               (node (vector-ref a 1)))
           (if node
               (string-append type-name "(" (tr-name node) ")")
               type-name)))
        (else (tr-name a))))))

;; Start of a decision record.  Returns nothing; the caller writes the rest of
;; the fields and calls tr-end-decision.
(define tr-begin-decision
  (lambda (kind)
    (tr-put "{\"t\":\"decision\",\"c\":")
    (tr-num *tr-c*)
    (tr-put ",\"ctx\":")
    (tr-q *tr-ctx*)
    (tr-put ",\"who\":")
    (tr-q *tr-who*)
    (if *tr-u*
        (begin (tr-put ",\"u\":") (tr-num *tr-u*)))
    (tr-put ",\"n\":")
    (tr-num *tr-n*)
    (set! *tr-n* (+ *tr-n* 1))
    (let ((about (tr-about-name)))
      (if about
          (begin (tr-put ",\"about\":") (tr-q about))))
    (if *tr-scope*
        (begin (tr-put ",\"scope\":") (tr-q *tr-scope*)))
    (tr-put ",\"kind\":")
    (tr-q kind)))

(define tr-end-decision
  (lambda (site)
    (tr-put ",\"site\":")
    (tr-q (string-append site "@" *tr-who*))
    (tr-put "}")
    (tr-nl)))

;; ---------------------------------------------------------------------------
;; Decision records.  Trivial decisions (spec 7.1) are not logged.

;; Write fields shared by every choice: options, weights (unless uniform).
;; items: list of option names; weights: list of real numbers or #f (uniform).
;; extra: procedure called with the kept-index list to write extra array
;; fields (stamps) after the weights, or #f.
(define tr-log-choice
  (lambda (site names weights picked-name extras)
    ;; Keep options with non-zero weight; if all weights are zero the choice
    ;; is uniform over every option (both engines' fallback).
    (let* ((fweights (and weights (map exact->inexact weights)))
           (any-positive? (and fweights (exists (lambda (w) (not (= w 0.0))) fweights)))
           (keep
             (if (and fweights any-positive?)
                 (map (lambda (w) (not (= w 0.0))) fweights)
                 (map (lambda (n) #t) names)))
           (uniform? (or (not fweights) (not any-positive?)))
           (kept-names (tr-keep names keep))
           (kept-weights (and (not uniform?) (tr-keep fweights keep))))
      (if (>= (length kept-names) 2)
          (begin
            (tr-begin-decision "choice")
            (tr-put ",\"options\":")
            (tr-array kept-names tr-q)
            (if kept-weights
                (begin (tr-put ",\"weights\":") (tr-array kept-weights tr-num)))
            (tr-put ",\"picked\":")
            (tr-q picked-name)
            (if extras (extras keep))
            (tr-end-decision site))))))

(define tr-keep
  (lambda (l keep)
    (cond
      ((null? l) '())
      ((car keep) (cons (car l) (tr-keep (cdr l) (cdr keep))))
      (else (tr-keep (cdr l) (cdr keep))))))

(define tr-log-prob
  (lambda (site p result)
    (if (and (> p 0.0) (< p 1.0))
        (begin
          (tr-begin-decision "prob")
          (tr-put ",\"p\":")
          (tr-float p)
          (tr-put ",\"result\":")
          (tr-bool result)
          (tr-end-decision site)))))

(define tr-log-perturb
  (lambda (site n bound result)
    (if (> bound 1)
        (begin
          (tr-begin-decision "perturb")
          (tr-put ",\"value\":")
          (tr-num n)
          (tr-put ",\"bound\":")
          (tr-num bound)
          (tr-put ",\"integer\":true,\"result\":")
          (tr-num result)
          (tr-end-decision site)))))

(define tr-log-int
  (lambda (site bound result)
    (if (> bound 1)
        (begin
          (tr-begin-decision "int")
          (tr-put ",\"bound\":")
          (tr-num bound)
          (tr-put ",\"result\":")
          (tr-num result)
          (tr-end-decision site)))))

;; ---------------------------------------------------------------------------
;; Run-time wrappers for the helpers of utilities.ss (spec 5.3).  A depth
;; counter makes nested helper calls log once: the outermost call logs when it
;; completes; calls nested inside it (~ -> prob?, stochastic-pick ->
;; random-pick, ...) run the original with no logging.

(define tr-call-outermost
  (lambda (orig args log)
    (if (or (> *tr-depth* 0) (not *tr-enabled*))
        (apply orig args)
        (begin
          (set! *tr-depth* 1)
          (let ((result (apply orig args)))
            (set! *tr-depth* 0)
            (log result)
            result)))))

(define tr-orig-prob? prob?)
(define tr-orig-~ ~)
(define tr-orig-random-pick random-pick)
(define tr-orig-stochastic-pick stochastic-pick)
(define tr-orig-stochastic-select stochastic-select)

(set! prob?
  (lambda (p)
    (tr-call-outermost tr-orig-prob? (list p)
      (lambda (result) (tr-log-prob "prob?" (exact->inexact p) result)))))

(set! ~
  (lambda (n)
    (tr-call-outermost tr-orig-~ (list n)
      (lambda (result)
        (let ((bound (+ 1 (round (sqrt n)))))
          (tr-log-perturb "~" n bound result))))))

(set! random-pick
  (lambda (l)
    (tr-call-outermost tr-orig-random-pick (list l)
      (lambda (result)
        (if (and (pair? l) (pair? (cdr l)))
            (tr-log-choice "random-pick" (map tr-name l) #f (tr-name result) #f))))))

(set! stochastic-pick
  (lambda (l weights)
    (tr-call-outermost tr-orig-stochastic-pick (list l weights)
      (lambda (result)
        (if (and (pair? l) (pair? (cdr l)))
            (tr-log-choice "stochastic-pick" (map tr-name l) weights (tr-name result) #f))))))

;; Each element is (weight obj ...); the option is named after obj (the second
;; element) -- the rest of the element (e.g. flip conditions) is not part of
;; the choice -- falling back to the whole element if it has no second item.
(set! stochastic-select
  (lambda (selection-list)
    (tr-call-outermost tr-orig-stochastic-select (list selection-list)
      (lambda (result)
        (if (and (pair? selection-list) (pair? (cdr selection-list)))
            (let ((element-name
                    (lambda (e) (if (pair? (cdr e)) (tr-name (cadr e)) (tr-name e)))))
              (tr-log-choice "stochastic-select"
                (map element-name selection-list)
                (map car selection-list)
                (element-name result)
                #f)))))))

;; ---------------------------------------------------------------------------
;; Patched hook points (installed over the no-op defaults in syntactic-sugar.ss)

;; stochastic-if*: the macro drew its coin first, then computed p.
(set! trace-hook-if
  (lambda (p result)
    (if *tr-audit?*
        (if (> *audit-pending* 0)
            (set! *audit-pending* 0)
            (set! *audit-orphan-hooks* (+ *audit-orphan-hooks* 1))))
    (if (and *tr-enabled* (= *tr-depth* 0))
        (tr-log-prob "stochastic-if*" (exact->inexact p) result))))

;; Local-density walks (and any other place that wants an `about`).
(set! trace-hook-with-about
  (lambda (object thunk)
    (let ((saved *tr-about*))
      (set! *tr-about* object)
      (let ((result (thunk)))
        (set! *tr-about* saved)
        result))))

(set! trace-hook-about (lambda (object) (set! *tr-about* object)))

;; about for posting loops: the codelet type, plus the node for top-down
;; posting, written <type>(<node>).
(set! trace-hook-about-codelet
  (lambda (codelet-type node) (set! *tr-about* (vector codelet-type node))))

;; A codelet's 'run.
(set! trace-hook-codelet-begin
  (lambda (codelet)
    (tr-set-unit! "codelet"
                  (symbol->string (tell codelet 'get-codelet-type-name))
                  (+ *codelet-count* 1)
                  #f)
    ;; The scope Metacat hands each top-down scout (slipnet.ss:220-222) is its
    ;; second argument; log it for triage in a separate `scope` field.
    (let ((args (tell codelet 'get-arguments))
          (name (symbol->string (tell codelet 'get-codelet-type-name))))
      (if (and (>= (string-length name) 9)
               (string=? (substring name 0 9) "top-down-")
               (pair? args) (pair? (cdr args)))
          (set! *tr-scope* (tr-name (cadr args)))))))

(set! trace-hook-codelet-end
  (lambda (codelet)
    (tr-set-unit! "other" "run-mcat" (+ *codelet-count* 1) #f)))

;; Composite codelet choice (coderack.ss 'choose-codelet).  Begin sets the
;; unit and suppresses the two inner picks; the mark is unused.
(set! trace-hook-choose-begin
  (lambda ()
    (tr-set-unit! "choose" "coderack" (+ *codelet-count* 1) #f)
    (set! *tr-depth* (+ *tr-depth* 1))
    0))

;; `picked_weight` is the chosen codelet's own weight.  Name and stamp do not
;; always identify a codelet: a clamp restamps the codelets it moves to another
;; bin, so a moved codelet and one posted in the same cycle can share both while
;; sitting in different bins.  Replay uses the weight to tell them apart.
(define tr-weight-of
  (lambda (codelets weights chosen)
    (cond
      ((null? codelets) 0)
      ((eq? (car codelets) chosen) (car weights))
      (else (tr-weight-of (cdr codelets) (cdr weights) chosen)))))

(define tr-log-codelet-choice
  (lambda (site codelets weights chosen)
    (let ((names (map tr-name codelets))
          (stamps (map (lambda (c) (tell c 'get-time-stamp)) codelets)))
      (tr-log-choice site names weights (tr-name chosen)
        (lambda (keep)
          (tr-put ",\"stamps\":")
          (tr-array (tr-keep stamps keep) tr-num)
          (tr-put ",\"picked_stamp\":")
          (tr-num (tell chosen 'get-time-stamp))
          (tr-put ",\"picked_weight\":")
          (tr-num (exact->inexact (tr-weight-of codelets weights chosen)))
          ;; Two codelets can agree on name, stamp and bin yet differ in the
          ;; urgency an unclamp restores them to (`reset-urgency`), so the
          ;; picked codelet's two urgencies are logged as well.
          (tr-put ",\"picked_urgency\":")
          (tr-float (tell chosen 'get-relative-urgency))
          (tr-put ",\"picked_original_urgency\":")
          (tr-float (tell chosen 'get-original-urgency)))))))

(set! trace-hook-choose-end
  (lambda (codelets chosen mark)
    (set! *tr-depth* (- *tr-depth* 1))
    (if *tr-enabled*
        (tr-log-codelet-choice "choose-codelet" codelets
          (map (lambda (c) (tell (tell c 'get-coderack-bin) 'get-urgency)) codelets)
          chosen))))

;; Composite eviction (coderack.ss 'delete-codelets): one choice per eviction
;; with each codelet's removal weight.  The unit is the current one.
(set! trace-hook-evict-begin
  (lambda ()
    (set! *tr-depth* (+ *tr-depth* 1))
    0))

(set! trace-hook-evict-end
  (lambda (codelets chosen mark)
    (set! *tr-depth* (- *tr-depth* 1))
    (if *tr-enabled*
        (tr-log-codelet-choice "evict" codelets
          (map (lambda (c) (tell c 'get-removal-weight)) codelets)
          chosen))))

;; rules.ss:582, (random (length bridges)).
(set! trace-hook-int
  (lambda (bound)
    (set! *tr-depth* (+ *tr-depth* 1))
    (let ((result (random bound)))
      (set! *tr-depth* (- *tr-depth* 1))
      (if *tr-enabled* (tr-log-int "random" bound result))
      result)))

;; update-everything (run.ss): phases and snapshot.
(set! trace-hook-update-begin
  (lambda ()
    (set! *tr-saved*
      (cons (vector *tr-ctx* *tr-who* *tr-c* *tr-u* *tr-n* *tr-about* *tr-scope*)
            *tr-saved*))
    (set! *tr-u-counter* (+ *tr-u-counter* 1))
    (set! *tr-ctx* "update")
    (set! *tr-u* *tr-u-counter*)))

(set! trace-hook-phase
  (lambda (phase)
    (tr-set-unit! "update" (symbol->string phase) *tr-c* *tr-u-counter*)))

(set! trace-hook-update-end
  (lambda ()
    (if (and *tr-enabled* *tr-snapshots?*)
        (tr-snapshot *tr-u-counter* *tr-c*))
    (let ((s (car *tr-saved*)))
      (set! *tr-saved* (cdr *tr-saved*))
      (set! *tr-ctx* (vector-ref s 0))
      (set! *tr-who* (vector-ref s 1))
      (set! *tr-c* (vector-ref s 2))
      (set! *tr-u* (vector-ref s 3))
      (set! *tr-n* (vector-ref s 4))
      (set! *tr-about* (vector-ref s 5))
      (set! *tr-scope* (vector-ref s 6)))))

;; ---------------------------------------------------------------------------
;; Snapshots (spec section 8).  One record per update cycle:
;;   temperature  {value, clamped}
;;   slipnet      {node: [activation, frozen]}
;;   themes       {theme: activation}
;;   coderack     {codelets: [[name, bin, time-stamp]...], clamped: [type...]}
;;   structures   {bonds|groups|bridges|rules|descriptions: [[name, strength]...],
;;                 proposed: {bonds|groups|bridges: [name...]}}
;;   trace        {events: {type: count}, snag: bool, clamp: bool}

(define tr-write-pair-name-strength
  (lambda (s)
    (tr-char #\[)
    (tr-q (tr-name s))
    (tr-char #\,)
    (tr-float (tell s 'get-strength))
    (tr-char #\])))

(define tr-write-object-field
  (lambda (key pairs writer)
    ;; pairs: list of (name . value) written as a JSON object
    (tr-q key)
    (tr-char #\:)
    (tr-char #\{)
    (let loop ((rest pairs) (first? #t))
      (if (not (null? rest))
          (begin
            (if (not first?) (tr-char #\,))
            (tr-q (caar rest))
            (tr-char #\:)
            (writer (cdar rest))
            (loop (cdr rest) #f))))
    (tr-char #\})))

(define tr-struct-list
  (lambda (key structures)
    (tr-q key)
    (tr-char #\:)
    (tr-array structures tr-write-pair-name-strength)))

(define tr-names-list
  (lambda (key structures)
    (tr-q key)
    (tr-char #\:)
    (tr-array (map tr-name structures) tr-q)))

(define tr-built?
  (lambda (s) (= (tell s 'get-proposal-level) %built%)))

(define tr-snapshot
  (lambda (u c)
    (tr-put "{\"t\":\"snapshot\",\"u\":")
    (tr-num u)
    (tr-put ",\"c\":")
    (tr-num c)
    ;; temperature
    (tr-put ",\"temperature\":{\"value\":")
    (tr-float *temperature*)
    (tr-put ",\"clamped\":")
    (tr-bool *temperature-clamped?*)
    (tr-put "},")
    ;; slipnet
    (tr-write-object-field "slipnet"
      (map (lambda (node) (cons (tr-name node) node)) *slipnet-nodes*)
      (lambda (node)
        (tr-char #\[)
        (tr-float (tell node 'get-activation))
        (tr-char #\,)
        (tr-bool (tell node 'frozen?))
        (tr-char #\])))
    (tr-char #\,)
    ;; themes
    (tr-write-object-field "themes"
      (map (lambda (entry)
             (cons (format "theme(~a,~a,~a)"
                           (tr-name (car entry))
                           (tr-name (cadr entry))
                           (if (caddr entry) (tr-name (caddr entry)) "different"))
                   (cadddr entry)))
           (caddr (tell *themespace* 'get-complete-state)))
      tr-float)
    (tr-char #\,)
    ;; coderack
    (tr-put "\"coderack\":{\"codelets\":")
    (let ((bins (tell *coderack* 'get-all-bins)))
      (tr-array
        (let loop ((bins bins) (k 0))
          (if (null? bins)
              '()
              (append
                (map (lambda (codelet) (vector codelet k))
                     (tell (car bins) 'get-codelets))
                (loop (cdr bins) (+ k 1)))))
        (lambda (entry)
          (tr-char #\[)
          (tr-q (tr-name (vector-ref entry 0)))
          (tr-char #\,)
          (tr-num (vector-ref entry 1))
          (tr-char #\,)
          (tr-num (tell (vector-ref entry 0) 'get-time-stamp))
          (tr-char #\]))))
    (tr-put ",\"clamped\":")
    (tr-array (filter (lambda (type) (tell type 'clamped?)) *codelet-types*)
      (lambda (type) (tr-q (tr-name type))))
    (tr-put "},")
    ;; structures
    (let* ((structures (tell *workspace* 'get-structures))
           (of-type (lambda (type)
                      (filter (lambda (s) (eq? (tell s 'object-type) type)) structures)))
           (strings *non-answer-strings*)
           (proposed-bonds
             (filter (lambda (s) (not (tr-built? s)))
               (apply append (map (lambda (str) (tell str 'get-all-bonds)) strings))))
           (proposed-groups
             (filter (lambda (s) (not (tr-built? s)))
               (apply append (map (lambda (str) (tell str 'get-all-groups)) strings))))
           (proposed-bridges
             (filter (lambda (s) (not (tr-built? s)))
               (tell *workspace* 'get-all-proposed-bridges)))
           (descriptions
             (apply append
               (map (lambda (obj) (tell obj 'get-descriptions))
                    (tell *workspace* 'get-objects)))))
      (tr-put "\"structures\":{")
      (tr-struct-list "bonds" (of-type 'bond)) (tr-char #\,)
      (tr-struct-list "groups" (of-type 'group)) (tr-char #\,)
      (tr-struct-list "bridges" (of-type 'bridge)) (tr-char #\,)
      (tr-struct-list "rules" (of-type 'rule)) (tr-char #\,)
      (tr-struct-list "descriptions" descriptions) (tr-char #\,)
      (tr-put "\"proposed\":{")
      (tr-names-list "bonds" proposed-bonds) (tr-char #\,)
      (tr-names-list "groups" proposed-groups) (tr-char #\,)
      (tr-names-list "bridges" proposed-bridges)
      (tr-put "}},"))
    ;; temporal trace
    (tr-snapshot-trace)
    (tr-put "}")
    (tr-nl)))

(define tr-snapshot-trace
  (lambda ()
    (let ((counts '()))
      (for-each
        (lambda (event)
          (let* ((type (tell event 'get-type))
                 (hit (assq type counts)))
            (if hit
                (set-cdr! hit (+ (cdr hit) 1))
                (set! counts (cons (cons type 1) counts)))))
        (tell *trace* 'get-all-events))
      (tr-put "\"trace\":{\"events\":{")
      (let loop ((rest (sort (lambda (a b) (string<? (symbol->string (car a))
                                                    (symbol->string (car b))))
                             counts))
                 (first? #t))
        (if (not (null? rest))
            (begin
              (if (not first?) (tr-char #\,))
              (tr-q (symbol->string (caar rest)))
              (tr-char #\:)
              (tr-num (cdar rest))
              (loop (cdr rest) #f))))
      (tr-put "},\"snag\":")
      (tr-bool (tell *trace* 'within-snag-period?))
      (tr-put ",\"clamp\":")
      (tr-bool (tell *trace* 'within-clamp-period?))
      (tr-put "}"))))

;; ---------------------------------------------------------------------------
;; Open / run / close

;; problem: list of three symbols; revision: string (bundle manifest hash).
(define trace-open
  (lambda (path problem seed cap revision)
    (set! *tr-port* (open-output-file path 'replace))
    (set! *tr-enabled* #t)
    (set! *tr-depth* 0)
    (set! *tr-u-counter* 0)
    (set! *tr-saved* '())
    (tr-set-unit! "init" "init-mcat" 1 #f)
    (tr-put "{\"t\":\"header\",\"format\":1,\"engine\":\"metacat\",\"revision\":")
    (tr-q revision)
    (tr-put ",\"problem\":")
    (tr-array (map symbol->string problem) tr-q)
    (tr-put ",\"seed\":")
    (tr-num seed)
    (tr-put ",\"cap\":")
    (tr-num cap)
    (tr-put ",\"settings\":{\"recorder\":1,\"snapshots\":")
    (tr-bool *tr-snapshots?*)
    (tr-put "}}")
    (tr-nl)))

(define tr-end-record
  (lambda (reason answer error codelets)
    (tr-put "{\"t\":\"end\",\"c\":")
    (tr-num *tr-c*)
    (tr-put ",\"reason\":")
    (tr-q reason)
    (if answer (begin (tr-put ",\"answer\":") (tr-q answer)))
    (if error (begin (tr-put ",\"error\":") (tr-q error)))
    (tr-put ",\"codelets\":")
    (tr-num codelets)
    (tr-put "}")
    (tr-nl)))

;; Run the problem set up by init-mcat to its end and write the end record.
;; An answer and a give-up both reach `suspend`; they are told apart by whether
;; memory gained an answer.  Errors (KNOWN-FAILURES.md) become reason "error".
(define trace-run
  (lambda ()
    ;; Unrecognised messages must raise (the default prints and (reset)s).
    (set! report-error-and-halt
      (lambda (message object)
        (assertion-violation 'metacat-message "unrecognized object message"
                             (cdr message))))
    (let ((outcome
            (guard (c (#t (cons 'error c)))
              (call/cc
                (lambda (k)
                  (set! suspend (lambda () (k 'suspended)))
                  (set! break (lambda () (k 'capped)))
                  (run-mcat))))))
      (set! *tr-depth* 0)
      (let ((answers (tell *memory* 'get-answers)))
        (cond
          ((pair? outcome)
           (tr-end-record "error" #f (tr-condition-text (cdr outcome)) *codelet-count*))
          ((not (null? answers))
           (tr-end-record "answer" (tell (car answers) 'get-answer-print-name) #f
                          *codelet-count*))
          ((eq? outcome 'capped)
           (tr-end-record "cap" #f #f *codelet-count*))
          (else
           (tr-end-record "give-up" #f #f *codelet-count*))))
      (flush-output-port *tr-port*)
      (close-output-port *tr-port*)
      (set! *tr-port* #f)
      (set! *tr-enabled* #f)
      (if *tr-audit?* (tr-audit-report))
      ;; The outcome in the collector's vocabulary, for record.py's check.
      (let ((answers (tell *memory* 'get-answers)))
        (printf "RESULT ~a ~a~%"
          (cond
            ((pair? outcome) "*ERROR*")
            ((not (null? answers)) (tell (car answers) 'get-answer-print-name))
            ((eq? outcome 'capped) "*CAP*")
            (else "*NONE*"))
          *codelet-count*)))))

(define tr-audit-report
  (lambda ()
    (if (> *audit-pending* 0)
        (begin
          (set! *audit-strays* (cons *audit-pending-who* *audit-strays*))
          (set! *audit-pending* 0)))
    (printf "AUDIT raw-draws=~a strays=~a orphan-if-hooks=~a~%"
      *audit-raw* (length *audit-strays*) *audit-orphan-hooks*)
    (for-each (lambda (who) (printf "AUDIT stray at ~a~%" who))
      (list-head *audit-strays* (min 20 (length *audit-strays*))))))

(if *tr-audit?*
    (set! audit-who
      (lambda () (format "~a/~a c=~a" *tr-ctx* *tr-who* *tr-c*))))

;; ---------------------------------------------------------------------------
;; Naming check (spec section 4, M0): write the canonical names of every
;; letter, description and slipnet node of the opening state, as a sorted JSON
;; list.  Call after init-mcat.

(define dump-opening-names
  (lambda (path)
    (let* ((letters (tell *workspace* 'get-all-letters))
           (descriptions
             (apply append (map (lambda (l) (tell l 'get-descriptions)) letters)))
           (names
             (sort string<?
               (append (map tr-name letters)
                       (map tr-name descriptions)
                       (map tr-name *slipnet-nodes*)))))
      (set! *tr-port* (open-output-file path 'replace))
      (tr-array names tr-q)
      (tr-nl)
      (close-output-port *tr-port*)
      (set! *tr-port* #f))))
