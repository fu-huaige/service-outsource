"""Unified worker entry point for the existing native FIR estimator."""

from app.services.arx_platform_adapter import fit_dynamic_with_manifest


async def fit_fir_with_manifest(factory, *, spec, parameters, artifact_root):
    return await fit_dynamic_with_manifest(
        factory, spec=spec, parameters=parameters, artifact_root=artifact_root, kind="fir",
    )
