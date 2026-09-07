;; Native get-answers is newest first (memory.ss:55,104). Reverse once before
;; filtering; both selectors preserve their input order. No history is exported.
;; themes.ss:1142 defines the relation diff as #f, not as a slipnode.
(set! study-concept-name
  (let ((original study-concept-name))
    (lambda (x) (if (eq? x diff) "diff" (original x)))))

(define (pilot-best-groups native-answers)
  (let ((oldest-first (reverse native-answers)))
    (list (study-best-quality oldest-first) (study-preferred oldest-first))))

(define (pilot-write-best port definition winners)
  (display (format "~a\t~a" definition
              (if (null? winners) "*NONE*"
                  (tell (car winners) 'get-answer-print-name))) port)
  (write-char #\newline port))
