Strip Proceedings JSON

Usage examples

- Keep only a small set of top-level keys (using example config):

```
python scripts/strip_proceedings.py UIST_2020_program.json --config strip_config_example.json
```

- Remove specific keys and write outputs next to originals:

```
python scripts/strip_proceedings.py . --mode remove --keys attachments videos schedules
```

- Overwrite files in-place (create backups):

```
python scripts/strip_proceedings.py UIST_2020_program.json --mode remove --keys attachments --inplace --backup
```

Notes
- The script operates on top-level keys only. It creates an output file named `originalname.stripped.json` unless `--inplace` is used.
- Use `--config` to store commonly used keep/remove lists.
