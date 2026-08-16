# Local audio and pronunciation

5MinBooks generates audio locally with
[Kokoro-ONNX](https://github.com/thewh1teagle/kokoro-onnx), using the open
[Kokoro](https://github.com/hexgrad/kokoro) model. The runtime can accept a
phoneme sequence directly. The project therefore uses a small, versioned
dictionary rather than retraining the model. This makes each correction
deterministic, visible in review and reusable across books. Kokoro's language
frontend is maintained separately as
[Misaki](https://github.com/hexgrad/misaki).

`config/pronunciations.json` stores exact terms and aliases with a phoneme
sequence for each supported language. Longer matches take priority, so a full
name can override one part of that name — which means an alias must carry
phonemes for everything it matches. Giving `Sloterdijk` an alias of
`Peter Sloterdijk` while supplying only the surname's phonemes deletes the
given name from the narration. Either add the full name as its own term with
its own complete phonemes, as `Alain de Botton` does, or list no alias and let
the surname match inside the longer name.

A possessive is taken with the term it follows, so `Proust's` is voiced as one
word rather than leaving a stray `'s` for the phonemiser to read as the letter
"ess". The generator first phonemises normal
text, substitutes verified entries, then sends the final phonemes to Kokoro.
Its sidecar records the dictionary hash and the entries used. A dictionary
change stales only audio whose narration speaks an affected term; unrelated
audio stays fresh.

That hash covers the dictionary's contents, not the code that applies it.
Changing how `scripts/pronunciation.py` matches or renders entries therefore
leaves existing audio looking fresh when its pronunciation would now differ.
After such a change, work out which narrations it can affect and regenerate
them with `--force`.

## Correction workflow

1. Run `./bookflow audio <book-id> 30-seconds` and listen to the result.
2. Check the title, author, names, specialist terms, abbreviations and numbers.
3. Confirm a disputed pronunciation from the person's own recorded speech, a
   publisher or author source, or a reliable dictionary. Record the direct URL
   and verification date. Do not infer pronunciation from spelling alone.
4. Inspect Kokoro's current result with
   `./bookflow pronunciation "name or term"`. Add the smallest exact entry to
   `config/pronunciations.json`. Use the
   language code selected by the voice, normally `en-gb` for a British voice
   or `en-us` for an American voice. The phoneme string must use symbols known
   to Kokoro's tokenizer.
5. Run the pronunciation command again to confirm that the entry matched and
   its symbols are valid. Then run `./bookflow check`, regenerate the affected
   audio, and listen again.

The dictionary is a correction layer, not a speech-model training set. It is
the preferred approach because the library needs repeatable pronunciation of
book-specific names and terms, not a new voice or speaking style. Audio files
live under `library/books/<book-id>/audio/` beside their provenance sidecars,
and both are committed so the published site can serve them. Regenerating a
narration therefore adds its full weight to history for good — worth
remembering before a library-wide `--force`.
