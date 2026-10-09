# __TITLE__

A shader layer for bromigOS. It draws over the animated background, behind every window,
using real readings from the machine. This one sweeps a scan line up the screen. It
moves faster as the CPU works, and turns amber or red when something runs hot or goes
down.

## Edit it

- `layer.frag` is the shader, in GLSL 330 core. The readings it gets are listed at the
  top as uniforms: CPU, GPU and memory load, network traffic, and health.
- `layer.json` turns the layer on, and sets its opacity, blend mode and GPU budget in
  `budget_ms`.

A layer that goes over its budget, or fails to compile, is switched off until its files
change. It never stops the background. The full contract is at the top of the live
layer's `live/plugins.py`.

## Try it

First, try it headless from a bromigOS checkout. In its `live/` folder, run:

```bash
python -m live.plugins test-layer path/to/__NAME__/layer.frag out.png
```

It compiles the shader on the GPU, draws it over a dark plate with sample readings, and
reports its GPU time. Then, from the folder that holds this one:

```bash
bromigos ext validate ./__NAME__
bromigos ext install --copy ./__NAME__    # asks first; it draws within a few seconds
```

After each edit, run `bromigos ext update __NAME__` to copy your folder in again.

## Publish it

Put this folder in a Git repository, push it, and tag a release:

```bash
git tag v0.1.0 && git push --tags
```

People then install it with `bromigos ext install <your repository's URL>@v0.1.0`. To
list it in the catalog, see "Publish an extension" in bromigOS's `docs/extensions.md`.
