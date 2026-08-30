"""Model identifiers exposed by the compatibility surface."""

# Generic pseudo model names used by most agents (Pi, Claude Code, OpenCode)
_GENERIC_PSEUDO_MODELS = {"autoconduck", "autoconduck-budget", "autoconduck-expensive"}

# Variant suffixes recognised for the autoconduck namespace.
# OMP registers three variants; we accept them so autoconduck/fast,
# autoconduck/balanced and autoconduck/frontier are routed through the
# AutoConduck dispatcher rather than passed verbatim to an upstream LLM
# that doesn't know those IDs.  "smart-dag" removed in Phase 7C Batch 2a
# (legacy pseudo-variant) — compat fallback via normalize_pseudo_model().
_AUTOCONDUCK_VARIANTS = {"fast", "balanced", "frontier"}

# Deprecated variants kept only for compat — not advertised, not in PSEUDO_MODELS
_DEPRECATED_VARIANTS = {"smart-dag"}

# Build deprecated pseudo-model aliases (smart-dag and its prefixed forms) for
# compat checking without advertising.  Kept out of PSEUDO_MODELS.
_DEPRECATED_PSEUDO_MODELS = frozenset(
    {
        v
        for v in _DEPRECATED_VARIANTS
    }
    | {f"autoconduck/{v}" for v in _DEPRECATED_VARIANTS}
    | {f"autoconduck-{v}" for v in _DEPRECATED_VARIANTS}
    | {f"autoconduck {v}" for v in _DEPRECATED_VARIANTS}
)


def _build_pseudo_models():
    """Return the union of generic pseudo-models plus any autoconduck/<variant> and variant names."""
    variants = set(_AUTOCONDUCK_VARIANTS)
    prefixed_slash = {f"autoconduck/{v}" for v in variants}
    prefixed_dash = {f"autoconduck-{v}" for v in variants}
    prefixed_space = {f"autoconduck {v}" for v in variants}
    return (
        set(_GENERIC_PSEUDO_MODELS)
        | variants
        | prefixed_slash
        | prefixed_dash
        | prefixed_space
    )


PSEUDO_MODELS: frozenset[str] = frozenset(_build_pseudo_models())

_warned_smart_dag = False


def normalize_pseudo_model(model: str) -> str:
    """Map deprecated smart-dag aliases to base autoconduck (warn-once)."""
    global _warned_smart_dag
    if model and "smart-dag" in model:
        if not _warned_smart_dag:
            import logging

            logging.getLogger("autoconduck").warning(
                "deprecated pseudo-variant 'smart-dag' requested; routing as 'autoconduck'"
            )
            _warned_smart_dag = True
        return "autoconduck"
    return model


def is_pseudo_model(model: str) -> bool:
    """Check whether model is a known pseudo-model (including deprecated compat)."""
    if model in PSEUDO_MODELS:
        return True
    if model and "smart-dag" in model:
        # Trigger warn-once side effect without double-logging via normalize
        normalize_pseudo_model(model)
        return True
    return False
