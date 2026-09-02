# AutoConduck legacy snapshot

This directory is an inert reference snapshot of AutoConduck 0.5.2. It is excluded from
Rudder packaging, test discovery, linting, type checking, Graphify's active product scope,
and normal CI.

Do not install these dependencies beside Rudder. This snapshot receives no security,
compatibility, or packaging maintenance on the `rudder` branch. Fixes for the former product
belong on its preserved history, including the local `autoconduck-v0.5.2-final` tag.

Rudder runtime code must never import this package or manipulate `~/.autoconduck/`. The files
remain only so approved design work can consult proven concepts such as provider normalization,
pricing, terminal techniques, deterministic failure signals, and local accounting.
