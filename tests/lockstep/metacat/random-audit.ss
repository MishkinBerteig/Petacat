;;=============================================================================
;; Debug-only raw-draw audit.  Load this BEFORE metacat-headless.ss.
;;
;; Chez lets a top-level (define random ...) shadow the primitive for code
;; loaded afterwards (set! of the primitive is refused: immutable).  This file
;; shadows `random` with a counting wrapper that calls the real primitive with
;; the same arguments, so the draw sequence is unchanged.
;;
;; Accounting (see decision-trace.ss): every draw made while the trace wrapper
;; depth counter is above zero belongs to a logged or explicitly suppressed
;; decision.  A draw at depth zero is "pending"; the stochastic-if* trace hook
;; claims it (the macro draws its coin before the hook runs).  Any pending draw
;; that is never claimed is a stray: a raw draw attributed to no decision.
;;=============================================================================
(define *audit-enabled* #t)
(define *audit-raw* 0)
(define *audit-pending* 0)
(define *audit-pending-who* "?")
(define *audit-strays* '())
(define *audit-orphan-hooks* 0)
(define *tr-depth* 0)
(define audit-who (lambda () "?"))
(define audit-random-orig random)
(define random
  (lambda args
    (set! *audit-raw* (+ *audit-raw* 1))
    (if (= *tr-depth* 0)
        (begin
          (if (> *audit-pending* 0)
              (set! *audit-strays* (cons *audit-pending-who* *audit-strays*)))
          (set! *audit-pending* 1)
          (set! *audit-pending-who* (audit-who))))
    (apply audit-random-orig args)))
