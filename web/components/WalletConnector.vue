<script setup lang="ts">
/** xrpl-connect wallet picker, themed with the VELUM tokens. The wallet signs; no seed enters this page. */
import { WalletConnector as XrplWalletConnector } from '@xrpl-commons/xrpl-connect-vue'

const error = ref<string | null>(null)
</script>

<template>
  <div class="wc">
    <XrplWalletConnector
      id="wallet-connector"
      aria-label="Choose an XRPL wallet"
      primary-wallet="gemwallet"
      :wallets="['gemwallet', 'xaman', 'walletconnect']"
      show-unavailable
      theme="light"
      :css-vars="{
        '--xc-font-family': 'Instrument Sans, Helvetica Neue, Arial, sans-serif',
        '--xc-primary-color': '#12132E',
        '--xc-text-color': '#12132E',
        '--xc-text-muted-color': '#3F4160',
        '--xc-background-color': '#FFFFFF',
        '--xc-background-secondary': '#F5F4EE',
        '--xc-background-tertiary': '#ECEAE1',
        '--xc-focus-color': '#2F3FE0',
        '--xc-border-radius': '8px',
        '--xc-modal-border-radius': '12px',
        '--xc-connect-button-background': '#12132E',
        '--xc-connect-button-hover-background': '#1f2150',
        '--xc-connect-button-color': '#F5F4EE',
        '--xc-connect-button-border': '1.5px solid #12132E',
        '--xc-connect-button-border-radius': '8px',
        '--xc-connect-button-font-weight': '600',
        '--xc-connect-button-font-size': '15px',
        '--xc-primary-button-background': '#12132E',
        '--xc-primary-button-color': '#F5F4EE',
        '--xc-primary-button-border-radius': '8px',
      }"
      @connect="error = null"
      @error="(e: { message?: string }) => (error = e.message || 'Wallet connection failed')"
    />
    <p v-if="error" class="err"><VIcon name="warn" :size="14" />{{ error }}</p>
  </div>
</template>

<style scoped>
.wc { display: flex; flex-direction: column; gap: 8px; }
.err { margin: 0; display: flex; gap: 6px; align-items: center; font-size: 13px; color: var(--bad-fg); }
</style>
