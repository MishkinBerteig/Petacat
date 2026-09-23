# Anonymous TMLR Manuscript Source

This bundle builds **Large References, Fast Checks: Oracle-Guided Porting
of a Stochastic Learning System** in TMLR's anonymous submission format.
The editable source is `support-set-oracles-final.md`; generated LaTeX and
the twelve data tables are included. It contains no author information.
The paper uses its own tables in `final/generated/` and its bibliography
in `final/references.bib`.

## Build the PDF

Install [Tectonic](https://tectonic-typesetting.github.io/en-US/install.html),
then run in this extracted directory:

```sh
tectonic support-set-oracles-final.tex
```

The first build may download TeX dependencies. The result is
`support-set-oracles-final.pdf`. The checked build uses Tectonic 0.17.0.
The official TMLR style files and their licence are supplied; do not enable
the `preprint` or `accepted` options for initial submission.

## Rebuild From Markdown

Install [Pandoc](https://pandoc.org/installing.html) as well. The checked
conversion uses Pandoc 3.11. The following is the same Markdown-to-LaTeX
conversion used by the repository workflow, using the supplied audited tables:

```sh
pandoc support-set-oracles-final.md --from=markdown+raw_tex --to=latex \
  --standalone --natbib --wrap=auto --columns=90 \
  --syntax-highlighting=none --template=tools/tmlr-template.tex \
  --output=support-set-oracles-final.tex
tectonic support-set-oracles-final.tex
```

The separate experimental bundle supplies the scientific records, audit
scripts, and reconstruction patches. Its `python3 verify.py` regenerates
the shared data tables and checks the saved results without rerunning
either analogy engine. This source bundle is sufficient to build the
paper, but is not itself the experimental data release. The tables in this
source bundle correspond to the scope of this manuscript.
