# Screenshots

Four pictures of the interface, and where each one comes from.

| Picture | What it shows |
| --- | --- |
| [dashboard.png](dashboard.png) | The dashboard: the counters, the list of scripts and the action of each row. |
| [executions.png](executions.png) | The execution history, with the filters above it. |
| [editor.png](editor.png) | The script editor: the code, the settings and the output console. |
| [settings.png](settings.png) | The settings page, with the general settings, the alerts, the backups and the counters. |

Every picture is 1440 by 900 pixels and shows the "dim" theme, which is the
one the server renders when the browser has no theme of its own saved. The
theme is applied with the `data-theme` attribute on the page element, so
the same pages look different once the theme in the settings is changed.

## The dashboard

The page a scheduler opens in the morning. Five counters along the top:
the scripts, the enabled ones, the runs of the day, the failures of the
day and the runs in progress. The number takes the colour of what it
counts, so a failure is red before the number is read.

Under the counters sits the list of scripts. Every row carries the state
of the last run, the cron expression, the time of the last run and of the
next one, and three actions: run, edit and pause.

## The execution history

The same list of runs, with the filters for the script and for the state
above it and a search field that looks into the output of the run as well
as into its name. The id of a run is in the primary colour, so a row can
be followed from the list to the page of the run.

## The script editor

The page a script is written on. The left column holds the CodeMirror
editor with the Python mode and the output console under it; the right
column holds the name, the description, the version notes and the
schedule. The schedule is chosen from a set of preset buttons, and the
expression that will be used is shown next to them.

The two buttons at the top of the editor are the ones a reader comes for:
Validate checks the syntax, and Run Test starts the script once without
waiting for its schedule.

## The settings page

Six cards: the general settings, the appearance and the version, the
email alerts, the webhook alerts, the backups and the counters of the
execution history. The theme selector sits in the appearance card, and
choosing a theme changes the page at once and is remembered by the
browser.

## A note on the files

The pictures are referenced from the README by relative path, so they
resolve both on GitHub and in a local checkout. The house-style checker
verifies that every image reference points at a file that exists, so a
renamed picture cannot quietly break the README.
