"""Provider name/model accessors used by the eval runners.

Provider classes (OpenAITranscriptionProvider, OpenAIExtractionProvider,
OpenAIEmbeddingProvider, StubEmbeddingProvider, ...) don't share a base
class — they implement Protocols. These helpers normalize the two attribute
spellings (`name` / `model` are public on some, `_model` on the older
extraction provider) so eval-cost logging records a consistent string for
the dashboards even as providers come and go.
"""

from __future__ import annotations


def provider_name(provider) -> str:
    name = getattr(provider, "name", None)
    if name:
        return str(name)
    class_name = provider.__class__.__name__.lower()
    if "openai" in class_name:
        return "openai"
    if "stub" in class_name:
        return "stub"
    return provider.__class__.__name__


def provider_model(provider) -> str:
    model = getattr(provider, "model", None)
    if model:
        return str(model)
    return str(getattr(provider, "_model", "?"))
