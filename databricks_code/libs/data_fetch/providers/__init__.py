"""Provider registry + factory (WS0 skeleton).

PROVIDERS maps a SourceSpec.provider key to a Provider class. WS-A (http_file) and
WS-B (fred_api) register their classes here; WS0 ships the empty registry and the
factory so the contract is frozen (design §5, §6). Adding the Weather source later =
one new class + one entry, core untouched.

Provider construction contract: every registered class is instantiated uniformly as
`cls(secrets=<SecretResolver>, session=<requests.Session | None>)` and uses only what
it needs (FRED uses `secrets`; HTTP uses `session`). This keeps the factory ignorant
of per-provider specifics (design §5).
"""

from __future__ import annotations

from data_fetch.manifest import SourceSpec
from data_fetch.providers.arcgis_feature_service import ArcGisFeatureServiceProvider
from data_fetch.providers.base import Provider
from data_fetch.providers.fred_api import FredApiProvider
from data_fetch.providers.http_file import HttpFileProvider
from data_fetch.secrets import SecretResolver

# Registered providers.
PROVIDERS: dict[str, type[Provider]] = {
    "http_file": HttpFileProvider,
    "fred_api": FredApiProvider,
    "arcgis_feature_service": ArcGisFeatureServiceProvider,
}


def make_provider(spec: SourceSpec, *, secrets: SecretResolver,
                  session=None) -> Provider:
    """Build the Provider for `spec.provider`.

    `secrets` and `session` are threaded into every provider per the construction
    contract above. Raises ValueError with the registered keys if the provider key is
    unregistered (design §5).
    """
    try:
        provider_cls = PROVIDERS[spec.provider]
    except KeyError:
        raise ValueError(
            f"Unknown provider {spec.provider!r} for source {spec.name!r}. "
            f"Registered: {sorted(PROVIDERS)}. Register the class in "
            f"data_fetch.providers.PROVIDERS."
        ) from None
    return provider_cls(secrets=secrets, session=session)
