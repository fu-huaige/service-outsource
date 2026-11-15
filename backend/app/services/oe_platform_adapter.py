"""OE eligibility, evidence, and publication for confirmed-model execution."""

import json
import os
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import numpy as np
from algorithms.identifiability.regressor import IdentifiabilityError, build_regressor
from algorithms.identifiability.validation import free_run_simulate
from sqlalchemy import update

from app.models.dataset import ProcessingRun
from app.schemas.experiment_spec import ExperimentSpec, OeSimulationInterval, RowSet
from app.schemas.model_catalog import ModelArtifactManifest
from app.services.arx_platform_adapter import OE_IMPLEMENTATION, fit_dynamic_with_manifest
from app.services.experiment_spec_service import contained_path, sha256_file
from app.services.model_registry import get_model
from app.services.modeling_service import ModelingDomainError, _oe_experiments


def oe_training_evidence(params, series, structure, split):
    """Resolve the exact weighted Train targets and original initialization histories."""
    train_start = split.train[0].start
    stop = split.train[0].stop - split.history_guard
    history = structure.max_history
    if params.evaluate_test or stop <= train_start + history:
        raise ValueError("OE needs guarded Train records and Validation-only evaluation")
    if any(not train_start <= row < stop for row in params.sample_weights):
        raise ValueError("OE sample weights must reference guarded Train rows")
    selected = params.training_sample_indices
    if selected and (
        sorted(set(selected)) != selected
        or any(not train_start + history <= row < stop for row in selected)
    ):
        raise ValueError("OE selected targets must be ordered, unique, and within guarded Train")
    inputs = {name: series.values[name][:stop] for name in params.input_columns}
    output = series.values[params.output_column][:stop]
    try:
        reg = build_regressor(
            inputs=inputs, output=output, structure=structure, start=train_start + history,
        )
        targets = reg.time_indices
        if selected:
            targets = targets[np.isin(targets, selected)]
        minimum = 8 if (params.ridge_alpha or 0) > 0 else 2 * reg.n_parameters + 1
        if targets.size < minimum:
            raise ValueError(f"OE requires at least {minimum} valid Train regressor rows")
        reliability = np.asarray([
            min(params.sample_weights.get(int(row) - lag, 1.) for lag in range(history + 1))
            for row in targets
        ])
        experiments = _oe_experiments(inputs, output, targets, reliability)
    except (IdentifiabilityError, ModelingDomainError) as error:
        raise ValueError(error.message) from error

    proof = []
    digest = sha256()
    minimum_segment = max(16, structure.parameter_count + 1)
    for experiment in experiments:
        a, b = experiment.start, experiment.stop
        left = a - history
        if b - a < minimum_segment:
            raise ValueError(f"OE positive-weight interval [{a}, {b}) needs at least {minimum_segment} targets")
        interval = OeSimulationInterval(start=a, stop=b, history_start=left)
        proof.append(interval)
        digest.update(json.dumps(interval.model_dump(), sort_keys=True).encode())
        for values in [output, *inputs.values()]:
            block = np.asarray(values[left:b], dtype=">f8")
            if not np.isfinite(block).all():
                raise ValueError("OE needs finite inputs and outputs throughout each interval and its history")
            digest.update(block.tobytes())
    centers = [np.mean(output[interval.start:interval.stop]) for interval in proof]
    center = float(np.mean(centers))
    scale = np.sqrt(np.mean([
        np.mean(np.square(output[interval.start:interval.stop] - center)) for interval in proof
    ]))
    if not np.isfinite(scale) or scale <= np.finfo(float).eps * max(1., abs(center)):
        raise ValueError("OE needs nonconstant positive-weight Train output")
    if split.validation[0].stop - split.validation[0].start - 2 * split.history_guard <= structure.na:
        raise ValueError("OE history guard leaves insufficient Validation targets")
    return tuple(proof), digest.hexdigest()


async def fit_oe_with_manifest(factory, *, spec, parameters, artifact_root):
    return await fit_dynamic_with_manifest(
        factory, spec=spec, parameters=parameters, artifact_root=artifact_root, kind="oe",
    )


def has_oe_publication_checkpoint(run: ProcessingRun | None) -> bool:
    return bool(
        run is not None and run.run_type == "modeling.oe" and run.status == "running"
        and run.result.get("model_type_id") == "oe" and run.result.get("payload_sha256")
        and not run.result.get("publication_blocked")
    )


async def finish_oe_publication(session, run: ProcessingRun, root: Path) -> bool:
    """Verify and publish a saved result. The state transition grants evaluation ownership."""
    from app.services.model_artifact_service import _load_native_dynamic, publish_verified_manifest

    if not has_oe_publication_checkpoint(run):
        return False
    model_id = UUID(run.result["model_id"])
    manifest = ModelArtifactManifest(
        model_type_id="oe", model_id=model_id, training_run_id=run.id,
        implementation_id=get_model("oe").implementation_id,
        implementation_version=OE_IMPLEMENTATION,
        experiment_spec=ExperimentSpec.model_validate(run.parameters["experiment_spec"]),
        experiment_spec_hash=run.parameters["experiment_spec_hash"],
        effective_training_rows=RowSet.model_validate(run.result["effective_training_rows"]),
        payload_uri=f"models/oe/{model_id}.json", payload_sha256=run.result["payload_sha256"],
    )
    target = contained_path(root, manifest.payload_uri)
    if not target.is_file():
        staged = contained_path(root, f"models/oe/{model_id}.pending.json")
        if not staged.is_file() or sha256_file(staged) != manifest.payload_sha256:
            raise ValueError("OE staged payload does not match its committed SHA256")
        with suppress(FileExistsError):
            os.link(staged, target)
    await _load_native_dynamic(session, manifest, root, expected_status="running")
    publish_verified_manifest(root, manifest)
    claimed = await session.execute(update(ProcessingRun).where(
        ProcessingRun.id == run.id, ProcessingRun.status == "running",
        ProcessingRun.result["payload_sha256"].as_string() == manifest.payload_sha256,
    ).values(status="succeeded", finished_at=datetime.now(UTC)))
    await session.commit()
    if claimed.rowcount == 1:
        contained_path(root, f"models/oe/{model_id}.pending.json").unlink(missing_ok=True)
        return True
    return False


def oe_validation_series(saved, series, *, start: int, stop: int):
    """Use fixed open-loop simulation, with history restricted to Validation."""
    left = start - saved.structure.max_history
    inputs = {name: series.values[name][left:stop] for name in saved.structure.input_columns}
    output = series.values[saved.payload.output_column][left:stop]
    if left < 0 or not all(np.isfinite(values).all() for values in [output, *inputs.values()]):
        raise ValueError("OE Validation and initialization history must be finite")
    return free_run_simulate(
        saved.theta, saved.structure, inputs=inputs, output=output,
        start=start - left, stop=stop - left, intercept=saved.intercept,
        initialization_policy=saved.payload.initialization_policy,
    )
