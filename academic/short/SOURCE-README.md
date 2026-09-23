# Anonymous TMLR Manuscript Source

This bundle builds **Large References, Fast Checks: Oracle-Guided Porting
of a Stochastic Learning System** in anonymous TMLR submission format.
The main content is limited to 12 pages; references and appendices follow.
The editable source is `support-set-oracles-12-page.md`. The directory
name `final/` holds the bibliography; it does not indicate author approval.
The `short/generated/` directory holds the audited tables with terminology
matching the manuscript. Only caption and heading wording changed from the
earlier tables; every reported value is retained.

## Build the PDF

Install [Tectonic](https://tectonic-typesetting.github.io/en-US/install.html),
then run in the extracted directory:

```sh
tectonic support-set-oracles-12-page.tex
```

The first build may download TeX dependencies. The verified version is
Tectonic 0.17.0. Do not enable the `preprint` or `accepted` template options.

## Rebuild From Markdown

Install [Pandoc](https://pandoc.org/installing.html) as well. The checked
version is Pandoc 3.11. This is the repository's conversion command:

```sh
pandoc support-set-oracles-12-page.md --from=markdown+raw_tex --to=latex \
  --standalone --natbib --wrap=auto --columns=90 \
  --syntax-highlighting=none --template=tools/tmlr-template.tex \
  --output=support-set-oracles-12-page.tex
tectonic support-set-oracles-12-page.tex
```

The resulting file is `support-set-oracles-12-page.pdf`. The supplied tables
are audited saved-data results. Building the paper does not run either
analogy engine. The separate experimental bundle supplies scientific
records, audit scripts, and reference reconstruction patches; its
`python3 verify.py` checks saved evidence without repeating the experiments.

After edits, confirm that all main content, including title, abstract and
tables, ends by page 12 and that references begin on a new page. The
repository build enforces this limit automatically. All appendix detail is
part of the manuscript PDF, not a second main-text submission.
