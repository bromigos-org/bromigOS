# Lab models

bromigOS knows the best open AI models for each job, and which of them fit your
homelab's graphics cards. It can suggest better ones, plan which model goes on which
card, and tell you when a better model comes out.

The jobs it knows: chat, coding, memory, pictures, picture edits, cutouts, upscaling,
video, 3D, voice, hearing, reading text in pictures, and reading your screen.

You need a [connected homelab](homelab.md) for most of this. To ask what fits a card you
don't have yet, you don't.

## What fits my graphics cards?

```bash
bromigos lab models recommend          # for each card: what runs now, the best fit, upgrades
bromigos lab models pick image 12      # the best picture model for a 12 GB card, and why
bromigos lab models pick llm --gpu "RX 7900 XTX"   # the best chat model for this card
bromigos lab models tiers video        # the best video model at every card size
```

`recommend` reads what your lab actually runs and says when something better fits. It
also warns when a model you have isn't licensed where you are, or for the use you chose.

## Plan the whole lab

```bash
bromigos lab models plan
```

This gives you up to four ways to set up your lab. Each one says:

- which model goes on which graphics card;
- what stays loaded, and what loads only when it's needed;
- how full each card gets;
- how fast each job will be;
- what that set-up gives up compared with the others.

You can steer the plan:

```bash
bromigos lab models plan --budget "RTX 5070=6G"      # leave room on the card you game on
bromigos lab models plan --goal quality,video=speed  # quality, balanced or speed, per job
bromigos lab models plan --clients 16 --context 32k  # many programs sharing one model
```

**Settings › Lab**, under **Plan**, does the same with sliders and switches, and plans
again as you move them.

- **Goals.** *Best quality* takes the strongest model that fits, even if it's slower.
  *Fastest* takes smaller models and keeps them loaded. *Balanced* is in between.
- **Speeds.** For chat models, speeds come from published tests of the same model on the
  same card where there are any. Otherwise they're estimates.
- **Licences.** Choose *any*, which is fine for a personal lab, *commercial* or
  *permissive*. Some models aren't licensed in every country. bromigOS goes by your time
  zone unless you say where you are.

## Upgrades

Nothing changes on your lab unless you ask. In **Settings › Lab**, under **Upgrades**,
turn on **Model upgrades**. Then each kind of model can be set to:

| Setting | What it allows |
|---|---|
| Off | Nothing. |
| Safe | Only a newer version, or a better-packed copy, of the same model. |
| Any | Any better model that fits. |

For now, bromigOS only tells you about a better model. Applying an upgrade, through your
homelab's own repository, isn't ready yet.

Once a week, bromigOS fetches the newest list of models. If a better model fits one of your
cards, you get one quiet notification. To stop the weekly check:

```bash
systemctl --user disable --now bromigos-lab-models.timer
```

## Get the newest list now

```bash
bromigos lab models refresh        # the newest signed list
bromigos lab models refresh --hf   # also ask Hugging Face now (needs python-huggingface-hub)
```

The full tables, with every job, every card size and every licence, are in the developer
docs: [lab-models.md](https://github.com/bromigos-org/bromigOS/blob/main/docs/lab-models.md).
