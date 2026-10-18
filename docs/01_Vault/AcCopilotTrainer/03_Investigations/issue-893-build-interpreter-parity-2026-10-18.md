---
type: investigation
status: active
memory_tier: canonical
created: 2026-10-18
updated: 2026-10-18
issue: https://github.com/agorokh/ac-copilot-trainer/issues/893
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-569-frozen-build-identity-bake-2026-07-14.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #893: Game Point EXE contents depended on the build interpreter

Found while deploying #885 (16068f3). A repo `.venv` build of `--build-exe` was 62.6 MB.
A system Python 3.13 build was 70.1 MB, and that one matched every earlier rig deploy
file-for-file. The build args were the same. Only ambient site-packages differed.

## What differed (pyi-archive_viewer -l -r)

- **PIL (88 entries) + defusedxml.** These came in only via `pygments.formatters.img`, which
  guards the import with `try/except ImportError`. Nothing we ship uses images. The system
  Python just has Pillow installed.
- **jinja2 + markupsafe** (via `pyparsing.diagram`, never imported at runtime) and
  **threadpoolctl** (via numpy `show_runtime`, guarded).
- **`comtypes.gen.SpeechLib`.** pyttsx3's SAPI5 driver does `from comtypes.gen import
  SpeechLib`. comtypes generates that module the first time SAPI runs in that interpreter. The
  system Python had a cached copy. The venv only had one when something such as a test run had
  happened to import the SAPI driver.
- Everything else was version drift of the same packages: numpy 2.5/2.4, cryptography 49/46,
  click, setuptools.

## Does SAPI need the pre-generated module when frozen?

Not strictly. I built a probe EXE from a venv with `comtypes/gen` emptied. It generated
SpeechLib at first run into `%TEMP%\comtypes_cache\<exe>-313` (508 KB, since comtypes.tools is
bundled through `comtypes.client._generate`). It enumerated 2 voices and rendered a WAV. So an
unbundled EXE still speaks. But it writes codegen into TEMP on every new rig profile, and
whether it does that depended on the build interpreter.

## Fix (PR for #893)

- `build_pyinstaller_args` adds `--hidden-import comtypes.gen.SpeechLib` and excludes
  `PIL`, `defusedxml`, `jinja2`, `markupsafe`, and `threadpoolctl`.
- `tools.rig_launcher.build.pyinstaller_command` is the single path both entrypoints use.
  Before Analysis it:
  - fails on missing runtime modules: `numpy`, `sounddevice`, `pyttsx3`, `serial`,
    `websockets`, and on Windows `comtypes` and `pythoncom`. PyInstaller only warns.
  - generates SpeechLib in a child interpreter.
  - fails if comtypes put SpeechLib outside its own `gen` dir. That happens with a read-only
    site-packages, where Analysis would silently miss it.
- The canonical build interpreter is now documented in
  `docs/10_Development/14_Game_Point_Launcher.md`.

**Verified after the fix:** venv and system builds are 62.57 MB and 62.45 MB. They have the
same top-level package set apart from stdlib `_osx_support`, which the newer setuptools in
the venv pulls in. Both contain SpeechLib. The venv build generated SpeechLib itself starting
from an empty `comtypes/gen`. The new EXE's `--self-test` exited 0, and its
`comtypes_cache` dir stayed empty, so no runtime codegen happened.
