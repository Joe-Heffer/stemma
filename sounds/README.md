# Sounds

Reusable patches, samples and soundfonts shared between tracks.

* `manifest.yaml` names each sound, where to find or download it, and its licence.
* `LICENCES.md` is the human-readable licence register. Update it in the same commit as any new sound.
* `cache/` (gitignored) holds downloaded files. Fill it with `stemma sounds fetch [NAME]`.
* `patches/` holds reusable Faust and Csound sources that tracks can reference with `sound.path`.

Track parts refer to a sound by manifest name (`soundfont: FluidR3_GM`) or by a
path relative to the track folder or to this folder.

## Installing the General MIDI soundfont

* Debian/Ubuntu: `sudo apt install fluidsynth fluid-soundfont-gm`
* Fedora: `sudo dnf install fluidsynth fluid-soundfont-gm`
* Arch: `sudo pacman -S fluidsynth soundfont-fluid`
* macOS: `brew install fluid-synth`, then put `FluidR3_GM.sf2` in `sounds/cache/`

Run `stemma doctor` to see what stemma can find.
