;; Bundle-only tests, not changes to the captured Metacat engine.
;; Run with the reconstructed source as the current directory.
(load "metacat-headless.ss")

(define check
  (lambda (condition label)
    (unless condition
      (printf "FAIL ~a~%" label)
      (exit 1))))

;; Metacat normally resets to a REPL on bad messages. Fail the test instead.
(set! report-error-and-halt
  (lambda (message object)
    (printf "FAIL bad message: ~a~%" (cdr message))
    (exit 1)))
(reset-handler (lambda () (exit 1)))

(printf "RUNTIME ~a ~a~%" (scheme-version) (machine-type))
(check (not %gui-mode%) 'headless-mode)
(check (not (getenv "DISPLAY")) 'no-display)
(check (not (top-level-bound? 'swl:application)) 'no-swl-application)

(define run-one
  (lambda (initial modified target seed fresh? cap)
    (when fresh? (tell *memory* 'clear))
    (init-mcat initial modified target #f seed)
    (set! *break-time* cap)
    (let* ((outcome
             (call/cc
               (lambda (k)
                 (set! suspend (lambda () (k 'suspended)))
                 (set! break (lambda () (k 'capped)))
                 (run-mcat))))
           (answers (tell *memory* 'get-answers))
           (result (list outcome *codelet-count*
                     (map (lambda (a) (tell a 'get-answer-print-name)) answers))))
      (check (<= *codelet-count* cap) 'codelet-cap)
      (printf "RUN ~a ~a ~a seed=~a fresh=~a result=~a~%"
        initial modified target seed fresh? result)
      result)))

(define first-result (run-one 'abc 'abd 'xyz 42 #t 100000))
(check (not (null? (tell *memory* 'get-answers))) 'baseline-answer)
(check (equal? first-result (run-one 'abc 'abd 'xyz 42 #t 100000))
  'fresh-memory-repeatability)
(define remembered-answer (car (tell *memory* 'get-answers)))
(run-one 'abc 'abd 'xyz 43 #f 100000)
(check (memq remembered-answer (tell *memory* 'get-answers)) 'episodic-memory-retained)

;; The two documented crash reproducers, and a whole-string transformation.
(run-one 'aabc 'aabd 'ijkk 35 #t 100000)
(run-one 'xy 'z 'xy 5 #t 100000)
(run-one 'abc 'aaa 'xyz 42 #t 100000)
(check (eq? (car (run-one 'abc 'abd 'xyz 42 #t 1)) 'capped) 'cap-exit)

(init-mcat 'abc 'aaa 'xyz #f 42)
(define target-objects (tell *target-string* 'get-top-level-objects))
(check (null? (constituent-objects-of (car target-objects))) 'letter-has-no-constituents)
(check (equal? (constituent-objects-of *target-string*) target-objects)
  'workspace-string-keeps-constituents)
(check (eq? (tell *target-string* 'get-string) *target-string*) 'string-self)
(check (eq? (tell *target-string* 'which-string) 'target) 'which-string)
(check (eq? (tell *target-string* 'get-group-category) #f) 'group-category)
(check (eq? (tell *target-string* 'get-direction) #f) 'direction)
(check (= (tell *target-string* 'get-group-length) 3) 'group-length)
(check (eq? (tell *target-string* 'clamp-salience) 'done) 'clamp-salience)
(check (eq? (tell *target-string* 'unclamp-salience) 'done) 'unclamp-salience)
(check (null? (tell *target-string* 'get-all-descriptors)) 'descriptors)
(check (null? (tell *target-string* 'get-descriptions)) 'descriptions)
(printf "PASS headless smoke and targeted method checks~%")
(exit 0)
