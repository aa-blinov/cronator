---
name: Cronator
description: A scheduler for a team that runs its own scripts: one dark console, one green accent, and a status colour for every run.
colors:
  primary: "oklch(86.133% 0.141 139.549)"
  primary-content: "oklch(17.226% 0.028 139.549)"
  secondary: "oklch(73.375% 0.165 35.353)"
  secondary-content: "oklch(14.675% 0.033 35.353)"
  accent: "oklch(74.229% 0.133 311.379)"
  accent-content: "oklch(14.845% 0.026 311.379)"
  neutral: "oklch(24.731% 0.02 264.094)"
  neutral-content: "oklch(82.901% 0.031 222.959)"
  base-100: "oklch(30.857% 0.023 264.149)"
  base-200: "oklch(25% 0.019 264.182)"
  base-300: "oklch(22% 0.018 262.177)"
  base-content: "oklch(82.901% 0.031 222.959)"
  info: "oklch(86.078% 0.142 206.182)"
  success: "oklch(86.171% 0.142 166.534)"
  warning: "oklch(86.163% 0.142 94.818)"
  error: "oklch(82.418% 0.099 33.756)"
typography:
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  title:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, sans-serif"
    fontSize: "24px"
    fontWeight: 700
    lineHeight: 1.25
  code:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "12.8px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  box: "1rem"
  button: "0.5rem"
  badge: "1rem"
  control: "0.5rem"
  pill: "9999px"
spacing:
  tight: "0.25rem"
  base: "1rem"
  gutter: "1.5rem"
  section: "2rem"
---

# Design system: Cronator

## Overview

**Creative North Star: "the control room of a small plant"**

Cronator watches scripts run. Somebody has to be able to look at a wall of
results and know in a second which one is broken, and the interface is
built for that second: a dark console, one green accent that marks the
things you can act on, and a colour per state of a run.

The screen is mostly ground. The content sits in a few cards, and the
cards are flat and quiet, so that the two bright things on the page, a
failed run and a live one, are the only things that pull the eye.

The aesthetic comes from the stack rather than from a hand: Tailwind with
DaisyUI, and the "dim" theme of DaisyUI as the default. The dark ground
was chosen because the interface is often left open on a second monitor
while scripts run, and a bright page in a dim room is tiring.

The confirmed rejections, all visible in the code:

- No animation on a button or an input. DaisyUI's own timings are set to
  zero in `tailwind.config.js`, and only the pulse of a running script
  moves.
- No shadow. Depth comes from the tone of the ground and from one blur on
  the sidebar.
- No picture, no illustration and no logo beyond a clock glyph drawn in
  the template.
- No gradient. Every surface is a flat tone.

Key characteristics:

- a fixed 256 pixel sidebar that slides in on a narrow screen;
- one accent colour, used for the primary action and for the brand;
- a status colour per state of a run, carried by a pill;
- monospace for anything the machine wrote, sans for everything else;
- a dark ground by default, with four more themes in the settings.

## Colors

The palette is the "dim" theme of DaisyUI, written out in `oklch` in
`tailwind.config.js`. Four more themes are listed next to it: `light`,
`cupcake`, `dracula` and `business`. The theme is applied with the
`data-theme` attribute on `<html>`, so a change is one attribute and
nothing else.

### Primary

- **Signal green** (`oklch(86.133% 0.141 139.549)`): the primary button,
  the brand word in the sidebar, and the focus ring of an active element.
  Nothing else is green, so green always means one thing.
- **Ink on green** (`oklch(17.226% 0.028 139.549)`): the text of a primary
  button.

### Secondary

- **Ember** (`oklch(73.375% 0.165 35.353)`): the secondary action.
- **Violet** (`oklch(74.229% 0.133 311.379)`): the accent, used where a
  third weight of emphasis is needed.

### Neutral

- **Ground** (`oklch(30.857% 0.023 264.149)`): the base surface, the
  background of the page.
- **Panel** (`oklch(25% 0.019 264.182)`): the cards and the code blocks.
- **Edge** (`oklch(22% 0.018 262.177)`): the borders, and the background of
  the output console.
- **Paper** (`oklch(82.901% 0.031 222.959)`): the text, and the muted
  foreground at half opacity.

### Status

- **Success** (`oklch(86.171% 0.142 166.534)`): a run that finished well.
- **Failure** (`oklch(82.418% 0.099 33.756)`): a run that failed or timed
  out.
- **Running** (`oklch(86.078% 0.142 206.182)`): a run in progress.
- **Waiting** (`oklch(86.163% 0.142 94.818)`): a run that is queued.
- **Cancelled** (`oklch(82.901% 0.031 222.959 / 0.5)`): a run that was
  stopped, dimmed so that it reads as past rather than as broken.
- **Skipped** (`oklch(70% 0.01 264.182 / 0.7)`): a run that never started
  because the previous one was still going.

The status colours are written twice: once as DaisyUI's own `success`,
`error`, `info` and `warning`, and once as the six `.status-*` classes in
`app/static/input.css`. The second set exists because a run has more
states than a button does.

### Named rules

**The One Accent Rule.** The primary green marks the action the page
starts from and the brand. It is not used for a state, and a state is
never green.

**The State Rule.** Every state of a run has a colour and a word. The
pill says "success", "failed", "running", "pending", "cancelled" or
"skipped" in words, and the colour says the same thing again. A reader
who cannot see the colour still reads the state.

**The Flat Ground Rule.** The backgrounds are flat tones. The only
transparency in the interface is the sidebar, which is the panel colour at
70% over a blur.

## Typography

**Display Font:** Inter.
**Body Font:** Inter.
**Code Font:** JetBrains Mono.

Both families are self-hosted under `app/static/vendor/fonts/`, in the
latin, latin-ext, cyrillic, cyrillic-ext, greek and greek-ext subsets.
The Content Security Policy allows `style-src 'self'` only, so a
stylesheet from a font CDN is blocked and the whole interface would fall
back to the system fonts.

Inter is loaded at 400, 500, 600 and 700. JetBrains Mono is loaded at 400
and 500.

### Hierarchy

- **Title** (700, 24px): the name of the page in the header bar, and the
  brand in the sidebar at 24px as well.
- **Card title** (600, 18px): the heading of a card, such as "Script
  Code" or "General Settings".
- **Body** (400, 16px): the labels, the values and the table cells.
- **Small** (500, 12px): the hint under a field, the subtitle of a
  script, and the badge text.
- **Code** (JetBrains Mono, 400, 12.8px, 1.5): the editor, the output
  console and the cron expression.

### Named rules

**The Machine Speaks In Mono Rule.** Everything a script wrote is set in
JetBrains Mono, and everything a person wrote is set in Inter. The
boundary is visible without reading it.

## Layout

The page is two columns: a sidebar and a content area.

The sidebar is 256 pixels wide. Below the `lg` breakpoint it is fixed to
the left, translated off the screen and pulled in by a button in the
header, with a backdrop behind it. At `lg` and above it is a static
column and the toggle disappears. The sidebar holds the brand at the top,
the navigation in the middle, and the signed-in user at the bottom.

The content area has a header bar with the name of the page on the left
and the page's main action on the right, and the body of the page under
it in cards.

The dashboard puts five stat cards in one row, then the list of scripts
in a card under them. The stat card is a rounded panel with a label, a
number and an icon, and it lifts by two pixels when the pointer is over
it.

The script editor is two columns. The left one holds the code editor and
the output console under it. The right one holds the settings, and the
settings are a stack of labelled fields with the schedule presets as a
grid of small buttons at the bottom.

## Elevation & Depth

Flat. The cards are the panel colour on the ground colour, and the
separation between them is the tone, not a shadow. The interface uses no
box-shadow anywhere.

The sidebar is the one exception. It is the panel colour at 70% over a
blur of 10 pixels, with a border at 10% of the text colour, so that the
content behind it shows through slightly.

The output console is the deepest surface in the interface: it uses the
edge colour, which is darker than the card it sits in.

## Shapes

Three radii, from DaisyUI: 1rem for boxes and badges, 0.5rem for buttons
and inputs, and 0.5rem for the panels that the application styles itself.

The status badge is a pill, 9999px, so that a one-word state reads as a
tag rather than as a chip. The pulse dot of a running script is a circle
of 8 pixels.

The cron expression is set in a small rounded block, because it is a
fragment of code rather than a word.

## Components

### Buttons

- **Shape:** 0.5rem radius, one line of text, a border of 1px.
- **Primary:** the green, with the ink colour on top. One per page, on the
  action the page starts from.
- **Secondary:** an outlined button in the text colour.
- **Hover:** the background lightens by a tenth of the foreground.
- **Focus:** a ring in the primary colour.
- **Animation:** none. DaisyUI's button animation is set to zero.

### The sidebar

- **Style:** a glass panel with a right border, a padding of 1rem, and
  the navigation links in a column with 0.5rem between them.
- **The active link:** a line of the text colour at 10% opacity behind
  the row.
- **The brand:** a clock glyph and the word in the primary colour, with
  "Python Script Scheduler" beneath it in small muted type.

### Stat cards

- **Shape:** a rounded box, a label in small type, a number in the title
  size, and an icon on the right.
- **Number:** the number takes the colour of what it counts: green for
  the enabled scripts, blue for the runs today, red for the failures.

### Tables

- **Style:** a card with a header row in small muted type, and rows
  separated by a hairline in the edge colour.
- **The first column:** the id, in the primary colour, so that a row can
  be followed from the list to the detail page.

### Status badges

- **Style:** a pill with the status colour at 20% as the ground and the
  status colour itself as the text, in 12px at weight 500.
- **States:** success, failed, timeout, running, pending, cancelled,
  skipped.

### The code editor

- **Style:** CodeMirror, with the Python mode, the material-ocean theme
  for the light one and dracula for the dark one, a 0.5rem radius and a
  1rem padding.
- **The gutter:** the line numbers, in the muted colour.

### The output console

- **Style:** the edge colour as the ground, a 0.5rem radius, 1rem of
  padding, a maximum height of 400 pixels and a scrollbar.
- **The text:** JetBrains Mono at 12.8px, with the lines wrapped rather
  than cut.
- **Above it:** the state of the stream, the auto-scroll switch, and the
  copy, download and clear buttons.

## Do's and Don'ts

### Do:

- **Do** give every state of a run a colour and a word together.
- **Do** set the code and the output in JetBrains Mono, and the rest in
  Inter.
- **Do** keep the primary green for one action per page.
- **Do** read the colours from the DaisyUI variables, and never write an
  `oklch` value inside a template.
- **Do** check a new page in the dim theme first, since that is the one
  the server renders by default.

### Don't:

- **Don't** add a shadow. The cards are flat.
- **Don't** let a button animate. Only the pulse of a running script
  moves.
- **Don't** use the primary colour for a state. Green means the action
  and the brand.
- **Don't** add a new theme without adding it to the `themes` list in
  `tailwind.config.js`. DaisyUI only generates the CSS for the themes
  that are listed there, and a theme that is not built does nothing when
  it is picked.
- **Don't** load a font from a CDN. The Content Security Policy blocks
  it, and the interface falls back to the system fonts.
