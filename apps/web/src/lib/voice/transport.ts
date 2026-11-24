/**
 * Transport boundary for the browser side of a call. The page and hook only see `VoiceTransport`;
 * the real LiveKit adapter and the controlled test adapter implement it. The test adapter is only
 * reachable when NEXT_PUBLIC_VOICE_TEST_TRANSPORT=1 (development and Playwright), so a production
 * build can never swap the real transport out.
 */
export type TransportEvent =
  | { type: "connected" }
  | { type: "reconnecting" }
  | { type: "agent_joined" }
  | { type: "agent_left" }
  | { type: "disconnected"; reason?: string };

export class MicrophoneDeniedError extends Error {
  constructor() {
    super("Microphone access was denied");
  }
}

export interface VoiceTransport {
  /** Join the room with a scoped participant token and publish the microphone. */
  connect(url: string, token: string): Promise<void>;
  disconnect(): Promise<void>;
  setMicEnabled(enabled: boolean): Promise<void>;
  subscribe(handler: (e: TransportEvent) => void): () => void;
}

export async function createTransport(): Promise<VoiceTransport> {
  if (process.env.NEXT_PUBLIC_VOICE_TEST_TRANSPORT === "1") {
    const { createTestTransport } = await import("./test-transport");
    return createTestTransport();
  }
  const { LiveKitTransport } = await import("./livekit-transport");
  return new LiveKitTransport();
}
