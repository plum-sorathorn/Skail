# Skail legacy snapshot

This directory is an inert reference snapshot of Skail 0.5.2. It is excluded from
Skail packaging, test discovery, linting, type checking, Graphify's active product scope,
and normal CI.

Do not install these dependencies beside Skail. This snapshot receives no security,
compatibility, or packaging maintenance on the `skail` branch. Fixes for the former product
belong on its preserved history, including the local `skail-v0.5.2-final` tag.

Skail runtime code must never import this package or manipulate `~/.skail/`. The files
remain only so approved design work can consult proven concepts such as provider normalization,
pricing, terminal techniques, deterministic failure signals, and local accounting.
