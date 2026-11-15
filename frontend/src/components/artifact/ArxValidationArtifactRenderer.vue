<template>
  <section data-test="arx-validation-artifact">
    <small>ARX · 模型 {{ evaluation.model_id }} · 评价 {{ evaluation.evaluation_run_id }}</small>
    <p v-if="status" role="status">{{ status }}</p>
    <ModelEvaluationArtifactRenderer :payload="{ ...evaluation, series }" validation />
  </section>
</template>

<script setup lang="ts">
import { ref, shallowRef, watch } from 'vue';
import apiClient from '../../api/client';
import type { ModelEvaluationResult } from '../../types/api';
import ModelEvaluationArtifactRenderer from './ModelEvaluationArtifactRenderer.vue';

interface ArxPredictionArtifact {
  format_version: 1;
  model_type_id: "arx";
  model_id: string;
  evaluation_run_id: string;
  training_run_id: string;
  dataset_version_id: string;
  experiment_spec_hash: string;
  partition: string;
  horizons: [{
    source_row_index: number[];
    timestamps: string[] | null;
    y_true: number[];
    y_pred: number[];
    residual: number[];
  }];
  prediction_modes: {
    one_step: number[];
    one_step_residual: number[];
  };
}

const props = defineProps<{ evaluation: ModelEvaluationResult }>();
const series = shallowRef<Record<string, unknown>>();
const status = ref('');

watch(() => props.evaluation, async (evaluation, _, onCleanup) => {
  const controller = new AbortController();
  onCleanup(() => controller.abort());
  series.value = undefined;
  if (!evaluation.prediction_artifact_sha256) {
    status.value = '本次评价没有可用的逐样本预测文件。';
    return;
  }
  status.value = '正在读取 Validation 预测文件…';
  try {
    const data = await apiClient.get<unknown, ArxPredictionArtifact>(
      '/modeling/evaluations/' + encodeURIComponent(evaluation.evaluation_run_id) + '/predictions',
      { signal: controller.signal },
    );
    if (controller.signal.aborted) return;
    if (
      data.format_version !== 1 || data.model_type_id !== "arx" ||
      data.model_id !== evaluation.model_id || data.evaluation_run_id !== evaluation.evaluation_run_id ||
      data.training_run_id !== evaluation.training_run_id || data.dataset_version_id !== evaluation.dataset_version_id ||
      data.experiment_spec_hash !== evaluation.experiment_spec_hash || data.partition !== 'validation'
    ) throw new Error('ARX evaluation identity mismatch');
    const [horizon] = data.horizons;
    series.value = {
      sample_indices: horizon.source_row_index,
      timestamps: horizon.timestamps,
      y_true: horizon.y_true,
      free_run_prediction: horizon.y_pred,
      one_step_prediction: data.prediction_modes.one_step,
      free_run_residual: horizon.residual,
      one_step_residual: data.prediction_modes.one_step_residual,
    };
    status.value = '';
  } catch {
    if (!controller.signal.aborted) status.value = 'Validation 预测文件不可用或与评价记录不一致。';
  }
}, { immediate: true });
</script>
