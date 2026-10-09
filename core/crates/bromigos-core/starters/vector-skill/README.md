# __TITLE__

A skill for VECTOR, bromigOS's desktop AI assistant. A skill is know-how written in
Markdown. VECTOR sees its name and description in his catalog, and reads the rest only
when a task needs it. This one teaches him to read the machine's load average.

## Edit it

`skill.md` starts with frontmatter: `name`, `description` and `when_to_use`. Write the
description and `when_to_use` so he can tell when the skill applies. The body is the
know-how itself, as steps.

A skill can also be a folder with a `SKILL.md` in it, plus any files it refers to.

## Try it

From the folder that holds this one:

```bash
bromigos ext validate ./__NAME__
bromigos ext install --copy ./__NAME__    # asks first, because it's for VECTOR
```

VECTOR reads his skills again when the folder changes. Ask him whether the computer is
busy. After each edit, run `bromigos ext update __NAME__`.

## Publish it

Put this folder in a Git repository, push it, and tag a release:

```bash
git tag v0.1.0 && git push --tags
```

People then install it with `bromigos ext install <your repository's URL>@v0.1.0`. To
list it in the catalog, see "Publish an extension" in bromigOS's `docs/extensions.md`.
