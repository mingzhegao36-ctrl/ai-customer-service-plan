<script setup lang="ts">
import { ref, watch, onMounted, useId } from 'vue'
import AppIcon from './AppIcon.vue'
const props = defineProps<{ open: boolean; title: string; description?: string }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement>()
const titleId = useId()
function sync() { if (props.open && !dialog.value?.open) dialog.value?.showModal(); else if (!props.open) dialog.value?.close() }
watch(() => props.open, sync)
onMounted(sync)
</script>
<template>
  <dialog ref="dialog" class="modal" :aria-labelledby="titleId" @cancel.prevent="emit('close')">
    <div class="modal-heading"><h2 :id="titleId">{{ title }}</h2><button class="icon-button" aria-label="关闭弹窗" @click="emit('close')"><AppIcon name="close" /></button></div>
    <p v-if="description" class="muted modal-description">{{ description }}</p>
    <slot />
  </dialog>
</template>

