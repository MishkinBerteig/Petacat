#!/usr/bin/env python3
"""Record how Metacat's own input parser reads text, for Petacat's differential test.

Metacat reads a problem from one line of text (the control panel's command line, ``gui.ss:147``):
``tokenize-string`` (``gui.ss:95``) splits the line into symbols and numbers with ``char-noise?``
(``gui.ss:135``), and ``valid-token-list?`` (``syntactic-sugar.ss:51``, with ``valid-number?`` and
``symbol-or-valid-number?`` beside it) says whether the tokens are a problem.  This recorder runs
those real procedures, in the Chez Scheme of the ``metacat:1.2`` image, and writes what they do.
``tokenize-string`` and ``char-noise?`` are taken from ``gui.ss`` by name (it cannot be loaded
whole: it is the GUI), by reading the file and evaluating those two ``define`` forms; the other
three come from the loaded engine source.  Nothing is retyped.  The tree is the patched Metacat
(``Metacat/build/source``), and the recorder refuses any other.

    python3 tests/lockstep/metacat/record_parser.py            # tests/lockstep/data/parser_metacat.json.gz

THE FORMAT of ``parser_metacat.json.gz`` (gzip, mtime 0, one JSON object, keys sorted; the file is
byte-identical for a given tree).  A character below means a Unicode scalar value, 0 to 0x10FFFF
without the surrogates 0xD800 to 0xDFFF; ``lowered(c)`` is Chez's ``(char-downcase c)``.

    format        "petacat-parser-recording-1"
    revision      "metacat-bundle-manifest-sha256:<hash>+known-failure-fixes" (the tree that ran)
    chez_version  Chez's ``(scheme-version)``
    placeholder   "\\u0001": see ``lines`` below
    downcase      [[first, last, delta], ...] every run of consecutive characters whose
                  ``char-downcase`` is the character plus ``delta`` (delta is never 0; a character
                  in no run is its own lowered form)
    alphabetic    [[first, last], ...] every run of characters c with ``char-alphabetic?`` true of lowered(c)
    numeric       [[first, last], ...] the same for ``char-numeric?`` of lowered(c)
    noise         [[first, last], ...] the same for ``char-noise?`` of lowered(c) (the real procedure;
                  not alphabetic and not numeric).  ``tokenize-string`` applies all three tests to
                  lowered characters only.
    lines         {name: [[first, last, result, valid], ...]} for the three lines
                  ``abc abd x{c}z`` ("x_c_z"), ``abc abd {c}`` ("abc_abd_c") and ``{c}bc abd xyz``
                  ("c_bc_abd_xyz"), where ``{c}`` is the one character c.  The runs partition 0..0x10FFFF
                  without the surrogates, in order.  ``result`` is what ``tokenize-string`` returned and
                  ``valid`` is ``(valid-token-list? result)``.  ``result`` is one of
                      {"error": true}                       the procedure returned the symbol ``error``
                      {"tokens": [token, ...]}              a token is a JSON string (a symbol's name),
                                                            {"num": n} (an exact integer), null (#f, as
                                                            ``string->number`` gives for digits it
                                                            cannot read) or {"other": "<written>"}
                      {"exception": "<message>"}            Chez raised a condition
                  Inside a run whose characters are all non-ASCII, a symbol name has every occurrence
                  of lowered(c) replaced by the placeholder, so one run states the result for all of
                  its characters: for a character c, replace the placeholder with lowered(c).  A run
                  of ASCII characters (c below 128) is a single character or a run with no
                  substitution, and holds the names as they are.
    whole_lines   [{"line": text, "result": result, "valid": bool}, ...] about 200 whole input lines
                  (seeds, answers, token counts, digit forms, non-ASCII digits, mixed cases,
                  punctuation, non-English letters), the result as above with names as they are.

``tests/lockstep/metacat/record_parser.py`` is the only writer.  Needs Docker and the
``metacat:1.2`` image.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import record  # noqa: E402
import wrap  # noqa: E402

FORMAT = "petacat-parser-recording-1"
DEFAULT_PATH = record.REPO / "tests" / "lockstep" / "data" / "parser_metacat.json.gz"
PLACEHOLDER = "\u0001"
LINE_STREAMS = {"x_c_z": "abc abd x{c}z", "abc_abd_c": "abc abd {c}", "c_bc_abd_xyz": "{c}bc abd xyz"}


def whole_lines() -> list[str]:
    """About 200 whole lines: deterministic, written out here."""
    base = "abc abd xyz"
    out = [
        # the plain problems, with and without an answer and a seed
        "abc abd xyz", "abc abd xyz wyz", "abc abd xyz 5", "abc abd xyz wyz 5", "abc abd xyz 1",
        "abc abd xyz 4294967295", "abc abd xyz 4294967296", "abc abd xyz 0", "abc abd xyz -5",
        "abc abd xyz 00012", "abc abd xyz 1e5", "abc abd xyz 1.5", "abc abd xyz 99999999999999999999",
        "abc abd xyz wyz 4294967295", "abc abd xyz wyz 0", "abc abd xyz wyz 4294967296",
        "abc abd xyz 7 wyz", "abc abd xyz wyz wyz 3", "abc abd xyz 5 6", "abc abd xyz wyz 5 6",
        "abc abd xyz wyz 5.0", "abc abd xyz wyz +5", "abc abd xyz 0x10", "abc abd xyz #5",
        # token counts
        "", " ", "abc", "abc abd", "abc abd xyz wyz 3 4", "abc abd xyz wyz 3 4 5", "1", "1 2", "1 2 3",
        # digit forms
        "ab1 abd xyz", "abc abd 12", "abc 1 xyz", "a1b abd xyz", "abc abd xyz1", "1abc abd xyz",
        "abc1 abd xyz", "abc abd xyz 12abc", "abc abd xyz 1a", "12 34 56", "abc abd xyz 12 34",
        # non-ASCII digits and numeric characters
        "abc abd xyz ٣", "abc abd xyz १२", "abc abd xyz １２", "abc abd ٣",
        "abc abd xyz wyz ٣", "x٣z abd xyz", "abc abd xyz ²", "abc abd xyz Ⅳ",
        "abc abd xyz ½", "abc abd xyz ๑", "abc abd xyz 1٣", "abc abd xyz ٣ 1",
        # mixed case
        "ABC abd XYZ", "AbC aBd xYz", "abc ABD xyz", "ABC ABD XYZ", "Abc Abd Xyz Wyz 5",
        "abc abd xyz WYZ", "abc abd xyz Wyz 7",
        # punctuation and separators
        "abc,abd;xyz", "abc-abd-xyz", "abc\tabd\nxyz", "(abc)(abd)(xyz)", "a'b abd xyz", "a.b abd xyz",
        "abc abd x-z", "abc abd x_z", "abc abd x!z", "abc abd  xyz", "  abc   abd   xyz  ",
        "abc, abd, xyz, wyz, 5", "abc/abd/xyz", "abc>abd>xyz", "abc -> abd; xyz -> ?", "abc -> abd; xyz -> wyz",
        "abc abd xyz", "abc abd xyz", "abc​abd xyz", "abc　abd　xyz",
        # emoji and combining marks
        "abc abd x\U0001f600z", "abc abd \U0001f600", "\U0001f600 abd xyz", "abc abd xéz",
        "abc abd xyź", "ébc abd xyz", "abc abd ́", "abc abd x‍z",
        # non-English letters
        "abc abd xéz", "abc abd é", "ébc abd xyz", "ñandú abd xyz",
        "abc abd xyz é", "abc abd xyz wyz é", "abc abd xyz wyz é 5",
        "日本 abd xyz", "abc abd 日本語", "abc абв xyz",
        "αβγ abd xyz", "abc abd σ", "abc abd ß", "abc abd ı", "abc abd İ",
        "abc abd K", "abc abd ǅ", "abc abd ǈ", "abc abd ＡＢＣ", "abc abd ａ",
        "abc abd ɑ", "abc abd Ⅰ", "abc abd ⅰ", "abc abd Ⓐ", "abc abd À",
        "ÀBC abd xyz", "abc abd مرحبا", "abc abd שלום",
        "abc abd 한국어", "abc abd あい", "abc abd アイ",
        # seeds and answers in more forms
        "abc abd xyz 2", "abc abd xyz 3", "abc abd xyz 10", "abc abd xyz 123456789", "abc abd xyz 2147483648",
        "abc abd xyz 4294967294", "abc abd xyz wyz 1", "abc abd xyz wyz 2", "abc abd xyz wyz 4294967294",
        "abc abd xyz wyz  7", "abc abd xyz,wyz,7", "mrrjjj aabbcc kkjjii", "iijjkk iijjll mmnnoo 42",
        "abc cba mrrjjj 20713988", "abc aabbcc kkjjii 20226148", "abc abd xyz xyz", "abc abd ijk ijl 3",
        "a b c", "a b c d", "a b c d 9", "z y x", "abcdefghijklmnopqrstuvwxyz abc xyz",
        "AbC-aBd-XyZ-wYz-5", "abc abd xyz\n5", "abc abd xyz\r\n", "abc abd xyz\t", "\tabc abd xyz",
    ]
    # one word of each kind in each of the three positions of the plain problem
    words = ["a", "Z", "1", "-", "é", "日", "\U0001f600", "́", "٣", "abc9", "xy z",
             "A1", "É", "qü", "Ω", "Ж", "5", "x.y", "abé"]
    for k in range(3):
        for w in words:
            parts = base.split()
            parts[k] = w
            out.append(" ".join(parts))
    seen: list[str] = []
    for line in out:
        if line not in seen:
            seen.append(line)
    return seen


def scm_str(text: str) -> str:
    """The inside of a Scheme string literal: plain ASCII, every other character a ``\\x<hex>;`` escape."""
    return "".join(c if (c.isascii() and c.isalnum()) else f"\\x{ord(c):x};" for c in text)


def driver(lines: list[str]) -> str:
    """The Scheme driver: loads the patched engine, takes the two parser procedures out of ``gui.ss``,
    and prints ``PARSER`` lines (tab separated) for the four recordings."""
    literals = " ".join(f'"{scm_str(l)}"' for l in lines)
    return wrap.PRELUDE + r'''
;; tokenize-string and char-noise? are in gui.ss, the GUI, which cannot be loaded whole: read the
;; file and evaluate those two definitions, by name.  The others (valid-token-list? and its two
;; helpers) are the engine's own, loaded above from syntactic-sugar.ss.
(define (take-definitions! path names)
  (let ((port (open-input-file path)))
    (let loop ()
      (let ((form (read port)))
        (cond
          ((eof-object? form) (close-port port))
          (else
            (if (and (pair? form) (eq? (car form) 'define) (pair? (cdr form)) (memq (cadr form) names))
                (eval form))
            (loop)))))))
(take-definitions! "/metacat/gui.ss" '(tokenize-string char-noise?))
(for-each (lambda (p) (if (not (procedure? p)) (error 'record-parser "missing procedure")))
          (list tokenize-string char-noise? valid-token-list? valid-number? symbol-or-valid-number?))

(define placeholder (integer->char 1))

(define (hex4 n)
  (let ((s (number->string n 16)))
    (string-append (make-string (- 4 (string-length s)) #\0) s)))

;; JSON string, plain ASCII.
(define (json-str s)
  (let ((out (open-output-string)))
    (write-char #\" out)
    (string-for-each
      (lambda (ch)
        (let ((n (char->integer ch)))
          (cond
            ((char=? ch #\") (display "\\\"" out))
            ((char=? ch #\\) (display "\\\\" out))
            ((or (< n 32) (> n 126))
             (if (> n #xFFFF)
                 (let ((m (- n #x10000)))
                   (display (string-append "\\u" (hex4 (+ #xD800 (quotient m 1024)))
                                                "\\u" (hex4 (+ #xDC00 (remainder m 1024)))) out))
                 (display (string-append "\\u" (hex4 n)) out)))
            (else (write-char ch out)))))
      s)
    (write-char #\" out)
    (get-output-string out)))

(define (replace-char s from to)
  (list->string (map (lambda (c) (if (char=? c from) to c)) (string->list s))))

;; The JSON of a tokenize-string result; the lowered character d is replaced by the placeholder in
;; the names of symbols when sub is true.
(define (result-json r sub d)
  (define (name sym)
    (let ((s (symbol->string sym)))
      (json-str (if sub (replace-char s d placeholder) s))))
  (cond
    ((eq? r 'error) "{\"error\":true}")
    ((list? r)
     (string-append
       "{\"tokens\":["
       (let loop ((ts r) (acc ""))
         (cond
           ((null? ts) acc)
           (else
             (loop (cdr ts)
                   (string-append acc (if (string=? acc "") "" ",")
                     (let ((t (car ts)))
                       (cond
                         ((symbol? t) (name t))
                         ((and (number? t) (exact? t) (integer? t)) (string-append "{\"num\":" (number->string t) "}"))
                         ((eq? t #f) "null")
                         (else (string-append "{\"other\":" (json-str (format "~s" t)) "}")))))))))
       "]}"))
    (else (string-append "{\"other\":" (json-str (format "~s" r)) "}"))))

(define (run-line line sub d)
  ;; (values result-json valid?)
  (guard (c (#t (values (string-append "{\"exception\":"
                          (json-str (call-with-string-output-port (lambda (p) (display-condition c p)))) "}")
                        #f)))
    (let ((r (tokenize-string line)))
      (values (result-json r sub d)
              (if (valid-token-list? r) #t #f)))))

;; Run-length streams: name -> (vector start last key).
(define streams (make-hashtable string-hash string=?))
(define stream-names '())
(define (emit! name start last key)
  (display "PARSER\t") (display name) (display "\t") (display start) (display "\t")
  (display last) (display "\t") (display key) (newline))
(define (rle! name c key)
  (let ((st (hashtable-ref streams name #f)))
    (cond
      ((not st)
       (set! stream-names (cons name stream-names))
       (hashtable-set! streams name (vector c c key)))
      ((string=? (vector-ref st 2) key) (vector-set! st 1 c))
      (else
       (emit! name (vector-ref st 0) (vector-ref st 1) (vector-ref st 2))
       (hashtable-set! streams name (vector c c key))))))
(define (flush-streams!)
  (for-each
    (lambda (name)
      (let ((st (hashtable-ref streams name #f)))
        (if st (emit! name (vector-ref st 0) (vector-ref st 1) (vector-ref st 2)))
        (hashtable-delete! streams name)))
    (reverse stream-names))
  (set! stream-names '()))

(define (bool-key b) (if b "1" "0"))
(define (record-char! n)
  (let* ((c (integer->char n))
         (d (char-downcase c))
         (sub (> n 127)))
    (rle! "downcase" n (number->string (- (char->integer d) n)))
    (rle! "alphabetic" n (bool-key (char-alphabetic? d)))
    (rle! "numeric" n (bool-key (char-numeric? d)))
    (rle! "noise" n (bool-key (char-noise? d)))
    (for-each
      (lambda (spec)
        (let ((line (string-append (car spec) (string c) (cadr spec))))
          (let-values (((json valid) (run-line line sub d)))
            (rle! (caddr spec) n (string-append json "|" (bool-key valid))))))
      (list (list "abc abd x" "z" "x_c_z")
            (list "abc abd " "" "abc_abd_c")
            (list "" "bc abd xyz" "c_bc_abd_xyz")))))

(define (record-range! lo hi)
  (let loop ((n lo))
    (when (<= n hi)
      (record-char! n)
      (loop (+ n 1))))
  (flush-streams!))

(record-range! 0 #xD7FF)
(record-range! #xE000 #x10FFFF)

(define whole-lines (list ''' + literals + r'''))
(let loop ((ls whole-lines) (i 0))
  (when (pair? ls)
    (let-values (((json valid) (run-line (car ls) #f #\a)))
      (display "PARSER\tline\t") (display i) (display "\t") (display json) (display "\t")
      (display (bool-key valid)) (newline))
    (loop (cdr ls) (+ i 1))))
(display "PARSER\tdone\t") (display (scheme-version)) (newline)
(exit 0)
'''


def parse(output: str, lines: list[str]) -> dict:
    streams: dict[str, list[list]] = {}
    whole: dict[int, tuple[str, bool]] = {}
    version = None
    for row in output.splitlines():
        if not row.startswith("PARSER\t"):
            continue
        f = row.split("\t")
        if f[1] == "line":
            whole[int(f[2])] = (f[3], f[4] == "1")
        elif f[1] == "done":
            version = f[2]
        else:
            streams.setdefault(f[1], []).append([int(f[2]), int(f[3]), f[4]])
    if version is None:
        sys.exit("the driver did not finish:\n" + output[-2000:])
    for name in ("downcase", "alphabetic", "numeric", "noise", *LINE_STREAMS):
        if name not in streams:
            sys.exit(f"no {name} stream:\n" + output[-2000:])
    doc = {
        "format": FORMAT,
        "chez_version": version,
        "placeholder": PLACEHOLDER,
        "downcase": [[a, b, int(k)] for a, b, k in streams["downcase"] if int(k) != 0],
        "alphabetic": [[a, b] for a, b, k in streams["alphabetic"] if k == "1"],
        "numeric": [[a, b] for a, b, k in streams["numeric"] if k == "1"],
        "noise": [[a, b] for a, b, k in streams["noise"] if k == "1"],
        "lines": {},
        "whole_lines": [],
    }
    for name in LINE_STREAMS:
        runs = []
        for a, b, k in streams[name]:
            result, _, valid = k.rpartition("|")
            runs.append([a, b, json.loads(result), valid == "1"])
        doc["lines"][name] = runs
    for i, line in enumerate(lines):
        result, valid = whole[i]
        doc["whole_lines"].append({"line": line, "result": json.loads(result), "valid": valid})
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_PATH, help=f"default {DEFAULT_PATH}")
    args = ap.parse_args()
    if record.source_state() != "fixes":
        sys.exit("Metacat/build/source is not the patched Metacat; Metacat always means the patched build")
    lines = whole_lines()
    output = wrap.run_driver(driver(lines), "parser")
    doc = parse(output, lines)
    doc["revision"] = ("metacat-bundle-manifest-sha256:" + record.sha256(record.METACAT / "manifest.json")
                       + "+known-failure-fixes")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    with args.out.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0,
                                                   compresslevel=9) as zipped:
        zipped.write(text.encode("ascii"))
    print(f"{args.out}: {args.out.stat().st_size} bytes; {len(doc['whole_lines'])} whole lines; "
          f"runs: " + ", ".join(f"{k} {len(v)}" for k, v in doc['lines'].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
