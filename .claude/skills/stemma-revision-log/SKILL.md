---
name: stemma-revision-log
description: Close out a stemma revision - check it is safe to commit, add a row to the track's notes.md revision log quoting the analysis figures, and commit with a message that describes the musical change. Use after any working change to a track's spec, parts, patches or mix, or when asked to commit, log or record progress on a track.
---

# Record and commit a revision

Commit after each working revision. A revision is working when `validate`
passes, the chain runs, and there are no new warnings you have not
explained.

## 1. Pre-commit checks

```sh
uv run stemma validate <slug>
uv run stemma all <slug> | jq '{warnings: .analysis.warnings, delta: .analysis.delta}'
git status --short
```

* `valid` is true.
* Every entry in `warnings` and in `delta.warnings_added` is either gone or
  explained in the log row.
* `git status` shows nothing under `renders/` or `generated/`, and no `.wav`,
  `.flac`, `.mp3` or `.ogg` files. These are build output and are
  gitignored; if one appears, it was force-added or put outside those
  folders: unstage it.
* Any new sample, soundfont, SFZ or impulse response is in
  `sounds/LICENCES.md` (and `sounds/manifest.yaml` if shared) in this same
  commit. See the `stemma-add-sound` skill.
* If you changed generator code, `make lint` passes (ruff covers `tracks/`).
* Generated MIDI in `midi/` changes when generators change. Commit it with
  the generator so the two stay in step.

## 2. Add the log row

Append to the `## Revision log` table in `tracks/<slug>/notes.md`:

| Rev | Change | Why (analysis) |
|-----|--------|----------------|

* **Rev**: the next integer.
* **Change**: the musical change in plain words, with the parameters that
  matter (“Bass ducks under the kick: sidechain from drums, lowpassed at
  120 Hz, threshold −16 dB, up to 4 dB”).
* **Why (analysis)**: the figure that prompted it, the figure after, and the
  master’s headline numbers. Take them from `delta.changed`
  (`old` → `new`). Mention attempts that failed if they taught something
  (“at −30 dB it ducked 89.8% of the time”).

`tracks/example-sketch/notes.md` has good rows to copy the style from.

Also update `## Decisions` if the change alters the form, harmony, register
or sound choices, and remove items from “Ideas for next revisions” once done.

For generated parts, the log row records the prompt change, and the
ElevenLabs plan and date must be in `notes.md`.

## 3. Commit

Stage the track’s files (and `sounds/` changes) only:

```sh
git add tracks/<slug>/track.yaml tracks/<slug>/notes.md tracks/<slug>/parts tracks/<slug>/midi
git commit
```

The message describes the musical change, not the file edits:

* Good: “Lead: answer phrase climbs to G5 to lift into the outro”.
* Good: “Bass ducks under the kick so the low end stops blurring”.
* Poor: “Update track.yaml and lead.py”.

Add a body line with the key figures if they help a reader of `git log`.
Follow the repository’s attribution conventions for commit trailers.
