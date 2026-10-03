# Red-team report

33 scam seeds from the holdouts and archives; the originals are caught 24/33.
Each seed is rewritten with the tricks below. A variant counts as caught when the rules send it to a person or the model flags it. Run seed 20261003: every run makes new variants, so fixes are never graded on the variants they were built from.

| Trick | Variants caught |
|---|---|
| leetspeak | 24/33 |
| no_dollar_amounts | 25/33 |
| polite_tone | 24/33 |
| synonyms | 24/33 |
| synonyms+polite_tone | 24/33 |
| zero_width | 24/33 |

## Slipped through (0): the original was caught, the rewrite wasn't


## Regression set: 8/8 still caught
Variants saved after a fix was made for them (`--save-regression`). The release gate requires every new model to catch at least as many as the active one.

These are for a person to read and turn into rules or normalization. They are never trained on.
