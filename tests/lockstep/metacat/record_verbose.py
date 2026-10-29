"""Log everything Metacat prints with Verbose mode on (the vprintf / say / print narration).
python3 tests/lockstep/metacat/record_verbose.py I M T LO-HI [--answer A] [--episode N] [--cap N]
Plain mode: seeds LO..HI, memory cleared before each.  --episode N: LO..HI are episode seeds;
each runs N runs (seeds S..S+N-1) with memory carried.  Output, on stdout:
@@RUN<TAB>key
<the console output of that run, verbatim, one line per line>
@@END<TAB>key<TAB>codelet-count<TAB>outcome        key = seed or S.rk
`%verbose%` is switched on after init-mcat (the Options menu's "Verbose mode"), so the
output is exactly what the menu item prints; nothing else is changed, no random number is drawn."""
import argparse, os, sys, time, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import record

ap = argparse.ArgumentParser()
ap.add_argument("i"); ap.add_argument("m"); ap.add_argument("t"); ap.add_argument("seeds")
ap.add_argument("--answer"); ap.add_argument("--episode", type=int, default=0)
ap.add_argument("--cap", type=int, default=100000)
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
(define (one-run key run-seed clear?)
  (display (format "@@RUN\t~a" key)) (newline)
  (if clear? (tell *memory* 'clear))
  (let* ((outcome
           (guard (c (#t 'error))
             (init-mcat 'I 'M 'T ANS run-seed)
             (set! %verbose% #t)
             (set! *break-time* CAP)
             (call/cc (lambda (k)
                        (set! suspend (lambda () (k 'suspended)))
                        (set! break (lambda () (k 'capped)))
                        (run-mcat))))))
    (set! %verbose% #f)
    (display (format "@@END\t~a\t~a\t~a" key *codelet-count* outcome))
    (newline)
    outcome))
'''.replace("%JUSTIFY%", "(set! %justify-mode% #t)" if a.answer else "").replace("'I 'M 'T ANS", f"'{a.i} '{a.m} '{a.t} {ans}").replace("CAP", str(a.cap))

if a.episode:
    body = "".join(
        f"(tell *memory* 'clear)\n(let loop ((k 0)) (if (< k {a.episode}) "
        f"(if (not (eq? (one-run (format \"{s}.r~a\" (+ k 1)) (+ {s} k) #f) 'error)) "
        f"(loop (+ k 1)))))\n"
        for s in range(LO, HI + 1)
    )
else:
    body = "".join(f"(one-run \"{s}\" {s} #t)\n" for s in range(LO, HI + 1))
drv = PRE + body + "(exit 0)\n"
rundir = record.WORK / f"vrb-{a.i}-{a.m}-{a.t}-{a.answer}-{LO}-{os.getpid()}-{time.monotonic_ns()}"
rundir.mkdir(parents=True)
(rundir / "driver.ss").write_text(drv)
code, out, wall = record.run_container(record.SOURCE, rundir, 7200)
sys.stdout.write(out)
if code != 0:
    print("EXIT", code, file=sys.stderr)
shutil.rmtree(rundir, ignore_errors=True)
