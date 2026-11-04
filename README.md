# amass
Vendor libraries from cdnjs

## Usage

Declare your dependencies under `[tool.amass.dependencies]` in
`pyproject.toml`, then lock and install:

```shell
amass lock
amass install
```

### `install --output`

By default `amass install` writes the vendored assets to the directory named
by `[tool.amass].output` in `pyproject.toml` (falling back to `vendor` when the
key is unset), resolved relative to the current working directory.

Pass `--output`/`-o` to override that destination on the command line:

```shell
amass install --output /srv/assets   # absolute path, used as-is
amass install -o build/vendor        # relative path, resolved against the CWD
```

- The flag takes precedence over `[tool.amass].output`.
- Absolute paths are used exactly as given; relative paths are resolved against
  the current working directory.
- The destination is **replaced** if it already exists: the existing directory
  is removed before the freshly downloaded assets are moved into place. Any
  missing parent directories are created automatically.
