"""Layout profiles: remember how a quote format is read, so the same format never fails twice.

  fingerprint.py  privacy-preserving signature of a workbook (hashes of structural labels, no customer text)
  recipes.py      generic readers that discover a structure (labelled section table, location matrix, scalar labels) and
                  locators for cells a person has taught (row label + column header, with the absolute cell as fallback)
  store.py        profiles on disk: seed/ (committed, generic) and learned/ (private, git-ignored); auto-saved after a verified read
  engine.py       order of attack: matching profile -> built-in readers -> generic discovery -> "unsupported, please teach"

A value read through a profile or a discovered recipe is only trusted when the arithmetic ties out (section premiums = net premium);
otherwise it is shown as `check`. A stale profile (the format changed) fails verification and is ignored, never believed.
"""
