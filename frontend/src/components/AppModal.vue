<template>
  <div id="modal" class="modal" :hidden="!modalState.open" @click.self="resolveModal(false)">
    <div class="modal-card glass" data-slot="modal">
      <h3 id="modalTitle" data-slot="modal-title">{{ modalState.title }}</h3>
      <p id="modalBody">{{ modalState.body }}</p>
      <input
        id="modalInput"
        v-model="modalState.value"
        type="text"
        :hidden="!modalState.input"
        @keydown.enter.prevent="resolveModal(true)"
        @keydown.esc.prevent="resolveModal(false)"
      >
      <div id="modalPresets" class="modal-presets" :hidden="!modalState.presets.length">
        <button
          v-for="preset in modalState.presets"
          :key="preset"
          type="button"
          class="preset-chip"
          @click="modalState.value = (modalState.value.trim() + ' ' + preset).trim()"
        >{{ preset }}</button>
      </div>
      <div class="modal-foot">
        <button id="modalCancel" class="btn glass-btn" type="button" @click="resolveModal(false)">取消</button>
        <button id="modalOk" class="btn primary" type="button" @click="resolveModal(true)">
          {{ modalState.okText }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { modalState, resolveModal } from "@/core/modal"
</script>

<style>
.preset-chip {
  height: 26px;
  padding: 0 11px;
  border-radius: var(--r-pill);
  border: 1px solid var(--stroke-soft);
  background: var(--srf080);
  color: var(--text-2);
  font-size: 11.5px;
  cursor: pointer;
}
.preset-chip:hover { background: var(--fil150); color: var(--text-1); }
</style>
