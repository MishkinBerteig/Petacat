"""Log what Metacat's rule translation left on every answer and snag event.

    python3 tests/lockstep/metacat/record_translation.py I M T LO-HI [--answer A] [--cap N] [--out DIR]

Runs seeds LO..HI of the problem ``I -> M, T -> ?`` in the ``metacat:1.2`` container
(plain mode, or justify mode with ``--answer``), memory cleared before each run, and for
every answer and snag event the run recorded reads off the event:

* the slippage log (``make-slippage-log``, ``answers.ss:1198``): the directly applied
  slippages, the coattail slippages with the slippage that induced each, the bridges they
  came from, and the applied list;
* the supporting vertical bridges, and the rules' reference objects (``trace.ss:335``,
  ``trace.ss:1052``);
* for an answer, the supporting groups.

Lines, tab separated (``TR`` rows are what ``scripts/compare_translation_log.py`` reads)::

    TR<TAB>seed<TAB>codelet-count<TAB>answer|snag<TAB>JSON
    END<TAB>seed<TAB>codelet-count<TAB>outcome

An object is ``string:left-right``, a bridge ``orientation:l1-r1:l2-r2``, a concept mapping
``{type, from, label, to}`` by short name.  The recorder only reads: it draws nothing and
changes no run.  With ``--out DIR`` the lines go to ``DIR/<slug>.<LO-HI>.tsv`` instead of
standard output.  Needs Docker and the image (``metacat/README.md``).
"""
import argparse, os, shutil, sys, time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import record

ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
ap.add_argument("i"); ap.add_argument("m"); ap.add_argument("t"); ap.add_argument("seeds", help="LO-HI")
ap.add_argument("--answer", help="justify mode: the answer to justify")
ap.add_argument("--cap", type=int, default=100000, help="codelet cap per run")
ap.add_argument("--out", help="directory for the output file (default: standard output)")
a = ap.parse_args()
LO, HI = map(int, a.seeds.split("-"))
ans = f"'{a.answer}" if a.answer else "#f"

PRE = r'''(define *metacat-directory* "/metacat/")
(load "/metacat/metacat-headless.ss")
(set! report-error-and-halt
  (lambda (message object)
    (assertion-violation 'metacat-message "unrecognized object message" (cdr message))))
(reset-handler (lambda () (exit 1)))
%JUSTIFY%
(define (js s) (format "~s" s))
(define (jn s) (if s (js s) "null"))
(define (jl items)
  (let loop ((l items) (acc ""))
    (cond ((null? l) (string-append "[" acc "]"))
          ((string=? acc "") (loop (cdr l) (car l)))
          (else (loop (cdr l) (string-append acc "," (car l)))))))
(define (cm-ref cm)
  (format "{\"type\":~a,\"from\":~a,\"label\":~a,\"to\":~a}"
    (jn (tell (tell cm 'get-CM-type) 'get-CM-short-name))
    (jn (tell (tell cm 'get-descriptor1) 'get-CM-short-name))
    (jn (let ((l (tell cm 'get-label))) (if l (tell l 'get-short-name) #f)))
    (jn (tell (tell cm 'get-descriptor2) 'get-CM-short-name))))
(define (obj-key o)
  (if (workspace-string? o)
    (js (format "~a:-1--1" (tell o 'get-string-type)))
    (js (format "~a:~a-~a" (tell (tell o 'get-string) 'get-string-type)
          (tell o 'get-left-string-pos) (tell o 'get-right-string-pos)))))
(define (bridge-key b)
  (let ((o1 (tell b 'get-object1)) (o2 (tell b 'get-object2)))
    (js (format "~a:~a-~a:~a-~a" (tell b 'get-bridge-type)
          (tell o1 'get-left-string-pos) (tell o1 'get-right-string-pos)
          (tell o2 'get-left-string-pos) (tell o2 'get-right-string-pos)))))
(define (log-json log)
  (format "{\"directly_applied\":~a,\"coattail\":~a,\"bridges\":~a,\"applied\":~a}"
    (jl (map cm-ref (tell log 'get-directly-applied-slippages)))
    (jl (map (lambda (c i) (format "{\"slippage\":~a,\"inducing\":~a}" (cm-ref c) (cm-ref i)))
          (tell log 'get-coattail-slippages) (tell log 'get-coattail-inducing-slippages)))
    (jl (map bridge-key (tell log 'get-slippage-bridges)))
    (jl (map cm-ref (tell log 'get-applied-slippages)))))
(define (event-json e)
  (if (eq? (tell e 'get-type) 'answer)
    (format "{\"slippage_log\":~a,\"supporting_vertical_bridges\":~a,\"supporting_groups\":~a,\"top_ref_objects\":~a,\"bottom_ref_objects\":~a}"
      (log-json (tell e 'get-slippage-log))
      (jl (map bridge-key (tell e 'get-supporting-bridges 'vertical)))
      (jl (map obj-key (tell e 'get-supporting-groups)))
      (jl (map obj-key (tell e 'get-rule-ref-objects 'top)))
      (jl (map obj-key (tell e 'get-rule-ref-objects 'bottom))))
    (format "{\"slippage_log\":~a,\"supporting_vertical_bridges\":~a,\"top_ref_objects\":~a}"
      (log-json (tell e 'get-slippage-log))
      (jl (map bridge-key (tell e 'get-supporting-bridges 'vertical)))
      (jl (map obj-key (tell e 'get-rule-ref-objects))))))
(define (dump-events seed)
  (for* each e in (reverse (tell *trace* 'get-all-events)) do
    (if* (memq (tell e 'get-type) '(answer snag))
      (display (format "TR\t~a\t~a\t~a\t~a"
        seed (tell e 'get-time) (tell e 'get-type) (event-json e)))
      (write-char #\newline))))
(define (one-run run-seed)
  (tell *memory* 'clear)
  (let* ((outcome
           (guard (c (#t 'error))
             (init-mcat 'I 'M 'T ANS run-seed)
             (set! *break-time* CAP)
             (call/cc (lambda (k)
                        (set! suspend (lambda () (k 'suspended)))
                        (set! break (lambda () (k 'capped)))
                        (run-mcat))))))
    (display (format "END\t~a\t~a\t~a" run-seed *codelet-count* outcome))
    (write-char #\newline)
    (dump-events run-seed)))
'''.replace("%JUSTIFY%", "(set! %justify-mode% #t)" if a.answer else "").replace(
    "'I 'M 'T ANS", f"'{a.i} '{a.m} '{a.t} {ans}").replace("CAP", str(a.cap))

drv = PRE + "".join(f"(one-run {s})\n" for s in range(LO, HI + 1)) + "(exit 0)\n"
rundir = record.WORK / f"trn-{a.i}-{a.m}-{a.t}-{a.answer}-{LO}-{os.getpid()}-{time.monotonic_ns()}"
rundir.mkdir(parents=True)
(rundir / "driver.ss").write_text(drv)
code, out, wall = record.run_container(record.SOURCE, rundir, 7200)
lines = [l for l in out.splitlines() if l.startswith(("TR\t", "END\t"))]
if a.out:
    slug = "-".join([a.i, a.m, a.t] + ([a.answer] if a.answer else []))
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / f"{slug}.{LO}-{HI}.tsv").write_text("\n".join(lines) + "\n")
else:
    print("\n".join(lines))
if code != 0:
    print("EXIT", code, out[-500:], file=sys.stderr)
shutil.rmtree(rundir, ignore_errors=True)
