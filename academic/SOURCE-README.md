# LaTeX Build Bundle

From the extracted directory, use a standard TeX installation:

```sh
pdflatex -interaction=nonstopmode -halt-on-error support-set-oracles-tmlr.tex
bibtex support-set-oracles-tmlr
pdflatex -interaction=nonstopmode -halt-on-error support-set-oracles-tmlr.tex
pdflatex -interaction=nonstopmode -halt-on-error support-set-oracles-tmlr.tex
```

Alternatively, with Tectonic installed:

```sh
tectonic support-set-oracles-tmlr.tex
```

Keep the `generated` directory beside the main `.tex` file. No external
measurement data, source checkout, or Pandoc installation is required to build
this generated LaTeX. A TeX engine may download packages on its first run.

The official TMLR style files and their license are included. The style's
automatic review header is template text, not a statement that this draft has
been submitted. Scientific and provenance limitations are disclosed in the
manuscript; a successful build does not establish submission readiness.
