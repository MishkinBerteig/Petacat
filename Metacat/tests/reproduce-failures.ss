;; One fresh-process reproducer per recorded support-study failure.
(define study-failure-cases
  '(("misc1-20713988" abc cba mrrjjj 20713988)
    ("misc1-20716342" abc cba mrrjjj 20716342)
    ("misc3-20226148" abc aabbcc kkjjii 20226148)))
(define study-failure-args (cdr (command-line)))
(define study-failure-case
  (and (= (length study-failure-args) 1)
       (assoc (car study-failure-args) study-failure-cases)))
(unless study-failure-case
  (display "Choose misc1-20713988, misc1-20716342, or misc3-20226148\n")
  (exit 2))
(define *metacat-directory* "/metacat/")
(load "/metacat/metacat-headless.ss")
(set! report-error-and-halt
  (lambda (message object)
    (printf "REPRODUCER bad object message: ~s\n" (cdr message))
    (exit 1)))
(printf "REPRODUCER ~a; fresh memory; cap 100000\n" (car study-failure-case))
(flush-output-port (current-output-port))
(tell *memory* 'clear)
(init-mcat (list-ref study-failure-case 1)
           (list-ref study-failure-case 2)
           (list-ref study-failure-case 3)
           #f (list-ref study-failure-case 4))
(set! *break-time* 100000)
(let ((outcome
       (call/cc
        (lambda (k)
          (set! suspend (lambda () (k 'suspended)))
          (set! break (lambda () (k 'capped)))
          (run-mcat)))))
  (printf "REPRODUCER returned ~s at ~s codelets; expected an exception\n"
          outcome *codelet-count*)
  (exit 2))
