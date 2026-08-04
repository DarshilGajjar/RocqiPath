# Native dependencies

Two C libraries do the heavy lifting, and neither arrives reliably through
`pip`:

- **libvips** — pyramidal TIFF writing, resizing, and the streamed
  aligned-WSI export. Required by the `orb` and `valis` extras.
- **OpenSlide** — reading vendor whole-slide formats (`.svs`, `.ndpi`,
  `.mrxs`, `.scn`, and friends). Without it, RocqiPath falls back to PIL and
  can only open ordinary TIFFs.

Run `rocqipath doctor` at any point to see which of these RocqiPath can
actually find.

## Windows

1. Download the 64-bit Windows libvips binary from the
   [official libvips installation page](https://www.libvips.org/install.html).
2. Extract it somewhere permanent, for example `C:\tools\vips`.
3. Add the extracted `bin` directory (`C:\tools\vips\bin`) to your **User
   PATH** environment variable.
4. Close and reopen PowerShell, activate your environment, and install the
   extra:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[orb]"   # or .[valis]
```

`openslide-python` ships prebuilt wheels that bundle the OpenSlide binaries on
Windows, so no separate download is needed.

> **Staging note.** Studies stage inputs using symbolic links. Creating
> symlinks on Windows requires Developer Mode or an elevated shell. Without
> either, RocqiPath falls back to hardlinks and then to copying — and warns
> you, because copying whole-slide images is expensive. Enabling Developer
> Mode in Settings → Privacy & security → For developers avoids this.

## macOS

```console
$ brew install vips openslide
$ python -m pip install -e ".[orb]"
```

On Apple silicon, confirm your Python and Homebrew are the same architecture;
a Rosetta Python cannot load an arm64 libvips.

## Linux

Debian and Ubuntu:

```console
$ sudo apt-get update
$ sudo apt-get install -y libvips-tools libopenslide0
$ python -m pip install -e ".[orb]"
```

Fedora and RHEL:

```console
$ sudo dnf install vips-tools openslide
```

## Verifying

```console
$ vips --version
$ python -c "import openslide; print(openslide.__library_version__)"
$ rocqipath doctor
```

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `OSError: cannot load library 'libvips.so.42'` | libvips not installed, or not on the loader path | Install libvips; on Windows add its `bin` to PATH and reopen the terminal |
| `ModuleNotFoundError: No module named 'pyvips'` | The `orb` or `valis` extra is not installed | `pip install -e ".[orb]"` |
| Slides open but every file reports "no metadata" | OpenSlide missing, so PIL is reading the file | Install OpenSlide, then re-run `rocqipath study survey` |
| Staging warns that slides were copied | Symlinks and hardlinks both unavailable | Enable Developer Mode on Windows, or keep the workspace on the same volume as the archive |
