<template>
  <router-view />
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";
import { useSystemStore } from "./stores/systemStore";

const systemStore = useSystemStore();

onMounted(() => {
  systemStore.startHealthPolling();
});

onBeforeUnmount(() => {
  systemStore.stopHealthPolling();
});
</script>
