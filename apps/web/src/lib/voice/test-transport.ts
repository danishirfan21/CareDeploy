import {
  MicrophoneDeniedError,
  type TransportEvent,
  type VoiceTransport,
} from "./transport";

/**
 * Controlled transport for Playwright and local UI work: no audio and no LiveKit connection.
 * Tests drive it through `window.__voiceTest`, so a test using it proves UI and backend behaviour
 * only, never audio or provider behaviour.
 */
export interface VoiceTestControls {
  failNextConnect: boolean;
  denyMic: boolean;
  micEnabled: boolean;
  connected: boolean;
  lastToken: string | null;
  emit: (e: TransportEvent) => void;
}

declare global {
  interface Window {
    __voiceTest?: Partial<VoiceTestControls>;
  }
}

export function createTestTransport(): VoiceTransport {
  const handlers = new Set<(e: TransportEvent) => void>();
  const emit = (e: TransportEvent) => handlers.forEach((h) => h(e));
  const preset = window.__voiceTest ?? {};
  const controls: VoiceTestControls = {
    failNextConnect: preset.failNextConnect ?? false,
    denyMic: preset.denyMic ?? false,
    micEnabled: false,
    connected: false,
    lastToken: null,
    emit,
  };
  window.__voiceTest = controls;
  return {
    async connect(_url, token) {
      controls.lastToken = token;
      if (controls.failNextConnect) {
        controls.failNextConnect = false;
        throw new Error("connection refused");
      }
      controls.connected = true;
      emit({ type: "connected" });
      if (controls.denyMic) {
        controls.connected = false;
        throw new MicrophoneDeniedError();
      }
      controls.micEnabled = true;
      emit({ type: "agent_joined" });
    },
    async disconnect() {
      controls.connected = false;
      controls.micEnabled = false;
    },
    async setMicEnabled(on) {
      controls.micEnabled = on;
    },
    subscribe(h) {
      handlers.add(h);
      return () => {
        handlers.delete(h);
      };
    },
  };
}
